"""명시적인 초기화와 원래 #154 스키마의 호환성을 검증한다."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import UUID

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from spakky.plugins.sqlalchemy.orm.table import AbstractTable
from sqlalchemy.ext.asyncio import AsyncSession

from neurath.domain.errors import StorageNotReady
from neurath.infrastructure.database import (
    create_database_engine,
    initialize_database,
    user_database_path,
    verify_schema,
)
from tests.conftest import initialize_git
from tests.support.session_requests import (
    get_session_context,
    move_session,
    register_session,
    session_state,
)


def test_database_path_is_user_wide_and_relative_xdg_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    expected = tmp_path / "data" / "neurath" / "core.sqlite3"
    monkeypatch.chdir(tmp_path)
    assert user_database_path() == expected
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert user_database_path() == expected
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    with pytest.raises(ValueError, match="absolute"):
        user_database_path()


async def test_missing_database_is_not_implicitly_created_and_initialize_is_idempotent(tmp_path):
    database = tmp_path / "new.sqlite3"
    with pytest.raises(StorageNotReady):
        (await get_session_context("missing", "missing", database_path=database))
    assert not database.exists()
    (await initialize_database(database))
    first = await register_session(str(tmp_path), "codex", "native", database_path=database)
    (await initialize_database(database))
    assert session_state(
        await get_session_context(first.project.id, first.session.id, database_path=database)
    ) == session_state(first)


async def test_legacy_database_bytes_are_preserved_on_rejected_initialization(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        (connection.execute("CREATE TABLE task (source TEXT)"))
        (connection.execute("INSERT INTO task VALUES ('unfinished original source')"))
    before = path.read_bytes()
    with pytest.raises(StorageNotReady, match="migration"):
        (await initialize_database(path))
    assert path.read_bytes() == before


async def test_original_schema_records_are_readable_and_updatable_after_uuid_migration(tmp_path):
    path = tmp_path / "original.sqlite3"
    folder = tmp_path / "project"
    folder.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "core_0001.sql"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(fixture.read_text())
        (
            connection.execute(
                "INSERT INTO core_projects (id, root_path) VALUES ('a4fd2728-8009-4f60-b834-eed0596691aa', ?)",
                (str(folder),),
            )
        )
        (
            connection.execute(
                "INSERT INTO core_project_locations VALUES ('folder', ?, 'a4fd2728-8009-4f60-b834-eed0596691aa')",
                (str(folder),),
            )
        )
        (
            connection.execute(
                "INSERT INTO core_sessions (id, project_id, provider, host_session_id, working_directory, revision) VALUES ('bb29ee78-e417-47a1-bd4d-fb6b82208926', 'a4fd2728-8009-4f60-b834-eed0596691aa', 'codex', 'native', ?, 7)",
                (str(folder),),
            )
        )
    database = path
    before = path.read_bytes()
    with pytest.raises(StorageNotReady):
        (
            await get_session_context(
                "a4fd2728-8009-4f60-b834-eed0596691aa",
                "bb29ee78-e417-47a1-bd4d-fb6b82208926",
                database_path=path,
            )
        )
    assert path.read_bytes() == before
    (await initialize_database(database))
    original = await get_session_context(
        UUID("a4fd2728-8009-4f60-b834-eed0596691aa"),
        UUID("bb29ee78-e417-47a1-bd4d-fb6b82208926"),
        database_path=path,
    )
    assert original.session.revision == 7
    initialize_git(folder)
    child = folder / "child"
    child.mkdir()
    assert session_state(
        await register_session(str(folder), "codex", "native", database_path=path)
    ) == session_state(original)
    changed = await move_session(
        original.project.id, original.session.id, str(child), 7, database_path=path
    )
    assert changed.session.id == UUID("bb29ee78-e417-47a1-bd4d-fb6b82208926")
    assert changed.session.revision == 8
    engine = create_database_engine(database, write=False)
    try:
        async with engine.connect() as connection:
            differences = await connection.run_sync(
                lambda sync_connection: compare_metadata(
                    MigrationContext.configure(
                        sync_connection, opts={"version_table": "core_schema_revision"}
                    ),
                    AbstractTable.metadata,
                )
            )
            assert differences == []
    finally:
        (await engine.dispose())


async def test_initialization_is_serialized_between_processes_and_unknown_revision_is_rejected(
    tmp_path,
):
    path = tmp_path / "concurrent.sqlite3"
    script = "from neurath.infrastructure.database import initialize_database; from pathlib import Path; import sys, asyncio; asyncio.run(initialize_database(Path(sys.argv[1])))"

    def initialize(_):
        subprocess.run([sys.executable, "-c", script, str(path)], check=True, capture_output=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(initialize, range(3)))
    with closing(sqlite3.connect(path)) as connection, connection:
        (connection.execute("UPDATE core_schema_revision SET version_num='future'"))
    before = path.read_bytes()
    with pytest.raises(StorageNotReady, match="version"):
        (await get_session_context("project", "session", database_path=path))
    assert path.read_bytes() == before


async def test_existing_empty_file_requires_initialization(tmp_path):
    path = tmp_path / "empty.sqlite3"
    path.touch()
    database = path
    engine = create_database_engine(database, write=False)
    try:
        async with AsyncSession(engine) as session, session.begin():
            with pytest.raises(StorageNotReady, match="Schema missing"):
                await (await session.connection()).run_sync(verify_schema)
    finally:
        (await engine.dispose())


async def test_framework_migration_preserves_legacy_values_and_marks_unknown_metadata(tmp_path):
    from datetime import UTC, datetime
    from uuid import UUID

    from neurath.application.ports.repositories.project import IProjectRepository
    from neurath.application.ports.repositories.session import ISessionRepository
    from tests.conftest import storage_scope

    path = tmp_path / "old.sqlite3"
    fixture = Path(__file__).parent / "fixtures" / "core_0001.sql"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(fixture.read_text())
        (
            connection.execute(
                "INSERT INTO core_projects (id, root_path) VALUES ('17dc3986-8d19-45d0-bef0-ee8180dcb078', '/legacy')"
            )
        )
        (
            connection.execute(
                "INSERT INTO core_project_locations VALUES ('folder', '/legacy', '17dc3986-8d19-45d0-bef0-ee8180dcb078')"
            )
        )
        (
            connection.execute(
                "INSERT INTO core_sessions (id, project_id, provider, host_session_id, working_directory, revision) VALUES ('3f8a2a41-912d-4082-90d7-efb6d68184b9', '17dc3986-8d19-45d0-bef0-ee8180dcb078', 'codex', 'original', '/legacy/sub', 17)"
            )
        )
        (
            connection.execute(
                "CREATE TABLE dependent_fixture (project_id TEXT REFERENCES core_projects(id), source TEXT)"
            )
        )
        (
            connection.execute(
                "INSERT INTO dependent_fixture VALUES ('17dc3986-8d19-45d0-bef0-ee8180dcb078', 'unfinished original source')"
            )
        )
    (await initialize_database(path))
    async with storage_scope(path, write=False) as scope:
        project = await scope.get(IProjectRepository).get(
            UUID("17dc3986-8d19-45d0-bef0-ee8180dcb078")
        )
        session = await scope.get(ISessionRepository).get(
            UUID("3f8a2a41-912d-4082-90d7-efb6d68184b9")
        )
        assert (
            project.uid == UUID("17dc3986-8d19-45d0-bef0-ee8180dcb078")
            and project.root_path == "/legacy"
        )
        assert project.locations[0].path == "/legacy"
        assert (
            session.project_id == UUID("17dc3986-8d19-45d0-bef0-ee8180dcb078")
            and session.revision == 17
        )
        assert session.working_directory == "/legacy/sub"
        for entity in (project, session):
            assert entity.version == UUID(int=0)
            assert entity.created_at == datetime(1970, 1, 1, tzinfo=UTC)
            assert entity.updated_at == entity.created_at
    before = path.read_bytes()
    (await initialize_database(path))
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as connection:
        assert (connection.execute("SELECT * FROM dependent_fixture")).fetchall() == [
            ("17dc39868d1945d0bef0ee8180dcb078", "unfinished original source")
        ]
        assert (connection.execute("PRAGMA foreign_key_check")).fetchall() == []


async def test_failed_framework_migration_rolls_back_schema_data_and_revision(
    tmp_path, monkeypatch
):
    from neurath.infrastructure import database as database_module

    path = tmp_path / "rollback.sqlite3"
    fixture = Path(__file__).parent / "fixtures" / "core_0001.sql"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(fixture.read_text())
        (
            connection.execute(
                "INSERT INTO core_projects (id, root_path) VALUES ('17dc3986-8d19-45d0-bef0-ee8180dcb078', '/legacy')"
            )
        )
    before = path.read_bytes()
    original_upgrade = database_module.command.upgrade

    def fail_after_upgrade(config, revision):
        original_upgrade(config, revision)
        raise RuntimeError("after schema migration")

    monkeypatch.setattr(database_module.command, "upgrade", fail_after_upgrade)
    with pytest.raises(RuntimeError, match="after schema migration"):
        (await initialize_database(path))
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as connection:
        assert (connection.execute("SELECT * FROM core_projects")).fetchall() == [
            ("17dc3986-8d19-45d0-bef0-ee8180dcb078", "/legacy")
        ]
        assert (connection.execute("SELECT version_num FROM core_schema_revision")).fetchone() == (
            "core_0001",
        )
        assert [row[1] for row in (connection.execute("PRAGMA table_info(core_projects)"))] == [
            "id",
            "root_path",
        ]


def migration_config(connection):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", "neurath.infrastructure:migrations")
    config.attributes["connection"] = connection
    return config


async def test_metadata_downgrade_preserves_original_records_and_can_upgrade(database, repository):
    from alembic import command
    from sqlalchemy import text

    original = await register_session(str(repository), "codex", "retained", database_path=database)
    with closing(sqlite3.connect(database)) as connection, connection:
        (
            connection.execute(
                "CREATE TABLE dependent_fixture (project_id TEXT REFERENCES core_projects(id), source TEXT)"
            )
        )
        (
            connection.execute(
                "INSERT INTO dependent_fixture VALUES (?, 'unfinished original source')",
                (original.project.id.hex,),
            )
        )
    engine = create_database_engine(database, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: command.downgrade(
                    migration_config(sync_connection), "core_0001"
                )
            )
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM core_schema_revision"))
            ).scalar_one() == "core_0001"
            assert [
                row[1]
                for row in (await connection.exec_driver_sql("PRAGMA table_info(core_projects)"))
            ] == ["id", "root_path"]
            assert [
                row[1]
                for row in (await connection.exec_driver_sql("PRAGMA table_info(core_sessions)"))
            ] == [
                "id",
                "project_id",
                "provider",
                "host_session_id",
                "working_directory",
                "revision",
            ]
            assert (
                await connection.execute(
                    text("SELECT id, project_id, host_session_id, revision FROM core_sessions")
                )
            ).one() == (str(original.session.id), str(original.project.id), "retained", 1)
            assert (await connection.execute(text("SELECT * FROM dependent_fixture"))).one() == (
                str(original.project.id),
                "unfinished original source",
            )
            assert (await connection.exec_driver_sql("PRAGMA foreign_key_check")).all() == []
            assert (
                await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            ).all() == []
    finally:
        (await engine.dispose())
    (await initialize_database(database))
    assert session_state(
        await get_session_context(original.project.id, original.session.id, database_path=database)
    ) == session_state(original)
    with closing(sqlite3.connect(database)) as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        ).fetchall() == [("core_location_owner_immutable",)]


async def test_destructive_downgrade_is_rejected_and_rolls_back_intermediate_metadata_removal(
    database, repository
):
    from alembic import command

    original = await register_session(str(repository), "codex", "retained", database_path=database)
    before = database.read_bytes()
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="Destructive core downgrade is unsupported"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: command.downgrade(
                        migration_config(sync_connection), "base"
                    )
                )
    finally:
        (await engine.dispose())
    assert database.read_bytes() == before
    assert session_state(
        await get_session_context(original.project.id, original.session.id, database_path=database)
    ) == session_state(original)
    with closing(sqlite3.connect(database)) as connection:
        assert (connection.execute("SELECT version_num FROM core_schema_revision")).fetchone() == (
            "core_0009",
        )
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        ).fetchall() == [("core_location_owner_immutable",)]


@pytest.mark.parametrize("invalid_connection", [None, "sqlite:///not-a-connection"])
def test_migration_rejects_non_connection_input_before_touching_database(
    database, invalid_connection
):
    from alembic import command

    before = database.read_bytes()
    with pytest.raises(TypeError, match="explicit SQLAlchemy Connection"):
        command.upgrade(migration_config(invalid_connection), "head")
    assert database.read_bytes() == before


async def test_alembic_files_alone_define_the_deployed_schema_head(
    database, repository, tmp_path, monkeypatch
):
    from shutil import copytree

    from alembic.script import ScriptDirectory

    import neurath.infrastructure.migrations as migrations

    first = await register_session(str(repository), "codex", "native", database_path=database)
    scripts = tmp_path / "deployment-migrations"
    copytree(Path(migrations.__file__).parent, scripts)
    deployed_head = ScriptDirectory(str(scripts)).get_current_head()
    (
        scripts / "versions" / "review_probe.py"
    ).write_text(f'''"""배포 리비전 추가만으로 호환성 판단이 갱신되는지 검증한다."""
from alembic import op
from sqlalchemy import Column, Integer
revision = "review_probe"
down_revision = "{deployed_head}"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("review_probe", Column("id", Integer, primary_key=True))
def downgrade():
    op.drop_table("review_probe")
''')
    monkeypatch.setattr(
        ScriptDirectory, "from_config", lambda config: ScriptDirectory(str(scripts))
    )
    before = database.read_bytes()
    with pytest.raises(StorageNotReady, match="version differs"):
        (await get_session_context(first.project.id, first.session.id, database_path=database))
    assert database.read_bytes() == before
    (await initialize_database(database))
    assert session_state(
        await get_session_context(first.project.id, first.session.id, database_path=database)
    ) == session_state(first)
    with closing(sqlite3.connect(database)) as connection:
        assert (connection.execute("SELECT version_num FROM core_schema_revision")).fetchone() == (
            "review_probe",
        )
        assert (connection.execute("SELECT COUNT(*) FROM review_probe")).fetchone() == (0,)


async def test_ordinary_request_checks_missing_schema_before_reading_entities(tmp_path):
    path = tmp_path / "uninitialized.sqlite3"
    path.touch()
    before = path.read_bytes()
    with pytest.raises(StorageNotReady, match="Schema missing"):
        (await get_session_context("project", "session", database_path=path))
    assert path.read_bytes() == before
