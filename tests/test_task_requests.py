"""Task requirements remain durable across corrections, failed attempts and external waits."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurath.application.ports.usecases.correct_task import CorrectTaskCommand
from neurath.application.ports.usecases.create_task import CreateTaskCommand
from neurath.application.ports.usecases.get_sources import GetSourcesQuery
from neurath.application.ports.usecases.get_task_attempts import GetTaskAttemptsQuery
from neurath.application.ports.usecases.get_task_history import GetTaskHistoryQuery
from neurath.application.ports.usecases.get_tasks import GetTasksQuery
from neurath.application.ports.usecases.invalidate_task import InvalidateTaskCommand
from neurath.application.ports.usecases.record_source import RecordSourceCommand
from neurath.application.ports.usecases.report_task_result import ReportTaskResultCommand
from neurath.application.ports.usecases.resume_task import ResumeTaskCommand
from neurath.application.ports.usecases.start_task import StartTaskCommand
from neurath.application.ports.usecases.wait_task import WaitTaskCommand
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.aggregates.task import ExternalWait, TaskStatus
from neurath.domain.aggregates.task_attempt import AttemptOutcome
from neurath.domain.errors import ContextNotFound, InvalidTaskOperation, RevisionConflict
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.task_change import ChangeRepository
from neurath.transport.correct_task import correct_task
from neurath.transport.create_task import create_task
from neurath.transport.get_sources import get_sources
from neurath.transport.get_task_attempts import get_task_attempts
from neurath.transport.get_task_history import get_task_history
from neurath.transport.get_tasks import get_tasks
from neurath.transport.invalidate_task import invalidate_task
from neurath.transport.record_source import record_source
from neurath.transport.report_task_result import report_task_result
from neurath.transport.resume_task import resume_task
from neurath.transport.session_requests import register_session
from neurath.transport.start_task import start_task
from neurath.transport.wait_task import wait_task


@dataclass
class Environment:
    path: Path
    project: str
    session: str

    def source(
        self,
        kind=SourceKind.INSTRUCTION,
        text="원문을 그대로 보존하세요.\n실패도 기록합니다.",
        corrects_id=None,
        author="human",
    ):
        return record_source(
            RecordSourceCommand(
                self.project, self.session, kind, author, "ticket://140", text, corrects_id
            ),
            database_path=self.path,
        )

    def create(self, source, title="분석", **fields):
        return create_task(
            CreateTaskCommand(
                self.project, self.session, source.id, title, "검증한 산출물", **fields
            ),
            database_path=self.path,
        )

    def projection(self):
        return get_tasks(GetTasksQuery(self.project, self.session), database_path=self.path)

    def current(self, task):
        return next(value for value in self.projection().tasks if value.id == task.id)

    def start(self, task, executor="worker"):
        return start_task(
            StartTaskCommand(self.project, self.session, task.id, executor, task.revision),
            database_path=self.path,
        )

    def report(self, attempt, outcome=AttemptOutcome.SUCCEEDED, **fields):
        return report_task_result(
            ReportTaskResultCommand(
                self.project,
                self.session,
                attempt.id,
                fields.pop("executor", attempt.executor),
                outcome,
                fields.pop("summary", "실제 실행 결과"),
                fields.pop("evidence", "artifact://checked-output"),
                **fields,
            ),
            database_path=self.path,
        )

    def correct(self, task, source, **fields):
        return correct_task(
            CorrectTaskCommand(
                self.project, self.session, task.id, source.id, task.revision, **fields
            ),
            database_path=self.path,
        )

    def history(self, task):
        return get_task_history(
            GetTaskHistoryQuery(self.project, self.session, task.id), database_path=self.path
        )

    def attempts(self, task):
        return get_task_attempts(
            GetTaskAttemptsQuery(self.project, self.session, task.id), database_path=self.path
        )


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    SqliteDatabase(path).initialize()
    context = register_session(str(tmp_path), "codex", "native", database_path=path)
    return Environment(path, context.project.id, context.session.id)


def test_a01_attributed_source_is_reusable_without_fresh_direct_human_input(env):
    source = env.source(author="delegated-agent")
    first = env.create(source)
    second = env.create(source, "보고서")
    originals = get_sources(GetSourcesQuery(env.project, env.session), database_path=env.path)
    assert originals == (source,)
    assert source.text == "원문을 그대로 보존하세요.\n실패도 기록합니다."
    assert {task.id for task in env.projection().tasks} == {first.id, second.id}
    assert first.source_id == second.source_id == source.id


@pytest.mark.parametrize("kind", [SourceKind.STATUS_QUESTION, SourceKind.SUMMARY])
def test_a04_status_question_and_old_summary_never_create_a_goal(env, kind):
    observed = env.source(kind)
    with pytest.raises(InvalidTaskOperation, match="instruction"):
        env.create(observed)
    assert env.projection().tasks == ()
    assert not env.projection().all_terminal
    assert not env.projection().all_succeeded


def test_a04_correction_changes_only_selected_fields_and_task(env):
    source = env.source()
    first = env.create(source)
    second = env.create(source, "unchanged")
    correction = env.source(SourceKind.CORRECTION, "제목만 수정", source.id)
    changed = env.correct(first, correction, title="새 제목")
    assert changed.expected_outcome == first.expected_outcome
    assert changed.source_id == first.source_id
    assert changed.definition_revision == 2
    assert env.current(second) == second
    assert [item.task for item in env.history(first)] == [first, changed]
    assert [item.reason for item in env.history(first)] == [source.reference, correction.id]
    with pytest.raises(InvalidTaskOperation, match="current task source"):
        env.correct(changed, correction, title="stale correction")


def test_b04_late_result_is_recorded_but_cannot_close_corrected_requirement(env):
    source = env.source()
    task = env.create(source)
    old_attempt = env.start(task)
    correction = env.source(SourceKind.CORRECTION, "새 결과 조건", source.id)
    changed = env.correct(env.current(task), correction, expected_outcome="new expected result")
    assert env.report(old_attempt) == changed
    assert env.attempts(task)[0].outcome is AttemptOutcome.SUCCEEDED
    assert env.current(task).status is TaskStatus.PENDING
    new_attempt = env.start(changed)
    assert env.report(new_attempt).status is TaskStatus.SUCCEEDED
    assert len(env.attempts(task)) == 2


def test_a05_start_is_not_success_and_todo_is_complete_current_projection(env):
    source = env.source()
    success = env.create(source, "success")
    failure = env.create(source, "failure")
    cancelled = env.create(source, "cancelled")
    attempt = env.start(success)
    assert env.current(success).status is TaskStatus.ACTIVE
    assert env.attempts(success)[0].outcome is None
    env.report(attempt)
    env.report(env.start(failure), AttemptOutcome.FAILED, remaining_work="검증 오류 해결")
    correction = env.source(SourceKind.CORRECTION, "cancel requirement", source.id)
    invalidate_task(
        InvalidateTaskCommand(
            env.project, env.session, cancelled.id, correction.id, "사용자가 취소", 1
        ),
        database_path=env.path,
    )
    projection = env.projection()
    assert {task.status for task in projection.tasks} == {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.INVALIDATED,
    }
    assert projection.all_terminal and not projection.all_succeeded
    assert len(projection.tasks) == 3


def test_a06_failure_retry_preserves_attempt_and_remaining_work(env):
    task = env.create(env.source())
    first = env.start(task)
    failed = env.report(first, AttemptOutcome.FAILED, remaining_work="실패한 검사 수리")
    assert failed.remaining_work == "실패한 검사 수리"
    second = env.start(failed)
    env.report(second)
    attempts = env.attempts(task)
    assert {item.outcome for item in attempts} == {AttemptOutcome.FAILED, AttemptOutcome.SUCCEEDED}
    assert (
        next(item for item in attempts if item.id == first.id).remaining_work == "실패한 검사 수리"
    )
    assert env.projection().all_succeeded
    assert [item.task.status for item in env.history(task)] == [
        TaskStatus.PENDING,
        TaskStatus.ACTIVE,
        TaskStatus.FAILED,
        TaskStatus.ACTIVE,
        TaskStatus.SUCCEEDED,
    ]


def test_a06_failed_requirement_can_have_linked_followup_without_erasing_failure(env):
    source = env.source()
    task = env.create(source)
    failed = env.report(env.start(task), AttemptOutcome.FAILED, remaining_work="fix broken output")
    followup = env.create(source, "repair output", follows_task_id=failed.id)
    env.report(env.start(followup))
    assert env.current(task) == failed
    assert env.projection().all_terminal and not env.projection().all_succeeded


@pytest.mark.parametrize(
    "fields",
    [
        {"evidence": ""},
        {"summary": ""},
        {"remaining_work": "not done"},
        {"executor": "unrelated-peer"},
    ],
)
def test_no_success_without_actual_complete_attributed_result(env, fields):
    task = env.create(env.source())
    attempt = env.start(task)
    with pytest.raises(InvalidTaskOperation):
        env.report(attempt, **fields)
    assert env.current(task).status is TaskStatus.ACTIVE
    assert env.attempts(task)[0].outcome is None


def test_failure_without_remaining_work_is_rejected_and_duplicate_result_is_immutable(env):
    task = env.create(env.source())
    attempt = env.start(task)
    with pytest.raises(InvalidTaskOperation, match="remaining work"):
        env.report(attempt, AttemptOutcome.FAILED)
    succeeded = env.report(attempt)
    with pytest.raises(InvalidTaskOperation, match="already"):
        env.report(attempt, AttemptOutcome.FAILED, remaining_work="overwrite")
    assert env.current(task) == succeeded


def test_a44_external_wait_and_dependencies_do_not_block_independent_ready_work(env):
    source = env.source()
    waiting = env.create(source, "external")
    dependent = env.create(source, "dependent", dependencies=(waiting.id,))
    independent = env.create(source, "independent")
    waited = wait_task(
        WaitTaskCommand(
            env.project,
            env.session,
            waiting.id,
            ExternalWait(
                "PR #10", "review completed", "apply authorized review fixes", "review://pending"
            ),
            1,
        ),
        database_path=env.path,
    )
    assert env.projection().ready == (independent,)
    with pytest.raises(InvalidTaskOperation, match="unfinished dependency"):
        env.start(dependent)
    env.report(env.start(independent))
    with pytest.raises(InvalidTaskOperation, match="release evidence"):
        resume_task(
            ResumeTaskCommand(env.project, env.session, waited.id, "", waited.revision),
            database_path=env.path,
        )
    resumed = resume_task(
        ResumeTaskCommand(
            env.project, env.session, waited.id, "review://completed", waited.revision
        ),
        database_path=env.path,
    )
    env.report(env.start(resumed))
    assert env.projection().ready == (dependent,)
    env.report(env.start(dependent))
    assert env.projection().all_succeeded


def test_a44_reason_only_fake_wait_is_not_representable(env):
    with pytest.raises(InvalidTaskOperation, match="target, condition"):
        ExternalWait("", "waiting for user to repeat request", "", "")
    task = env.create(env.source(author="agent"))
    assert env.projection().ready == (task,)
    env.report(env.start(task))


def test_result_for_same_attempt_resolves_external_wait_without_reexecution(env):
    task = env.create(env.source())
    attempt = env.start(task)
    active = env.current(task)
    wait_task(
        WaitTaskCommand(
            env.project,
            env.session,
            task.id,
            ExternalWait("job://1", "job completed", "collect output", "job://running"),
            active.revision,
        ),
        database_path=env.path,
    )
    assert env.report(attempt).status is TaskStatus.SUCCEEDED
    assert len(env.attempts(task)) == 1


def test_invalidated_task_preserves_late_actual_attempt_without_fabricated_stop(env):
    source = env.source()
    task = env.create(source)
    attempt = env.start(task)
    active = env.current(task)
    correction = env.source(SourceKind.CORRECTION, "cancel", source.id)
    cancelled = invalidate_task(
        InvalidateTaskCommand(
            env.project, env.session, task.id, correction.id, "cancelled", active.revision
        ),
        database_path=env.path,
    )
    assert env.attempts(task)[0].outcome is None
    assert env.report(attempt) == cancelled
    assert env.attempts(task)[0].outcome is AttemptOutcome.SUCCEEDED


def test_dependency_cycle_rejection_rolls_back_correction(env):
    source = env.source()
    first = env.create(source)
    second = env.create(source, "depends on first", dependencies=(first.id,))
    correction = env.source(SourceKind.CORRECTION, "add dependency", source.id)
    with pytest.raises(InvalidTaskOperation, match="cycle"):
        env.correct(first, correction, dependencies=(second.id,))
    assert env.current(first) == first
    assert len(env.history(first)) == 1


def test_cross_session_and_project_sources_tasks_and_attempts_are_rejected(env, tmp_path):
    source = env.source()
    task = env.create(source)
    attempt = env.start(task)
    context = register_session(str(tmp_path), "codex", "other-session", database_path=env.path)
    other = Environment(env.path, context.project.id, context.session.id)
    reused = other.create(source)
    assert reused.source_id == source.id
    with pytest.raises(ContextNotFound):
        other.report(attempt)
    own = other.source()
    with pytest.raises(ContextNotFound):
        other.create(own, dependencies=(task.id,))
    folder = tmp_path / "another-project"
    folder.mkdir()
    separate = register_session(str(folder), "codex", "native", database_path=env.path)
    with pytest.raises(ContextNotFound):
        get_tasks(GetTasksQuery(separate.project.id, env.session), database_path=env.path)
    assert other.projection().tasks == (reused,)
    unrelated = Environment(env.path, separate.project.id, separate.session.id)
    with pytest.raises(ContextNotFound):
        unrelated.create(source)


def test_stale_revision_and_concurrent_start_create_exactly_one_attempt(env):
    task = env.create(env.source())

    def start(_):
        try:
            env.start(task)
            return "started"
        except RevisionConflict:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(start, range(2))) == ["stale", "started"]
    assert len(env.attempts(task)) == 1
    assert len(env.history(task)) == 2


def test_history_failure_rolls_back_task_and_attempt_atomically(env, monkeypatch):
    task = env.create(env.source())

    def fail(self, value):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(ChangeRepository, "add", fail)
    with pytest.raises(RuntimeError, match="history unavailable"):
        env.start(task)
    assert env.current(task) == task
    assert env.attempts(task) == ()


def test_result_and_attempt_roll_back_together_when_history_write_fails(env, monkeypatch):
    task = env.create(env.source())
    attempt = env.start(task)

    def fail(self, value):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(ChangeRepository, "add", fail)
    with pytest.raises(RuntimeError):
        env.report(attempt)
    assert env.current(task).status is TaskStatus.ACTIVE
    assert env.attempts(task)[0].outcome is None


def test_request_uses_fresh_process_and_readonly_projection_preserves_database(env):
    source = env.source()
    task = env.create(source)
    before = env.path.read_bytes()
    script = """from pathlib import Path
