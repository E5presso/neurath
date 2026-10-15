"""SQLite engine configuration and explicit Alembic initialization."""

import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from neurath.domain.errors import StorageNotReady

SCHEMA_REVISION = "core_0001"


def user_database_path() -> Path:
    """Resolve one user-wide database path independently of the current directory.

    Returns:
        Path: User-wide core database path, independent of the working directory.

    Raises:
        ValueError: A supplied path, identifier, or directory is invalid for the operation.
    """
    configured = os.environ.get("XDG_DATA_HOME")
    data_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be absolute")
    return data_home / "neurath" / "core.sqlite3"


def create_database_engine(
    path: Path | None = None, *, write: bool, create: bool = False, timeout: float = 5.0
) -> Engine:
    """Create an unpooled engine; callers own Session.begin and engine disposal.

    Args:
        path: Explicit database path, or None to resolve the user-wide default.
        write: Whether to permit writes and reserve a writer before reading.
        create: Whether explicit initialization may create the database file.
        timeout: Seconds SQLite waits to acquire a database lock.

    Returns:
        Engine: Unpooled engine whose caller must dispose after use.

    Raises:
        StorageNotReady: The database is absent, uninitialized, or incompatible with this package.
    """
    path = (path if path is not None else user_database_path()).expanduser().resolve()
    if not create and not path.is_file():
        raise StorageNotReady("Database is missing; initialize it explicitly")
    mode = "rwc" if create else ("rw" if write else "ro")
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database="file:" + quote(str(path), safe="/"),
            query={"mode": mode, "uri": "true"},
        ),
        poolclass=NullPool,
        connect_args={"timeout": timeout},
    )

    def configure(connection: sqlite3.Connection, record: ConnectionPoolEntry) -> None:
        """Let SQLAlchemy begin transactions and enforce foreign keys on each connection.

        Args:
            connection: Connection whose SQLite transaction behavior is configured.
            record: Pool entry supplied by the SQLAlchemy connection event.
        """
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")
        if not write:
            connection.execute("PRAGMA query_only=ON")

    def begin(connection: Connection) -> None:
        """Acquire the write reservation before any read-modify-write operation.

        Args:
            connection: Connection whose SQLite transaction behavior is configured.
        """
        connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")

    event.listen(engine, "connect", configure)
    event.listen(engine, "begin", begin)
    return engine


def initialize_database(path: Path | None = None) -> None:
    """Apply known revisions explicitly, refusing to reinterpret a legacy database.

    Args:
        path: Explicit database path, or None to resolve the user-wide default.

    Raises:
        StorageNotReady: The database is absent, uninitialized, or incompatible with this package.
    """
    path = (path if path is not None else user_database_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(path, write=True, create=True)
    try:
        with engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            if tables and "core_schema_revision" not in tables:
                raise StorageNotReady(
                    "Existing database is not a current store; migration required"
                )
            config = Config()
            config.set_main_option("script_location", "neurath.infrastructure:migrations")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def verify_schema(session: Session) -> None:
    """Reject absent or incompatible schema without running migrations on a request.

    Args:
        session: Request-local SQLAlchemy session.

    Raises:
        StorageNotReady: The database is absent, uninitialized, or incompatible with this package.
    """
    if not inspect(session.connection()).has_table("core_schema_revision"):
        raise StorageNotReady("Schema missing; initialize or migrate explicitly")
    versions = session.scalars(text("SELECT version_num FROM core_schema_revision")).all()
    if versions != [SCHEMA_REVISION]:
        raise StorageNotReady("Schema version differs; use matching package or migrate")
