"""실제 SQLite·Spakky 요청으로 원문·TODO·시도·정정·외부 대기를 검증한다."""

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict

import pytest
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from spakky.plugins.sqlalchemy.persistency.session_manager import SessionManager
from sqlalchemy import text

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.usecases.correct_task import CorrectTaskCommand
from neurath.application.usecases.create_task import CreateTaskCommand
from neurath.application.usecases.get_sources import GetSourcesQuery
from neurath.application.usecases.get_task import GetTaskQuery
from neurath.application.usecases.get_tasks import GetTasksQuery
from neurath.application.usecases.invalidate_task import InvalidateTaskCommand
from neurath.application.usecases.record_source import RecordSourceCommand
from neurath.application.usecases.report_result import ReportResultCommand
from neurath.application.usecases.resume_task import ResumeTaskCommand
from neurath.application.usecases.start_task import StartTaskCommand
from neurath.application.usecases.submit_result import SubmitResultCommand
from neurath.application.usecases.wait_task import WaitTaskCommand
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.task_records import (
    ExternalWait,
    Outcome,
    SubmittedResult,
    TaskResult,
    TaskStatus,
)
from neurath.infrastructure.repositories.request_source import RequestSourceRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.transport import task_requests as api
from neurath.transport.session_requests import register_session
from tests.conftest import storage_scope


@pytest.fixture
def actors(database, repository, tmp_path):
    first = register_session(str(repository), "codex", "first", database_path=database)
    peer = register_session(str(repository), "claude", "peer", database_path=database)
    folder = tmp_path / "outside"
    folder.mkdir()
    outside = register_session(str(folder), "codex", "outside", database_path=database)
    return first, peer, outside


def record(database, actor, kind=SourceKind.PROMPT, *, corrects_id=None, author=None):
    return api.record_source(
        RecordSourceCommand(
            actor.project.id,
            actor.session.id,
            kind,
            "original requirement text",
            author,
            "ticket:140",
            corrects_id,
        ),
        database_path=database,
    )


def create(
    database, actor, *, source=None, title="build artifact", dependencies=(), follow_up_of=None
):
    original = record(database, actor) if source is None else source
    return api.create_task(
        CreateTaskCommand(
            actor.project.id,
            actor.session.id,
            original.id,
            title,
            "artifact exists with required content",
            dependencies,
            follow_up_of,
        ),
        database_path=database,
    )


def start(database, task):
    return api.start_task(
        StartTaskCommand(task.project_id, task.owner_session_id, task.id, task.revision),
        database_path=database,
    )


def report(
    database,
    task,
    outcome=Outcome.SUCCEEDED,
    *,
    attempt=None,
    observation="artifact:observed",
    remaining=None,
    exit_code=0,
):
    number = task.attempt.number if attempt is None else attempt
    result = TaskResult(
        outcome=outcome,
        summary="observed result",
        observations=(observation,),
        remaining_work=remaining,
        exit_code=exit_code,
    )
    return api.report_result(
        ReportResultCommand(
            task.project_id, task.owner_session_id, task.id, task.revision, number, result
        ),
        database_path=database,
    )


def history(database, task):
    return api.get_task(
        GetTaskQuery(task.project_id, task.owner_session_id, task.id), database_path=database
    )


def board(database, actor):
    return api.get_tasks(GetTasksQuery(actor.project.id, actor.session.id), database_path=database)


def snapshot(database):
    with closing(sqlite3.connect(database)) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in tables
        }


@pytest.mark.parametrize("kind", [SourceKind.PROMPT, SourceKind.TICKET, SourceKind.SPEC])
def test_source_reuse_keeps_original_session_and_nonhuman_author_without_new_human_gate(
    database, actors, kind
):
    first, peer, outside = actors
    assert (
        api.get_sources(GetSourcesQuery(first.project.id, first.session.id), database_path=database)
        == ()
    )
    source = record(database, first, kind, author="peer:existing assignment")
    work = create(database, peer, source=source)
    assert work.owner_session_id == peer.session.id and work.definition.source_id == source.id
    assert board(database, first).tasks == ()
    assert board(database, peer).tasks == (work,)
    sources = api.get_sources(
        GetSourcesQuery(first.project.id, peer.session.id), database_path=database
    )
    assert sources == (source,) and sources[0].session_id == first.session.id
    assert sources[0].author == "peer:existing assignment"
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        create(database, outside, source=source)
    with pytest.raises(ContextNotFound):
        api.get_task(
            GetTaskQuery(work.project_id, first.session.id, work.id), database_path=database
        )
    assert snapshot(database) == before


