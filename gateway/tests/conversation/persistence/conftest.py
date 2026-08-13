from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from gateway.conversation.core.models import Thread
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.sqlmodel import SQLModelRepository


@pytest_asyncio.fixture
async def repository() -> SQLModelRepository:
    """A ready-to-use repository backed by a fresh in-memory database."""
    instance = SQLModelRepository(create_sqlite_engine(":memory:"))
    await instance.initialize()
    return instance


@pytest_asyncio.fixture
async def thread(repository: SQLModelRepository) -> Thread:
    """A persisted thread with no turns yet."""
    created = Thread(id=uuid4(), created_at=datetime.now(UTC))
    await repository.create_thread(created)
    return created
