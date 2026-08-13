from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class TurnStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Thread:
    id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Turn:
    id: UUID
    thread_id: UUID
    status: TurnStatus
    created_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserMessageItem:
    id: UUID
    thread_id: UUID
    turn_id: UUID
    created_at: datetime
    content: str
    type: str = "user_message"


@dataclass(frozen=True, slots=True)
class AgentMessageItem:
    id: UUID
    thread_id: UUID
    turn_id: UUID
    created_at: datetime
    content: str
    type: str = "agent_message"


@dataclass(frozen=True, slots=True)
class ToolCallItem:
    id: UUID
    thread_id: UUID
    turn_id: UUID
    created_at: datetime
    name: str
    arguments: dict[str, Any]
    call_id: str
    type: str = "tool_call"


@dataclass(frozen=True, slots=True)
class ToolResultItem:
    id: UUID
    thread_id: UUID
    turn_id: UUID
    created_at: datetime
    call_id: str
    output: Any
    type: str = "tool_result"


type Item = UserMessageItem | AgentMessageItem | ToolCallItem | ToolResultItem


@dataclass(frozen=True, slots=True)
class ThreadSnapshot:
    thread: Thread
    turns: tuple[Turn, ...]
    items: tuple[Item, ...]

    @property
    def active_turn(self) -> Turn | None:
        return next(
            (turn for turn in self.turns if turn.status is TurnStatus.RUNNING), None
        )
