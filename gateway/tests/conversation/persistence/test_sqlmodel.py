import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from gateway.conversation.core.models import AgentMessageItem, TurnStatus
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.sqlmodel import SQLModelRepository


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

    repository = SQLModelRepository(create_sqlite_engine(str(database)))
    await repository.initialize()
    snapshot = await repository.get_thread(thread_id)

    assert snapshot.turns[0].status is TurnStatus.COMPLETED
    assert isinstance(snapshot.items[0], AgentMessageItem)
    assert snapshot.items[0].content == "legacy message"
