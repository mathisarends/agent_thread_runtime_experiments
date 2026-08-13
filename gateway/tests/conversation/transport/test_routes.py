from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.conversation.agents.contracts import (
    AgentContext,
    AgentEvent,
    AgentMessageCreated,
    AgentProgressUpdated,
    AgentRunner,
    TurnControl,
)

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


def test_json_rpc_commands_and_events_share_one_websocket(app: FastAPI) -> None:
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


def test_the_full_rpc_method_surface_is_reachable_over_one_socket(
    app: FastAPI,
) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            thread_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "thread.get",
                    "params": {"thread_id": thread_id},
                }
            )
            get_response = socket.receive_json()

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "thread.subscribe",
                    "params": {"thread_id": thread_id},
                }
            )
            socket.receive_json()

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "thread.unsubscribe",
                    "params": {"thread_id": thread_id},
                }
            )
            unsubscribe_response = socket.receive_json()

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "turn.start",
                    "params": {"thread_id": thread_id, "message": "hello"},
                }
            )
            turn_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "turn.progress.get",
                    "params": {"thread_id": thread_id},
                }
            )
            progress_response = socket.receive_json()

    assert get_response["result"]["thread"]["id"] == thread_id
    assert unsubscribe_response["result"] == {"unsubscribed": thread_id}
    assert isinstance(turn_id, str)
    assert progress_response["result"] == {"progress": None}


def test_resubscribing_to_the_same_thread_replaces_the_previous_subscription(
    app: FastAPI,
) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            thread_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "thread.subscribe",
                    "params": {"thread_id": thread_id},
                }
            )
            socket.receive_json()

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "thread.subscribe",
                    "params": {"thread_id": thread_id},
                }
            )
            second_subscribe = socket.receive_json()

    assert second_subscribe["result"] == {"subscribed": thread_id, "progress": "off"}


def test_steering_a_running_turn_over_json_rpc(make_app: AppFactory) -> None:
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
                    "params": {"thread_id": thread_id, "message": "hello"},
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
                        "message": "actually, do this instead",
                    },
                }
            )
            steer_response = socket.receive_json()

    assert steer_response["result"] is None


def test_interrupting_a_running_turn_over_json_rpc(make_app: AppFactory) -> None:
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
                    "params": {"thread_id": thread_id, "message": "hello"},
                }
            )
            turn_id = socket.receive_json()["result"]["id"]

            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "turn.interrupt",
                    "params": {"thread_id": thread_id, "turn_id": turn_id},
                }
            )
            interrupt_response = socket.receive_json()

    assert interrupt_response["result"] is None


def test_json_rpc_params_are_validated_by_pydantic(app: FastAPI) -> None:
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


def test_unknown_rpc_method_returns_method_not_found(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 7, "method": "thread.unknown"})
            response = socket.receive_json()

    assert response["id"] == 7
    assert response["error"]["code"] == -32601


def test_proactive_progress_is_streamed_over_json_rpc(make_app: AppFactory) -> None:
    app = make_app(ProgressRunner())

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
