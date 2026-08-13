from datetime import UTC, datetime
from uuid import uuid4

import pytest
from gateway.conversation.agents.context import RepositoryContextBuilder
from gateway.conversation.core.models import Thread, Turn, TurnStatus, UserMessageItem
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.sqlmodel import SQLModelRepository


@pytest.mark.asyncio
async def test_build_returns_the_thread_items_with_progress_disabled() -> None:
    engine = create_sqlite_engine(":memory:")
    repository = SQLModelRepository(engine)
    await repository.initialize()
    builder = RepositoryContextBuilder(repository)

    thread = Thread(id=uuid4(), created_at=datetime.now(UTC))
    await repository.create_thread(thread)
    turn = Turn(
        id=uuid4(),
        thread_id=thread.id,
        status=TurnStatus.RUNNING,
        created_at=datetime.now(UTC),
    )
    item = UserMessageItem(
        id=uuid4(),
        thread_id=thread.id,
        turn_id=turn.id,
        created_at=datetime.now(UTC),
        content="hello",
    )
    await repository.create_turn(turn, item)

    context = await builder.build(thread.id)
    engine.dispose()

    assert context.progress_enabled is False
    assert len(context.items) == 1
    assert isinstance(context.items[0], UserMessageItem)
    assert context.items[0].content == "hello"