import sys
from neurath.application.ports.usecases.get_tasks import GetTasksQuery
from neurath.transport.get_tasks import get_tasks
p = get_tasks(GetTasksQuery(sys.argv[2], sys.argv[3]), database_path=Path(sys.argv[1]))
assert p.tasks[0].id == sys.argv[4]
assert p.tasks[0].status.value == 'pending'
"""
    subprocess.run(
        [sys.executable, "-c", script, str(env.path), env.project, env.session, task.id],
        check=True,
        capture_output=True,
    )
    assert env.path.read_bytes() == before


def test_sqlite_foreign_keys_reject_cross_scope_source_and_preserve_schema(env):
    source = env.source()
    task = env.create(source)
    database = SqliteDatabase(env.path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            with pytest.raises(IntegrityError):
                session.connection().exec_driver_sql(
                    "UPDATE tasks SET source_id='absent' WHERE id=?", (task.id,)
                )
    finally:
        engine.dispose()
    with sqlite3.connect(env.path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert env.current(task) == task


def test_source_correction_must_target_an_actionable_record_in_same_scope(env):
    question = env.source(SourceKind.STATUS_QUESTION)
    with pytest.raises(InvalidTaskOperation, match="question or summary"):
        env.source(SourceKind.CORRECTION, "invented change", question.id)
    with pytest.raises(ContextNotFound):
        env.source(SourceKind.CORRECTION, "missing original", "missing")
    with pytest.raises(InvalidTaskOperation, match="Only a correction"):
        env.source(SourceKind.INSTRUCTION, corrects_id=question.id)
    with pytest.raises(InvalidTaskOperation, match="Only a correction"):
        env.source(SourceKind.CORRECTION)
    assert len(get_sources(GetSourcesQuery(env.project, env.session), database_path=env.path)) == 1


def test_failure_and_invalidation_never_satisfy_dependencies(env):
    source = env.source()
    first = env.create(source)
    dependent = env.create(source, dependencies=(first.id,))
    failed = env.report(env.start(first), AttemptOutcome.FAILED, remaining_work="repair")
    assert dependent not in env.projection().ready
    correction = env.source(SourceKind.CORRECTION, "cancel first", source.id)
    cancelled = invalidate_task(
        InvalidateTaskCommand(
            env.project, env.session, first.id, correction.id, "cancelled", failed.revision
        ),
        database_path=env.path,
    )
    assert dependent not in env.projection().ready
    with pytest.raises(InvalidTaskOperation, match="pending or failed"):
        env.start(cancelled)
    with pytest.raises(InvalidTaskOperation, match="unfinished dependency"):
        env.start(dependent)


def test_only_current_source_lineage_can_correct_a_task(env):
    source = env.source()
    task = env.create(source)
    unrelated = env.source(text="unrelated instruction")
    unrelated_correction = env.source(SourceKind.CORRECTION, "other change", unrelated.id)
    with pytest.raises(InvalidTaskOperation, match="current task source"):
        env.correct(task, unrelated_correction, title="unrelated overwrite")
    first_correction = env.source(SourceKind.CORRECTION, "correct title", source.id)
    changed = env.correct(task, first_correction, title="correct title")
    second_correction = env.source(
        SourceKind.CORRECTION, "correct expected output", first_correction.id
    )
    newest = env.correct(changed, second_correction, expected_outcome="correct expected output")
    assert newest.title == changed.title
    assert newest.source_id == source.id
    assert len(env.history(task)) == 3


def test_submission_is_preserved_but_never_completes_task(env):
    task = env.create(env.source())
    attempt = env.start(task)
    active = env.current(task)
    assert (
        env.report(
            attempt, AttemptOutcome.SUBMITTED, summary="job submitted", evidence="job://submission"
        )
        == active
    )
    observed = env.attempts(task)[0]
    assert observed.outcome is None
    assert observed.submission_summary == "job submitted"
    assert observed.submission_evidence == "job://submission"
    assert not env.projection().all_terminal
    with pytest.raises(InvalidTaskOperation, match="Submission is already"):
        env.report(attempt, AttemptOutcome.SUBMITTED)
    assert env.report(attempt).status is TaskStatus.SUCCEEDED
    finished = env.attempts(task)[0]
    assert finished.submission_evidence == "job://submission"
    assert finished.evidence == "artifact://checked-output"


def test_partial_output_preserves_remaining_work_and_is_retryable_failure(env):
    task = env.create(env.source())
    attempt = env.start(task)
    with pytest.raises(InvalidTaskOperation, match="remaining work"):
        env.report(attempt, AttemptOutcome.PARTIAL)
    failed = env.report(
        attempt, AttemptOutcome.PARTIAL, remaining_work="second requested output is missing"
    )
    assert failed.status is TaskStatus.FAILED
    assert not env.projection().all_succeeded
    assert env.attempts(task)[0].outcome is AttemptOutcome.PARTIAL
    env.report(env.start(failed))
    assert env.projection().all_succeeded


def test_existing_source_reuse_keeps_original_attribution_and_allows_scoped_correction(
    env, tmp_path
):
    source = env.source()
    original = env.create(source)
    context = register_session(str(tmp_path), "codex", "next-chat", database_path=env.path)
    other = Environment(env.path, context.project.id, context.session.id)
    reused = other.create(source)
    correction = other.source(
        SourceKind.CORRECTION, "revise this chat's task", source.id, author="delegated-agent"
    )
    changed = other.correct(reused, correction, title="revised here")
    assert changed.correction_source_id == correction.id
    assert env.current(original) == original
    sources = get_sources(GetSourcesQuery(env.project, env.session), database_path=env.path)
    assert sources == (source,)
    assert sources[0].session_id == env.session
    assert sources[0].author == "human"


def test_real_failed_command_and_successful_artifact_are_distinct_attempt_results(env, tmp_path):
    task = env.create(env.source())
    first = env.start(task)
    failure = subprocess.run(
        [sys.executable, "-c", "raise SystemExit(7)"], capture_output=True, text=True
    )
    assert failure.returncode == 7
    failed_log = tmp_path / "failed-command.log"
    failed_log.write_text(f"returncode={failure.returncode}\n{failure.stderr}")
    failed = env.report(
        first,
        AttemptOutcome.FAILED,
        summary="Command exited with status 7",
        evidence=failed_log.as_uri(),
        remaining_work="Produce the requested artifact",
    )
    second = env.start(failed)
    output = tmp_path / "verified-artifact.txt"
    success = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('verified output')",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert success.returncode == 0 and output.read_text() == "verified output"
    env.report(second, summary="Command produced the verified artifact", evidence=output.as_uri())
    attempts = {attempt.id: attempt for attempt in env.attempts(task)}
    assert attempts[first.id].evidence == failed_log.as_uri()
    assert attempts[second.id].evidence == output.as_uri()
    assert env.projection().all_succeeded
