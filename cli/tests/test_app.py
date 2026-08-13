import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from agent_cli import app
from agent_cli.console import Console
from agent_cli.protocol import Method
from agent_cli.rpc import RpcError
from agent_cli.session import Session

from .conftest import FakeRpc

pytestmark = pytest.mark.asyncio


class ScriptedRpc(FakeRpc):
    """A FakeRpc that also replays a fixed list of notifications."""

    def __init__(
        self, results: dict[str, Any] | None = None, events: list[Any] | None = None
    ) -> None:
        super().__init__(results)
        self.events = events or []

    async def notifications(self) -> AsyncIterator[dict[str, Any]]:
        for event in self.events:
            yield event
        await asyncio.Event().wait()  # then idle, like a live connection


@pytest.fixture
def scripted_session(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> Callable[[ScriptedRpc], Session]:
    def install(rpc: ScriptedRpc) -> Session:
        session = Session(rpc, console)  # type: ignore[arg-type]

        @asynccontextmanager
        async def fake_open(url: str, _console: Console) -> AsyncIterator[Session]:
            yield session

        monkeypatch.setattr(app, "open_session", fake_open)
        return session

    return install


@pytest.fixture
def typed_lines(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], None]:
    def install(lines: list[str]) -> None:
        remaining: Iterator[str] = iter(lines)

        def fake_input() -> str:
            try:
                return next(remaining)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr("builtins.input", fake_input)

    return install


async def test_interactive_run_creates_a_thread_and_runs_commands(
    scripted_session: Callable[[ScriptedRpc], Session],
    typed_lines: Callable[[list[str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rpc = ScriptedRpc(
        {
            Method.THREAD_CREATE: {"id": "thread-1"},
            Method.THREAD_GET: {"turns": []},
            Method.TURN_START: {"id": "turn-1"},
        }
    )
    session = scripted_session(rpc)
    typed_lines(["", "hello", "/quit"])

    await app.run_interactive("ws://test", session.console)

    output = capsys.readouterr().out
    assert "connected to ws://test" in output
    assert "Commands" in output
    assert (
        Method.TURN_START,
        {"thread_id": "thread-1", "message": "hello"},
    ) in rpc.calls


async def test_interactive_run_can_resume_a_thread_and_report_errors(
    scripted_session: Callable[[ScriptedRpc], Session],
    typed_lines: Callable[[list[str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_params: Any) -> Any:
        raise RpcError(-32004, "thread is busy")

    rpc = ScriptedRpc({Method.THREAD_GET: {"turns": []}, Method.TURN_START: fail})
    session = scripted_session(rpc)
    typed_lines(["boom"])  # then EOF ends the loop

    await app.run_interactive("ws://test", session.console, "thread-7")

    assert session.state.thread_id == "thread-7"
    assert "thread is busy" in capsys.readouterr().out


async def test_interactive_run_renders_events_while_waiting(
    scripted_session: Callable[[ScriptedRpc], Session],
    typed_lines: Callable[[list[str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rpc = ScriptedRpc(
        {Method.THREAD_CREATE: {"id": "thread-1"}, Method.THREAD_GET: {"turns": []}},
        events=[
            {
                "type": "item.completed",
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "item": {"type": "agent_message", "content": "live"},
            }
        ],
    )
    session = scripted_session(rpc)
    typed_lines([])

    await app.run_interactive("ws://test", session.console)

    assert "agent │ live" in capsys.readouterr().out


async def test_run_once_stops_at_the_terminal_event(
    scripted_session: Callable[[ScriptedRpc], Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rpc = ScriptedRpc(
        {
            Method.THREAD_CREATE: {"id": "thread-1"},
            Method.THREAD_GET: {"turns": []},
            Method.TURN_START: {"id": "turn-1"},
        },
        events=[
            {
                "type": "item.completed",
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "item": {"type": "agent_message", "content": "done"},
            },
            {"type": "turn.completed", "thread_id": "thread-1", "turn_id": "turn-1"},
        ],
    )
    session = scripted_session(rpc)

    await app.run_once("ws://test", session.console, "hi")

    output = capsys.readouterr().out
    assert "agent │ done" in output
    assert "turn turn-1" in output


async def test_open_session_closes_the_rpc_client(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_rpc import FakeSocket

    socket = FakeSocket()

    @asynccontextmanager
    async def fake_connect(url: str) -> AsyncIterator[FakeSocket]:
        yield socket

    monkeypatch.setattr(app, "connect", fake_connect)

    async with app.open_session("ws://test", console) as session:
        assert session.console is console

    assert socket.closed


async def test_run_once_can_target_an_existing_thread(
    scripted_session: Callable[[ScriptedRpc], Session],
) -> None:
    rpc = ScriptedRpc(
        {Method.THREAD_GET: {"turns": []}, Method.TURN_START: {"id": "turn-1"}},
        events=[
            {"type": "turn.failed", "thread_id": "t", "turn_id": "turn-1", "error": "x"}
        ],
    )
    session = scripted_session(rpc)

    await app.run_once("ws://test", session.console, "hi", "thread-7")

    assert session.state.thread_id == "thread-7"
