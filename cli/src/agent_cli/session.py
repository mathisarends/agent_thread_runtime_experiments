"""Thread and turn operations, one level above raw JSON-RPC."""

from typing import Any

from agent_cli.console import Console
from agent_cli.protocol import (
    RUNNING_TURN_STATUS,
    TERMINAL_TURN_EVENTS,
    EventType,
    Method,
    ProgressMode,
)
from agent_cli.render import Event, EventRenderer
from agent_cli.rpc import JsonRpcClient
from agent_cli.state import CliState


class Session:
    """Owns the state of one CLI connection and how it is presented."""

    def __init__(
        self,
        rpc: JsonRpcClient,
        console: Console,
        *,
        state: CliState | None = None,
        renderer: EventRenderer | None = None,
    ) -> None:
        self.rpc = rpc
        self.console = console
        self.state = state if state is not None else CliState()
        self.renderer = renderer if renderer is not None else EventRenderer(console)

    async def create_thread(self) -> str:
        thread = await self.rpc.request(Method.THREAD_CREATE)
        thread_id: str = thread["id"]
        await self.use_thread(thread_id)
        return thread_id

    async def use_thread(self, thread_id: str) -> None:
        snapshot = await self.rpc.request(Method.THREAD_GET, {"thread_id": thread_id})
        await self.subscribe(thread_id)
        self.state.thread_id = thread_id
        self.state.active_turn_id = _running_turn_id(snapshot)
        self.console.note(f"thread {thread_id}")

    async def subscribe(
        self, thread_id: str, progress: ProgressMode = ProgressMode.OFF
    ) -> None:
        await self.rpc.request(
            Method.THREAD_SUBSCRIBE,
            {"thread_id": thread_id, "progress": progress.value},
        )
        self.state.track_subscription(thread_id, progress)

    async def unsubscribe(self, thread_id: str) -> None:
        await self.rpc.request(Method.THREAD_UNSUBSCRIBE, {"thread_id": thread_id})
        self.state.drop_subscription(thread_id)

    async def start_turn(self, message: str) -> str:
        turn = await self.rpc.request(
            Method.TURN_START,
            {"thread_id": self.state.require_thread(), "message": message},
        )
        turn_id: str = turn["id"]
        if turn_id not in self.state.finished_turn_ids:
            self.state.active_turn_id = turn_id
        return turn_id

    async def steer_turn(self, message: str) -> None:
        await self.rpc.request(
            Method.TURN_STEER,
            {
                "thread_id": self.state.require_thread(),
                "turn_id": self.state.require_active_turn(),
                "message": message,
            },
        )

    async def interrupt_turn(self) -> None:
        await self.rpc.request(
            Method.TURN_INTERRUPT,
            {
                "thread_id": self.state.require_thread(),
                "turn_id": self.state.require_active_turn(),
            },
        )

    async def consume_events(self) -> None:
        """Render notifications until cancelled."""
        async for event in self.rpc.notifications():
            self.handle_event(event)

    def handle_event(self, event: Event) -> None:
        thread_id = event.get("thread_id")
        is_current = thread_id == self.state.thread_id
        if is_current:
            self._track_turn(event)
        self.renderer.render(event, thread_id=None if is_current else thread_id)

    def _track_turn(self, event: Event) -> None:
        event_type = event["type"]
        if event_type == EventType.TURN_STARTED:
            self.state.active_turn_id = event["turn_id"]
        elif event_type in TERMINAL_TURN_EVENTS:
            self.state.finished_turn_ids.add(event["turn_id"])
            self.state.active_turn_id = None


def _running_turn_id(snapshot: dict[str, Any]) -> str | None:
    running = next(
        (turn for turn in snapshot["turns"] if turn["status"] == RUNNING_TURN_STATUS),
        None,
    )
    return running["id"] if running else None
