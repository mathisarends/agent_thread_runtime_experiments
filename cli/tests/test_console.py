import io

import pytest
from agent_cli.console import CLEAR_LINE, Console
from agent_cli.theme import Theme, color_supported


@pytest.fixture
def buffer() -> io.StringIO:
    return io.StringIO()


def test_messages_share_a_fixed_width_gutter(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=False), buffer)

    console.message("you", "hi")
    console.message("agent", "hello")

    assert buffer.getvalue() == "   you │ hi\n agent │ hello\n"


def test_partial_lines_are_closed_before_the_next_block(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=False), buffer)

    console.message("agent", newline=False)
    console.write("streamed")
    console.note("done")

    assert buffer.getvalue() == " agent │ streamed\n     ↳ │ done\n"


def test_break_line_is_a_no_op_at_line_start(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=False), buffer)

    console.line("text")
    console.break_line()
    console.break_line()

    assert buffer.getvalue() == "text\n"


def test_json_and_banner_render_plainly(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=False), buffer)

    console.banner("agent cli", "connected")
    console.json({"id": "thread-1"})

    assert buffer.getvalue() == ('agent cli\nconnected\n{\n  "id": "thread-1"\n}\n')


def test_banner_without_subtitle(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=False), buffer)

    console.banner("agent cli")

    assert buffer.getvalue() == "agent cli\n"


def test_badge_shortens_background_thread_ids(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=False), buffer)

    assert console.badge(None) == ""
    assert console.badge("0123456789abcdef") == "[01234567] "


def test_colors_are_applied_when_the_theme_is_enabled(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=True), buffer)

    console.message("you", "hi", style=console.theme.user)

    assert "\033[36m" in buffer.getvalue()


@pytest.mark.asyncio
async def test_live_output_redraws_the_pending_prompt(
    monkeypatch: pytest.MonkeyPatch, buffer: io.StringIO
) -> None:
    console = Console(Theme(enabled=True), buffer)

    def type_while_an_event_arrives() -> str:
        console.message("agent", "hi")
        return ""

    monkeypatch.setattr("builtins.input", type_while_an_event_arrives)

    await console.ask("you")

    output = buffer.getvalue()
    prompt_count = output.count("you")
    assert CLEAR_LINE in output
    assert prompt_count == 2, "prompt is drawn, erased for the event, then redrawn"


@pytest.mark.asyncio
async def test_without_colors_the_prompt_is_not_erased(
    monkeypatch: pytest.MonkeyPatch, buffer: io.StringIO
) -> None:
    console = Console(Theme(enabled=False), buffer)

    def type_while_an_event_arrives() -> str:
        console.note("event")
        return "typed"

    monkeypatch.setattr("builtins.input", type_while_an_event_arrives)

    assert await console.ask("you") == "typed"

    output = buffer.getvalue()
    assert CLEAR_LINE not in output
    assert "↳ │ event" in output


def test_color_support_follows_the_stream_and_no_color(
    monkeypatch: pytest.MonkeyPatch, buffer: io.StringIO
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color_supported(buffer) is False

    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert color_supported(Tty()) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_supported(Tty()) is False


def test_theme_for_stream_can_be_forced_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)

    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert Theme.for_stream(Tty()).enabled is True
    assert Theme.for_stream(Tty(), force_plain=True).enabled is False


def test_empty_text_is_never_written(buffer: io.StringIO) -> None:
    console = Console(Theme(enabled=True), buffer)

    console.write("")

    assert buffer.getvalue() == ""
    assert console.theme.user("") == ""


def test_the_stream_defaults_to_stdout_at_write_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    console = Console(Theme(enabled=False))

    console.line("to stdout")

    assert capsys.readouterr().out == "to stdout\n"
