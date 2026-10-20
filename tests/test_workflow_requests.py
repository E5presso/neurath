"""실제 저장·명령 실행·유실 복구를 연결하여 phase runner의 결과를 검증한다."""

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest
from alembic import command
from spakky.data.persistency.transaction import AbstractTransaction
from spakky.plugins.sqlalchemy.persistency.session_manager import SessionManager
from sqlalchemy import text

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.services.phase_executor import (
    IPhaseExecutorService,
    IWorkflowNotifierService,
)
from neurath.application.usecases.execute_phase import ExecutePhaseCommand, ExecutePhaseUseCase
from neurath.application.usecases.get_workflow import GetWorkflowQuery, GetWorkflowUseCase
from neurath.application.usecases.prepare_phase import PreparePhaseCommand, PreparePhaseUseCase
from neurath.application.usecases.report_phase import ReportPhaseCommand, ReportPhaseUseCase
from neurath.application.usecases.report_result import ReportResultCommand, ReportResultUseCase
from neurath.application.usecases.revise_workflow import (
    ReviseWorkflowCommand,
    ReviseWorkflowUseCase,
)
from neurath.application.usecases.skip_phase import SkipPhaseCommand, SkipPhaseUseCase
from neurath.application.usecases.start_workflow import StartWorkflowCommand, StartWorkflowUseCase
from neurath.domain.errors import InvalidWorkflowState, RevisionConflict
from neurath.domain.task_records import Outcome, TaskResult, TaskStatus
from neurath.domain.workflow_records import (
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    WorkflowDefinition,
)
from neurath.infrastructure.database import create_database_engine, initialize_database
from neurath.infrastructure.phase_executor import (
    StderrWorkflowNotifierService,
    SubprocessPhaseExecutorService,
)
from neurath.infrastructure.providers import DatabaseSettings, request_container
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_task_migrations import migration_config
from tests.test_task_requests import create, snapshot


@pytest.fixture
def work(database, tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    actor = register_session(str(folder), "codex", "workflow", database_path=database)
    task = create(database, actor)
    step = PhaseDefinition(
        key="build",
        purpose="산출물 만들기",
        arguments=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path('artifact').write_text('ok')",
        ),
        directory=str(folder),
        target_revision="source-1",
    )
    definition = WorkflowDefinition(
        skill="implement-spec", version="1", phases=(step,), inputs=(("request", "산출물"),)
    )
    request = StartWorkflowCommand(
        actor.project.uid, actor.session.uid, task.uid, task.revision, definition
    )
    flow = run(StartWorkflowUseCase, request, database_path=database).run
    return actor, task, flow


def read(database, flow):
    return run(
        GetWorkflowUseCase,
        GetWorkflowQuery(flow.project_id, flow.session_id, flow.uid),
        database_path=database,
    ).run


def execute(database, flow, executor=None, notifier=None):
    with request_container(DatabaseSettings(database, write=True)) as scope:
        usecase = scope.get(ExecutePhaseUseCase)
        if executor is not None:
            usecase.executor = executor
        if notifier is not None:
            usecase.notifier = notifier
        return usecase.run(
            ExecutePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision)
        )


def result(phase, **changes):
    values = dict(
        status=PhaseStatus.SUCCEEDED,
        target_revision=phase.target_revision,
        summary="검사 통과",
        evidence=("host:actual",),
        checks=tuple(phase.checks),
        exit_code=0,
    )
    values.update(changes)
    return PhaseResult(**values)


def test_real_execution_finishes_workflow_then_allows_task_success(database, work):
    actor, task, flow = work
    with storage_scope(database, write=False) as scope:
        active = scope.get(ITaskRepository).get(task.uid)
    report = ReportResultCommand(
        flow.project_id,
        flow.session_id,
        task.uid,
        active.revision,
        active.current_attempt_number,
        TaskResult(outcome=Outcome.SUCCEEDED, summary="산출물 확인", observations=("artifact",)),
    )
    with pytest.raises(InvalidWorkflowState):
        run(ReportResultUseCase, report, database_path=database)
    executed = execute(database, flow)
    assert executed.run.current is None
    assert Path(flow.definition.phases[0].directory, "artifact").read_text() == "ok"
    assert executed.request_id == f"{flow.uid}:1"
    assert read(database, flow).attempts[0].result.exit_code == 0
    assert execute(database, executed.run).request_id is None
    saved = run(ReportResultUseCase, report, database_path=database).task
    assert saved.status is TaskStatus.SUCCEEDED
    assert (
        run(ReportResultUseCase, report, database_path=database).task.status is TaskStatus.SUCCEEDED
    )


