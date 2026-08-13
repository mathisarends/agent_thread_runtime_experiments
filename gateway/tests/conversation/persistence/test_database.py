from pathlib import Path

from gateway.conversation.persistence.database import create_sqlite_engine
from sqlalchemy import text


def test_in_memory_engine_enforces_foreign_keys() -> None:
    engine = create_sqlite_engine(":memory:")

    with engine.connect() as connection:
        pragma = connection.execute(text("PRAGMA foreign_keys")).scalar()
    engine.dispose()

    assert pragma == 1


def test_file_engine_persists_across_connections(tmp_path: Path) -> None:
    database = tmp_path / "gateway.db"
    engine = create_sqlite_engine(str(database))

    with engine.connect() as connection:
        connection.execute(
            text("CREATE TABLE marker (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        )
        connection.execute(text("INSERT INTO marker (value) VALUES ('kept')"))
        connection.commit()

    with engine.connect() as connection:
        value = connection.execute(text("SELECT value FROM marker")).scalar()
    engine.dispose()

    assert value == "kept"
    assert database.exists()
