from collections.abc import Callable

import pytest
from agent_cli.commands import ExitRequested, registry
from agent_cli.protocol import Method, ProgressMode
from agent_cli.session import Session
from agent_cli.state import CliState

from .conftest import FakeRpc

pytestmark = pytest.mark.asyncio


def thread_session(
    make_session: Callable[..., Session],
    rpc: FakeRpc | None = None,
    active_turn_id: str | None = None,
) -> Session:
    state = CliState(thread_id="thread-1", active_turn_id=active_turn_id)
    return make_session(rpc or FakeRpc(), state)


async def test_plain_text_starts_a_turn_and_stays_quiet(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc({Method.TURN_START: {"id": "turn-1"}})
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "hello there")

    assert (
        Method.TURN_START,
        {"thread_id": "thread-1", "message": "hello there"},
    ) in rpc.calls
    assert capsys.readouterr().out == ""


async def test_plain_text_steers_while_a_turn_is_active(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc()
    session = thread_session(make_session, rpc, active_turn_id="turn-1")

    await registry.dispatch(session, "actually, in German")

    assert rpc.calls == [
        (
            Method.TURN_STEER,
            {
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "message": "actually, in German",
            },
        )
    ]


async def test_start_and_steer_commands_report_back(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc({Method.TURN_START: {"id": "turn-9"}})
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/start hello")
    assert "turn turn-9" in capsys.readouterr().out

    await registry.dispatch(session, "/steer more")
    assert "steering delivered" in capsys.readouterr().out


async def test_commands_reject_missing_arguments(
    make_session: Callable[..., Session],
) -> None:
    session = thread_session(make_session)

    with pytest.raises(ValueError, match="missing message"):
        await registry.dispatch(session, "/start")
    with pytest.raises(ValueError, match="missing thread ID"):
        await registry.dispatch(session, "/use")


async def test_unknown_commands_point_at_help(
    make_session: Callable[..., Session],
) -> None:
    session = thread_session(make_session)

    with pytest.raises(ValueError, match="unknown command /ne"):
        await registry.dispatch(session, "/ne")


async def test_new_and_use_switch_threads(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc(
        {
            Method.THREAD_CREATE: {"id": "thread-new"},
            Method.THREAD_GET: {"turns": []},
        }
    )
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/new")
    assert session.state.thread_id == "thread-new"

    await registry.dispatch(session, "/use thread-old")
    assert session.state.thread_id == "thread-old"


async def test_get_prints_the_snapshot(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc({Method.THREAD_GET: {"id": "thread-1", "turns": []}})
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/get")

    assert '"id": "thread-1"' in capsys.readouterr().out


async def test_interrupt_requires_and_uses_the_active_turn(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc()
    session = thread_session(make_session, rpc, active_turn_id="turn-1")

    await registry.dispatch(session, "/interrupt")

    assert (
        Method.TURN_INTERRUPT,
        {"thread_id": "thread-1", "turn_id": "turn-1"},
    ) in rpc.calls
    assert "interrupt requested" in capsys.readouterr().out


async def test_subscribe_and_unsubscribe_default_to_the_current_thread(
    make_session: Callable[..., Session],
) -> None:
    rpc = FakeRpc()
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/subscribe")
    assert session.state.subscribed_thread_ids == {"thread-1"}

    await registry.dispatch(session, "/subscribe other-thread")
    assert session.state.subscribed_thread_ids == {"thread-1", "other-thread"}

    await registry.dispatch(session, "/unsubscribe other-thread")
    await registry.dispatch(session, "/unsubscribe")
    assert session.state.subscribed_thread_ids == set()


async def test_progress_mode_is_validated(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc()
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/progress proactive")
    assert session.state.progress_modes == {"thread-1": ProgressMode.PROACTIVE}
    assert "progress mode: proactive" in capsys.readouterr().out

    with pytest.raises(ValueError, match="off, on_request, proactive"):
        await registry.dispatch(session, "/progress loud")


async def test_status_reports_progress_or_its_absence(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc({Method.TURN_PROGRESS_GET: {"progress": {"message": "reading"}}})
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/status")
    assert "reading" in capsys.readouterr().out

    rpc.results[Method.TURN_PROGRESS_GET] = {"progress": None}
    await registry.dispatch(session, "/status")
    assert "no active progress" in capsys.readouterr().out


async def test_raw_rpc_passes_json_params_through(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    rpc = FakeRpc({"thread.get": {"ok": True}})
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, '/rpc thread.get {"thread_id": "x"}')

    assert (("thread.get", {"thread_id": "x"})) in rpc.calls
    assert '"ok": true' in capsys.readouterr().out


async def test_raw_rpc_without_params(make_session: Callable[..., Session]) -> None:
    rpc = FakeRpc()
    session = thread_session(make_session, rpc)

    await registry.dispatch(session, "/rpc thread.create")

    assert ("thread.create", None) in rpc.calls


async def test_raw_rpc_rejects_bad_input(make_session: Callable[..., Session]) -> None:
    session = thread_session(make_session)

    with pytest.raises(ValueError, match="usage: /rpc"):
        await registry.dispatch(session, "/rpc")
    with pytest.raises(ValueError, match="must be a JSON object"):
        await registry.dispatch(session, "/rpc thread.get [1]")


async def test_help_lists_every_command(
    make_session: Callable[..., Session], capsys: pytest.CaptureFixture[str]
) -> None:
    session = thread_session(make_session)

    await registry.dispatch(session, "/?")

    output = capsys.readouterr().out
    assert "<text>" in output
    assert "/use THREAD_ID" in output
    assert "/quit" in output


async def test_quit_signals_the_loop(make_session: Callable[..., Session]) -> None:
    session = thread_session(make_session)

    with pytest.raises(ExitRequested):
        await registry.dispatch(session, "/exit")
