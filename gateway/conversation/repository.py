import asyncio
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, col, select

from gateway.conversation.database import ItemRow, ThreadRow, TurnRow
from gateway.conversation.models import (
    Item,
    Thread,
    ThreadSnapshot,
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


_ITEM_ADAPTER: TypeAdapter[Item] = TypeAdapter(Item)


class SQLModelRepository:
    """SQLModel persistence with short sessions and serialized writes."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            SQLModel.metadata.create_all(self._engine)
            with Session(self._engine) as session:
                running = session.exec(
                    select(TurnRow).where(TurnRow.status == TurnStatus.RUNNING)
                ).all()
                now = datetime.now(UTC)
                for row in running:
                    row.status = TurnStatus.INTERRUPTED
                    row.completed_at = now
                    session.add(row)
                session.commit()

    async def create_thread(self, thread: Thread) -> None:
        async with self._lock:
            with Session(self._engine) as session:
                session.add(ThreadRow(id=str(thread.id), created_at=thread.created_at))
                session.commit()

    async def get_thread(self, thread_id: UUID) -> ThreadSnapshot:
        with Session(self._engine) as session:
            thread_row = session.get(ThreadRow, str(thread_id))
            if thread_row is None:
                raise ThreadNotFoundError(str(thread_id))
            turn_rows = session.exec(
                select(TurnRow)
                .where(TurnRow.thread_id == str(thread_id))
                .order_by(col(TurnRow.created_at), col(TurnRow.id))
            ).all()
            item_rows = session.exec(
                select(ItemRow)
                .where(ItemRow.thread_id == str(thread_id))
                .order_by(col(ItemRow.created_at), col(ItemRow.id))
            ).all()
        return ThreadSnapshot(
            thread=_thread_from_row(thread_row),
            turns=tuple(_turn_from_row(row) for row in turn_rows),
            items=tuple(_item_from_row(row) for row in item_rows),
        )

    async def create_turn(self, turn: Turn, initial_item: UserMessageItem) -> None:
        async with self._lock:
            with Session(self._engine) as session:
                if session.get(ThreadRow, str(turn.thread_id)) is None:
                    raise ThreadNotFoundError(str(turn.thread_id))
                try:
                    session.add(_turn_to_row(turn))
                    session.flush()
                    session.add(_item_to_row(initial_item))
                    session.commit()
                except IntegrityError as error:
                    session.rollback()
                    if "turns.thread_id" in str(error):
                        raise TurnAlreadyRunningError(str(turn.thread_id)) from error
                    raise

    async def add_item(self, item: Item) -> None:
        async with self._lock:
            with Session(self._engine) as session:
                session.add(_item_to_row(item))
                session.commit()

    async def finish_turn(
        self, turn_id: UUID, status: TurnStatus, completed_at: datetime
    ) -> None:
        if status is TurnStatus.RUNNING:
            raise ValueError("a finished turn cannot have running status")
        async with self._lock:
            with Session(self._engine) as session:
                row = session.get(TurnRow, str(turn_id))
                if row is None or row.status != TurnStatus.RUNNING:
                    raise TurnNotFoundError(str(turn_id))
                row.status = status
                row.completed_at = completed_at
                session.add(row)
                session.commit()


def _thread_from_row(row: ThreadRow) -> Thread:
    return Thread(id=UUID(row.id), created_at=row.created_at)


def _turn_to_row(turn: Turn) -> TurnRow:
    return TurnRow(
        id=str(turn.id),
        thread_id=str(turn.thread_id),
        status=turn.status,
        created_at=turn.created_at,
        completed_at=turn.completed_at,
    )


def _turn_from_row(row: TurnRow) -> Turn:
    return Turn(
        id=UUID(row.id),
        thread_id=UUID(row.thread_id),
        status=TurnStatus(row.status),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _item_to_row(item: Item) -> ItemRow:
    payload = item.model_dump(
        mode="json", exclude={"id", "thread_id", "turn_id", "created_at", "type"}
    )
    return ItemRow(
        id=str(item.id),
        thread_id=str(item.thread_id),
        turn_id=str(item.turn_id),
        type=item.type,
        created_at=item.created_at,
        payload=payload,
    )


def _item_from_row(row: ItemRow) -> Item:
    return _ITEM_ADAPTER.validate_python(
        {
            "id": row.id,
            "thread_id": row.thread_id,
            "turn_id": row.turn_id,
            "created_at": row.created_at,
            "type": row.type,
            **row.payload,
        }
    )
