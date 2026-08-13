import pytest
from gateway.conversation.transport.schemas import (
    CONVERSATION_REQUEST_ADAPTER,
    CreateThreadRequest,
    GetThreadRequest,
    RpcMethod,
)
from pydantic import ValidationError


def test_rpc_request_union_uses_method_as_discriminator() -> None:
    request = CONVERSATION_REQUEST_ADAPTER.validate_python(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "thread.get",
            "params": {"thread_id": "cc46f5e6-ea80-4578-b815-61503ef66139"},
        }
    )

    assert isinstance(request, GetThreadRequest)
    assert request.method is RpcMethod.THREAD_GET


def test_unknown_method_fails_discrimination() -> None:
    with pytest.raises(ValidationError):
        CONVERSATION_REQUEST_ADAPTER.validate_python(
            {"jsonrpc": "2.0", "id": 1, "method": "thread.unknown"}
        )


def test_a_request_without_an_id_does_not_expect_a_response() -> None:
    notification = CreateThreadRequest.model_validate(
        {"jsonrpc": "2.0", "method": "thread.create"}
    )
    request = CreateThreadRequest.model_validate(
        {"jsonrpc": "2.0", "id": 1, "method": "thread.create"}
    )

    assert notification.expects_response is False
    assert request.expects_response is True


def test_create_thread_params_default_to_empty() -> None:
    request = CreateThreadRequest.model_validate(
        {"jsonrpc": "2.0", "id": 1, "method": "thread.create"}
    )

    assert request.params.model_dump() == {}


def test_rpc_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CreateThreadRequest.model_validate(
            {"jsonrpc": "2.0", "id": 1, "method": "thread.create", "unexpected": True}
        )
