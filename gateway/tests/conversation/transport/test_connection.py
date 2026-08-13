from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.conversation.agents.contracts import (
    AgentContext,
    AgentEvent,
    AgentRunner,
    TurnControl,
)
from gateway.conversation.transport.connection import _rpc_error
from gateway.conversation.transport.schemas import RpcErrorCode

AppFactory = Callable[[AgentRunner], FastAPI]


class HoldingRunner:
    """Waits for a control message so a turn stays running until steered/interrupted."""

    async def run(
        self, context: AgentContext, input: str, control: TurnControl
    ) -> AsyncIterator[AgentEvent]:
        del context, input
        await control.receive_one()
        return
        yield  # pragma: no cover - makes this an async generator


def test_malformed_json_yields_a_parse_error(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_text("not json")
            response = socket.receive_json()

    assert response["id"] is None
    assert response["error"]["code"] == -32700


def test_a_request_missing_the_method_field_is_an_invalid_request(
    app: FastAPI,
) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1})
            response = socket.receive_json()

    assert response["error"]["code"] == -32600


def test_a_non_scalar_request_id_is_reported_as_a_null_id(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": [1], "method": "thread.create"})
            response = socket.receive_json()

    assert response["id"] is None


def test_getting_an_unknown_thread_is_a_resource_not_found_error(
    app: FastAPI,
) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "thread.get",
                    "params": {"thread_id": "cc46f5e6-ea80-4578-b815-61503ef66139"},
                }
            )
            response = socket.receive_json()

    assert response["error"]["code"] == -32004


def test_starting_a_second_turn_on_a_running_thread_is_rejected(
    make_app: AppFactory,
) -> None:
    app = make_app(HoldingRunner())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            thread_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "turn.start",
                    "params": {"thread_id": thread_id, "message": "first"},
                }
            )
            socket.receive_json()

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "turn.start",
                    "params": {"thread_id": thread_id, "message": "second"},
                }
            )
            response = socket.receive_json()

    assert response["error"]["code"] == -32009


def test_a_blank_steer_message_is_an_invalid_params_error(
    make_app: AppFactory,
) -> None:
    app = make_app(HoldingRunner())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            thread_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "turn.start",
                    "params": {"thread_id": thread_id, "message": "first"},
                }
            )
            turn_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "turn.steer",
                    "params": {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "message": " ",
                    },
                }
            )
            response = socket.receive_json()

    assert response["error"]["code"] == -32602
    assert "Invalid params" in response["error"]["message"]


def test_a_non_object_payload_is_reported_with_a_null_id(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json([1, 2, 3])
            response = socket.receive_json()

    assert response["id"] is None
    assert response["error"]["code"] == -32600


def test_unmapped_exceptions_become_an_internal_error() -> None:
    error = _rpc_error(RuntimeError("something the protocol never expected"))

    assert error.code is RpcErrorCode.INTERNAL_ERROR


def test_a_request_without_an_id_gets_no_response(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "method": "thread.create"})
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            response = socket.receive_json()

    assert response["id"] == 1
