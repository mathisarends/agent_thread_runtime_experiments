import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from .agent import (
    AgentContext,
    AgentEvent,
    AgentMessageCreated,
    AgentRunner,
    ContextBuilder,
    Interrupt,
    Steer,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)
from .context import RepositoryContextBuilder
from .events import (
    EventBroker,
    ItemCompleted,
    ThreadEvent,
    TurnCompleted,
    TurnFailed,
    TurnInterrupted,
    TurnStarted,
)
from .models import (
    AgentMessageItem,
    Item,
    Thread,
    ThreadSnapshot,
    ToolCallItem,
    ToolResultItem,
    Turn,
    TurnStatus,
    UserMessageItem,
)
from .repository import Repository, TurnNotFoundError


class _RunningTurn:
    def __init__(self, thread_id: UUID, control: TurnControl) -> None:
        self.thread_id = thread_id
        self.control = control
        self.task: asyncio.Task[None] | None = None


class AgentThreadService:
    """The single canonical owner of conversation and active execution state."""

    def __init__(
        self,
        repository: Repository,
        runner: AgentRunner,
        *,
        context_builder: ContextBuilder | None = None,
        event_broker: EventBroker | None = None,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._context_builder = context_builder or RepositoryContextBuilder(repository)
        self._events = event_broker or EventBroker()
        self._running: dict[UUID, _RunningTurn] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._repository.initialize()

    async def create_thread(self) -> Thread:
        thread = Thread(id=uuid4(), created_at=_now())
        await self._repository.create_thread(thread)
        return thread

    async def start_turn(self, thread_id: UUID, message: str) -> Turn:
        if not message.strip():
            raise ValueError("message must not be empty")
        context = await self._context_builder.build(thread_id)
        now = _now()
        turn = Turn(
            id=uuid4(),
            thread_id=thread_id,
            status=TurnStatus.RUNNING,
            created_at=now,
        )
        user_item = UserMessageItem(
            id=uuid4(),
            thread_id=thread_id,
            turn_id=turn.id,
            created_at=now,
            content=message,
        )
        control = TurnControl()
        running = _RunningTurn(thread_id=thread_id, control=control)
        async with self._lock:
            await self._repository.create_turn(turn, user_item)
            self._running[turn.id] = running
        await self._events.publish(TurnStarted(thread_id=thread_id, turn_id=turn.id))
        await self._events.publish(
            ItemCompleted(thread_id=thread_id, turn_id=turn.id, item=user_item)
        )
        running.task = asyncio.create_task(
            self._execute(turn, context, message, running),
            name=f"agent-turn-{turn.id}",
        )
        return turn

    async def steer_turn(self, thread_id: UUID, turn_id: UUID, message: str) -> None:
        if not message.strip():
            raise ValueError("message must not be empty")
        running = await self._get_running(thread_id, turn_id)
        item = UserMessageItem(
            id=uuid4(),
            thread_id=thread_id,
            turn_id=turn_id,
            created_at=_now(),
            content=message,
        )
        await self._repository.add_item(item)
        await self._events.publish(
            ItemCompleted(thread_id=thread_id, turn_id=turn_id, item=item)
        )
        await running.control.send(Steer(message=message))

    async def interrupt_turn(self, thread_id: UUID, turn_id: UUID) -> None:
        running = await self._get_running(thread_id, turn_id)
        await running.control.send(Interrupt())
        if running.task is not None:
            running.task.cancel()

    async def get_thread(self, thread_id: UUID) -> ThreadSnapshot:
        return await self._repository.get_thread(thread_id)

    async def subscribe(
        self, thread_id: UUID, *, _ready: asyncio.Event | None = None
    ) -> AsyncIterator[ThreadEvent]:
        await self._repository.get_thread(thread_id)
        async for event in self._events.subscribe(thread_id, ready=_ready):
            yield event

    async def wait_for_turn(self, turn_id: UUID) -> None:
        async with self._lock:
            running = self._running.get(turn_id)
            task = running.task if running is not None else None
        if task is not None:
            await task

    async def _get_running(self, thread_id: UUID, turn_id: UUID) -> _RunningTurn:
        async with self._lock:
            running = self._running.get(turn_id)
            if running is None or running.thread_id != thread_id:
                raise TurnNotFoundError(str(turn_id))
            return running

    async def _execute(
        self,
        turn: Turn,
        context: AgentContext,
        message: str,
        running: _RunningTurn,
    ) -> None:
        try:
            events = self._runner.run(context, message, running.control)
            async for agent_event in events:
                item = _to_item(agent_event, turn)
                await self._repository.add_item(item)
                await self._events.publish(
                    ItemCompleted(
                        thread_id=turn.thread_id,
                        turn_id=turn.id,
                        item=item,
                    )
                )
        except asyncio.CancelledError:
            await self._finish(turn, TurnStatus.INTERRUPTED)
            await self._events.publish(
                TurnInterrupted(thread_id=turn.thread_id, turn_id=turn.id)
            )
        except Exception as error:
            await self._finish(turn, TurnStatus.FAILED)
            await self._events.publish(
                TurnFailed(
                    thread_id=turn.thread_id,
                    turn_id=turn.id,
                    error=str(error),
                )
            )
        else:
            await self._finish(turn, TurnStatus.COMPLETED)
            await self._events.publish(
                TurnCompleted(thread_id=turn.thread_id, turn_id=turn.id)
            )
        finally:
            async with self._lock:
                if self._running.get(turn.id) is running:
                    del self._running[turn.id]

    async def _finish(self, turn: Turn, status: TurnStatus) -> None:
        await self._repository.finish_turn(turn.id, status, _now())


def _to_item(event: AgentEvent, turn: Turn) -> Item:
    item_id = uuid4()
    created_at = _now()
    if isinstance(event, AgentMessageCreated):
        return AgentMessageItem(
            id=item_id,
            thread_id=turn.thread_id,
            turn_id=turn.id,
            created_at=created_at,
            content=event.content,
        )
    if isinstance(event, ToolCallCreated):
        return ToolCallItem(
            id=item_id,
            thread_id=turn.thread_id,
            turn_id=turn.id,
            created_at=created_at,
            name=event.name,
            arguments=event.arguments,
            call_id=event.call_id,
        )
    if isinstance(event, ToolResultCreated):
        return ToolResultItem(
            id=item_id,
            thread_id=turn.thread_id,
            turn_id=turn.id,
            created_at=created_at,
            call_id=event.call_id,
            output=event.output,
        )
    raise TypeError(f"unsupported agent event: {type(event).__name__}")


def _now() -> datetime:
    return datetime.now(UTC)
