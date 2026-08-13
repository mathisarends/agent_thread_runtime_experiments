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
