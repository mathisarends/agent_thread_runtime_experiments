from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_protocol.models import (
    Item,
    Thread,
    ThreadSnapshot,
    Turn,
    TurnStatus,
    UserMessageItem,
)
from pydantic import TypeAdapter, ValidationError

_ITEM_ADAPTER: TypeAdapter[Item] = TypeAdapter(Item)


def _turn(status: TurnStatus) -> Turn:
    return Turn(
        id=uuid4(),
        thread_id=uuid4(),
        status=status,
        created_at=datetime.now(UTC),
    )


def test_active_turn_is_the_one_still_running() -> None:
    running = _turn(TurnStatus.RUNNING)
    snapshot = ThreadSnapshot(
        thread=Thread(id=uuid4(), created_at=datetime.now(UTC)),
        turns=(_turn(TurnStatus.COMPLETED), running),
        items=(),
    )

    assert snapshot.active_turn is running


def test_active_turn_is_none_when_every_turn_is_finished() -> None:
    snapshot = ThreadSnapshot(
        thread=Thread(id=uuid4(), created_at=datetime.now(UTC)),
        turns=(_turn(TurnStatus.COMPLETED), _turn(TurnStatus.FAILED)),
        items=(),
    )

    assert snapshot.active_turn is None


def test_schema_models_are_frozen() -> None:
    item = UserMessageItem(
        id=uuid4(),
        thread_id=uuid4(),
        turn_id=uuid4(),
        created_at=datetime.now(UTC),
        content="hello",
    )

    with pytest.raises(ValidationError):
        item.content = "changed"


def test_item_union_discriminates_on_type() -> None:
    now = datetime.now(UTC).isoformat()
    item = _ITEM_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "thread_id": str(uuid4()),
            "turn_id": str(uuid4()),
            "created_at": now,
            "type": "user_message",
            "content": "hi",
        }
    )

    assert isinstance(item, UserMessageItem)
    assert item.content == "hi"
