"""실제 SQLite·Spakky 요청으로 원문·TODO·시도·정정·외부 대기를 검증한다."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict
from uuid import uuid7

import pytest
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import text

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.usecases.correct_task import CorrectTaskCommand, CorrectTaskUseCase
from neurath.application.usecases.create_task import CreateTaskCommand, CreateTaskUseCase
from neurath.application.usecases.get_sources import GetSourcesQuery, GetSourcesUseCase
from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
from neurath.application.usecases.get_tasks import GetTasksQuery, GetTasksUseCase
from neurath.application.usecases.invalidate_task import (
    InvalidateTaskCommand,
    InvalidateTaskUseCase,
)
from neurath.application.usecases.record_source import RecordSourceCommand, RecordSourceUseCase
from neurath.application.usecases.report_result import ReportResultCommand, ReportResultUseCase
from neurath.application.usecases.resume_task import ResumeTaskCommand, ResumeTaskUseCase
from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
from neurath.application.usecases.submit_result import SubmitResultCommand, SubmitResultUseCase
from neurath.application.usecases.wait_task import WaitTaskCommand, WaitTaskUseCase
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.values.external_wait import ExternalWait
from neurath.domain.values.task_attempt import Outcome, SubmittedResult, TaskResult
from neurath.infrastructure.repositories.request_source import SQLAlchemyRequestSourceRepository
from neurath.infrastructure.repositories.task import SQLAlchemyTaskRepository
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.support.session_requests import register_session


@pytest.fixture
async def actors(database, repository, tmp_path):
    first = await register_session(str(repository), "codex", "first", database_path=database)
    peer = await register_session(str(repository), "claude", "peer", database_path=database)
    folder = tmp_path / "outside"
    folder.mkdir()
    outside = await register_session(str(folder), "codex", "outside", database_path=database)
    return first, peer, outside


async def record(database, actor, kind=SourceKind.PROMPT, *, corrects_id=None, author=None):
    return (
        await run(
            RecordSourceUseCase,
            RecordSourceCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                kind=kind,
                body="original requirement text",
                author=author,
                reference="ticket:140",
                corrects_id=corrects_id,
            ),
            database_path=database,
        )
    ).source


async def create(
    database, actor, *, source=None, title="build artifact", dependencies=(), follow_up_of=None
):
    original = (await record(database, actor)) if source is None else source
    return (
        await run(
            CreateTaskUseCase,
            CreateTaskCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                source_id=original.uid,
                title=title,
                required_result="artifact exists with required content",
                dependencies=dependencies,
                follow_up_of=follow_up_of,
            ),
            database_path=database,
        )
    ).task


async def start(database, task):
    return (
        await run(
            StartTaskUseCase,
            StartTaskCommand(
                project_id=task.project_id,
                session_id=task.owner_session_id,
                task_id=task.uid,
                expected_revision=task.revision,
            ),
            database_path=database,
        )
    ).task


async def report(
    database,
    task,
    outcome=Outcome.SUCCEEDED,
    *,
    attempt=None,
    observation="artifact:observed",
    remaining=None,
    exit_code=0,
):
    number = task.current_attempt_number if attempt is None else attempt
    result = TaskResult(
        outcome=outcome,
        summary="observed result",
        observations=(observation,),
        remaining_work=remaining,
        exit_code=exit_code,
    )
    return (
        await run(
            ReportResultUseCase,
            ReportResultCommand(
                project_id=task.project_id,
                session_id=task.owner_session_id,
                task_id=task.uid,
                expected_revision=task.revision,
                attempt_number=number,
                result=result,
            ),
            database_path=database,
        )
    ).task


async def history(database, task):
    return (
        await run(
            GetTaskUseCase,
            GetTaskQuery(
                project_id=task.project_id, session_id=task.owner_session_id, task_id=task.uid
            ),
            database_path=database,
        )
    ).task


async def board(database, actor):
    return await run(
        GetTasksUseCase,
        GetTasksQuery(project_id=actor.project.uid, session_id=actor.session.uid),
        database_path=database,
    )


def snapshot(database):
    with closing(sqlite3.connect(database)) as connection:
        tables = [
            row[0]
            for row in (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            )
        ]
        return {
            table: (connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')).fetchall()
            for table in tables
        }


@pytest.mark.parametrize("kind", [SourceKind.PROMPT, SourceKind.TICKET, SourceKind.SPEC])
async def test_source_reuse_keeps_original_session_and_nonhuman_author_without_new_human_gate(
    database, actors, kind
):
    first, peer, outside = actors
    assert (
        await run(
            GetSourcesUseCase,
            GetSourcesQuery(project_id=first.project.uid, session_id=first.session.uid),
            database_path=database,
        )
    ).sources == ()
    source = await record(database, first, kind, author="peer:existing assignment")
    work = await create(database, peer, source=source)
    assert work.owner_session_id == peer.session.uid and work.definition.source_id == source.uid
    assert (await board(database, first)).tasks == ()
    assert (await board(database, peer)).tasks == (work,)
    sources = (
        await run(
            GetSourcesUseCase,
            GetSourcesQuery(project_id=first.project.uid, session_id=peer.session.uid),
            database_path=database,
        )
    ).sources
    assert sources == (source,) and sources[0].session_id == first.session.uid
    assert sources[0].author == "peer:existing assignment"
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        (await create(database, outside, source=source))
    with pytest.raises(ContextNotFound):
        (
            await run(
                GetTaskUseCase,
                GetTaskQuery(
                    project_id=work.project_id, session_id=first.session.uid, task_id=work.uid
                ),
                database_path=database,
            )
        ).task
    assert snapshot(database) == before


async def test_actual_failed_command_retry_and_followup_preserve_results_and_todo(
    database, actors, tmp_path
):
    actor, _, _ = actors
    work = await create(database, actor)
    active = await start(database, work)
    submission = SubmittedResult(summary="candidate output", references=("artifact:draft",))
    submitted = (
        await run(
            SubmitResultUseCase,
            SubmitResultCommand(
                project_id=active.project_id,
                session_id=active.owner_session_id,
                task_id=active.uid,
                expected_revision=active.revision,
                attempt_number=1,
                submission=submission,
            ),
            database_path=database,
        )
    ).task
    assert (
        submitted.status is TaskStatus.ACTIVE
        and submitted.attempt(submitted.current_attempt_number).result is None
    )
    before_stale = snapshot(database)
    with pytest.raises(RevisionConflict):
        (await report(database, active))
    assert snapshot(database) == before_stale
    failed_process = subprocess.run(
        [sys.executable, "-c", "raise SystemExit(7)"], capture_output=True, text=True
    )
    assert failed_process.returncode == 7
    failed = await report(
        database,
        submitted,
        Outcome.FAILED,
        observation=f"command:exit={failed_process.returncode}",
        remaining="generate correct artifact",
        exit_code=failed_process.returncode,
    )
    failed_board = await board(database, actor)
    assert failed_board.all_terminal and not failed_board.all_succeeded
    assert failed_board.tasks == (failed,)
    source = (
        await run(
            GetSourcesUseCase,
            GetSourcesQuery(project_id=actor.project.uid, session_id=actor.session.uid),
            database_path=database,
        )
    ).sources[0]
    followup = await create(
        database, actor, source=source, title="validate produced artifact", follow_up_of=failed.uid
    )
    assert (
        followup.follow_up_of == failed.uid
        and (await history(database, failed)).status is TaskStatus.FAILED
    )
    assert followup.uid in (await board(database, actor)).ready_task_ids
    retry = await start(database, failed)
    assert retry.current_attempt_number == 2
    artifact = tmp_path / "produced.txt"
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('required content')",
            str(artifact),
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0 and artifact.read_text() == "required content"
    done = await report(database, retry, observation=str(artifact), exit_code=process.returncode)
    saved = await history(database, done)
    assert [attempt.result.outcome for attempt in saved.attempts] == [
        Outcome.FAILED,
        Outcome.SUCCEEDED,
    ]
    assert saved.attempts[0].submission == submission and saved.attempts[0].result.remaining_work
    assert saved.attempts[1].result.observations == (str(artifact),)
    assert not (await board(database, actor)).all_succeeded
    assert artifact.read_text() == "required content"
    (await report(database, (await start(database, followup)), observation=f"read:{artifact}"))
    assert (await board(database, actor)).all_succeeded


async def test_correction_only_changes_selected_fields_and_late_result_does_not_close_new_requirement(
    database, actors
):
    actor, _, _ = actors
    active = await start(database, (await create(database, actor)))
    original = active.definition
    correction = await record(
        database,
        actor,
        SourceKind.CORRECTION,
        corrects_id=original.source_id,
        author="peer:forwarded correction",
    )
    corrected = (
        await run(
            CorrectTaskUseCase,
            CorrectTaskCommand(
                project_id=active.project_id,
                session_id=active.owner_session_id,
                task_id=active.uid,
                expected_revision=active.revision,
                source_id=correction.uid,
                required_result="corrected artifact",
            ),
            database_path=database,
        )
    ).task
    assert (
        corrected.definition.title == original.title
        and corrected.definition.dependencies == original.dependencies
    )
    late = await report(database, corrected, attempt=1)
    assert late.status is TaskStatus.PENDING and late.current_attempt_number is None
    saved = await history(database, late)
    assert saved.definitions == (original, corrected.definition)
    assert saved.attempts[0].result.outcome is Outcome.SUCCEEDED
    now = await report(database, (await start(database, late)))
    assert (
        now.status is TaskStatus.SUCCEEDED
        and now.attempt(now.current_attempt_number).definition_number == 2
    )
    assert len((await history(database, now)).attempts) == 2


async def test_partial_wait_resume_and_independent_task_keep_exact_same_attempt(
    database, actors, tmp_path
):
    actor, _, _ = actors
    active = await start(database, (await create(database, actor)))
    partial = await report(database, active, Outcome.PARTIAL, remaining="finish remaining artifact")
    assert (
        partial.status is TaskStatus.PENDING
        and partial.attempt(partial.current_attempt_number).result.remaining_work
    )
    active = await start(database, partial)
    independent = await create(database, actor, title="independent requirement")
    target = tmp_path / "external-result"
    assert not target.exists()
    condition = ExternalWait(
        target=str(target),
        condition="file exists",
        resume_scope="read external result",
        observation="file absent",
    )
    waiting = (
        await run(
            WaitTaskUseCase,
            WaitTaskCommand(
                project_id=active.project_id,
                session_id=active.owner_session_id,
                task_id=active.uid,
                expected_revision=active.revision,
                condition=condition,
            ),
            database_path=database,
        )
    ).task
    current = await board(database, actor)
    assert current.ready_task_ids == (independent.uid,) and not current.all_terminal
    assert next(item for item in current.tasks if item.uid == waiting.uid).waits[-1] == condition
    with pytest.raises(InvalidTaskState):
        (await start(database, waiting))
    target.write_text("external result")
    resumed = (
        await run(
            ResumeTaskUseCase,
            ResumeTaskCommand(
                project_id=waiting.project_id,
                session_id=waiting.owner_session_id,
                task_id=waiting.uid,
                expected_revision=waiting.revision,
                resolution=f"read:{target.read_text()}",
            ),
            database_path=database,
        )
    ).task
    assert resumed.current_attempt_number == active.current_attempt_number == 2
    saved = await history(database, resumed)
    assert len(saved.attempts) == 2 and saved.waits[0].resolution == "read:external result"
    assert resumed.status is TaskStatus.ACTIVE


@pytest.mark.parametrize("kind", [SourceKind.STATUS, SourceKind.SUMMARY])
async def test_status_question_and_summary_do_not_create_or_revise_goals(database, actors, kind):
    actor, _, _ = actors
    work = await create(database, actor)
    informational = await record(database, actor, kind)
    before = snapshot(database)
    with pytest.raises(InvalidTaskState):
        (await create(database, actor, source=informational))
    with pytest.raises(InvalidTaskState):
        (
            await run(
                CorrectTaskUseCase,
                CorrectTaskCommand(
                    project_id=work.project_id,
                    session_id=work.owner_session_id,
                    task_id=work.uid,
                    expected_revision=work.revision,
                    source_id=informational.uid,
                    title="unrequested goal",
                ),
                database_path=database,
            )
        ).task
    assert snapshot(database) == before
    assert (await history(database, work)) == work


async def test_dependency_correction_rejects_cycle_and_keeps_previous_graph_and_other_tasks(
    database, actors
):
    actor, _, _ = actors
    parent = await create(database, actor, title="parent")
    child = await create(database, actor, title="child", dependencies=(parent.uid,))
    with pytest.raises(InvalidTaskState):
        (await start(database, child))
    correction = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=parent.definition.source_id
    )
    before = snapshot(database)
    with pytest.raises(InvalidTaskState):
        (
            await run(
                CorrectTaskUseCase,
                CorrectTaskCommand(
                    project_id=parent.project_id,
                    session_id=parent.owner_session_id,
                    task_id=parent.uid,
                    expected_revision=parent.revision,
                    source_id=correction.uid,
                    dependencies=(child.uid,),
                ),
                database_path=database,
            )
        ).task
    with pytest.raises(ContextNotFound):
        (await create(database, actor, source=correction, dependencies=(uuid7(),)))
    assert snapshot(database) == before
    (await report(database, (await start(database, parent))))
    assert child.uid in (await board(database, actor)).ready_task_ids
    corrected = (
        await run(
            CorrectTaskUseCase,
            CorrectTaskCommand(
                project_id=child.project_id,
                session_id=child.owner_session_id,
                task_id=child.uid,
                expected_revision=child.revision,
                source_id=(
                    await record(
                        database,
                        actor,
                        SourceKind.CORRECTION,
                        corrects_id=child.definition.source_id,
                    )
                ).uid,
                title="changed child",
                dependencies=(),
            ),
            database_path=database,
        )
    ).task
    saved = await history(database, corrected)
    assert saved.definitions[0].dependencies == (parent.uid,)
    assert saved.definitions[1].dependencies == ()
    assert (await history(database, parent)).status is TaskStatus.SUCCEEDED


async def test_invalidated_task_never_revives_from_late_result_and_is_not_all_successful(
    database, actors
):
    actor, _, _ = actors
    active = await start(database, (await create(database, actor)))
    change = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=active.definition.source_id
    )
    invalidated = (
        await run(
            InvalidateTaskUseCase,
            InvalidateTaskCommand(
                project_id=active.project_id,
                session_id=active.owner_session_id,
                task_id=active.uid,
                expected_revision=active.revision,
                source_id=change.uid,
                reason="actual user correction",
            ),
            database_path=database,
        )
    ).task
    late = await report(database, invalidated, attempt=1)
    assert late.status is TaskStatus.INVALIDATED
    current = await board(database, actor)
    assert current.all_terminal and not current.all_succeeded
    assert (await history(database, late)).attempts[0].result.outcome is Outcome.SUCCEEDED


async def test_stale_mutation_and_duplicate_result_keep_current_revision(database, actors):
    actor, _, _ = actors
    work = await create(database, actor)
    active = await start(database, work)
    with pytest.raises(RevisionConflict):
        (await start(database, work))
    done = await report(database, active)
    duplicate = await report(database, active)
    assert duplicate == done
    with pytest.raises(InvalidTaskState):
        (
            await report(
                database, done, Outcome.FAILED, remaining="contradictory report", exit_code=7
            )
        )
    with pytest.raises(ContextNotFound):
        (await report(database, done, attempt=404))
    assert (await history(database, done)) == done


async def test_concurrent_start_has_one_winner_and_never_creates_duplicate_attempts(
    database, actors
):
    actor, _, _ = actors
    work = await create(database, actor)

    async def begin():
        try:
            return await start(database, work)
        except RevisionConflict:
            return None

    started = await asyncio.gather(begin(), begin())
    assert sum(item is not None for item in started) == 1
    saved = await history(database, work)
    assert saved.status is TaskStatus.ACTIVE and len(saved.attempts) == 1


async def test_exception_after_generic_flush_rolls_back_attempt_definition_and_state(
    database, actors, monkeypatch
):
    actor, _, _ = actors
    work = await create(database, actor)
    before = snapshot(database)
    original = SQLAlchemyTaskRepository.save

    async def fail_after_flush(self, aggregate):
        await original(self, aggregate)
        raise RuntimeError("after aggregate flush")

    monkeypatch.setattr(SQLAlchemyTaskRepository, "save", fail_after_flush)
    with pytest.raises(RuntimeError, match="after aggregate flush"):
        (await start(database, work))
    assert snapshot(database) == before


async def test_source_correction_and_followup_cannot_cross_project_scope(database, actors):
    actor, _, outside = actors
    foreign = await record(database, outside)
    foreign_task = await create(database, outside, source=foreign)
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        (await record(database, actor, SourceKind.CORRECTION, corrects_id=foreign.uid))
    with pytest.raises(ContextNotFound):
        (await create(database, actor, source=foreign))
    local = await record(database, actor)
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        (await create(database, actor, source=local, follow_up_of=foreign_task.uid))
    with pytest.raises(ContextNotFound):
        (
            await run(
                GetSourcesUseCase,
                GetSourcesQuery(project_id=actor.project.uid, session_id=outside.session.uid),
                database_path=database,
            )
        ).sources
    assert snapshot(database) == before


async def test_source_and_task_repositories_inherit_all_basic_methods(database, actors):
    actor, _, _ = actors
    work = await create(database, actor)
    for adapter in (SQLAlchemyRequestSourceRepository, SQLAlchemyTaskRepository):
        for method in (
            "get",
            "get_or_none",
            "contains",
            "range",
            "save",
            "save_all",
            "delete",
            "delete_all",
            "__init__",
        ):
            assert method not in adapter.__dict__
            assert getattr(adapter, method) is getattr(AbstractAsyncGenericRepository, method)
    async with storage_scope(database, write=False) as scope:
        task = await scope.get(ITaskRepository).get(work.uid)
        assert task.definitions[0].source_id == work.definition.source_id
        assert (
            await scope.get(IRequestSourceRepository).get(task.definition.source_id)
        ).body == "original requirement text"
        assert (
            await scope.get(AsyncSessionManager).session.execute(text("PRAGMA foreign_key_check"))
        ).all() == []


async def test_independent_process_reads_same_todo_without_mutating_task_outcome(database, actors):
    actor, _, _ = actors
    active = await start(database, (await create(database, actor)))
    script = """
