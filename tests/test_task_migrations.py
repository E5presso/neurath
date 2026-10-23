"""이전 스키마와 원본을 보존하면서 태스크 원장을 명시적으로 이전한다."""

import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.config import Config
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.usecases.get_tasks import GetTasksQuery, GetTasksUseCase
from neurath.domain.aggregates.request_source import RequestSource, SourceKind
from neurath.domain.aggregates.task import Task
from neurath.domain.errors import StorageNotReady
from neurath.infrastructure import database as storage
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_task_requests import create, record, snapshot


def migration_config(connection):
    config = Config()
    config.set_main_option("script_location", "neurath.infrastructure:migrations")
    config.attributes["connection"] = connection
    return config


async def previous_store(path):
    engine = storage.create_database_engine(path, write=True, create=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: command.upgrade(
                    migration_config(sync_connection), "core_0002"
                )
            )
            (
                await connection.execute(
                    text("INSERT INTO core_projects (id,root_path) VALUES ('old-project','/old')")
                )
            )
            (
                await connection.execute(
                    text(
                        "INSERT INTO core_project_locations VALUES ('folder','/old','old-project')"
                    )
                )
            )
            (
                await connection.execute(
                    text(
                        "INSERT INTO core_sessions (id,project_id,provider,host_session_id,working_directory,revision) VALUES ('old-session','old-project','codex','native','/old',7)"
                    )
                )
            )
            (
                await connection.execute(
                    text(
                        "CREATE TABLE legacy_task (project_id TEXT REFERENCES core_projects(id), body TEXT, state TEXT)"
                    )
                )
            )
            (
                await connection.execute(
                    text(
                        "INSERT INTO legacy_task VALUES ('old-project','unfinished original requirement','waiting')"
                    )
                )
            )
    finally:
        (await engine.dispose())


async def test_core0002_upgrade_keeps_every_old_row_foreign_key_and_unfinished_original(tmp_path):
    path = tmp_path / "previous.sqlite3"
    (await previous_store(path))
    before = snapshot(path)
    original_bytes = path.read_bytes()
    with pytest.raises(StorageNotReady):
        (
            await run(
                GetTasksUseCase, GetTasksQuery("old-project", "old-session"), database_path=path
            )
        )
    assert path.read_bytes() == original_bytes
    await storage.initialize_database(path)
    after = snapshot(path)
    for table, records in before.items():
        if table == "core_sessions":
            assert after[table] == [(*row, None) for row in records]
        elif table != "core_schema_revision":
            assert after[table] == records
    assert after["legacy_task"] == [("old-project", "unfinished original requirement", "waiting")]
    assert after["core_tasks"] == after["core_request_sources"] == []
    assert (
        await run(GetTasksUseCase, GetTasksQuery("old-project", "old-session"), database_path=path)
    ).tasks == ()
    with closing(sqlite3.connect(path)) as connection:
        assert (connection.execute("PRAGMA foreign_key_check")).fetchall() == []
    stable = snapshot(path)
    await storage.initialize_database(path)
    assert snapshot(path) == stable


async def test_failed_core0003_upgrade_rolls_back_new_tables_and_preserves_original_bytes(
    tmp_path, monkeypatch
):
    path = tmp_path / "rollback.sqlite3"
    (await previous_store(path))
    original_bytes = path.read_bytes()
    before = snapshot(path)
    upgrade = storage.command.upgrade

    def fail_after_schema(config, revision):
        upgrade(config, revision)
        raise RuntimeError("after task schema")

    monkeypatch.setattr(storage.command, "upgrade", fail_after_schema)
    with pytest.raises(RuntimeError, match="after task schema"):
        await storage.initialize_database(path)
    assert snapshot(path) == before
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("with_task", [False, True])
async def test_populated_task_downgrade_refuses_without_deleting_sources_or_unfinished_work(
    database, repository, with_task
):
    actor = await register_session(str(repository), "codex", "native", database_path=database)
    original = await record(database, actor)
    if with_task:
        work = await create(database, actor, source=original)
        assert work.status.value == "pending"
    before = snapshot(database)
    engine = storage.create_database_engine(database, write=True)
    try:
        with pytest.raises(RuntimeError, match="must be preserved"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: command.downgrade(
                        migration_config(sync_connection), "core_0002"
                    )
                )
    finally:
        (await engine.dispose())
    assert snapshot(database) == before


@pytest.mark.parametrize("kind", ["source-session", "task-owner", "definition-source"])
async def test_database_foreign_keys_reject_cross_project_records_atomically(
    database, repository, tmp_path, kind
):
    local = await register_session(str(repository), "codex", "local", database_path=database)
    folder = tmp_path / "foreign"
    folder.mkdir()
    foreign = await register_session(str(folder), "codex", "foreign", database_path=database)
    original = await record(database, local)
    foreign_source = await record(database, foreign)
    before = snapshot(database)
    with pytest.raises(IntegrityError):
        async with storage_scope(database) as scope:
            if kind == "source-session":
                item = RequestSource.create(
                    local.project.uid, foreign.session.uid, SourceKind.PROMPT, "wrong scope"
                )
                (await scope.get(IRequestSourceRepository).save(item))
            elif kind == "task-owner":
                item = Task.create(
                    local.project.uid,
                    foreign.session.uid,
                    (await scope.get(IRequestSourceRepository).get(original.uid)),
                    "task",
                    "result",
                )
                (await scope.get(ITaskRepository).save(item))
            else:
                item = Task.create(
                    local.project.uid,
                    local.session.uid,
                    (await scope.get(IRequestSourceRepository).get(original.uid)),
                    "task",
                    "result",
                )
                from dataclasses import replace

                item.definitions = (replace(item.definition, source_id=foreign_source.uid),)
                (await scope.get(ITaskRepository).save(item))
    assert snapshot(database) == before
    async with storage_scope(database, write=False) as scope:
        assert (
            await scope.get(AsyncSessionManager).session.execute(text("PRAGMA foreign_key_check"))
        ).all() == []
