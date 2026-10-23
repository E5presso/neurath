"""무효 요청·커밋 실패에서 외부 변경이 없고 실제 결과만 보고되는지 검증한다."""

import io
import json
import sqlite3
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic import command as migration
from spakky.data.persistency.repository import EntityNotFoundError
from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.read_memory import ReadMemoryQuery, ReadMemoryUseCase
from neurath.application.usecases.save_checkpoint import (
    SaveCheckpointCommand,
    SaveCheckpointUseCase,
)
from neurath.application.usecases.search_memory import SearchMemoryQuery, SearchMemoryUseCase
from neurath.domain.aggregates.memory import GraphUpdateStatus, Memory, MemoryKind
from neurath.domain.errors import ContextNotFound, InvalidExecutionState
from neurath.infrastructure.database import create_database_engine, initialize_database
from neurath.infrastructure.graph import SubprocessGraphService
from neurath.infrastructure.repositories.memory import SQLAlchemyMemoryRepository
from neurath.transport.cli.memory import MemoryCliController
from tests.conftest import storage_scope
from tests.support.application import spakky_context
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_memory_requests import cli
from tests.test_task_migrations import migration_config
from tests.test_task_requests import create, snapshot


@pytest.fixture
async def context(database, tmp_path):
    actor = await register_session(str(tmp_path), "codex", "checkpoint", database_path=database)
    peer = await register_session(str(tmp_path), "claude", "peer", database_path=database)
    task = await create(database, actor)
    return actor, peer, task


@pytest.fixture
def graph_write(monkeypatch, tmp_path):
    marker = tmp_path / "external-write.txt"
    calls = []

    def update(self, directory):
        calls.append(directory)
        marker.write_text("graph updated")
        return "file:///graph.json#sha256=verified"

    monkeypatch.setattr(SubprocessGraphService, "update", update)
    return marker, calls


@pytest.mark.parametrize(
    "invalid",
    [
        "project",
        "session",
        "missing_task",
        "other_task_owner",
        "handed_off",
        "blank_content",
        "oversized_content",
        "empty_references",
        "blank_reference",
        "blank_graph_directory",
    ],
)
async def test_invalid_checkpoint_never_changes_graph_or_ledger(
    database, context, graph_write, invalid
):
    actor, peer, task = context
    project_id, session_id, task_id = actor.project.uid, actor.session.uid, task.uid
    content, references, directory = "report", ["source:original"], "/graph"
    if invalid == "project":
        project_id = uuid7()
    if invalid == "session":
        session_id = uuid7()
    if invalid == "missing_task":
        task_id = uuid7()
    if invalid == "other_task_owner":
        session_id = peer.session.uid
    if invalid == "handed_off":
        async with storage_scope(database) as scope:
            source = await scope.get(ISessionRepository).get(actor.session.uid)
            source.hand_off(peer.session, source.revision)
            await scope.get(ISessionRepository).save(source)
    if invalid == "blank_content":
        content = " "
    if invalid == "oversized_content":
        content = "가" * 349526
    if invalid == "empty_references":
        references = []
    if invalid == "blank_reference":
        references = [" "]
    if invalid == "blank_graph_directory":
        directory = " "
    before = snapshot(database)
    expected_error = {
        "project": ContextNotFound,
        "session": EntityNotFoundError,
        "missing_task": EntityNotFoundError,
        "other_task_owner": ContextNotFound,
        "handed_off": InvalidExecutionState,
    }.get(invalid, ValueError)
    with pytest.raises(expected_error):
        await run(
            SaveCheckpointUseCase,
            SaveCheckpointCommand(
                project_id=project_id,
                session_id=session_id,
                content=content,
                references=references,
                task_id=task_id,
                graph_directory=directory,
            ),
            database_path=database,
        )
    marker, calls = graph_write
    assert calls == [] and not marker.exists()
    assert snapshot(database) == before


async def test_invalid_cli_checkpoint_is_rejected_before_external_update(
    database, context, graph_write
):
    actor, _, _ = context
    before = snapshot(database)
    result = await cli(
        database,
        [
            "memory",
            "checkpoint",
            "--project-id",
            actor.project.uid,
            "--session-id",
            "missing-session",
            "--content",
            "report",
            "--reference",
            "source",
            "--graph-directory",
            "/graph",
        ],
    )
    assert result.exit_code != 0
    marker, calls = graph_write
    assert not marker.exists() and calls == []
    assert snapshot(database) == before


async def test_stdin_failure_has_no_database_or_graph_effect(database, context, graph_write):
    actor, _, _ = context
    before = snapshot(database)
    stream = io.StringIO()
    stream.close()
    async with spakky_context(database) as scope:
        with patch("sys.stdin", stream), pytest.raises(ValueError):
            await scope.get(MemoryCliController).save_checkpoint(
                actor.project.uid, actor.session.uid, "-", ["source"], graph_directory="/graph"
            )
    marker, calls = graph_write
    assert not marker.exists() and calls == []
    assert snapshot(database) == before


async def test_checkpoint_commit_failure_never_starts_graph_update(
    database, context, graph_write, monkeypatch
):
    actor, _, _ = context
    before = snapshot(database)

    async def fail_commit(self):
        raise RuntimeError("checkpoint commit failed")

    monkeypatch.setattr(AsyncTransaction, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="checkpoint commit failed"):
        await run(
            SaveCheckpointUseCase,
            SaveCheckpointCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                content="report",
                references=["source"],
                graph_directory="/graph",
            ),
            database_path=database,
        )
    marker, calls = graph_write
    assert calls == [] and not marker.exists()
    assert snapshot(database) == before


