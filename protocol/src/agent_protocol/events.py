from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from agent_protocol.models import Item, ItemType, Schema
from agent_protocol.progress import ProgressImportance, ProgressMessage


class ThreadEventType(StrEnum):
    TURN_STARTED = "turn.started"
    ITEM_STARTED = "item.started"
    ITEM_DELTA = "item.delta"
    ITEM_COMPLETED = "item.completed"
    TURN_PROGRESS = "turn.progress"
    TURN_COMPLETED = "turn.completed"
    TURN_INTERRUPTED = "turn.interrupted"
    TURN_FAILED = "turn.failed"


class TurnStarted(Schema):
    thread_id: UUID
    turn_id: UUID
    type: Literal[ThreadEventType.TURN_STARTED] = ThreadEventType.TURN_STARTED


class ItemStarted(Schema):
    thread_id: UUID
    turn_id: UUID
    item_id: UUID
    item_type: ItemType
    type: Literal[ThreadEventType.ITEM_STARTED] = ThreadEventType.ITEM_STARTED


class ItemDelta(Schema):
    thread_id: UUID
    turn_id: UUID
    item_id: UUID
    delta: str
    type: Literal[ThreadEventType.ITEM_DELTA] = ThreadEventType.ITEM_DELTA


class ItemCompleted(Schema):
    thread_id: UUID
    turn_id: UUID
    item: Item
    type: Literal[ThreadEventType.ITEM_COMPLETED] = ThreadEventType.ITEM_COMPLETED


class TurnProgress(Schema):
    thread_id: UUID
    turn_id: UUID
    message: ProgressMessage
    importance: ProgressImportance = ProgressImportance.NORMAL
    type: Literal[ThreadEventType.TURN_PROGRESS] = ThreadEventType.TURN_PROGRESS


class TurnCompleted(Schema):
    thread_id: UUID
    turn_id: UUID
    type: Literal[ThreadEventType.TURN_COMPLETED] = ThreadEventType.TURN_COMPLETED


class TurnInterrupted(Schema):
    thread_id: UUID
    turn_id: UUID
    type: Literal[ThreadEventType.TURN_INTERRUPTED] = ThreadEventType.TURN_INTERRUPTED


class TurnFailed(Schema):
    thread_id: UUID
    turn_id: UUID
    error: str
    type: Literal[ThreadEventType.TURN_FAILED] = ThreadEventType.TURN_FAILED


type ThreadEvent = Annotated[
    TurnStarted
    | ItemStarted
    | ItemDelta
    | ItemCompleted
    | TurnProgress
    | TurnCompleted
    | TurnInterrupted
    | TurnFailed,
    Field(discriminator="type"),
]

THREAD_EVENT_ADAPTER: TypeAdapter[ThreadEvent] = TypeAdapter(ThreadEvent)
