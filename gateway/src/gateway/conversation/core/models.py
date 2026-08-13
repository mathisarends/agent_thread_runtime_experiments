from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ItemType(StrEnum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


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
    type: Literal[ItemType.USER_MESSAGE] = ItemType.USER_MESSAGE
    content: str


class AgentMessageItem(ItemBase):
    type: Literal[ItemType.AGENT_MESSAGE] = ItemType.AGENT_MESSAGE
    content: str


class ToolCallItem(ItemBase):
    type: Literal[ItemType.TOOL_CALL] = ItemType.TOOL_CALL
    name: str
    arguments: dict[str, Any]
    call_id: str


class ToolResultItem(ItemBase):
    type: Literal[ItemType.TOOL_RESULT] = ItemType.TOOL_RESULT
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
