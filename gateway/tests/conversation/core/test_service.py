import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from gateway.conversation.agents.contracts import (
    AgentContext,
    AgentEvent,
    AgentItemStarted,
    AgentMessageCreated,
    AgentMessageDelta,
    AgentProgressUpdated,
    AgentRunner,
    Interrupt,
    Steer,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)
from gateway.conversation.core.events import (
    ItemCompleted,
    ItemDelta,
    ItemStarted,
    ThreadEvent,
    TurnFailed,
)
from gateway.conversation.core.models import (
    AgentMessageItem,
    ItemType,
    TurnStatus,
    UserMessageItem,
)
from gateway.conversation.core.progress import ProgressMode
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.repository import (
    TurnAlreadyRunningError,
    TurnNotFoundError,
)

ServiceFactory = Callable[[AgentRunner], Awaitable[AgentThreadService]]


class EchoRunner:
    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, control
        yield AgentMessageCreated(content=f"Echo: {input}")


class ControlledRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input
        self.started.set()
        message = await control.receive_one()
        if isinstance(message, Steer):
            yield AgentMessageCreated(content=f"Steered: {message.message}")
        elif isinstance(message, Interrupt):
            return


class ToolRunner:
    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input, control
        yield ToolCallCreated(
            name="spotify.search",
            arguments={"query": "Believer"},
            call_id="call-1",
        )
        yield ToolResultCreated(call_id="call-1", output={"track": "Believer"})
        yield AgentMessageCreated(content="Believer is now playing.")


class DuplicateItemStartRunner:
    """Reports the same item as started more than once before completing it."""

    def __init__(self, item_id: UUID) -> None:
        self._item_id = item_id

    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input, control
        yield AgentItemStarted(item_id=self._item_id, item_type=ItemType.AGENT_MESSAGE)
        yield AgentItemStarted(item_id=self._item_id, item_type=ItemType.AGENT_MESSAGE)
        yield AgentMessageCreated(item_id=self._item_id, content="done")


class DeltaRunner:
    """Streams a message via deltas without an explicit AgentItemStarted."""

    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input, control
        item_id = uuid4()
        yield AgentMessageDelta(item_id=item_id, delta="Hel")
        yield AgentMessageDelta(item_id=item_id, delta="lo")
        yield AgentMessageCreated(item_id=item_id, content="Hello")


class FailingRunner:
    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input, control
        raise RuntimeError("boom")
        yield  # pragma: no cover - makes this an async generator


class UnsupportedEventRunner:
    """Yields an event type the service does not know how to persist."""

    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input, control
        yield object()  # type: ignore[misc]


class ProgressRunner:
    def __init__(self) -> None:
        self.context: AgentContext | None = None
        self.reported = asyncio.Event()

    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        del input
        self.context = context
        if context.progress_enabled:
            yield AgentProgressUpdated(message="Ich vergleiche passende Stellen.")
            self.reported.set()
        await control.receive_one()


async def collect_events(
    service: AgentThreadService, thread_id: UUID, count: int
) -> list[ThreadEvent]:
    events: list[ThreadEvent] = []
    async for event in service.subscribe(thread_id):
        events.append(event)
        if len(events) == count:
            return events
    raise AssertionError("subscription ended")


_TERMINAL_TYPES = {"turn.completed", "turn.interrupted", "turn.failed"}


async def collect_turn(
    service: AgentThreadService, thread_id: UUID
) -> list[ThreadEvent]:
    """Collect every event of one turn, from turn.started to its terminal event."""
    events: list[ThreadEvent] = []
    async for event in service.subscribe(thread_id):
        events.append(event)
        if event.type in _TERMINAL_TYPES:
            return events
    raise AssertionError("subscription ended")


async def _hold_subscription(
    service: AgentThreadService,
    thread_id: UUID,
    ready: asyncio.Event,
) -> None:
    async for _ in service.subscribe(
        thread_id, progress=ProgressMode.ON_REQUEST, _ready=ready
    ):
        pass


