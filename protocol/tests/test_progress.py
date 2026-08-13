from uuid import uuid4

from agent_protocol.progress import (
    ProgressImportance,
    ProgressMode,
    ProgressResult,
    ProgressSnapshot,
)


def test_only_off_mode_disables_the_agent_progress_capability() -> None:
    assert ProgressMode.OFF.enables_agent is False
    assert ProgressMode.ON_REQUEST.enables_agent is True
    assert ProgressMode.PROACTIVE.enables_agent is True


def test_progress_result_can_be_empty() -> None:
    result = ProgressResult(progress=None)

    assert result.progress is None


def test_progress_snapshot_requires_an_explicit_importance() -> None:
    snapshot = ProgressSnapshot(
        thread_id=uuid4(),
        turn_id=uuid4(),
        message="Working on it.",
        importance=ProgressImportance.HIGH,
    )

    assert snapshot.importance is ProgressImportance.HIGH
