import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from gateway.conversation.core.models import (
    AgentMessageItem,
    Thread,
    Turn,
    TurnStatus,
    UserMessageItem,
)
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.repository import (
    ThreadNotFoundError,
    TurnAlreadyRunningError,
    TurnNotFoundError,
)
from gateway.conversation.persistence.sqlmodel import SQLModelRepository
from sqlalchemy.exc import IntegrityError


def _turn(thread_id: UUID, status: TurnStatus = TurnStatus.RUNNING) -> Turn:
    return Turn(
        id=uuid4(), thread_id=thread_id, status=status, created_at=datetime.now(UTC)
    )


def _user_message(thread_id: UUID, turn_id: UUID) -> UserMessageItem:
    return UserMessageItem(
        id=uuid4(),
        thread_id=thread_id,
        turn_id=turn_id,
        created_at=datetime.now(UTC),
        content="hello",
    )


@pytest.mark.asyncio
async def test_sqlmodel_repository_reads_the_original_sqlite_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"
    thread_id, turn_id, item_id = uuid4(), uuid4(), uuid4()
    created_at = datetime.now(UTC).isoformat()
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE threads (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE turns (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES threads(id),
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE items (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES threads(id),
                turn_id TEXT NOT NULL REFERENCES turns(id),
                type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO threads VALUES (?, ?)", (str(thread_id), created_at)
        )
        connection.execute(
            "INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
            (
                str(turn_id),
                str(thread_id),
                TurnStatus.COMPLETED,
                created_at,
                created_at,
            ),
        )
        connection.execute(
            "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(item_id),
                str(thread_id),
                str(turn_id),
                "agent_message",
                created_at,
                '{"content": "legacy message"}',
            ),
        )

    engine = create_sqlite_engine(str(database))
    repository = SQLModelRepository(engine)
    await repository.initialize()
    snapshot = await repository.get_thread(thread_id)
    engine.dispose()

    assert snapshot.turns[0].status is TurnStatus.COMPLETED
    assert isinstance(snapshot.items[0], AgentMessageItem)
    assert snapshot.items[0].content == "legacy message"


@pytest.mark.asyncio
async def test_get_thread_raises_when_the_thread_does_not_exist(
    repository: SQLModelRepository,
) -> None:
    with pytest.raises(ThreadNotFoundError):
        await repository.get_thread(uuid4())


@pytest.mark.asyncio
async def test_create_turn_raises_when_the_thread_does_not_exist(
    repository: SQLModelRepository,
) -> None:
    orphan_turn = _turn(uuid4())

    with pytest.raises(ThreadNotFoundError):
        await repository.create_turn(
            orphan_turn, _user_message(orphan_turn.thread_id, orphan_turn.id)
        )


@pytest.mark.asyncio
async def test_create_turn_rejects_a_second_running_turn_for_the_same_thread(
    repository: SQLModelRepository, thread: Thread
) -> None:
    first = _turn(thread.id)
    await repository.create_turn(first, _user_message(thread.id, first.id))

    second = _turn(thread.id)
    with pytest.raises(TurnAlreadyRunningError):
        await repository.create_turn(second, _user_message(thread.id, second.id))


@pytest.mark.asyncio
async def test_create_turn_reraises_unrelated_integrity_errors(
    repository: SQLModelRepository, thread: Thread
) -> None:
    turn = _turn(thread.id)
    await repository.create_turn(turn, _user_message(thread.id, turn.id))
    await repository.finish_turn(turn.id, TurnStatus.COMPLETED, datetime.now(UTC))

    duplicate_id_turn = Turn(
        id=turn.id,
        thread_id=thread.id,
        status=TurnStatus.RUNNING,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(IntegrityError):
        await repository.create_turn(
            duplicate_id_turn, _user_message(thread.id, duplicate_id_turn.id)
        )


@pytest.mark.asyncio
async def test_finish_turn_rejects_the_running_status(
    repository: SQLModelRepository, thread: Thread
) -> None:
    turn = _turn(thread.id)
    await repository.create_turn(turn, _user_message(thread.id, turn.id))

    with pytest.raises(ValueError, match="cannot have running status"):
        await repository.finish_turn(turn.id, TurnStatus.RUNNING, datetime.now(UTC))


@pytest.mark.asyncio
async def test_finish_turn_raises_when_the_turn_is_unknown(
    repository: SQLModelRepository,
) -> None:
    with pytest.raises(TurnNotFoundError):
        await repository.finish_turn(uuid4(), TurnStatus.COMPLETED, datetime.now(UTC))


@pytest.mark.asyncio
async def test_finish_turn_raises_when_the_turn_is_already_finished(
    repository: SQLModelRepository, thread: Thread
) -> None:
    turn = _turn(thread.id)
    await repository.create_turn(turn, _user_message(thread.id, turn.id))
    await repository.finish_turn(turn.id, TurnStatus.COMPLETED, datetime.now(UTC))

    with pytest.raises(TurnNotFoundError):
        await repository.finish_turn(turn.id, TurnStatus.COMPLETED, datetime.now(UTC))


@pytest.mark.asyncio
async def test_add_item_appends_to_an_existing_turn(
    repository: SQLModelRepository, thread: Thread
) -> None:
    turn = _turn(thread.id)
    initial = _user_message(thread.id, turn.id)
    await repository.create_turn(turn, initial)

    follow_up = _user_message(thread.id, turn.id)
    await repository.add_item(follow_up)

    snapshot = await repository.get_thread(thread.id)
    assert [item.id for item in snapshot.items] == [initial.id, follow_up.id]


@pytest.mark.asyncio
async def test_initialize_recovers_turns_left_running_by_an_unclean_shutdown(
    tmp_path: Path,
) -> None:
    database = tmp_path / "recovery.db"
    thread_id, turn_id, item_id = uuid4(), uuid4(), uuid4()

    first_engine = create_sqlite_engine(str(database))
    first_run = SQLModelRepository(first_engine)
    await first_run.initialize()
    await first_run.create_thread(Thread(id=thread_id, created_at=datetime.now(UTC)))
    await first_run.create_turn(
        Turn(
            id=turn_id,
            thread_id=thread_id,
            status=TurnStatus.RUNNING,
            created_at=datetime.now(UTC),
        ),
        UserMessageItem(
            id=item_id,
            thread_id=thread_id,
            turn_id=turn_id,
            created_at=datetime.now(UTC),
            content="still running when the process died",
        ),
    )
    first_engine.dispose()

    second_engine = create_sqlite_engine(str(database))
    second_run = SQLModelRepository(second_engine)
    await second_run.initialize()
    snapshot = await second_run.get_thread(thread_id)
    second_engine.dispose()

    assert snapshot.turns[0].status is TurnStatus.INTERRUPTED
    assert snapshot.turns[0].completed_at is not None
