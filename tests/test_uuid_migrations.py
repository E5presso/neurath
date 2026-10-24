"""Uuid 표준 매핑의 전체 스키마 이전·보존·실패 원자성을 검증한다."""

import inspect
import sqlite3
from contextlib import closing
from typing import get_args, get_type_hints
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from spakky.plugins.sqlalchemy.orm.table import AbstractTable
from sqlalchemy import Uuid

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.usecases.prepare_phase import PreparePhaseCommand, PreparePhaseUseCase
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.aggregates.project import Project
from neurath.domain.errors import StorageNotReady
from neurath.domain.values.directory_observation import DirectoryObservation
from neurath.infrastructure.database import create_database_engine, initialize_database
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_collaboration import assignment, call
from tests.test_collaboration import collaboration as collaboration
from tests.test_memory_requests import update
from tests.test_task_migrations import migration_config
from tests.test_task_requests import snapshot
from tests.test_workflow_requests import work as work


async def downgrade(database, *, migration=True):
    engine = create_database_engine(database, write=True, migration=migration)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: command.downgrade(migration_config(c), "core_0008"))
    finally:
        await engine.dispose()


def test_all_uuid_mapped_attributes_use_sqlalchemy_uuid():
    import pkgutil
    from importlib import import_module

    import neurath.infrastructure.models

    count = 0
    for entry in pkgutil.iter_modules(
        neurath.infrastructure.models.__path__, neurath.infrastructure.models.__name__ + "."
    ):
        for _, model in inspect.getmembers(import_module(entry.name), inspect.isclass):
            if model.__module__ != entry.name or not issubclass(model, AbstractTable):
                continue
            for name, annotation in get_type_hints(model).items():
                args = get_args(annotation)
                if not args or (args[0] is not UUID and UUID not in get_args(args[0])):
                    continue
                column = model.__table__.c[name]
                assert isinstance(column.type, Uuid) and column.type.as_uuid, (model, name)
                count += 1
    assert count > 50


async def test_uuid_upgrade_preserves_collaboration_workflow_memory_and_external_references(
    database, collaboration, work, tmp_path
):
    actor, sender, _, recipient, task = collaboration
    delegation = await assignment(database, collaboration)
    await call(database, "accept_delegation", "AcceptDelegation", delegation.uid, recipient.uid)
    message = await call(
        database, "read_message", "ReadMessage", delegation.message_id, recipient.uid
    )
    assert "original requirement text" in message.body
    await call(
        database,
        "send_message",
        "SendMessage",
        message.conversation_id,
        recipient.uid,
        sender.uid,
        "reply",
        "응답",
        "미완료 원문",
        delegation.message_id,
    )
    await update(database, actor, task_id=task.uid)
    async with storage_scope(database) as scope:
        await scope.get(IMemoryRepository).save(
            Memory.create(
                actor.project.uid,
                actor.session.uid,
                task_id=task.uid,
                kind=MemoryKind.ARTIFACT,
                content="미완료 보고\n원문 유지",
                references=[str(task.uid), "artifact:original"],
            )
        )
        project = Project.create(DirectoryObservation(working_directory=str(tmp_path / "old")))
        project.uid = uuid4()
        await scope.get(IProjectRepository).save(project)
    flow = work[2]
    await run(
        PreparePhaseUseCase,
        PreparePhaseCommand(
            project_id=flow.project_id,
            session_id=flow.session_id,
            run_id=flow.uid,
            expected_revision=flow.revision,
        ),
        database_path=database,
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
CREATE TABLE external_owner (owner TEXT PRIMARY KEY REFERENCES core_projects(id), body TEXT CHECK(length(body)>0));
CREATE TABLE external_child (owner TEXT REFERENCES external_owner(owner), body TEXT);
CREATE TABLE audit_log (body TEXT);
CREATE TRIGGER unrelated_audit AFTER INSERT ON audit_log BEGIN SELECT id FROM core_projects; END;
CREATE TRIGGER preserve_original AFTER UPDATE ON external_owner
BEGIN INSERT INTO audit_log VALUES ('must not run during migration'); END;
""")
        connection.execute(
            "INSERT INTO external_owner VALUES (?, ?)", (actor.project.uid, str(task.uid))
        )
        connection.execute(
            "INSERT INTO external_child VALUES (?, ?)", (actor.project.uid, "미완료")
        )
        triggers = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
    before = snapshot(database)
    await downgrade(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT id FROM core_projects WHERE id=?", (str(project.uid),)
        ).fetchone() == (str(project.uid),)
        assert connection.execute("SELECT owner,body FROM external_owner").fetchone() == (
            str(actor.project.uid),
            str(task.uid),
        )
    await initialize_database(database)
    assert snapshot(database) == before
    async with storage_scope(database, write=False) as scope:
        restored = await scope.get(ITaskRepository).get(task.uid)
        assert restored.status.value == "pending"
        assert (await scope.get(IProjectRepository).get(project.uid)).uid == project.uid
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
            == triggers
        )
        assert connection.execute("SELECT * FROM audit_log").fetchall() == []
        assert connection.execute(
            "SELECT type FROM pragma_table_info('core_projects') WHERE name='id'"
        ).fetchone() == ("CHAR(32)",)
    stable = database.read_bytes()
    await initialize_database(database)
    assert database.read_bytes() == stable
    with closing(sqlite3.connect(database)) as connection, connection:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute("UPDATE external_owner SET body=''")
        with pytest.raises(sqlite3.IntegrityError, match="Location already belongs"):
            connection.execute(
                "UPDATE core_project_locations SET project_id=? WHERE project_id=?",
                (project.uid, actor.project.uid),
            )


@pytest.mark.parametrize(
    "failure", ["invalid-uuid", "existing-foreign-key", "produced-foreign-key"]
)
async def test_uuid_migration_failure_preserves_data_schema_triggers_and_revision(
    database, tmp_path, monkeypatch, failure
):
    actor = await register_session(str(tmp_path), "codex", "unchanged", database_path=database)
    await downgrade(database)
    if failure == "produced-foreign-key":
        original = MigrationContext.run_migrations

        def break_reference(context, **kwargs):
            original(context, **kwargs)
            context.connection.exec_driver_sql(
                "UPDATE core_sessions SET project_id='11111111111111111111111111111111'"
            )

        monkeypatch.setattr(MigrationContext, "run_migrations", break_reference)
    else:
        with closing(sqlite3.connect(database)) as connection, connection:
            if failure == "invalid-uuid":
                connection.execute("UPDATE core_sessions SET successor_id='invalid-identity'")
            else:
                connection.execute(
                    "UPDATE core_sessions SET project_id='11111111-1111-1111-1111-111111111111'"
                )
    before = database.read_bytes()
    with pytest.raises(ValueError if failure == "invalid-uuid" else StorageNotReady):
        await initialize_database(database)
    assert database.read_bytes() == before
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id FROM core_sessions").fetchone() == (
            str(actor.session.uid),
        )
        assert connection.execute("SELECT version_num FROM core_schema_revision").fetchone() == (
            "core_0008",
        )


async def test_uuid_table_recreation_rejects_an_ordinary_request_connection(database):
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="migration connection"):
        await downgrade(database, migration=False)
    assert database.read_bytes() == before
