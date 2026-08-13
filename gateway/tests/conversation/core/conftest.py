from collections.abc import Awaitable, Callable, Iterator

import pytest
from gateway.conversation.agents.contracts import AgentRunner
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.sqlmodel import SQLModelRepository
from sqlalchemy.engine import Engine

ServiceFactory = Callable[[AgentRunner], Awaitable[AgentThreadService]]


@pytest.fixture
def make_service() -> Iterator[ServiceFactory]:
    """Build a ready-to-use service backed by a fresh in-memory database."""
    engines: list[Engine] = []

    async def _make(runner: AgentRunner) -> AgentThreadService:
        engine = create_sqlite_engine(":memory:")
        engines.append(engine)
        service = AgentThreadService(SQLModelRepository(engine), runner)
        await service.initialize()
        return service

    yield _make

    for engine in engines:
        engine.dispose()
