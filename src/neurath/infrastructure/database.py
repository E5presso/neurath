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

SCHEMA_REVISION = "core_0002"


def user_database_path() -> Path:
    """Resolve one user-wide database path independently of the current directory."""
    configured = os.environ.get("XDG_DATA_HOME")
    data_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be absolute")
    return data_home / "neurath" / "core.sqlite3"


class SqliteDatabase:
    """Immutable configuration for request-local engines, with no transaction wrapper."""

    def __init__(self, path: Path | None = None, *, timeout: float = 5.0) -> None:
        """Select a user store or an explicit isolated test database."""
        self.path = (path if path is not None else user_database_path()).expanduser().resolve()
        self.timeout = timeout

    def create_engine(self, *, write: bool, create: bool = False) -> Engine:
        """Create an unpooled engine; callers own Session.begin and engine disposal."""
        if not create and not self.path.is_file():
            raise StorageNotReady("Database is missing; initialize it explicitly")
        mode = "rwc" if create else ("rw" if write else "ro")
        engine = create_engine(
            URL.create(
                "sqlite+pysqlite",
                database="file:" + quote(str(self.path), safe="/"),
                query={"mode": mode, "uri": "true"},
            ),
            poolclass=NullPool,
            connect_args={"timeout": self.timeout},
        )

        def configure(connection: sqlite3.Connection, record: ConnectionPoolEntry) -> None:
            """Let SQLAlchemy begin transactions and enforce foreign keys on each connection."""
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")
            if not write:
                connection.execute("PRAGMA query_only=ON")

        def begin(connection: Connection) -> None:
            """Acquire the write reservation before any read-modify-write operation."""
            connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")

        event.listen(engine, "connect", configure)
        event.listen(engine, "begin", begin)
        return engine

    def initialize(self) -> None:
        """Apply known revisions explicitly, refusing to reinterpret a legacy database."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        engine = self.create_engine(write=True, create=True)
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

    def verify_schema(self, session: Session) -> None:
        """Reject absent or incompatible schema without running migrations on a request."""
        if not inspect(session.connection()).has_table("core_schema_revision"):
            raise StorageNotReady("Schema missing; initialize or migrate explicitly")
        versions = session.scalars(text("SELECT version_num FROM core_schema_revision")).all()
        if versions != [SCHEMA_REVISION]:
            raise StorageNotReady("Schema version differs; use matching package or migrate")
