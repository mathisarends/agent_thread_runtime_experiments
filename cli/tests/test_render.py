import pytest
from agent_cli.console import Console
from agent_cli.render import EventRenderer

BASE = {"thread_id": "thread-1", "turn_id": "turn-1"}


@pytest.fixture
def renderer(console: Console) -> EventRenderer:
    return EventRenderer(console)


def test_agent_text_deltas_are_streamed_without_duplicate_completion(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render(
        {**BASE, "type": "item.started", "item_id": "item-1", "item_type": "agent"}
    )
    renderer.render({**BASE, "type": "item.delta", "item_id": "item-1", "delta": "He"})
    renderer.render({**BASE, "type": "item.delta", "item_id": "item-1", "delta": "llo"})
    renderer.render(
        {
            **BASE,
            "type": "item.completed",
            "item": {"id": "item-1", "type": "agent_message", "content": "Hello"},
        }
    )

    output = capsys.readouterr().out
    assert "agent │ Hello" in output
    assert output.count("Hello") == 1
    assert renderer.streaming_item_ids == frozenset()


def test_completed_agent_message_without_stream_is_printed_once(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render(
        {
            **BASE,
            "type": "item.completed",
            "item": {"id": "item-1", "type": "agent_message", "content": "Hi"},
        }
    )

    assert "agent │ Hi" in capsys.readouterr().out


def test_own_user_message_is_not_echoed_back(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    item = {"type": "user_message", "content": "add 1 and 2"}

    renderer.render({**BASE, "type": "item.completed", "item": item})
    assert capsys.readouterr().out == ""

    renderer.render(
        {**BASE, "type": "item.completed", "item": item}, thread_id="other-thread"
    )
    assert "you │ [other-th] add 1 and 2" in capsys.readouterr().out


def test_tool_lifecycle_is_readable(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render(
        {
            **BASE,
            "type": "item.completed",
            "item": {
                "type": "tool_call",
                "name": "add_numbers",
                "arguments": {"a": 1, "b": 2},
            },
        }
    )
    renderer.render(
        {**BASE, "type": "item.completed", "item": {"type": "tool_result", "output": 3}}
    )

    output = capsys.readouterr().out
    assert "tool │ add_numbers(a=1, b=2)" in output
    assert "↳ │ 3" in output


def test_non_dict_tool_arguments_still_render(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render(
        {
            **BASE,
            "type": "item.completed",
            "item": {"type": "tool_call", "name": "echo", "arguments": "raw"},
        }
    )

    assert "echo(raw)" in capsys.readouterr().out


def test_progress_and_failure_are_labelled(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render({**BASE, "type": "turn.progress", "message": "thinking"})
    renderer.render({**BASE, "type": "turn.failed", "error": "boom"})

    output = capsys.readouterr().out
    assert "… │ thinking" in output
    assert "turn failed: boom" in output


def test_turn_boundaries_are_quiet(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render({**BASE, "type": "turn.started"})
    renderer.render({**BASE, "type": "item.started", "item_id": "i", "item_type": "a"})
    assert capsys.readouterr().out == ""

    renderer.render({**BASE, "type": "turn.completed"})
    assert capsys.readouterr().out == "\n"

    renderer.render({**BASE, "type": "turn.interrupted"})
    assert "interrupted" in capsys.readouterr().out


def test_background_thread_events_carry_a_badge(
    renderer: EventRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer.render(
        {**BASE, "type": "item.delta", "item_id": "item-1", "delta": "hi"},
        thread_id="background-thread",
    )

    assert "[backgrou] hi" in capsys.readouterr().out