import asyncio, json, sys
from dataclasses import asdict
from pathlib import Path
from uuid import UUID
from neurath.application.usecases.get_tasks import GetTasksQuery, GetTasksUseCase
from tests.support.requests import run
print(json.dumps(asdict(asyncio.run(run(GetTasksUseCase, GetTasksQuery(project_id=UUID(sys.argv[2]),session_id=UUID(sys.argv[3])),database_path=Path(sys.argv[1])))), default=str))
"""
    before = snapshot(database)
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(database),
            str(actor.project.uid),
            str(actor.session.uid),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(process.stdout)
    assert observed["tasks"][0]["uid"] == str(active.uid)
    assert observed["tasks"][0]["status"] == "active"
    assert not observed["all_terminal"] and not observed["all_succeeded"]
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "adapter,port,operation",
    [
        (SQLAlchemyRequestSourceRepository, IRequestSourceRepository, "sources"),
        (SQLAlchemyTaskRepository, ITaskRepository, "tasks"),
    ],
)
async def test_query_failure_does_not_hide_remaining_tasks(
    database, actors, monkeypatch, adapter, port, operation
):
    actor, _, _ = actors
    work = await create(database, actor)

    from sqlalchemy.ext.asyncio import AsyncSession

    original = AsyncSession.scalars

    async def missing_rows(self, statement, *args, **kwargs):
        table = "core_request_sources" if operation == "sources" else "core_tasks"
        if table in str(statement):
            raise NotImplementedError("query unavailable")
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalars", missing_rows)
    before = snapshot(database)
    with pytest.raises(NotImplementedError):
        if operation == "sources":
            (
                await run(
                    GetSourcesUseCase,
                    GetSourcesQuery(project_id=actor.project.uid, session_id=actor.session.uid),
                    database_path=database,
                )
            ).sources
        else:
            (await board(database, actor))
    assert snapshot(database) == before
    assert (await history(database, work)) == work


async def test_correction_does_not_rewrite_sibling_goal_or_original_source_and_noop_keeps_success(
    database, actors
):
    actor, _, _ = actors
    original = await record(database, actor)
    first = await create(database, actor, source=original, title="first requirement")
    sibling = await start(
        database, (await create(database, actor, source=original, title="independent requirement"))
    )
    change = (
        await run(
            RecordSourceUseCase,
            RecordSourceCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                kind=SourceKind.CORRECTION,
                body="Change only the first requirement title",
                corrects_id=original.uid,
            ),
            database_path=database,
        )
    ).source
    updated = (
        await run(
            CorrectTaskUseCase,
            CorrectTaskCommand(
                project_id=first.project_id,
                session_id=first.owner_session_id,
                task_id=first.uid,
                expected_revision=first.revision,
                source_id=change.uid,
                title="corrected first title",
            ),
            database_path=database,
        )
    ).task
    assert updated.definition.required_result == first.definition.required_result
    assert (await history(database, sibling)) == sibling
    assert (
        await run(
            GetSourcesUseCase,
            GetSourcesQuery(project_id=actor.project.uid, session_id=actor.session.uid),
            database_path=database,
        )
    ).sources[0] == original
    done = await report(database, (await start(database, updated)))
    unchanged = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=done.definition.source_id
    )
    before = snapshot(database)
    no_change = (
        await run(
            CorrectTaskUseCase,
            CorrectTaskCommand(
                project_id=done.project_id,
                session_id=done.owner_session_id,
                task_id=done.uid,
                expected_revision=done.revision,
                source_id=unchanged.uid,
            ),
            database_path=database,
        )
    ).task
    assert no_change == done and snapshot(database) == before


async def test_todo_contains_all_six_states_and_client_display_cannot_mutate_the_ledger(
    database, actors
):
    actor, _, _ = actors
    pending = await create(database, actor, title="pending")
    active = await start(database, (await create(database, actor, title="active")))
    to_wait = await start(database, (await create(database, actor, title="waiting")))
    waiting = (
        await run(
            WaitTaskUseCase,
            WaitTaskCommand(
                project_id=to_wait.project_id,
                session_id=to_wait.owner_session_id,
                task_id=to_wait.uid,
                expected_revision=to_wait.revision,
                condition=ExternalWait(
                    target="external job",
                    condition="job completed",
                    resume_scope="read result",
                    observation="job running",
                ),
            ),
            database_path=database,
        )
    ).task
    succeeded = await report(
        database, (await start(database, (await create(database, actor, title="succeeded"))))
    )
    failed = await report(
        database,
        (await start(database, (await create(database, actor, title="failed")))),
        Outcome.FAILED,
        remaining="repair artifact",
        exit_code=7,
    )
    original = await create(database, actor, title="invalidated")
    change = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=original.definition.source_id
    )
    invalidated = (
        await run(
            InvalidateTaskUseCase,
            InvalidateTaskCommand(
                project_id=original.project_id,
                session_id=original.owner_session_id,
                task_id=original.uid,
                expected_revision=original.revision,
                source_id=change.uid,
                reason="actual request removed",
            ),
            database_path=database,
        )
    ).task
    current = await board(database, actor)
    assert {item.status for item in current.tasks} == set(TaskStatus)
    assert {item.uid for item in current.tasks} == {
        pending.uid,
        active.uid,
        waiting.uid,
        succeeded.uid,
        failed.uid,
        invalidated.uid,
    }
    assert set(current.ready_task_ids) == {pending.uid, failed.uid}
    before = snapshot(database)
    host_display = json.loads(json.dumps(asdict(current), default=str))
    for item in host_display["tasks"]:
        item["status"] = "completed"
    host_display["tasks"].clear()
    assert asdict(await board(database, actor)) == asdict(current)
    assert snapshot(database) == before
    assert not current.all_terminal and not current.all_succeeded
    # 실제 반환 엔티티를 변경해도 저장소 밖의 조작으로 원장이 바뀌지 않아야 한다.
    current.tasks[0].status = TaskStatus.SUCCEEDED
    reread = await board(database, actor)
    assert {item.status for item in reread.tasks} == set(TaskStatus)
    assert not reread.all_succeeded
    assert snapshot(database) == before