def test_start_is_idempotent_but_definition_changes_use_revision(database, work):
    actor, task, flow = work
    request = StartWorkflowCommand(
        flow.project_id, flow.session_id, task.uid, task.revision, flow.definition
    )
    assert run(StartWorkflowUseCase, request, database_path=database).run.uid == flow.uid
    with pytest.raises(InvalidWorkflowState):
        run(
            StartWorkflowUseCase,
            replace(request, definition=replace(flow.definition, version="2")),
            database_path=database,
        )


def test_explicit_prepare_report_skip_and_revision_roundtrip(database, work):
    _, _, flow = work
    optional = replace(flow.definition.phases[0], key="ui", skip_condition="no-ui")
    definition = replace(flow.definition, version="2", phases=(optional, *flow.definition.phases))
    flow = run(
        ReviseWorkflowUseCase,
        ReviseWorkflowCommand(
            flow.project_id,
            flow.session_id,
            flow.uid,
            flow.revision,
            definition,
            "UI 선택 분기 추가",
        ),
        database_path=database,
    ).run
    flow = run(
        SkipPhaseUseCase,
        SkipPhaseCommand(
            flow.project_id, flow.session_id, flow.uid, flow.revision, "no-ui", "UI 변경 없음"
        ),
        database_path=database,
    ).run
    prepared = run(
        PreparePhaseUseCase,
        PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
        database_path=database,
    ).run
    with pytest.raises(RevisionConflict):
        run(
            PreparePhaseUseCase,
            PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
            database_path=database,
        )
    flow = run(
        ReportPhaseUseCase,
        ReportPhaseCommand(
            flow.project_id,
            flow.session_id,
            flow.uid,
            prepared.attempts[-1].number,
            result(prepared.current),
        ),
        database_path=database,
    ).run
    assert flow.current is None
    restored = read(database, flow)
    assert len(restored.revisions) == 2
    assert restored.attempts[0].skip_reason == "UI 변경 없음"
    assert restored.attempts[1].result.evidence == ("host:actual",)
    assert restored.definition.inputs == (("request", "산출물"),)


class RecoverableExecutor(IPhaseExecutorService):
    def __init__(self, phase, *, found=None, dedup=False, fail=False, database=None):
        self.phase = phase
        self.found = found
        self.dedup = dedup
        self.fail = fail
        self.calls = []
        self.database = database

    @property
    def supports_deduplication(self):
        return self.dedup

    def execute(self, request_id, phase):
        self.calls.append(("execute", request_id))
        if self.database is not None:
            with closing(sqlite3.connect(self.database, timeout=0)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS host_side_effect(id TEXT)")
                connection.execute("INSERT INTO host_side_effect VALUES (?)", (request_id,))
        if self.fail:
            raise OSError("response lost after execution")
        return result(phase)

    def lookup(self, request_id, phase):
        self.calls.append(("lookup", request_id))
        return self.found


def test_execution_occurs_outside_database_write_lock(database, work):
    _, _, flow = work
    host = RecoverableExecutor(flow.current, database=database)
    final = execute(database, flow, host)
    assert final.run.current is None
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id FROM host_side_effect").fetchall() == [
            (f"{flow.uid}:1",)
        ]


def test_uncertain_mutation_is_not_repeated_and_notifies_once(database, work, capsys):
    _, _, flow = work
    host = RecoverableExecutor(flow.current, fail=True, database=database)
    first = execute(database, flow, host)
    assert first.run.attempts[0].status is PhaseStatus.WAITING
    with storage_scope(database, write=False) as scope:
        assert scope.get(ITaskRepository).get(flow.task_id).status is TaskStatus.WAITING
    assert first.request_id in capsys.readouterr().err
    again = execute(database, first.run, host)
    assert host.calls == [("execute", first.request_id), ("lookup", first.request_id)]
    assert capsys.readouterr().err == ""
    assert len(again.run.attempts) == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM host_side_effect").fetchone() == (1,)
    host.found = result(flow.current)
    assert execute(database, again.run, host).run.current is None
    assert host.calls[-1] == ("lookup", first.request_id)
    with storage_scope(database, write=False) as scope:
        assert scope.get(ITaskRepository).get(flow.task_id).status is TaskStatus.ACTIVE


