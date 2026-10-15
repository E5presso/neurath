"""Explicit initialization and compatibility with the schema shipped in original #154."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import Session

from neurath.domain.errors import StorageNotReady
from neurath.infrastructure.database import SqliteDatabase, user_database_path
from neurath.infrastructure.models.base import DatabaseModel
from neurath.transport.session_requests import get_session_context, move_session, register_session


def test_database_path_is_user_wide_and_relative_xdg_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    expected = tmp_path / "data" / "neurath" / "core.sqlite3"
    monkeypatch.chdir(tmp_path)
    assert user_database_path() == expected
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert SqliteDatabase().path == expected
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    with pytest.raises(ValueError, match="absolute"):
        user_database_path()


def test_missing_database_is_not_implicitly_created_and_initialize_is_idempotent(tmp_path):
    database = SqliteDatabase(tmp_path / "new.sqlite3")
    with pytest.raises(StorageNotReady):
        get_session_context("missing", "missing", database_path=database.path)
    assert not database.path.exists()
    database.initialize()
    first = register_session(str(tmp_path), "codex", "native", database_path=database.path)
    database.initialize()
    assert (
        get_session_context(first.project.id, first.session.id, database_path=database.path)
        == first
    )


def test_legacy_database_bytes_are_preserved_on_rejected_initialization(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE task (source TEXT)")
        connection.execute("INSERT INTO task VALUES ('unfinished original source')")
    before = path.read_bytes()
    with pytest.raises(StorageNotReady, match="migration"):
        SqliteDatabase(path).initialize()
    assert path.read_bytes() == before


def test_original_schema_records_are_readable_and_updatable_without_data_conversion(tmp_path):
    path = tmp_path / "original.sqlite3"
    folder = tmp_path / "project"
    folder.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "core_0001.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(fixture.read_text())
        connection.execute(
            "INSERT INTO core_projects VALUES ('original-project', ?)", (str(folder),)
        )
        connection.execute(
            "INSERT INTO core_project_locations VALUES ('folder', ?, 'original-project')",
            (str(folder),),
        )
        connection.execute(
            "INSERT INTO core_sessions VALUES ('original-session', 'original-project', 'codex', 'native', ?, 7)",
            (str(folder),),
        )
    database = SqliteDatabase(path)
    original = get_session_context("original-project", "original-session", database_path=path)
    assert original.session.revision == 7
    database.initialize()
    assert register_session(str(folder), "codex", "native", database_path=path) == original
    changed = move_session(
        original.project.id, original.session.id, str(folder), 7, database_path=path
    )
    assert changed.session.id == "original-session"
    assert changed.session.revision == 8
    engine = database.create_engine(write=False)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"version_table": "core_schema_revision"}
            )
            assert compare_metadata(context, DatabaseModel.metadata) == []
    finally:
        engine.dispose()


def test_initialization_is_serialized_between_processes_and_unknown_revision_is_rejected(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    script = "from neurath.infrastructure.database import SqliteDatabase; from pathlib import Path; import sys; SqliteDatabase(Path(sys.argv[1])).initialize()"

    def initialize(_):
        subprocess.run([sys.executable, "-c", script, str(path)], check=True, capture_output=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(initialize, range(3)))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE core_schema_revision SET version_num='future'")
    before = path.read_bytes()
    with pytest.raises(StorageNotReady, match="version"):
        get_session_context("project", "session", database_path=path)
    assert path.read_bytes() == before


def test_existing_empty_file_requires_initialization(tmp_path):
    path = tmp_path / "empty.sqlite3"
    path.touch()
    database = SqliteDatabase(path)
    engine = database.create_engine(write=False)
    try:
        with Session(engine) as session, session.begin():
            with pytest.raises(StorageNotReady, match="Schema missing"):
                database.verify_schema(session)
    finally:
        engine.dispose()
