from typing import Any

import pytest
from agent_cli import main as main_module
from agent_cli.console import Console
from agent_cli.main import DEFAULT_URL, build_parser, main


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    async def fake_interactive(url: str, console: Console, thread: str | None) -> None:
        calls["interactive"] = (url, console, thread)

    async def fake_once(
        url: str, console: Console, message: str, thread: str | None
    ) -> None:
        calls["once"] = (url, console, message, thread)

    monkeypatch.setattr(main_module, "run_interactive", fake_interactive)
    monkeypatch.setattr(main_module, "run_once", fake_once)
    return calls


def test_defaults_start_an_interactive_session(recorded: dict[str, Any]) -> None:
    main([])

    url, console, thread = recorded["interactive"]
    assert (url, thread) == (DEFAULT_URL, None)
    assert isinstance(console, Console)
    assert "once" not in recorded


def test_message_runs_once_against_the_given_thread(recorded: dict[str, Any]) -> None:
    main(["--url", "ws://host/v1", "--thread", "thread-7", "--message", "hi"])

    url, _console, message, thread = recorded["once"]
    assert (url, message, thread) == ("ws://host/v1", "hi", "thread-7")


def test_no_color_disables_styling(recorded: dict[str, Any]) -> None:
    main(["--no-color"])

    _url, console, _thread = recorded["interactive"]
    assert console.theme.enabled is False


def test_interrupting_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def interrupted(*_args: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "run_interactive", interrupted)

    main([])  # must not raise


def test_the_parser_documents_its_flags() -> None:
    help_text = build_parser().format_help()

    for flag in ("--url", "--thread", "--message", "--no-color"):
        assert flag in help_text
