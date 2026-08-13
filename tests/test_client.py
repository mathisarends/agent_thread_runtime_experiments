import pytest

from client import CliState, _process_notification


def test_events_from_another_subscribed_thread_are_rendered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = CliState(
        thread_id="current-thread",
        active_turn_id="current-turn",
        subscribed_thread_ids={"current-thread", "other-thread"},
    )

    _process_notification(
        state,
        {
            "type": "item.completed",
            "thread_id": "other-thread",
            "turn_id": "other-turn",
            "item": {"type": "agent_message", "content": "remote event"},
        },
    )

    output = capsys.readouterr().out
    assert "[thread other-thread] agent> remote event" in output
    assert state.active_turn_id == "current-turn"


def test_only_current_thread_events_change_active_turn() -> None:
    state = CliState(thread_id="current-thread", active_turn_id="current-turn")

    _process_notification(
        state,
        {
            "type": "turn.completed",
            "thread_id": "other-thread",
            "turn_id": "other-turn",
        },
    )
    assert state.active_turn_id == "current-turn"

    _process_notification(
        state,
        {
            "type": "turn.completed",
            "thread_id": "current-thread",
            "turn_id": "current-turn",
        },
    )
    assert state.active_turn_id is None


def test_agent_text_deltas_are_streamed_without_duplicate_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = CliState(thread_id="current-thread")
    base = {"thread_id": "current-thread", "turn_id": "turn-1"}

    _process_notification(
        state,
        {
            **base,
            "type": "item.started",
            "item_id": "item-1",
            "item_type": "agent_message",
        },
    )
    _process_notification(
        state,
        {**base, "type": "item.delta", "item_id": "item-1", "delta": "Hello "},
    )
    _process_notification(
        state,
        {**base, "type": "item.delta", "item_id": "item-1", "delta": "world"},
    )
    _process_notification(
        state,
        {
            **base,
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": "agent_message",
                "content": "Hello world",
            },
        },
    )

    output = capsys.readouterr().out
    assert "agent> Hello world" in output
    assert output.count("Hello world") == 1
    assert state.streaming_item_ids == set()
