"""Mutable state of one interactive CLI session."""

from dataclasses import dataclass, field

from agent_cli.protocol import ProgressMode


@dataclass(slots=True)
class CliState:
    thread_id: str | None = None
    active_turn_id: str | None = None
    finished_turn_ids: set[str] = field(default_factory=set)
    subscribed_thread_ids: set[str] = field(default_factory=set)
    streaming_item_ids: set[str] = field(default_factory=set)
    progress_modes: dict[str, ProgressMode] = field(default_factory=dict)

    def require_thread(self) -> str:
        if self.thread_id is None:
            raise ValueError("no current thread; use /new or /use")
        return self.thread_id

    def require_active_turn(self) -> str:
        if self.active_turn_id is None:
            raise ValueError("no active turn")
        return self.active_turn_id

    def track_subscription(self, thread_id: str, progress: ProgressMode) -> None:
        self.subscribed_thread_ids.add(thread_id)
        self.progress_modes[thread_id] = progress

    def drop_subscription(self, thread_id: str) -> None:
        self.subscribed_thread_ids.discard(thread_id)
        self.progress_modes.pop(thread_id, None)