def test_actual_failed_command_retry_and_followup_preserve_results_and_todo(
    database, actors, tmp_path
):
    actor, _, _ = actors
    work = create(database, actor)
    active = start(database, work)
    submission = SubmittedResult(summary="candidate output", references=("artifact:draft",))
    submitted = api.submit_result(
        SubmitResultCommand(
            active.project_id, active.owner_session_id, active.id, active.revision, 1, submission
        ),
        database_path=database,
    )
    assert submitted.status is TaskStatus.ACTIVE and submitted.attempt.result is None
    before_stale = snapshot(database)
    with pytest.raises(RevisionConflict):
        report(database, active)
    assert snapshot(database) == before_stale
    failed_process = subprocess.run(
        [sys.executable, "-c", "raise SystemExit(7)"], capture_output=True, text=True
    )
    assert failed_process.returncode == 7
    failed = report(
        database,
        submitted,
        Outcome.FAILED,
        observation=f"command:exit={failed_process.returncode}",
        remaining="generate correct artifact",
        exit_code=failed_process.returncode,
    )
    failed_board = board(database, actor)
    assert failed_board.all_terminal and not failed_board.all_succeeded
    assert failed_board.tasks == (failed,)
    source = api.get_sources(
        GetSourcesQuery(actor.project.id, actor.session.id), database_path=database
    )[0]
    followup = create(
        database, actor, source=source, title="validate produced artifact", follow_up_of=failed.id
    )
    assert (
        followup.follow_up_of == failed.id
        and history(database, failed).task.status is TaskStatus.FAILED
    )
    assert followup.id in board(database, actor).ready_task_ids
    retry = start(database, failed)
    assert retry.attempt.number == 2
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
    done = report(database, retry, observation=str(artifact), exit_code=process.returncode)
    saved = history(database, done)
    assert [attempt.result.outcome for attempt in saved.attempts] == [
        Outcome.FAILED,
        Outcome.SUCCEEDED,
    ]
    assert saved.attempts[0].submission == submission and saved.attempts[0].result.remaining_work
    assert saved.attempts[1].result.observations == (str(artifact),)
    assert not board(database, actor).all_succeeded
    assert artifact.read_text() == "required content"
    report(database, start(database, followup), observation=f"read:{artifact}")
    assert board(database, actor).all_succeeded


def test_correction_only_changes_selected_fields_and_late_result_does_not_close_new_requirement(
    database, actors
):
    actor, _, _ = actors
    active = start(database, create(database, actor))
    original = active.definition
    correction = record(
        database,
        actor,
        SourceKind.CORRECTION,
        corrects_id=original.source_id,
        author="peer:forwarded correction",
    )
    corrected = api.correct_task(
        CorrectTaskCommand(
            active.project_id,
            active.owner_session_id,
            active.id,
            active.revision,
            correction.id,
            required_result="corrected artifact",
        ),
        database_path=database,
    )
    assert (
        corrected.definition.title == original.title
        and corrected.definition.dependencies == original.dependencies
    )
    late = report(database, corrected, attempt=1)
    assert late.status is TaskStatus.PENDING and late.attempt is None
    saved = history(database, late)
    assert saved.definitions == (original, corrected.definition)
    assert saved.attempts[0].result.outcome is Outcome.SUCCEEDED
    now = report(database, start(database, late))
    assert now.status is TaskStatus.SUCCEEDED and now.attempt.definition_number == 2
    assert len(history(database, now).attempts) == 2


