"""기존 원장과 새 기억 기록을 보존하는 명시적 이전·되돌림을 검증한다."""

import pytest
from alembic import command
from sqlalchemy import text

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.infrastructure.database import create_database_engine, initialize_database
from tests.conftest import storage_scope
from tests.support.session_requests import register_session
from tests.test_memory_requests import update
from tests.test_task_migrations import migration_config
from tests.test_task_requests import snapshot


async def test_empty_memory_migration_can_downgrade_and_upgrade(database):
    engine = create_database_engine(database, write=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: command.downgrade(migration_config(c), "core_0005"))
            assert (
                await connection.scalar(text("SELECT version_num FROM core_schema_revision"))
                == "core_0005"
            )
        await initialize_database(database)
    finally:
        await engine.dispose()
    assert snapshot(database)["core_enclaves"] == []


@pytest.mark.parametrize("stored", ["enclave", "memory", "handoff"])
async def test_memory_or_handoff_history_prevents_destructive_downgrade(database, tmp_path, stored):
    actor = await register_session(str(tmp_path), "codex", "original", database_path=database)
    if stored == "enclave":
        await update(database, actor)
    elif stored == "memory":
        from neurath.application.usecases.save_checkpoint import (
            SaveCheckpointCommand,
            SaveCheckpointUseCase,
        )
        from tests.support.requests import run

        await run(
            SaveCheckpointUseCase,
            SaveCheckpointCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                content="unfinished report",
                references=["source"],
            ),
            database_path=database,
        )
    else:
        peer = await register_session(str(tmp_path), "claude", "peer", database_path=database)
        async with storage_scope(database) as scope:
            source = await scope.get(ISessionRepository).get(actor.session.uid)
            source.hand_off(peer.session, source.revision)
            await scope.get(ISessionRepository).save(source)
    before = snapshot(database)
    engine = create_database_engine(database, write=True)
    try:
        with pytest.raises(RuntimeError):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda c: command.downgrade(migration_config(c), "core_0005")
                )
    finally:
        await engine.dispose()
    assert snapshot(database) == before
