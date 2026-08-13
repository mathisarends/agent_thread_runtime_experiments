import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import UUID

from agent_protocol.events import ThreadEvent, TurnProgress
from agent_protocol.progress import ProgressMode


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