def test_partial_wait_resume_and_independent_task_keep_exact_same_attempt(
    database, actors, tmp_path
):
    actor, _, _ = actors
    active = start(database, create(database, actor))
    partial = report(database, active, Outcome.PARTIAL, remaining="finish remaining artifact")
    assert partial.status is TaskStatus.PENDING and partial.attempt.result.remaining_work
    active = start(database, partial)
    independent = create(database, actor, title="independent requirement")
    target = tmp_path / "external-result"
    assert not target.exists()
    condition = ExternalWait(
        target=str(target),
        condition="file exists",
        resume_scope="read external result",
        observation="file absent",
    )
    waiting = api.wait_task(
        WaitTaskCommand(
            active.project_id, active.owner_session_id, active.id, active.revision, condition
        ),
        database_path=database,
    )
    current = board(database, actor)
    assert current.ready_task_ids == (independent.id,) and not current.all_terminal
    assert next(item for item in current.tasks if item.id == waiting.id).external_wait == condition
    with pytest.raises(InvalidTaskState):
        start(database, waiting)
    target.write_text("external result")
    resumed = api.resume_task(
        ResumeTaskCommand(
            waiting.project_id,
            waiting.owner_session_id,
            waiting.id,
            waiting.revision,
            f"read:{target.read_text()}",
        ),
        database_path=database,
    )
    assert resumed.attempt.number == active.attempt.number == 2
    saved = history(database, resumed)
    assert len(saved.attempts) == 2 and saved.waits[0].resolution == "read:external result"
    assert resumed.status is TaskStatus.ACTIVE


@pytest.mark.parametrize("kind", [SourceKind.STATUS, SourceKind.SUMMARY])
def test_status_question_and_summary_do_not_create_or_revise_goals(database, actors, kind):
    actor, _, _ = actors
    work = create(database, actor)
    informational = record(database, actor, kind)
    before = snapshot(database)
    with pytest.raises(InvalidTaskState):
        create(database, actor, source=informational)
    with pytest.raises(InvalidTaskState):
        api.correct_task(
            CorrectTaskCommand(
                work.project_id,
                work.owner_session_id,
                work.id,
                work.revision,
                informational.id,
                title="unrequested goal",
            ),
            database_path=database,
        )
    assert snapshot(database) == before
    assert history(database, work).task == work


def test_dependency_correction_rejects_cycle_and_keeps_previous_graph_and_other_tasks(
    database, actors
):
    actor, _, _ = actors
    parent = create(database, actor, title="parent")
    child = create(database, actor, title="child", dependencies=(parent.id,))
    with pytest.raises(InvalidTaskState):
        start(database, child)
    correction = record(
        database, actor, SourceKind.CORRECTION, corrects_id=parent.definition.source_id
    )
    before = snapshot(database)
    with pytest.raises(InvalidTaskState):
        api.correct_task(
            CorrectTaskCommand(
                parent.project_id,
                parent.owner_session_id,
                parent.id,
                parent.revision,
                correction.id,
                dependencies=(child.id,),
            ),
            database_path=database,
        )
    with pytest.raises(ContextNotFound):
        create(database, actor, source=correction, dependencies=("missing",))
    assert snapshot(database) == before
    report(database, start(database, parent))
    assert child.id in board(database, actor).ready_task_ids
    corrected = api.correct_task(
        CorrectTaskCommand(
            child.project_id,
            child.owner_session_id,
            child.id,
            child.revision,
            record(
                database, actor, SourceKind.CORRECTION, corrects_id=child.definition.source_id
            ).id,
            title="changed child",
            dependencies=(),
        ),
        database_path=database,
    )
    saved = history(database, corrected)
    assert saved.definitions[0].dependencies == (parent.id,)
    assert saved.definitions[1].dependencies == ()
    assert history(database, parent).task.status is TaskStatus.SUCCEEDED


def test_invalidated_task_never_revives_from_late_result_and_is_not_all_successful(
    database, actors
):
    actor, _, _ = actors
    active = start(database, create(database, actor))
    change = record(database, actor, SourceKind.CORRECTION, corrects_id=active.definition.source_id)
    invalidated = api.invalidate_task(
        InvalidateTaskCommand(
            active.project_id,
            active.owner_session_id,
            active.id,
            active.revision,
            change.id,
            "actual user correction",
        ),
        database_path=database,
    )
    late = report(database, invalidated, attempt=1)
    assert late.status is TaskStatus.INVALIDATED
    current = board(database, actor)
    assert current.all_terminal and not current.all_succeeded
    assert history(database, late).attempts[0].result.outcome is Outcome.SUCCEEDED


