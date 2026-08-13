from gateway.conversation.persistence.repository import (
    Repository,
    ThreadNotFoundError,
    TurnAlreadyRunningError,
    TurnNotFoundError,
)


def test_lookup_errors_are_lookup_errors() -> None:
    assert issubclass(ThreadNotFoundError, LookupError)
    assert issubclass(TurnNotFoundError, LookupError)


def test_turn_already_running_is_a_runtime_error() -> None:
    assert issubclass(TurnAlreadyRunningError, RuntimeError)


def test_repository_is_an_abstract_persistence_boundary() -> None:
    assert Repository.__abstractmethods__ == {
        "initialize",
        "create_thread",
        "get_thread",
        "create_turn",
        "add_item",
        "finish_turn",
    }
