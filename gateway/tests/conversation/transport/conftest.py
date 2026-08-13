from collections.abc import Callable

import pytest
from fastapi import FastAPI
from gateway.config import Settings
from gateway.conversation.agents.contracts import AgentRunner, FakeAgentRunner
from gateway.main import create_app

AppFactory = Callable[[AgentRunner], FastAPI]


@pytest.fixture
def make_app() -> AppFactory:
    """Build a FastAPI app wired to an in-memory database and a given runner."""

    def _make(runner: AgentRunner) -> FastAPI:
        return create_app(Settings(database_path=":memory:"), runner)

    return _make


@pytest.fixture
def app(make_app: AppFactory) -> FastAPI:
    """An app backed by the FakeAgentRunner, sufficient for most protocol tests."""
    return make_app(FakeAgentRunner())