def test_stale_mutation_and_duplicate_result_keep_current_revision(database, actors):
    actor, _, _ = actors
    work = create(database, actor)
    active = start(database, work)
    with pytest.raises(RevisionConflict):
        start(database, work)
    done = report(database, active)
    duplicate = report(database, active)
    assert duplicate == done
    with pytest.raises(InvalidTaskState):
        report(database, done, Outcome.FAILED, remaining="contradictory report", exit_code=7)
    with pytest.raises(ContextNotFound):
        report(database, done, attempt=404)
    assert history(database, done).task == done


def test_concurrent_start_has_one_winner_and_never_creates_duplicate_attempts(database, actors):
    actor, _, _ = actors
    work = create(database, actor)

    def begin(_):
        try:
            return start(database, work)
        except RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        started = list(executor.map(begin, range(2)))
    assert sum(item is not None for item in started) == 1
    saved = history(database, work)
    assert saved.task.status is TaskStatus.ACTIVE and len(saved.attempts) == 1


def test_exception_after_generic_flush_rolls_back_attempt_definition_and_state(
    database, actors, monkeypatch
):
    actor, _, _ = actors
    work = create(database, actor)
    before = snapshot(database)
    original = TaskRepository.save

    def fail_after_flush(self, aggregate):
        original(self, aggregate)
        raise RuntimeError("after aggregate flush")

    monkeypatch.setattr(TaskRepository, "save", fail_after_flush)
    with pytest.raises(RuntimeError, match="after aggregate flush"):
        start(database, work)
    assert snapshot(database) == before


def test_source_correction_and_followup_cannot_cross_project_scope(database, actors):
    actor, _, outside = actors
    foreign = record(database, outside)
    foreign_task = create(database, outside, source=foreign)
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        record(database, actor, SourceKind.CORRECTION, corrects_id=foreign.id)
    with pytest.raises(ContextNotFound):
        create(database, actor, source=foreign)
    local = record(database, actor)
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        create(database, actor, source=local, follow_up_of=foreign_task.id)
    with pytest.raises(ContextNotFound):
        api.get_sources(
            GetSourcesQuery(actor.project.id, outside.session.id), database_path=database
        )
    assert snapshot(database) == before


def test_source_and_task_repositories_inherit_all_basic_methods(database, actors):
    actor, _, _ = actors
    work = create(database, actor)
    for adapter in (RequestSourceRepository, TaskRepository):
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
            assert getattr(adapter, method) is getattr(AbstractGenericRepository, method)
    with storage_scope(database, write=False) as scope:
        task = scope.get(ITaskRepository).get(work.id)
        assert task.definitions[0].source_id == work.definition.source_id
        assert (
            scope.get(IRequestSourceRepository).get(task.definition.source_id).body
            == "original requirement text"
        )
        assert (
            scope.get(SessionManager).session.execute(text("PRAGMA foreign_key_check")).all() == []
        )


def test_independent_process_reads_same_todo_without_mutating_task_outcome(database, actors):
    actor, _, _ = actors
    active = start(database, create(database, actor))
    script = """
import json, sys
from dataclasses import asdict
from pathlib import Path
from neurath.application.usecases.get_tasks import GetTasksQuery
from neurath.transport.task_requests import get_tasks
print(json.dumps(asdict(get_tasks(GetTasksQuery(sys.argv[2],sys.argv[3]),database_path=Path(sys.argv[1])))))
"""
    before = snapshot(database)
    process = subprocess.run(
        [sys.executable, "-c", script, str(database), actor.project.id, actor.session.id],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(process.stdout)
    assert observed["tasks"][0]["id"] == active.id
    assert observed["tasks"][0]["status"] == "active"
    assert not observed["all_terminal"] and not observed["all_succeeded"]
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "adapter,port,operation",
    [
        (RequestSourceRepository, IRequestSourceRepository, "sources"),
        (TaskRepository, ITaskRepository, "tasks"),
    ],
)
def test_missing_list_implementation_fails_instead_of_hiding_remaining_tasks(
    database, actors, monkeypatch, adapter, port, operation
):
    actor, _, _ = actors
    work = create(database, actor)

    def missing_list(self, project_id):
        return port.list(self, project_id)

    monkeypatch.setattr(adapter, "list", missing_list)
    before = snapshot(database)
    with pytest.raises(NotImplementedError):
        if operation == "sources":
            api.get_sources(
                GetSourcesQuery(actor.project.id, actor.session.id), database_path=database
            )
        else:
            board(database, actor)
    assert snapshot(database) == before
    assert history(database, work).task == work