@pytest.mark.parametrize("dedup", [False, True])
def test_restarted_reserved_attempt_uses_lookup_then_only_verified_dedup(
    database, work, dedup, capsys
):
    _, _, flow = work
    prepared = run(
        PreparePhaseUseCase,
        PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
        database_path=database,
    ).run
    host = RecoverableExecutor(flow.current, dedup=dedup)
    returned = execute(database, prepared, host)
    assert host.calls[0] == ("lookup", f"{flow.uid}:1")
    if dedup:
        assert host.calls[1] == ("execute", f"{flow.uid}:1")
        assert returned.run.current is None
    else:
        assert len(host.calls) == 1
        assert returned.run.attempts[0].status is PhaseStatus.WAITING
        assert "unknown" in capsys.readouterr().err


def test_task_cancellation_blocks_execution_and_prepare(database, work):
    _, task, flow = work
    with storage_scope(database) as scope:
        entity = scope.get(ITaskRepository).get(task.uid)
        entity.status = TaskStatus.INVALIDATED
        scope.get(ITaskRepository).save(entity)
    with pytest.raises(InvalidWorkflowState):
        execute(database, flow)
    with pytest.raises(InvalidWorkflowState):
        run(
            PreparePhaseUseCase,
            PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
            database_path=database,
        )
    assert not Path(flow.current.directory, "artifact").exists()


def test_subprocess_actual_failure_timeout_large_output_and_remaining_checks(tmp_path):
    host = SubprocessPhaseExecutorService()
    phase = PhaseDefinition(
        key="check",
        purpose="명령 검증",
        arguments=(sys.executable, "-c", "raise SystemExit(7)"),
        directory=str(tmp_path),
        target_revision="source",
        timeout=0.2,
        output_limit=8,
    )
    failed = host.execute("failure", phase)
    assert failed.exit_code == 7 and failed.status is PhaseStatus.FAILED
    timeout = host.execute(
        "timeout", replace(phase, arguments=(sys.executable, "-c", "import time; time.sleep(5)"))
    )
    assert (
        timeout.status is PhaseStatus.FAILED
        and "timeout" in timeout.summary
        and timeout.exit_code != 0
    )
    output = host.execute(
        "large",
        replace(
            phase,
            timeout=5,
            arguments=(sys.executable, "-c", "import sys; sys.stdout.write('a'*200000)"),
        ),
    )
    assert (
        output.status is PhaseStatus.SUCCEEDED
        and output.output == "a" * 8
        and "truncated" in output.summary
    )
    pending = host.execute(
        "review",
        replace(phase, arguments=(sys.executable, "-c", "pass"), checks=("exit:0", "review")),
    )
    assert pending.status is PhaseStatus.WAITING and pending.checks == ("exit:0",)
    missing = host.execute("missing", replace(phase, arguments=("missing-neurath-test-program",)))
    assert missing.status is PhaseStatus.FAILED and missing.exit_code is None
    assert host.lookup("lost", phase) is None and not host.supports_deduplication