@pytest.mark.asyncio
async def test_turn_is_persisted_and_fanned_out_in_order(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(EchoRunner())
    thread = await service.create_thread()

    first = asyncio.create_task(collect_events(service, thread.id, 6))
    second = asyncio.create_task(collect_events(service, thread.id, 6))
    await asyncio.sleep(0)

    turn = await service.start_turn(thread.id, "hello")
    await service.wait_for_turn(turn.id)
    first_events, second_events = await asyncio.gather(first, second)

    expected = [
        "turn.started",
        "item.started",
        "item.completed",
        "item.started",
        "item.completed",
        "turn.completed",
    ]
    assert [event.type for event in first_events] == expected
    assert [event.type for event in second_events] == expected
    first_started, first_completed = first_events[1], first_events[2]
    second_started, second_completed = first_events[3], first_events[4]
    assert isinstance(first_started, ItemStarted)
    assert isinstance(first_completed, ItemCompleted)
    assert isinstance(second_started, ItemStarted)
    assert isinstance(second_completed, ItemCompleted)
    assert first_started.item_id == first_completed.item.id
    assert second_started.item_id == second_completed.item.id

    snapshot = await service.get_thread(thread.id)
    assert snapshot.turns[0].status is TurnStatus.COMPLETED
    assert snapshot.turns[0].completed_at is not None
    assert isinstance(snapshot.items[0], UserMessageItem)
    assert isinstance(snapshot.items[1], AgentMessageItem)
    assert snapshot.items[1].content == "Echo: hello"


@pytest.mark.asyncio
async def test_start_turn_rejects_blank_message(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(EchoRunner())
    thread = await service.create_thread()

    with pytest.raises(ValueError, match="message must not be empty"):
        await service.start_turn(thread.id, "   ")


@pytest.mark.asyncio
async def test_steer_turn_rejects_blank_message(
    make_service: ServiceFactory,
) -> None:
    runner = ControlledRunner()
    service = await make_service(runner)
    thread = await service.create_thread()
    turn = await service.start_turn(thread.id, "wait")
    await runner.started.wait()

    with pytest.raises(ValueError, match="message must not be empty"):
        await service.steer_turn(thread.id, turn.id, "  ")

    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)


@pytest.mark.asyncio
async def test_steering_uses_the_existing_turn_and_is_persisted(
    make_service: ServiceFactory,
) -> None:
    runner = ControlledRunner()
    service = await make_service(runner)
    thread = await service.create_thread()
    turn = await service.start_turn(thread.id, "Play Believer")
    await runner.started.wait()

    await service.steer_turn(thread.id, turn.id, "Actually, play Thunder")
    await service.wait_for_turn(turn.id)

    snapshot = await service.get_thread(thread.id)
    assert len(snapshot.turns) == 1
    assert snapshot.turns[0].status is TurnStatus.COMPLETED
    assert [item.type for item in snapshot.items] == [
        "user_message",
        "user_message",
        "agent_message",
    ]
    assert isinstance(snapshot.items[-1], AgentMessageItem)
    assert snapshot.items[-1].content == "Steered: Actually, play Thunder"


@pytest.mark.asyncio
async def test_steering_an_unknown_turn_raises(make_service: ServiceFactory) -> None:
    service = await make_service(EchoRunner())
    thread = await service.create_thread()

    with pytest.raises(TurnNotFoundError):
        await service.steer_turn(thread.id, UUID(int=0), "hello")


@pytest.mark.asyncio
async def test_interrupt_and_one_running_turn_invariant(
    make_service: ServiceFactory,
) -> None:
    runner = ControlledRunner()
    service = await make_service(runner)
    thread = await service.create_thread()
    turn = await service.start_turn(thread.id, "wait")
    await runner.started.wait()

    with pytest.raises(TurnAlreadyRunningError):
        await service.start_turn(thread.id, "another")

    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)
    snapshot = await service.get_thread(thread.id)
    assert snapshot.turns[0].status is TurnStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_tool_call_and_result_are_semantic_items(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(ToolRunner())
    thread = await service.create_thread()

    turn = await service.start_turn(thread.id, "Play Believer")
    await service.wait_for_turn(turn.id)

    snapshot = await service.get_thread(thread.id)
    assert [item.type for item in snapshot.items] == [
        "user_message",
        "tool_call",
        "tool_result",
        "agent_message",
    ]


@pytest.mark.asyncio
async def test_repeated_item_started_events_are_collapsed(
    make_service: ServiceFactory,
) -> None:
    item_id = uuid4()
    service = await make_service(DuplicateItemStartRunner(item_id))
    thread = await service.create_thread()

    events = asyncio.create_task(collect_turn(service, thread.id))
    await asyncio.sleep(0)
    turn = await service.start_turn(thread.id, "hello")
    await service.wait_for_turn(turn.id)

    thread_events = await events
    assert [event.type for event in thread_events] == [
        "turn.started",
        "item.started",
        "item.completed",
        "item.started",
        "item.completed",
        "turn.completed",
    ]


@pytest.mark.asyncio
async def test_message_deltas_start_and_complete_the_item(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(DeltaRunner())
    thread = await service.create_thread()

    events = asyncio.create_task(collect_turn(service, thread.id))
    await asyncio.sleep(0)
    turn = await service.start_turn(thread.id, "hello")
    await service.wait_for_turn(turn.id)

    thread_events = await events
    assert [event.type for event in thread_events] == [
        "turn.started",
        "item.started",
        "item.completed",
        "item.started",
        "item.delta",
        "item.delta",
        "item.completed",
        "turn.completed",
    ]
    deltas = [event for event in thread_events if isinstance(event, ItemDelta)]
    assert [delta.delta for delta in deltas] == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_runner_failure_marks_the_turn_as_failed(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(FailingRunner())
    thread = await service.create_thread()

    events = asyncio.create_task(collect_turn(service, thread.id))
    await asyncio.sleep(0)
    turn = await service.start_turn(thread.id, "hello")
    await service.wait_for_turn(turn.id)

    thread_events = await events
    assert [event.type for event in thread_events] == [
        "turn.started",
        "item.started",
        "item.completed",
        "turn.failed",
    ]
    last_event = thread_events[-1]
    assert isinstance(last_event, TurnFailed)
    assert last_event.error == "boom"

    snapshot = await service.get_thread(thread.id)
    assert snapshot.turns[0].status is TurnStatus.FAILED


@pytest.mark.asyncio
async def test_unsupported_agent_event_fails_the_turn(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(UnsupportedEventRunner())
    thread = await service.create_thread()
    turn = await service.start_turn(thread.id, "hello")
    await service.wait_for_turn(turn.id)

    snapshot = await service.get_thread(thread.id)
    assert snapshot.turns[0].status is TurnStatus.FAILED


@pytest.mark.asyncio
async def test_progress_capability_is_disabled_without_demand(
    make_service: ServiceFactory,
) -> None:
    runner = ProgressRunner()
    service = await make_service(runner)
    thread = await service.create_thread()

    turn = await service.start_turn(thread.id, "Find jobs")
    await asyncio.sleep(0)

    assert runner.context is not None
    assert runner.context.progress_enabled is False
    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)


@pytest.mark.asyncio
async def test_on_request_enables_agent_and_retains_latest_progress(
    make_service: ServiceFactory,
) -> None:
    runner = ProgressRunner()
    service = await make_service(runner)
    thread = await service.create_thread()
    ready = asyncio.Event()
    subscription = asyncio.create_task(_hold_subscription(service, thread.id, ready))
    await ready.wait()

    turn = await service.start_turn(thread.id, "Find jobs")
    await runner.reported.wait()
    result = await service.get_progress(thread.id)

    assert runner.context is not None
    assert runner.context.progress_enabled is True
    assert result.progress is not None
    assert result.progress.turn_id == turn.id
    assert result.progress.message == "Ich vergleiche passende Stellen."

    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)
    subscription.cancel()
    await asyncio.gather(subscription, return_exceptions=True)


@pytest.mark.asyncio
async def test_get_progress_is_empty_without_a_running_turn(
    make_service: ServiceFactory,
) -> None:
    service = await make_service(EchoRunner())
    thread = await service.create_thread()

    result = await service.get_progress(thread.id)

    assert result.progress is None
