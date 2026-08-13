import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from gateway.conversation.core.models import Item, ItemType, Schema
from gateway.conversation.core.progress import (
    ProgressImportance,
    ProgressMessage,
    ProgressMode,
)


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


class EventBroker:
    """In-process live fan-out. Durable state remains in the repository."""

    def __init__(self) -> None:
        self._subscribers: dict[
            UUID, dict[asyncio.Queue[ThreadEvent], ProgressMode]
        ] = {}
        self._lock = asyncio.Lock()

    async def publish(self, event: ThreadEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.thread_id, {}).items())
        for queue, progress_mode in subscribers:
            if (
                isinstance(event, TurnProgress)
                and progress_mode is not ProgressMode.PROACTIVE
            ):
                continue
            queue.put_nowait(event)

    async def progress_requested(self, thread_id: UUID) -> bool:
        async with self._lock:
            return any(
                mode.enables_agent
                for mode in self._subscribers.get(thread_id, {}).values()
            )

    async def subscribe(
        self,
        thread_id: UUID,
        *,
        progress: ProgressMode = ProgressMode.OFF,
        ready: asyncio.Event | None = None,
    ) -> AsyncIterator[ThreadEvent]:
        queue: asyncio.Queue[ThreadEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(thread_id, {})[queue] = progress
        if ready is not None:
            ready.set()
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(thread_id)
                if subscribers is not None:
                    subscribers.pop(queue, None)
                    if not subscribers:
                        with suppress(KeyError):
                            del self._subscribers[thread_id]
