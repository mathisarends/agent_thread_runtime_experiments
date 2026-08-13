from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_protocol import (
    CONVERSATION_REQUEST_ADAPTER,
    THREAD_EVENT_ADAPTER,
    AgentMessageItem,
    ItemCompleted,
    ItemDelta,
    StartTurnRequest,
    ThreadEventType,
)
from pydantic import ValidationError


def test_request_union_uses_the_method_discriminator() -> None:
    request = CONVERSATION_REQUEST_ADAPTER.validate_python(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "turn.start",
            "params": {"thread_id": str(uuid4()), "message": "Hello"},
        }
    )

    assert isinstance(request, StartTurnRequest)
    assert request.expects_response is True


def test_event_union_uses_the_type_discriminator() -> None:
    event = THREAD_EVENT_ADAPTER.validate_python(
        {
            "type": "item.delta",
            "thread_id": str(uuid4()),
            "turn_id": str(uuid4()),
            "item_id": str(uuid4()),
            "delta": "Hi",
        }
    )

    assert isinstance(event, ItemDelta)
    assert event.type is ThreadEventType.ITEM_DELTA


def test_nested_completed_item_is_typed() -> None:
    thread_id = uuid4()
    turn_id = uuid4()
    event = THREAD_EVENT_ADAPTER.validate_python(
        {
            "type": "item.completed",
            "thread_id": thread_id,
            "turn_id": turn_id,
            "item": {
                "id": uuid4(),
                "thread_id": thread_id,
                "turn_id": turn_id,
                "created_at": datetime.now(UTC),
                "type": "agent_message",
                "content": "Done",
            },
        }
    )

    assert isinstance(event, ItemCompleted)
    assert isinstance(event.item, AgentMessageItem)


def test_unknown_events_are_rejected() -> None:
    with pytest.raises(ValidationError):
        THREAD_EVENT_ADAPTER.validate_python(
            {"type": "turn.future", "thread_id": uuid4(), "turn_id": uuid4()}
        )
