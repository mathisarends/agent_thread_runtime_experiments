from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.conversation.agent import FakeAgentRunner
from gateway.conversation.repository import SQLiteRepository
from gateway.conversation.routes import create_router
from gateway.conversation.service import AgentThreadService


def test_json_rpc_commands_and_events_share_one_websocket() -> None:
    repository = SQLiteRepository(":memory:")
    service = AgentThreadService(repository, FakeAgentRunner())
    app = FastAPI()
    app.include_router(create_router(service))

    with TestClient(app) as client:
        client.portal.call(service.initialize)
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
            messages = [socket.receive_json() for _ in range(5)]

    response = next(message for message in messages if message.get("id") == 3)
    notifications = [
        message for message in messages if message.get("method") == "thread.event"
    ]
    assert response["result"]["status"] == "running"
    assert [message["params"]["type"] for message in notifications] == [
        "turn.started",
        "item.completed",
        "item.completed",
        "turn.completed",
    ]
