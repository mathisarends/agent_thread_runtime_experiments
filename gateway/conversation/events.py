import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from uuid import UUID

from .models import Item


@dataclass(frozen=True, slots=True)
class TurnStarted:
    thread_id: UUID
    turn_id: UUID
    type: str = "turn.started"


@dataclass(frozen=True, slots=True)
class ItemStarted:
    thread_id: UUID
    turn_id: UUID
    item_id: UUID
    item_type: str
    type: str = "item.started"


@dataclass(frozen=True, slots=True)
class ItemDelta:
    thread_id: UUID
    turn_id: UUID
    item_id: UUID
    delta: str
    type: str = "item.delta"


@dataclass(frozen=True, slots=True)
class ItemCompleted:
    thread_id: UUID
    turn_id: UUID
    item: Item
    type: str = "item.completed"


@dataclass(frozen=True, slots=True)
class TurnCompleted:
    thread_id: UUID
    turn_id: UUID
    type: str = "turn.completed"


@dataclass(frozen=True, slots=True)
class TurnInterrupted:
    thread_id: UUID
    turn_id: UUID
    type: str = "turn.interrupted"


@dataclass(frozen=True, slots=True)
class TurnFailed:
    thread_id: UUID
    turn_id: UUID
    error: str
    type: str = "turn.failed"


type ThreadEvent = (
    TurnStarted
    | ItemStarted
    | ItemDelta
    | ItemCompleted
    | TurnCompleted
    | TurnInterrupted
    | TurnFailed
)


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
