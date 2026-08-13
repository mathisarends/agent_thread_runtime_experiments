import asyncio
from collections.abc import AsyncIterator

import pytest

from gateway.conversation.agent import (
    AgentContext,
    AgentEvent,
    AgentMessageCreated,
    Interrupt,
    Steer,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)
from gateway.conversation.database import create_sqlite_engine
from gateway.conversation.events import ThreadEvent
from gateway.conversation.models import AgentMessageItem, TurnStatus, UserMessageItem
from gateway.conversation.repository import (
    SQLModelRepository,
    TurnAlreadyRunningError,
)
from gateway.conversation.service import AgentThreadService


class EchoRunner:
    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, control
        yield AgentMessageCreated(content=f"Echo: {input}")


class ControlledRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input
        self.started.set()
        message = await control.receive_one()
        if isinstance(message, Steer):
            yield AgentMessageCreated(content=f"Steered: {message.message}")
        elif isinstance(message, Interrupt):
            return


class ToolRunner:
    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input, control
        yield ToolCallCreated(
            name="spotify.search",
            arguments={"query": "Believer"},
            call_id="call-1",
        )
        yield ToolResultCreated(call_id="call-1", output={"track": "Believer"})
        yield AgentMessageCreated(content="Believer is now playing.")


async def collect_events(
    service: AgentThreadService, thread_id: object, count: int
) -> list[ThreadEvent]:
    from uuid import UUID

    assert isinstance(thread_id, UUID)
    events: list[ThreadEvent] = []
    async for event in service.subscribe(thread_id):
        events.append(event)
        if len(events) == count:
            return events
    raise AssertionError("subscription ended")


@pytest.mark.asyncio
async def test_turn_is_persisted_and_fanned_out_in_order() -> None:
    repository = SQLModelRepository(create_sqlite_engine(":memory:"))
    service = AgentThreadService(repository, EchoRunner())
    await service.initialize()
    thread = await service.create_thread()

    first = asyncio.create_task(collect_events(service, thread.id, 4))
    second = asyncio.create_task(collect_events(service, thread.id, 4))
    await asyncio.sleep(0)

    turn = await service.start_turn(thread.id, "hello")
    await service.wait_for_turn(turn.id)
    first_events, second_events = await asyncio.gather(first, second)

    expected = [
        "turn.started",
        "item.completed",
        "item.completed",
        "turn.completed",
    ]
    assert [event.type for event in first_events] == expected
    assert [event.type for event in second_events] == expected

    snapshot = await service.get_thread(thread.id)
    assert snapshot.turns[0].status is TurnStatus.COMPLETED
    assert snapshot.turns[0].completed_at is not None
    assert isinstance(snapshot.items[0], UserMessageItem)
    assert isinstance(snapshot.items[1], AgentMessageItem)
    assert snapshot.items[1].content == "Echo: hello"


@pytest.mark.asyncio
async def test_steering_uses_the_existing_turn_and_is_persisted() -> None:
    runner = ControlledRunner()
    repository = SQLModelRepository(create_sqlite_engine(":memory:"))
    service = AgentThreadService(repository, runner)
    await service.initialize()
    thread = await service.create_thread()
    turn = await service.start_turn(thread.id, "Play Believer")
    await runner.started.wait()

    await service.steer_turn(thread.id, turn.id, "Actually, play Thunder")
    await service.wait_for_turn(turn.id)

    snapshot = await service.get_thread(thread.id)
    assert len(snapshot.turns) == 1
    assert snapshot.turns[0].status is TurnStatus.COMPLETED
    assert [item.type for item in snapshot.items] == [
        "user_message",
        "user_message",
        "agent_message",
    ]
    assert isinstance(snapshot.items[-1], AgentMessageItem)
    assert snapshot.items[-1].content == "Steered: Actually, play Thunder"


@pytest.mark.asyncio
async def test_interrupt_and_one_running_turn_invariant() -> None:
    runner = ControlledRunner()
    repository = SQLModelRepository(create_sqlite_engine(":memory:"))
    service = AgentThreadService(repository, runner)
    await service.initialize()
    thread = await service.create_thread()
    turn = await service.start_turn(thread.id, "wait")
    await runner.started.wait()

    with pytest.raises(TurnAlreadyRunningError):
        await service.start_turn(thread.id, "another")

    await service.interrupt_turn(thread.id, turn.id)
    await service.wait_for_turn(turn.id)
    snapshot = await service.get_thread(thread.id)
    assert snapshot.turns[0].status is TurnStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_tool_call_and_result_are_semantic_items() -> None:
    repository = SQLModelRepository(create_sqlite_engine(":memory:"))
    service = AgentThreadService(repository, ToolRunner())
    await service.initialize()
    thread = await service.create_thread()

    turn = await service.start_turn(thread.id, "Play Believer")
    await service.wait_for_turn(turn.id)

    snapshot = await service.get_thread(thread.id)
    assert [item.type for item in snapshot.items] == [
        "user_message",
        "tool_call",
        "tool_result",
        "agent_message",
    ]
