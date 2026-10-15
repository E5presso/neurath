"""A user-wide SQLite store with request-local connections and explicit migrations."""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import URL, Connection
from sqlalchemy.pool import NullPool

from neurath.domain.core import StorageNotReady
from neurath.infrastructure.core_identity import SqlIdentities

SCHEMA_REVISION = "core_0002"


def user_database_path() -> Path:
    """Independent of cwd/project/session; explicit paths are for isolated/test installs."""
    configured = os.environ.get("XDG_DATA_HOME")
    data_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be absolute")
    return data_home / "neurath" / "core.sqlite3"


@dataclass
class CoreUnitOfWork:
    connection: Connection

    @property
    def tasks(self):
        from neurath.infrastructure.core_tasks import SqlTasks

        return SqlTasks(self.connection)

    @property
    def identities(self) -> SqlIdentities:
        return SqlIdentities(self.connection)


class CoreDatabase:
    def __init__(self, path: Path | None = None, *, timeout: float = 5.0):
        self.path = (path if path is not None else user_database_path()).expanduser().resolve()
        self.timeout = timeout

    def _engine(self, *, write: bool, create: bool = False):
        if not create and not self.path.is_file():
            raise StorageNotReady("Core database is missing; initialize it explicitly")
        engine = create_engine(
            URL.create(
                "sqlite+pysqlite",
                database="file:" + quote(str(self.path), safe="/"),
                query={"mode": "rwc" if create else ("rw" if write else "ro"), "uri": "true"},
            ),
            poolclass=NullPool,
            connect_args={"timeout": self.timeout},
        )

        @event.listens_for(engine, "connect")
        def configure(connection, _record):
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")
            if not write:
                connection.execute("PRAGMA query_only=ON")

        @event.listens_for(engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")

        return engine

    def initialize(self) -> None:
        """Explicit setup only. Never interpret or alter a legacy database as new core."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        engine = self._engine(write=True, create=True)
        try:
            with engine.begin() as connection:
                tables = set(inspect(connection).get_table_names())
                if tables and "core_schema_revision" not in tables:
                    raise StorageNotReady(
                        "Existing database is not a core store; migration is required"
                    )
                config = Config()
                config.set_main_option("script_location", "neurath.infrastructure:core_migrations")
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        finally:
            engine.dispose()

    @contextmanager
    def transaction(self, *, write: bool = False):
        """Atomic local storage work only. Make host/network calls after leaving this block."""
        engine = self._engine(write=write)
        try:
            with engine.begin() as connection:
                if not inspect(connection).has_table("core_schema_revision"):
                    raise StorageNotReady(
                        "Core schema is missing; initialize or migrate explicitly"
                    )
                versions = (
                    connection.exec_driver_sql("SELECT version_num FROM core_schema_revision")
                    .scalars()
                    .all()
                )
                if versions != [SCHEMA_REVISION]:
                    raise StorageNotReady(
                        "Core schema version differs; use the matching package or migrate"
                    )
                yield CoreUnitOfWork(connection)
        finally:
            engine.dispose()