async def test_graph_runs_after_commit_without_db_lock_then_records_reference(
    database, context, monkeypatch
):
    actor, _, _ = context
    observed = []

    def graph_update(self, directory):
        with sqlite3.connect(database, timeout=0) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT content, graph_directory, graph_reference FROM core_memories"
            ).fetchone()
            assert row == ("report", "/graph", None)
            connection.rollback()
        observed.append(directory)
        return "file:///graph.json#sha256=verified"

    monkeypatch.setattr(SubprocessGraphService, "update", graph_update)
    reserved = await run(
        SaveCheckpointUseCase,
        SaveCheckpointCommand(
            project_id=actor.project.uid,
            session_id=actor.session.uid,
            content="report",
            references=["source"],
            graph_directory="/graph",
        ),
        database_path=database,
    )
    assert observed == ["/graph"]
    assert reserved.graph_status is GraphUpdateStatus.PENDING
    stored = await run(
        ReadMemoryUseCase,
        ReadMemoryQuery(project_id=actor.project.uid, memory_id=reserved.uid),
        database_path=database,
    )
    assert stored.graph_status is GraphUpdateStatus.SUCCEEDED
    assert stored.content == "report"
    assert tuple(stored.references) == ("source", "file:///graph.json#sha256=verified")


@pytest.mark.parametrize("outcome", ["failure", "empty", "record_failure"])
async def test_cli_reports_failed_or_unrecorded_graph_outcome_without_false_success(
    database, context, monkeypatch, tmp_path, outcome
):
    actor, _, _ = context
    marker = tmp_path / "updated.txt"

    def graph_update(self, directory):
        if outcome == "failure":
            raise RuntimeError("graph execution failed")
        if outcome == "empty":
            return " "
        marker.write_text("external update completed")
        return "file:///graph.json#sha256=verified"

    monkeypatch.setattr(SubprocessGraphService, "update", graph_update)
    original_save = SQLAlchemyMemoryRepository.save

    async def save(self, memory):
        if memory.graph_status is GraphUpdateStatus.SUCCEEDED:
            raise RuntimeError("result persistence failed")
        return await original_save(self, memory)

    if outcome == "record_failure":
        monkeypatch.setattr(SQLAlchemyMemoryRepository, "save", save)
    result = await cli(
        database,
        [
            "memory",
            "checkpoint",
            "--project-id",
            actor.project.uid,
            "--session-id",
            actor.session.uid,
            "--content",
            "report",
            "--reference",
            "source",
            "--graph-directory",
            "/graph",
        ],
    )
    assert result.exit_code == 1, result.output
    output = json.loads(result.stdout)
    expected = "pending" if outcome == "record_failure" else "failed"
    assert output["graph_status"] == expected and output["graph_reference"] is None
    assert bool(output["graph_error"]) == (outcome != "record_failure")
    ids = await run(
        SearchMemoryUseCase, SearchMemoryQuery(project_id=actor.project.uid), database_path=database
    )
    assert tuple(ids) == (UUID(output["id"]),)
    stored = await run(
        ReadMemoryUseCase,
        ReadMemoryQuery(project_id=actor.project.uid, memory_id=UUID(output["id"])),
        database_path=database,
    )
    assert stored.content == "report" and tuple(stored.references) == ("source",)
    assert marker.exists() == (outcome == "record_failure")
    read = await cli(
        database, ["memory", "read", "--project-id", actor.project.uid, "--memory-id", output["id"]]
    )
    assert json.loads(read.stdout)["graph_status"] == expected


def test_graph_request_and_outcome_are_bound_to_one_checkpoint():
    memory = Memory.create("p", "s", None, MemoryKind.CHECKPOINT, "report", ["source"])
    assert memory.graph_status is None
    with pytest.raises(ValueError):
        memory.request_graph_update(" ")
    memory.request_graph_update("/graph")
    assert memory.graph_status is GraphUpdateStatus.PENDING
    with pytest.raises(ValueError):
        memory.request_graph_update("/other")
    with pytest.raises(ValueError):
        memory.record_graph_update("/other", "ref", None)
    for reference, error in [(None, None), ("ref", "error"), (" ", None), (None, " ")]:
        with pytest.raises(ValueError):
            memory.record_graph_update("/graph", reference, error)
    memory.record_graph_update("/graph", "ref", None)
    with pytest.raises(ValueError):
        memory.record_graph_update("/graph", None, "late failure")
    assert memory.graph_status is GraphUpdateStatus.SUCCEEDED
    assert memory.references == ("source", "ref")


async def test_graph_migration_preserves_old_report_and_rejects_outcome_loss(
    database, context, monkeypatch
):
    actor, _, _ = context
    await run(
        SaveCheckpointUseCase,
        SaveCheckpointCommand(
            project_id=actor.project.uid,
            session_id=actor.session.uid,
            content="original report",
            references=["original source"],
        ),
        database_path=database,
    )
    before = snapshot(database)
    engine = create_database_engine(database, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda c: migration.downgrade(migration_config(c), "core_0006")
            )
        await initialize_database(database)
        assert snapshot(database) == before
        monkeypatch.setattr(
            SubprocessGraphService, "update", lambda self, directory: "verified-ref"
        )
        await run(
            SaveCheckpointUseCase,
            SaveCheckpointCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                content="graph report",
                references=["source"],
                graph_directory="/graph",
            ),
            database_path=database,
        )
        retained = snapshot(database)
        with pytest.raises(RuntimeError, match="outcomes must be preserved"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda c: migration.downgrade(migration_config(c), "core_0006")
                )
        assert snapshot(database) == retained
    finally:
        await engine.dispose()
