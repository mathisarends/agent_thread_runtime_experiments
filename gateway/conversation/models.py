from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(frozen=True)


class TurnStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class Thread(Schema):
    id: UUID
    created_at: datetime


class Turn(Schema):
    id: UUID
    thread_id: UUID
    status: TurnStatus
    created_at: datetime
    completed_at: datetime | None = None


class ItemBase(Schema):
    id: UUID
    thread_id: UUID
    turn_id: UUID
    created_at: datetime


class UserMessageItem(ItemBase):
    type: Literal["user_message"] = "user_message"
    content: str


class AgentMessageItem(ItemBase):
    type: Literal["agent_message"] = "agent_message"
    content: str


class ToolCallItem(ItemBase):
    type: Literal["tool_call"] = "tool_call"
    name: str
    arguments: dict[str, Any]
    call_id: str


class ToolResultItem(ItemBase):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    output: Any


type Item = Annotated[
    UserMessageItem | AgentMessageItem | ToolCallItem | ToolResultItem,
    Field(discriminator="type"),
]


class ThreadSnapshot(Schema):
    thread: Thread
    turns: tuple[Turn, ...]
    items: tuple[Item, ...]

    @property
    def active_turn(self) -> Turn | None:
        return next(
            (turn for turn in self.turns if turn.status is TurnStatus.RUNNING), None
        )
