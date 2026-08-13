from fastapi.testclient import TestClient

from gateway.config import Settings
from gateway.conversation.agent import FakeAgentRunner
from main import create_app


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
            assert socket.receive_json()["result"] == {"subscribed": thread_id}

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
