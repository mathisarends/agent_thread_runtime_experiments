import pytest
from gateway.conversation.agents.contracts import (
    AgentContext,
    FakeAgentRunner,
    Interrupt,
    Steer,
    TurnControl,
)


@pytest.mark.asyncio
async def test_turn_control_receive_streams_every_sent_message() -> None:
    control = TurnControl()
    await control.send(Steer(message="left"))
    await control.send(Interrupt())

    received = []
    async for message in control.receive():
        received.append(message)
        if len(received) == 2:
            break

    assert received == [Steer(message="left"), Interrupt()]


@pytest.mark.asyncio
async def test_turn_control_receive_one_returns_a_single_message() -> None:
    control = TurnControl()
    await control.send(Steer(message="right"))

    message = await control.receive_one()

    assert message == Steer(message="right")


@pytest.mark.asyncio
async def test_fake_agent_runner_echoes_the_input() -> None:
    runner = FakeAgentRunner()

    events = [
        event
        async for event in runner.run(
            AgentContext(items=()), "hello", TurnControl()
        )
    ]

    assert len(events) == 1
    assert events[0].content == "Echo: hello"


def test_steer_and_interrupt_are_frozen_and_distinguishable_by_type() -> None:
    steer = Steer(message="go left")
    interrupt = Interrupt()

    assert steer.type == "steer"
    assert interrupt.type == "interrupt"
    assert steer != interrupt