def test_correction_does_not_rewrite_sibling_goal_or_original_source_and_noop_keeps_success(
    database, actors
):
    actor, _, _ = actors
    original = record(database, actor)
    first = create(database, actor, source=original, title="first requirement")
    sibling = start(
        database, create(database, actor, source=original, title="independent requirement")
    )
    change = api.record_source(
        RecordSourceCommand(
            actor.project.id,
            actor.session.id,
            SourceKind.CORRECTION,
            "Change only the first requirement title",
            corrects_id=original.id,
        ),
        database_path=database,
    )
    updated = api.correct_task(
        CorrectTaskCommand(
            first.project_id,
            first.owner_session_id,
            first.id,
            first.revision,
            change.id,
            title="corrected first title",
        ),
        database_path=database,
    )
    assert updated.definition.required_result == first.definition.required_result
    assert history(database, sibling).task == sibling
    assert (
        api.get_sources(
            GetSourcesQuery(actor.project.id, actor.session.id), database_path=database
        )[0]
        == original
    )
    done = report(database, start(database, updated))
    unchanged = record(
        database, actor, SourceKind.CORRECTION, corrects_id=done.definition.source_id
    )
    before = snapshot(database)
    no_change = api.correct_task(
        CorrectTaskCommand(
            done.project_id, done.owner_session_id, done.id, done.revision, unchanged.id
        ),
        database_path=database,
    )
    assert no_change == done and snapshot(database) == before


def test_todo_contains_all_six_states_and_client_display_cannot_mutate_the_ledger(database, actors):
    actor, _, _ = actors
    pending = create(database, actor, title="pending")
    active = start(database, create(database, actor, title="active"))
    to_wait = start(database, create(database, actor, title="waiting"))
    waiting = api.wait_task(
        WaitTaskCommand(
            to_wait.project_id,
            to_wait.owner_session_id,
            to_wait.id,
            to_wait.revision,
            ExternalWait(
                target="external job",
                condition="job completed",
                resume_scope="read result",
                observation="job running",
            ),
        ),
        database_path=database,
    )
    succeeded = report(database, start(database, create(database, actor, title="succeeded")))
    failed = report(
        database,
        start(database, create(database, actor, title="failed")),
        Outcome.FAILED,
        remaining="repair artifact",
        exit_code=7,
    )
    original = create(database, actor, title="invalidated")
    change = record(
        database, actor, SourceKind.CORRECTION, corrects_id=original.definition.source_id
    )
    invalidated = api.invalidate_task(
        InvalidateTaskCommand(
            original.project_id,
            original.owner_session_id,
            original.id,
            original.revision,
            change.id,
            "actual request removed",
        ),
        database_path=database,
    )
    current = board(database, actor)
    assert {item.status for item in current.tasks} == set(TaskStatus)
    assert {item.id for item in current.tasks} == {
        pending.id,
        active.id,
        waiting.id,
        succeeded.id,
        failed.id,
        invalidated.id,
    }
    assert set(current.ready_task_ids) == {pending.id, failed.id}
    before = snapshot(database)
    host_display = json.loads(json.dumps(asdict(current)))
    for item in host_display["tasks"]:
        item["status"] = "completed"
    host_display["tasks"].clear()
    assert board(database, actor) == current
    assert snapshot(database) == before
    assert not current.all_terminal and not current.all_succeeded
