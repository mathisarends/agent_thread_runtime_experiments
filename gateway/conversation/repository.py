import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from .models import (
    AgentMessageItem,
    Item,
    Thread,
    ThreadSnapshot,
    ToolCallItem,
    ToolResultItem,
    Turn,
    TurnStatus,
    UserMessageItem,
)


class ThreadNotFoundError(LookupError):
    pass


class TurnNotFoundError(LookupError):
    pass


class TurnAlreadyRunningError(RuntimeError):
    pass


class Repository(Protocol):
    async def initialize(self) -> None: ...

    async def create_thread(self, thread: Thread) -> None: ...

    async def get_thread(self, thread_id: UUID) -> ThreadSnapshot: ...

    async def create_turn(self, turn: Turn, initial_item: UserMessageItem) -> None: ...

    async def add_item(self, item: Item) -> None: ...

    async def finish_turn(
        self, turn_id: UUID, status: TurnStatus, completed_at: datetime
    ) -> None: ...


class SQLiteRepository:
    """Small async facade over SQLite; writes are serialized per repository."""

    def __init__(self, path: str | Path = "agent_threads.db") -> None:
        self._path = str(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            if self._connection is not None:
                return
            connection = sqlite3.connect(self._path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id),
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_turn_per_thread
                    ON turns(thread_id) WHERE status = 'running';
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id),
                    turn_id TEXT NOT NULL REFERENCES turns(id),
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS items_by_thread
                    ON items(thread_id, created_at);
                """
            )
            now = datetime.now(UTC).isoformat()
            connection.execute(
                """UPDATE turns SET status = ?, completed_at = ?
                   WHERE status = ?""",
                (TurnStatus.INTERRUPTED, now, TurnStatus.RUNNING),
            )
            connection.commit()
            self._connection = connection

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("repository has not been initialized")
        return self._connection

    async def create_thread(self, thread: Thread) -> None:
        async with self._lock:
            self._db().execute(
                "INSERT INTO threads (id, created_at) VALUES (?, ?)",
                (str(thread.id), thread.created_at.isoformat()),
            )
            self._db().commit()

    async def get_thread(self, thread_id: UUID) -> ThreadSnapshot:
        async with self._lock:
            db = self._db()
            thread_row = db.execute(
                "SELECT id, created_at FROM threads WHERE id = ?", (str(thread_id),)
            ).fetchone()
            if thread_row is None:
                raise ThreadNotFoundError(str(thread_id))
            turn_rows = db.execute(
                """SELECT id, thread_id, status, created_at, completed_at
                   FROM turns WHERE thread_id = ? ORDER BY created_at, rowid""",
                (str(thread_id),),
            ).fetchall()
            item_rows = db.execute(
                """SELECT id, thread_id, turn_id, type, created_at, payload
                   FROM items WHERE thread_id = ? ORDER BY created_at, rowid""",
                (str(thread_id),),
            ).fetchall()
        thread = Thread(UUID(thread_row["id"]), _datetime(thread_row["created_at"]))
        turns = tuple(_turn(row) for row in turn_rows)
        items = tuple(_item(row) for row in item_rows)
        return ThreadSnapshot(thread=thread, turns=turns, items=items)

    async def create_turn(self, turn: Turn, initial_item: UserMessageItem) -> None:
        async with self._lock:
            db = self._db()
            if (
                db.execute(
                    "SELECT 1 FROM threads WHERE id = ?", (str(turn.thread_id),)
                ).fetchone()
                is None
            ):
                raise ThreadNotFoundError(str(turn.thread_id))
            try:
                with db:
                    db.execute(
                        """INSERT INTO turns
                           (id, thread_id, status, created_at, completed_at)
                           VALUES (?, ?, ?, ?, NULL)""",
                        (
                            str(turn.id),
                            str(turn.thread_id),
                            turn.status,
                            turn.created_at.isoformat(),
                        ),
                    )
                    self._insert_item(db, initial_item)
            except sqlite3.IntegrityError as error:
                if "turns.thread_id" in str(error):
                    raise TurnAlreadyRunningError(str(turn.thread_id)) from error
                raise

    async def add_item(self, item: Item) -> None:
        async with self._lock:
            db = self._db()
            with db:
                self._insert_item(db, item)

    async def finish_turn(
        self, turn_id: UUID, status: TurnStatus, completed_at: datetime
    ) -> None:
        if status is TurnStatus.RUNNING:
            raise ValueError("a finished turn cannot have running status")
        async with self._lock:
            cursor = self._db().execute(
                """UPDATE turns SET status = ?, completed_at = ?
                   WHERE id = ? AND status = ?""",
                (
                    status,
                    completed_at.isoformat(),
                    str(turn_id),
                    TurnStatus.RUNNING,
                ),
            )
            self._db().commit()
            if cursor.rowcount == 0:
                raise TurnNotFoundError(str(turn_id))

    @staticmethod
    def _insert_item(db: sqlite3.Connection, item: Item) -> None:
        payload: dict[str, Any]
        if isinstance(item, (UserMessageItem, AgentMessageItem)):
            payload = {"content": item.content}
        elif isinstance(item, ToolCallItem):
            payload = {
                "name": item.name,
                "arguments": item.arguments,
                "call_id": item.call_id,
            }
        else:
            payload = {"call_id": item.call_id, "output": item.output}
        db.execute(
            """INSERT INTO items
               (id, thread_id, turn_id, type, created_at, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(item.id),
                str(item.thread_id),
                str(item.turn_id),
                item.type,
                item.created_at.isoformat(),
                json.dumps(payload),
            ),
        )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _turn(row: sqlite3.Row) -> Turn:
    completed = row["completed_at"]
    return Turn(
        id=UUID(row["id"]),
        thread_id=UUID(row["thread_id"]),
        status=TurnStatus(row["status"]),
        created_at=_datetime(row["created_at"]),
        completed_at=_datetime(completed) if completed else None,
    )


def _item(row: sqlite3.Row) -> Item:
    item_id = UUID(row["id"])
    thread_id = UUID(row["thread_id"])
    turn_id = UUID(row["turn_id"])
    created_at = _datetime(row["created_at"])
    payload = json.loads(row["payload"])
    item_type = row["type"]
    if item_type == "user_message":
        return UserMessageItem(
            item_id, thread_id, turn_id, created_at, content=payload["content"]
        )
    if item_type == "agent_message":
        return AgentMessageItem(
            item_id, thread_id, turn_id, created_at, content=payload["content"]
        )
    if item_type == "tool_call":
        return ToolCallItem(
            item_id,
            thread_id,
            turn_id,
            created_at,
            name=payload["name"],
            arguments=payload["arguments"],
            call_id=payload["call_id"],
        )
    if item_type == "tool_result":
        return ToolResultItem(
            item_id,
            thread_id,
            turn_id,
            created_at,
            call_id=payload["call_id"],
            output=payload["output"],
        )
    raise ValueError(f"unknown item type: {item_type}")
