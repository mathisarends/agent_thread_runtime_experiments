from collections.abc import Callable

import pytest
from agent_cli.protocol import Method, ProgressMode
from agent_cli.session import Session
from agent_cli.state import CliState

from .conftest import FakeRpc


def test_events_from_another_subscribed_thread_are_rendered(
    make_session: Callable[..., Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = CliState(
        thread_id="current-thread",
        active_turn_id="current-turn",
        subscribed_thread_ids={"current-thread", "other-thread"},
    )
    session = make_session(state=state)

    session.handle_event(
        {
            "type": "item.completed",
            "thread_id": "other-thread",
            "turn_id": "other-turn",
            "item": {"type": "agent_message", "content": "remote event"},
        }
    )

    output = capsys.readouterr().out
    assert "[other-th] remote event" in output
    assert state.active_turn_id == "current-turn"


def test_only_current_thread_events_change_active_turn(
    make_session: Callable[..., Session],
) -> None:
    state = CliState(thread_id="current-thread", active_turn_id="current-turn")
    session = make_session(state=state)

    session.handle_event(
        {
            "type": "turn.completed",
            "thread_id": "other-thread",
            "turn_id": "other-turn",
        }
    )
    assert state.active_turn_id == "current-turn"

    session.handle_event(
        {
            "type": "turn.completed",
            "thread_id": "current-thread",
            "turn_id": "current-turn",
        }
    )
    assert state.active_turn_id is None
    assert state.finished_turn_ids == {"current-turn"}


def test_turn_started_marks_the_current_turn_active(
    make_session: Callable[..., Session],
) -> None:
    state = CliState(thread_id="thread-1")
    session = make_session(state=state)

    session.handle_event(
        {"type": "turn.started", "thread_id": "thread-1", "turn_id": "turn-1"}
    )

    assert state.active_turn_id == "turn-1"


@pytest.mark.asyncio
async def test_use_thread_subscribes_and_adopts_the_running_turn(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc(
        {
            Method.THREAD_GET: {
                "turns": [
                    {"id": "turn-done", "status": "completed"},
                    {"id": "turn-live", "status": "running"},
                ]
            }
        }
    )
    session = make_session(rpc)

    await session.use_thread("thread-1")

    assert session.state.thread_id == "thread-1"
    assert session.state.active_turn_id == "turn-live"
    assert session.state.subscribed_thread_ids == {"thread-1"}
    assert (
        Method.THREAD_SUBSCRIBE,
        {"thread_id": "thread-1", "progress": "off"},
    ) in rpc.calls


@pytest.mark.asyncio
async def test_use_thread_without_running_turn_clears_the_active_turn(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc({Method.THREAD_GET: {"turns": []}})
    session = make_session(rpc, CliState(active_turn_id="stale"))

    await session.use_thread("thread-1")

    assert session.state.active_turn_id is None


@pytest.mark.asyncio
async def test_create_thread_uses_the_new_thread(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc(
        {
            Method.THREAD_CREATE: {"id": "thread-new"},
            Method.THREAD_GET: {"turns": []},
        }
    )
    session = make_session(rpc)

    thread_id = await session.create_thread()

    assert thread_id == "thread-new"
    assert session.state.thread_id == "thread-new"


@pytest.mark.asyncio
async def test_start_turn_ignores_a_turn_that_already_finished(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc({Method.TURN_START: {"id": "turn-1"}})
    state = CliState(thread_id="thread-1", finished_turn_ids={"turn-1"})
    session = make_session(rpc, state)

    assert await session.start_turn("hello") == "turn-1"
    assert state.active_turn_id is None


@pytest.mark.asyncio
async def test_steer_and_interrupt_require_an_active_turn(
    make_session: Callable[..., Session],
) -> None:
    session = make_session(state=CliState(thread_id="thread-1"))

    with pytest.raises(ValueError, match="no active turn"):
        await session.steer_turn("hello")
    with pytest.raises(ValueError, match="no active turn"):
        await session.interrupt_turn()


@pytest.mark.asyncio
async def test_operations_require_a_current_thread(
    make_session: Callable[..., Session],
) -> None:
    session = make_session()

    with pytest.raises(ValueError, match="no current thread"):
        await session.start_turn("hello")


@pytest.mark.asyncio
async def test_unsubscribe_forgets_the_thread(
    make_session: Callable[..., Session],
) -> None:
    session = make_session()
    await session.subscribe("thread-1", ProgressMode.PROACTIVE)
    assert session.state.progress_modes == {"thread-1": ProgressMode.PROACTIVE}

    await session.unsubscribe("thread-1")

    assert session.state.subscribed_thread_ids == set()
    assert session.state.progress_modes == {}
