import asyncio
from collections.abc import AsyncIterator

import pytest

from gateway.conversation.agent import (
    AgentContext,
    AgentEvent,
    AgentProgressUpdated,
    AgentRunner,
    TurnControl,
)
from gateway.conversation.database import create_sqlite_engine
from gateway.conversation.events import EventBroker, TurnProgress
from gateway.conversation.progress import ProgressMode
from gateway.conversation.repository import SQLModelRepository
from gateway.conversation.service import AgentThreadService


class ProgressRunner:
    def __init__(self) -> None:
        self.context: AgentContext | None = None
        self.reported = asyncio.Event()

    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        del input
        self.context = context
        if context.progress_enabled:
            yield AgentProgressUpdated(message="Ich vergleiche passende Stellen.")
            self.reported.set()
        await control.receive_one()


async def _hold_subscription(
    service: AgentThreadService,
    thread_id: object,
    mode: ProgressMode,
    ready: asyncio.Event,
) -> None:
    from uuid import UUID

    assert isinstance(thread_id, UUID)
    async for _ in service.subscribe(thread_id, progress=mode, _ready=ready):
        pass


async def _new_service(runner: AgentRunner) -> tuple[AgentThreadService, object]:
    repository = SQLModelRepository(create_sqlite_engine(":memory:"))
    service = AgentThreadService(repository, runner)
    await service.initialize()
    return service, await service.create_thread()


@pytest.mark.asyncio
async def test_progress_capability_is_disabled_without_demand() -> None:
    runner = ProgressRunner()
    service, thread = await _new_service(runner)

    turn = await service.start_turn(thread.id, "Find jobs")
    await asyncio.sleep(0)

    assert runner.context is not None
    assert runner.context.progress_enabled is False
    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)


@pytest.mark.asyncio
async def test_on_request_enables_agent_and_retains_latest_progress() -> None:
    runner = ProgressRunner()
    service, thread = await _new_service(runner)
    ready = asyncio.Event()
    subscription = asyncio.create_task(
        _hold_subscription(service, thread.id, ProgressMode.ON_REQUEST, ready)
    )
    await ready.wait()

    turn = await service.start_turn(thread.id, "Find jobs")
    await runner.reported.wait()
    result = await service.get_progress(thread.id)

    assert runner.context is not None
    assert runner.context.progress_enabled is True
    assert result.progress is not None
    assert result.progress.turn_id == turn.id
    assert result.progress.message == "Ich vergleiche passende Stellen."

    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)
    subscription.cancel()
    await asyncio.gather(subscription, return_exceptions=True)


@pytest.mark.asyncio
async def test_broker_only_pushes_progress_to_proactive_subscribers() -> None:
    broker = EventBroker()
    thread_id = __import__("uuid").uuid4()
    turn_id = __import__("uuid").uuid4()
    proactive_ready = asyncio.Event()
    request_ready = asyncio.Event()

    async def first(mode: ProgressMode, ready: asyncio.Event) -> object:
        async for event in broker.subscribe(thread_id, progress=mode, ready=ready):
            return event
        raise AssertionError("subscription ended")

    proactive = asyncio.create_task(first(ProgressMode.PROACTIVE, proactive_ready))
    on_request = asyncio.create_task(first(ProgressMode.ON_REQUEST, request_ready))
    await asyncio.gather(proactive_ready.wait(), request_ready.wait())
    await broker.publish(
        TurnProgress(
            thread_id=thread_id,
            turn_id=turn_id,
            message="Searching",
        )
    )

    event = await asyncio.wait_for(proactive, timeout=1)
    assert isinstance(event, TurnProgress)
    assert not on_request.done()
    on_request.cancel()
    await asyncio.gather(on_request, return_exceptions=True)
