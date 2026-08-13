import asyncio
from uuid import UUID, uuid4

import pytest
from gateway.conversation.core.events import (
    EventBroker,
    ThreadEvent,
    TurnProgress,
    TurnStarted,
)
from gateway.conversation.core.progress import ProgressMode


async def _first(
    broker: EventBroker, thread_id: UUID, mode: ProgressMode, ready: asyncio.Event
) -> ThreadEvent:
    async for event in broker.subscribe(thread_id, progress=mode, ready=ready):
        return event
    raise AssertionError("subscription ended")


@pytest.mark.asyncio
async def test_broker_only_pushes_progress_to_proactive_subscribers() -> None:
    broker = EventBroker()
    thread_id = uuid4()
    turn_id = uuid4()
    proactive_ready = asyncio.Event()
    request_ready = asyncio.Event()

    proactive = asyncio.create_task(
        _first(broker, thread_id, ProgressMode.PROACTIVE, proactive_ready)
    )
    on_request = asyncio.create_task(
        _first(broker, thread_id, ProgressMode.ON_REQUEST, request_ready)
    )
    await asyncio.gather(proactive_ready.wait(), request_ready.wait())
    await broker.publish(
        TurnProgress(thread_id=thread_id, turn_id=turn_id, message="Searching")
    )

    event = await asyncio.wait_for(proactive, timeout=1)
    assert isinstance(event, TurnProgress)
    assert not on_request.done()
    on_request.cancel()
    await asyncio.gather(on_request, return_exceptions=True)


@pytest.mark.asyncio
async def test_non_progress_events_reach_every_subscriber_regardless_of_mode() -> None:
    broker = EventBroker()
    thread_id = uuid4()
    turn_id = uuid4()
    off_ready = asyncio.Event()

    off_mode = asyncio.create_task(_first(broker, thread_id, ProgressMode.OFF, off_ready))
    await off_ready.wait()
    await broker.publish(TurnStarted(thread_id=thread_id, turn_id=turn_id))

    event = await asyncio.wait_for(off_mode, timeout=1)
    assert isinstance(event, TurnStarted)


@pytest.mark.asyncio
async def test_progress_requested_reflects_active_subscriber_modes() -> None:
    broker = EventBroker()
    thread_id = uuid4()

    assert await broker.progress_requested(thread_id) is False

    ready = asyncio.Event()
    subscription = asyncio.create_task(
        _first(broker, thread_id, ProgressMode.ON_REQUEST, ready)
    )
    await ready.wait()

    assert await broker.progress_requested(thread_id) is True

    subscription.cancel()
    await asyncio.gather(subscription, return_exceptions=True)


@pytest.mark.asyncio
async def test_publishing_to_a_thread_without_subscribers_is_a_no_op() -> None:
    broker = EventBroker()

    await broker.publish(TurnStarted(thread_id=uuid4(), turn_id=uuid4()))


@pytest.mark.asyncio
async def test_unsubscribing_stops_further_progress_requests_from_counting() -> None:
    broker = EventBroker()
    thread_id = uuid4()
    ready = asyncio.Event()

    async def subscribe_and_stop() -> None:
        async for _ in broker.subscribe(
            thread_id, progress=ProgressMode.PROACTIVE, ready=ready
        ):
            pass  # pragma: no cover - cancelled before any event arrives

    subscription = asyncio.create_task(subscribe_and_stop())
    await ready.wait()
    assert await broker.progress_requested(thread_id) is True

    subscription.cancel()
    await asyncio.gather(subscription, return_exceptions=True)

    assert await broker.progress_requested(thread_id) is False