def test_subprocess_interrupt_terminates_actual_process(tmp_path):
    host = SubprocessPhaseExecutorService()
    ready = tmp_path / "ready"
    phase = PhaseDefinition(
        key="long",
        purpose="중단 대상",
        arguments=(
            sys.executable,
            "-c",
            "from pathlib import Path; import time; Path('ready').touch(); time.sleep(10)",
        ),
        directory=str(tmp_path),
        target_revision="source",
        timeout=10,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(host.execute, "interrupt", phase)
        deadline = monotonic() + 5
        while not ready.exists() and monotonic() < deadline:
            sleep(0.01)
        assert ready.exists()
        host.interrupt()
        stopped = running.result(timeout=3)
    assert stopped.status is PhaseStatus.FAILED and stopped.summary == "interrupted"
    assert not host.interrupted.is_set()


def test_populated_workflow_downgrade_preserves_all_records(database, work):
    before = snapshot(database)
    engine = create_database_engine(database, write=True)
    try:
        with pytest.raises(RuntimeError, match="Workflow history"):
            with engine.begin() as connection:
                command.downgrade(migration_config(connection), "core_0003")
    finally:
        engine.dispose()
    assert snapshot(database) == before


def test_primitive_repository_and_framework_transaction_are_used(database, work):
    _, _, flow = work
    with storage_scope(database, write=False) as scope:
        repository = scope.get(IWorkflowRepository)
        assert repository.find_by_task("missing") is None
        assert repository.get(flow.uid).uid == flow.uid
        assert scope.get(ExecutePhaseUseCase).transaction is scope.get(AbstractTransaction)
        assert scope.get(ExecutePhaseUseCase).executor is scope.get(IPhaseExecutorService)
        assert scope.get(IWorkflowNotifierService).__class__ is StderrWorkflowNotifierService
        assert (
            scope.get(SessionManager).session.scalar(text("SELECT COUNT(*) FROM core_workflows"))
            == 1
        )


def test_same_waiting_attempt_is_reconciled_after_unrelated_phase_revision(database, work, capsys):
    _, _, flow = work
    original = flow.current
    extended = replace(flow.definition, phases=(original, replace(original, key="docs")))
    flow = run(
        ReviseWorkflowUseCase,
        ReviseWorkflowCommand(
            flow.project_id, flow.session_id, flow.uid, flow.revision, extended, "문서 단계 추가"
        ),
        database_path=database,
    ).run
    host = RecoverableExecutor(original, fail=True, database=database)
    waiting = execute(database, flow, host).run
    updated = replace(
        extended,
        version="2",
        phases=(original, replace(original, key="docs", target_revision="docs-2")),
    )
    revised = run(
        ReviseWorkflowUseCase,
        ReviseWorkflowCommand(
            flow.project_id,
            flow.session_id,
            flow.uid,
            waiting.revision,
            updated,
            "문서 대상만 변경",
        ),
        database_path=database,
    ).run
    host.found = result(original)
    recovered = execute(database, revised, host).run
    assert recovered.current.key == "docs" and recovered.current.target_revision == "docs-2"
    assert recovered.attempts[0].definition_number == 2 and len(recovered.attempts) == 1
    assert [op for op, _ in host.calls] == ["execute", "lookup"]


def test_changed_target_during_external_execution_keeps_old_result_without_advancing(
    database, work
):
    _, _, flow = work

    class ChangingTarget(RecoverableExecutor):
        def execute(self, request_id, phase):
            current = read(database, flow)
            updated = replace(
                current.definition,
                version="2",
                phases=(replace(phase, target_revision="source-2"),),
            )
            run(
                ReviseWorkflowUseCase,
                ReviseWorkflowCommand(
                    flow.project_id,
                    flow.session_id,
                    flow.uid,
                    current.revision,
                    updated,
                    "실행 중 소스 변경",
                ),
                database_path=database,
            )
            return result(phase)

    final = execute(database, flow, ChangingTarget(flow.current)).run
    assert final.current.target_revision == "source-2"
    assert final.attempts[0].result.target_revision == "source-1"
    assert read(database, flow).current.target_revision == "source-2"


def test_start_attaches_to_existing_active_task_without_a_second_attempt(database, tmp_path):
    from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase

    folder = tmp_path / "active"
    folder.mkdir()
    actor = register_session(str(folder), "codex", "active", database_path=database)
    task = create(database, actor)
    task = run(
        StartTaskUseCase,
        StartTaskCommand(task.project_id, task.owner_session_id, task.uid, task.revision),
        database_path=database,
    ).task
    step = PhaseDefinition(
        key="one",
        purpose="기존 시도 수행",
        arguments=("true",),
        directory=str(folder),
        target_revision="1",
    )
    flow = run(
        StartWorkflowUseCase,
        StartWorkflowCommand(
            task.project_id,
            task.owner_session_id,
            task.uid,
            task.revision,
            WorkflowDefinition(skill="debug", version="1", phases=(step,), inputs=()),
        ),
        database_path=database,
    ).run
    with storage_scope(database, write=False) as scope:
        assert len(scope.get(ITaskRepository).get(task.uid).attempts) == 1
    assert flow.task_id == task.uid


def test_core0003_upgrade_preserves_unfinished_tasks_and_is_repeatable(database, tmp_path):
    folder = tmp_path / "retained"
    folder.mkdir()
    actor = register_session(str(folder), "codex", "retained", database_path=database)
    task = create(database, actor)
    engine = create_database_engine(database, write=True)
    try:
        with engine.begin() as connection:
            command.downgrade(migration_config(connection), "core_0003")
    finally:
        engine.dispose()
    before = snapshot(database)
    initialize_database(database)
    after = snapshot(database)
    for table, rows in before.items():
        if table != "core_schema_revision":
            assert after[table] == rows
    assert after["core_workflows"] == []
    with storage_scope(database, write=False) as scope:
        assert scope.get(ITaskRepository).get(task.uid).status is TaskStatus.PENDING
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    initialize_database(database)
    assert snapshot(database) == after


def test_core0004_failure_rolls_back_schema_and_preserves_old_bytes(database, monkeypatch):
    import neurath.infrastructure.database as storage

    engine = create_database_engine(database, write=True)
    try:
        with engine.begin() as connection:
            command.downgrade(migration_config(connection), "core_0003")
    finally:
        engine.dispose()
    before = database.read_bytes()
    upgrade = storage.command.upgrade

    def fail_after_upgrade(config, target):
        upgrade(config, target)
        raise RuntimeError("failed after workflow schema")

    monkeypatch.setattr(storage.command, "upgrade", fail_after_upgrade)
    with pytest.raises(RuntimeError, match="failed after workflow"):
        initialize_database(database)
    assert database.read_bytes() == before


@pytest.mark.parametrize("broken", ["execute", "lookup", "supports_deduplication"])
def test_incomplete_execution_adapters_leave_work_unconfirmed(
    database, work, monkeypatch, broken, capsys
):
    _, _, flow = work
    host = SubprocessPhaseExecutorService()
    if broken != "execute":
        flow = run(
            PreparePhaseUseCase,
            PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
            database_path=database,
        ).run
    if broken == "supports_deduplication":

        def missing_capability(self):
            return IPhaseExecutorService.supports_deduplication.fget(self)

        monkeypatch.setattr(SubprocessPhaseExecutorService, broken, property(missing_capability))
    else:

        def incomplete(self, request_id, phase):
            return getattr(IPhaseExecutorService, broken)(self, request_id, phase)

        monkeypatch.setattr(SubprocessPhaseExecutorService, broken, incomplete)
    result = execute(database, flow, host)
    assert result.run.attempts[0].status is PhaseStatus.WAITING
    assert "NotImplementedError" in result.run.attempts[0].result.summary
    assert "unconfirmed" in capsys.readouterr().err
    assert not Path(flow.current.directory, "artifact").exists()


def test_incomplete_notification_fails_after_persisting_unfinished_state(
    database, work, monkeypatch
):
    _, _, flow = work

    def incomplete(self, request_id, reason):
        return IWorkflowNotifierService.waiting(self, request_id, reason)

    monkeypatch.setattr(StderrWorkflowNotifierService, "waiting", incomplete)
    with pytest.raises(NotImplementedError):
        execute(database, flow, RecoverableExecutor(flow.current, fail=True))
    assert read(database, flow).attempts[0].status is PhaseStatus.WAITING
    with storage_scope(database, write=False) as scope:
        assert scope.get(ITaskRepository).get(flow.task_id).status is TaskStatus.WAITING


def test_incomplete_workflow_lookup_rolls_back_start(database, work, monkeypatch):
    from neurath.infrastructure.repositories.workflow import SQLAlchemyWorkflowRepository

    actor, task, flow = work

    def incomplete(self, task_id):
        return IWorkflowRepository.find_by_task(self, task_id)

    monkeypatch.setattr(SQLAlchemyWorkflowRepository, "find_by_task", incomplete)
    before = snapshot(database)
    with pytest.raises(NotImplementedError):
        run(
            StartWorkflowUseCase,
            StartWorkflowCommand(
                flow.project_id, flow.session_id, task.uid, task.revision, flow.definition
            ),
            database_path=database,
        )
    assert snapshot(database) == before
    for abstract in [IPhaseExecutorService, IWorkflowNotifierService, IWorkflowRepository]:
        with pytest.raises(TypeError):
            abstract()


def test_short_multibyte_output_is_preserved_without_truncation(tmp_path):
    phase = PhaseDefinition(
        key="print",
        purpose="출력 보존",
        arguments=(sys.executable, "-c", "print('정상')"),
        directory=str(tmp_path),
        target_revision="source",
    )
    result = SubprocessPhaseExecutorService().execute("short", phase)
    assert result.output == "정상\n" and "truncated" not in result.summary


def test_waiting_workflow_does_not_block_independent_task(database, work, capsys):
    from neurath.application.usecases.get_tasks import GetTasksQuery, GetTasksUseCase

    actor, _, flow = work
    independent = create(database, actor, title="별도 작업")
    execute(database, flow, RecoverableExecutor(flow.current, fail=True))
    board = run(
        GetTasksUseCase, GetTasksQuery(flow.project_id, flow.session_id), database_path=database
    )
    assert board.ready_task_ids == (independent.uid,)
    assert not board.all_terminal and not board.all_succeeded


def test_report_does_not_resume_unrelated_external_wait(database, work):
    from neurath.domain.task_records import ExternalWait

    _, _, flow = work
    prepared = run(
        PreparePhaseUseCase,
        PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
        database_path=database,
    ).run
    with storage_scope(database) as scope:
        task = scope.get(ITaskRepository).get(flow.task_id)
        task.wait(
            ExternalWait(
                target="other",
                condition="대기",
                resume_scope="다음",
                observation="외부 담당자 확인",
            )
        )
        scope.get(ITaskRepository).save(task)
    with pytest.raises(InvalidWorkflowState):
        execute(database, prepared)
    run(
        ReportPhaseUseCase,
        ReportPhaseCommand(
            flow.project_id,
            flow.session_id,
            flow.uid,
            prepared.attempts[-1].number,
            result(prepared.current),
        ),
        database_path=database,
    )
    with storage_scope(database, write=False) as scope:
        assert scope.get(ITaskRepository).get(flow.task_id).status is TaskStatus.WAITING


def test_simultaneous_execution_reserves_once_and_reconciles_same_attempt(database, work):
    from threading import Event

    _, _, flow = work
    entered = Event()
    release = Event()

    class SlowHost(RecoverableExecutor):
        def execute(self, request_id, phase):
            observed = super().execute(request_id, phase)
            entered.set()
            assert release.wait(5)
            return observed

    host = SlowHost(flow.current, database=database)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(execute, database, flow, host)
        try:
            assert entered.wait(5)
            second = execute(database, read(database, flow), host)
            assert second.run.attempts[0].status is PhaseStatus.WAITING
        finally:
            release.set()
        finished = first.result(timeout=5)
    assert finished.run.current is None
    assert [op for op, _ in host.calls].count("execute") == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM host_side_effect").fetchone() == (1,)


def test_workflow_is_readable_after_process_restart(database, work):
    import subprocess

    _, _, flow = work
    prepared = run(
        PreparePhaseUseCase,
        PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
        database_path=database,
    ).run
    script = """
import sys
from pathlib import Path
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction
from neurath.infrastructure.providers import DatabaseSettings, request_container
from neurath.application.usecases.get_workflow import GetWorkflowUseCase, GetWorkflowQuery
with request_container(DatabaseSettings(Path(sys.argv[1]),write=False)) as scope:
    with scope.get(Transaction):
        flow=scope.get(GetWorkflowUseCase).run(GetWorkflowQuery(*sys.argv[2:])).run
        print(flow.definition.version, flow.attempts[0].status.value, flow.current.target_revision)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(database), flow.project_id, flow.session_id, flow.uid],
        capture_output=True,
        text=True,
        check=True,
    )
    assert child.stdout.strip() == "1 running source-1"
    assert prepared.attempts[0].result is None


def test_workflow_default_crud_keeps_owned_definition_and_attempt_lifecycle(database, work):
    from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository

    from neurath.infrastructure.repositories.workflow import SQLAlchemyWorkflowRepository

    _, _, flow = work
    final = execute(database, flow).run
    for name in ["get", "save", "save_all", "delete", "delete_all"]:
        assert getattr(SQLAlchemyWorkflowRepository, name) is getattr(
            AbstractGenericRepository, name
        )
    with storage_scope(database) as scope:
        repository = scope.get(IWorkflowRepository)
        loaded = repository.get(flow.uid)
        assert loaded.revision == final.revision
        assert repository.save(loaded).revision == loaded.revision
        repository.delete(loaded)
    with storage_scope(database, write=False) as scope:
        assert scope.get(IWorkflowRepository).find_by_task(flow.task_id) is None
        session = scope.get(SessionManager).session
        for table in [
            "core_workflows",
            "core_workflow_revisions",
            "core_workflow_phases",
            "core_workflow_attempts",
        ]:
            assert session.scalar(text("SELECT COUNT(*) FROM " + table)) == 0


def test_phase_and_task_wait_are_rolled_back_together_on_save_failure(database, work, monkeypatch):
    from neurath.infrastructure.repositories.workflow import SQLAlchemyWorkflowRepository

    _, _, flow = work
    prepared = run(
        PreparePhaseUseCase,
        PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
        database_path=database,
    ).run
    before = snapshot(database)

    def fail_save(self, entity):
        raise RuntimeError("workflow storage failed")

    monkeypatch.setattr(SQLAlchemyWorkflowRepository, "save", fail_save)
    with pytest.raises(RuntimeError, match="workflow storage failed"):
        run(
            ReportPhaseUseCase,
            ReportPhaseCommand(
                flow.project_id,
                flow.session_id,
                flow.uid,
                prepared.attempts[-1].number,
                result(prepared.current, status=PhaseStatus.WAITING),
            ),
            database_path=database,
        )
    assert snapshot(database) == before


@pytest.mark.parametrize("mismatch", ["task", "session"])
def test_workflow_storage_rejects_cross_project_links(database, work, tmp_path, mismatch):
    from sqlalchemy.exc import IntegrityError

    from neurath.domain.aggregates.workflow import WorkflowRun

    _, _, flow = work
    folder = tmp_path / "outside"
    folder.mkdir()
    outside = register_session(str(folder), "codex", "other-project", database_path=database)
    other_task = create(database, outside)
    invalid = WorkflowRun.create(
        flow.project_id,
        outside.session.uid if mismatch == "session" else flow.session_id,
        other_task.uid,
        1,
        flow.definition,
    )
    before = snapshot(database)
    with pytest.raises(IntegrityError):
        with storage_scope(database) as scope:
            scope.get(IWorkflowRepository).save(invalid)
    assert snapshot(database) == before


def test_recovered_result_returns_before_capability_check_or_resubmission(database, work):
    _, _, flow = work
    prepared = run(
        PreparePhaseUseCase,
        PreparePhaseCommand(flow.project_id, flow.session_id, flow.uid, flow.revision),
        database_path=database,
    ).run

    class FoundOnly(RecoverableExecutor):
        @property
        def supports_deduplication(self):
            raise AssertionError("A found result needs no capability check")

        def execute(self, request_id, phase):
            raise AssertionError("A found result must not be executed again")

    host = FoundOnly(flow.current, found=result(flow.current))
    completed = execute(database, prepared, host)
    assert completed.run.current is None
    assert host.calls == [("lookup", f"{flow.uid}:1")]


def test_fresh_attempt_returns_without_lookup_or_recovery_capability(database, work):
    _, _, flow = work

    class FreshOnly(RecoverableExecutor):
        @property
        def supports_deduplication(self):
            raise AssertionError("A first execution needs no recovery capability")

        def lookup(self, request_id, phase):
            raise AssertionError("A newly reserved attempt has no previous execution to look up")

    host = FreshOnly(flow.current, database=database)
    completed = execute(database, flow, host)
    assert completed.run.current is None
    assert host.calls == [("execute", f"{flow.uid}:1")]
