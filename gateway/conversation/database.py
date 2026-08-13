from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Column, Index, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, create_engine


class ThreadRow(SQLModel, table=True):
    __tablename__: ClassVar[str] = "threads"

    id: str = Field(primary_key=True)
    created_at: datetime


class TurnRow(SQLModel, table=True):
    __tablename__: ClassVar[str] = "turns"
    __table_args__ = (
        Index(
            "one_running_turn_per_thread",
            "thread_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: str = Field(primary_key=True)
    thread_id: str = Field(foreign_key="threads.id", index=True)
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class ItemRow(SQLModel, table=True):
    __tablename__: ClassVar[str] = "items"

    id: str = Field(primary_key=True)
    thread_id: str = Field(foreign_key="threads.id", index=True)
    turn_id: str = Field(foreign_key="turns.id", index=True)
    type: str
    created_at: datetime
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


def create_sqlite_engine(path: str) -> Engine:
    """Create a SQLite engine suitable for the app and in-memory tests."""
    in_memory = path == ":memory:"
    url = "sqlite://" if in_memory else f"sqlite:///{path}"
    options: dict[str, Any] = {
        "connect_args": {"check_same_thread": False},
    }
    if in_memory:
        options["poolclass"] = StaticPool
    engine = create_engine(url, **options)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    return engine
