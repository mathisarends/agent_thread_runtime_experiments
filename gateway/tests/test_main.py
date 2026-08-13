from typing import Any

import pytest
from fastapi.testclient import TestClient
from gateway.config import Settings
from gateway.conversation.agents.contracts import FakeAgentRunner
from gateway.main import create_app

from gateway import main as main_module


def test_create_app_installs_the_conversation_router_and_schema() -> None:
    app = create_app(Settings(database_path=":memory:"), FakeAgentRunner())

    with TestClient(app) as client:
        schema_response = client.get("/v1/conversation/schema")
        with client.websocket_connect("/v1/conversation") as socket:
            socket.send_json({"jsonrpc": "2.0", "id": 1, "method": "thread.create"})
            create_response = socket.receive_json()

    assert schema_response.status_code == 200
    assert create_response["result"]["id"] is not None


def test_create_app_defaults_to_settings_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    app = create_app()

    assert app.title == "Agent Thread Runtime"


def test_main_runs_uvicorn_with_the_app_import_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(target: str, **kwargs: Any) -> None:
        calls.append({"target": target, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)

    main_module.main()

    assert calls == [
        {
            "target": "gateway.main:app",
            "host": "127.0.0.1",
            "port": 8000,
            "reload": False,
        }
    ]
