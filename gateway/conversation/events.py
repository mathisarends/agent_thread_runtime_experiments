import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from gateway.conversation.models import Item, ItemType, Schema


class TurnStarted(Schema):
    thread_id: UUID
    turn_id: UUID
    type: Literal["turn.started"] = "turn.started"


class ItemStarted(Schema):
    thread_id: UUID
    turn_id: UUID
    item_id: UUID
    item_type: ItemType
    type: Literal["item.started"] = "item.started"


class ItemDelta(Schema):
    thread_id: UUID
    turn_id: UUID
    item_id: UUID
    delta: str
    type: Literal["item.delta"] = "item.delta"


class ItemCompleted(Schema):
    thread_id: UUID
    turn_id: UUID
    item: Item
    type: Literal["item.completed"] = "item.completed"


class TurnCompleted(Schema):
    thread_id: UUID
    turn_id: UUID
    type: Literal["turn.completed"] = "turn.completed"


class TurnInterrupted(Schema):
    thread_id: UUID
    turn_id: UUID
    type: Literal["turn.interrupted"] = "turn.interrupted"


class TurnFailed(Schema):
    thread_id: UUID
    turn_id: UUID
    error: str
    type: Literal["turn.failed"] = "turn.failed"


type ThreadEvent = Annotated[
    TurnStarted
    | ItemStarted
    | ItemDelta
    | ItemCompleted
    | TurnCompleted
    | TurnInterrupted
    | TurnFailed,
    Field(discriminator="type"),
]


class EventBroker:
    """In-process live fan-out. Durable state remains in the repository."""

    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue[ThreadEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, event: ThreadEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.thread_id, ()))
        for queue in subscribers:
            queue.put_nowait(event)

    async def subscribe(
        self, thread_id: UUID, *, ready: asyncio.Event | None = None
    ) -> AsyncIterator[ThreadEvent]:
        queue: asyncio.Queue[ThreadEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(thread_id, set()).add(queue)
        if ready is not None:
            ready.set()
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(thread_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        with suppress(KeyError):
                            del self._subscribers[thread_id]
