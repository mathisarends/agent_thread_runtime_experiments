from collections.abc import Awaitable, Callable

import pytest
from gateway.conversation.agents.contracts import AgentRunner
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.sqlmodel import SQLModelRepository

ServiceFactory = Callable[[AgentRunner], Awaitable[AgentThreadService]]


@pytest.fixture
def make_service() -> ServiceFactory:
    """Build a ready-to-use service backed by a fresh in-memory database."""

    async def _make(runner: AgentRunner) -> AgentThreadService:
        repository = SQLModelRepository(create_sqlite_engine(":memory:"))
        service = AgentThreadService(repository, runner)
        await service.initialize()
        return service

    return _make
