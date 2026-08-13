from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from gateway.config import Settings
from gateway.conversation.agents.contracts import (
    AgentContext,
    AgentEvent,
    AgentMessageCreated,
    AgentProgressUpdated,
    FakeAgentRunner,
    TurnControl,
)
from gateway.conversation.transport.schemas import (
    CONVERSATION_REQUEST_ADAPTER,
    GetThreadRequest,
    RpcMethod,
)
from main import create_app


class ProgressRunner:
    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        del input, control
        assert context.progress_enabled
        yield AgentProgressUpdated(message="Ich recherchiere passende Stellen.")
        yield AgentMessageCreated(content="Fertig.")


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


def test_json_rpc_commands_and_events_share_one_websocket() -> None:
    app = create_app(Settings(database_path=":memory:"), FakeAgentRunner())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            created = socket.receive_json()
            thread_id = created["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "thread.subscribe",
                    "params": {"thread_id": thread_id},
                }
            )
            assert socket.receive_json()["result"] == {
                "subscribed": thread_id,
                "progress": "off",
            }

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "turn.start",
                    "params": {"thread_id": thread_id, "message": "hello"},
                }
            )
            messages = [socket.receive_json() for _ in range(7)]

    response = next(message for message in messages if message.get("id") == 3)
    notifications = [
        message for message in messages if message.get("method") == "thread.event"
    ]
    assert response["result"]["status"] == "running"
    assert [message["params"]["type"] for message in notifications] == [
        "turn.started",
        "item.started",
        "item.completed",
        "item.started",
        "item.completed",
        "turn.completed",
    ]


def test_json_rpc_params_are_validated_by_pydantic() -> None:
    app = create_app(Settings(database_path=":memory:"), FakeAgentRunner())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "thread.get",
                    "params": {"thread_id": "not-a-uuid", "extra": True},
                }
            )
            response = socket.receive_json()

    assert response["id"] == 1
    assert response["error"]["code"] == -32602
    assert "Invalid params" in response["error"]["message"]


def test_unknown_rpc_method_returns_method_not_found() -> None:
    app = create_app(Settings(database_path=":memory:"), FakeAgentRunner())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json(
                {"jsonrpc": "2.0", "id": 7, "method": "thread.unknown"}
            )
            response = socket.receive_json()

    assert response["id"] == 7
    assert response["error"]["code"] == -32601


def test_proactive_progress_is_streamed_over_json_rpc() -> None:
    app = create_app(Settings(database_path=":memory:"), ProgressRunner())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            thread_id = socket.receive_json()["result"]["id"]
            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "thread.subscribe",
                    "params": {"thread_id": thread_id, "progress": "proactive"},
                }
            )
            assert socket.receive_json()["result"]["progress"] == "proactive"
            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "turn.start",
                    "params": {"thread_id": thread_id, "message": "Find jobs"},
                }
            )

            messages = []
            while True:
                message = socket.receive_json()
                messages.append(message)
                if message.get("params", {}).get("type") == "turn.completed":
                    break

    progress = [
        message["params"]
        for message in messages
        if message.get("params", {}).get("type") == "turn.progress"
    ]
    assert [event["message"] for event in progress] == [
        "Ich recherchiere passende Stellen."
    ]
