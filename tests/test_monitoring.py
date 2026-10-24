"""실제 SQLite·스캔·CLI로 감시·사건·알림과 취소·인계 경계를 확인한다."""

import asyncio
import json
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command as alembic_command
from sqlalchemy.ext.asyncio import AsyncSession

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.monitor_notifier import (
    IMonitorNotifierService,
    MonitorDelivery,
)
from neurath.application.ports.services.monitor_observer import (
    IMonitorObserverService,
    MonitorObservation,
)
from neurath.application.usecases.acknowledge_monitor_event import (
    AcknowledgeMonitorEventCommand,
    AcknowledgeMonitorEventUseCase,
)
from neurath.application.usecases.cancel_execution import (
    CancelExecutionCommand,
    CancelExecutionUseCase,
)
from neurath.application.usecases.cancel_monitor import CancelMonitorCommand, CancelMonitorUseCase
from neurath.application.usecases.get_monitor import GetMonitorQuery, GetMonitorUseCase
from neurath.application.usecases.prepare_monitor_notice import (
    PrepareMonitorNoticeCommand,
    PrepareMonitorNoticeUseCase,
)
from neurath.application.usecases.prepare_monitor_poll import (
    PrepareMonitorPollCommand,
    PrepareMonitorPollUseCase,
)
from neurath.application.usecases.record_monitor_notice import (
    RecordMonitorNoticeCommand,
    RecordMonitorNoticeUseCase,
)
from neurath.application.usecases.record_monitor_observation import (
    RecordMonitorObservationCommand,
    RecordMonitorObservationUseCase,
)
from neurath.application.usecases.recover_monitor import (
    RecoverMonitorCommand,
    RecoverMonitorUseCase,
)
from neurath.application.usecases.register_monitor import (
    RegisterMonitorCommand,
    RegisterMonitorUseCase,
)
from neurath.application.usecases.resolve_monitor_event import (
    ResolveMonitorEventCommand,
    ResolveMonitorEventUseCase,
)
from neurath.application.usecases.resume_session import ResumeSessionCommand, ResumeSessionUseCase
from neurath.application.usecases.tick_monitor import TickMonitorCommand, TickMonitorUseCase
from neurath.application.usecases.wait_task import WaitTaskCommand, WaitTaskUseCase
from neurath.domain.enums.liveness import Liveness
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.values.external_wait import ExternalWait
from neurath.domain.values.task_monitor import MonitorKind, NoticeStatus, TaskMonitor
from neurath.infrastructure.database import create_database_engine, sqlite_url
from neurath.infrastructure.services.monitor_notifier import StderrMonitorNotifierService
from neurath.infrastructure.services.monitor_observer import SubprocessMonitorObserverService
from tests.conftest import storage_scope
from tests.support.application import scanned_application
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_cli import invoke
from tests.test_memory_requests import native
from tests.test_runtime import execution
from tests.test_task_migrations import migration_config
from tests.test_task_requests import create, snapshot, start


@pytest.fixture
async def monitored(database, repository, tmp_path):
    actor = await register_session(
        str(repository), "codex", "monitor-owner", database_path=database
    )
    await native(database, actor, "UserPromptSubmit")
    owner = await execution(database, actor)
    task = await start(database, await create(database, actor))
    output = tmp_path / "output.jsonl"
    output.write_text('{"state":"waiting"}\n')
    task = (
        await run(
            WaitTaskUseCase,
            WaitTaskCommand(
                project_id=task.project_id,
                session_id=task.owner_session_id,
                task_id=task.uid,
                expected_revision=task.revision,
                condition=ExternalWait(
                    target=str(output),
                    condition="state becomes done",
                    resume_scope="continue original task",
                    observation="external output pending",
                ),
            ),
            database_path=database,
        )
    ).task
    monitor = await run(
        RegisterMonitorUseCase,
        RegisterMonitorCommand(
            project_id=task.project_id,
            session_id=task.owner_session_id,
            task_id=task.uid,
            expected_revision=task.revision,
            execution_id=owner.uid,
            kind=MonitorKind.OUTPUT,
            target=str(output),
            budget=20,
        ),
        database_path=database,
    )
    return SimpleNamespace(actor=actor, task=task, owner=owner, output=output, monitor=monitor)


def command(m, cls=TickMonitorCommand, **fields):
    return cls(
        project_id=m.task.project_id,
        session_id=m.task.owner_session_id,
        task_id=m.task.uid,
        monitor_number=m.monitor.number,
        execution_id=m.monitor.owner_execution_id,
        generation=m.monitor.generation,
        **fields,
    )


async def call(database, m, usecase, cls=None, **fields):
    inputs = {
        TickMonitorUseCase: TickMonitorCommand,
        PrepareMonitorPollUseCase: PrepareMonitorPollCommand,
        PrepareMonitorNoticeUseCase: PrepareMonitorNoticeCommand,
        CancelMonitorUseCase: CancelMonitorCommand,
    }
    return await run(usecase, command(m, cls or inputs[usecase], **fields), database_path=database)


async def stored(database, m):
    return await run(
        GetMonitorUseCase,
        GetMonitorQuery(
            project_id=m.task.project_id,
            session_id=m.task.owner_session_id,
            task_id=m.task.uid,
            monitor_number=m.monitor.number,
        ),
        database_path=database,
    )


async def task_stored(database, m):
    async with storage_scope(database, write=False) as scope:
        return await scope.get(ITaskRepository).get(m.task.uid)


async def changed(database, m):
    await call(database, m, TickMonitorUseCase)
    m.output.write_text('{"state":"done"}\n')
    return await call(database, m, TickMonitorUseCase)


async def test_first_same_fragment_and_pr_wait_never_call_model_or_create_events(
    database, monitored, monkeypatch
):
    m = monitored

    def forbidden(*args, **kwargs):
        raise AssertionError("monitor must not invoke a model")

    from neurath.infrastructure.services.provider import SubprocessProviderService

    monkeypatch.setattr(SubprocessProviderService, "start", forbidden)
    first = await call(database, m, TickMonitorUseCase)
    assert first.initial_state == first.current_state == "waiting"
    assert first.events == () and first.poll_id is None
    for _ in range(3):
        same = await call(database, m, TickMonitorUseCase)
        assert same.events == ()
    with m.output.open("a") as stream:
        stream.write('{"state":"do')
    assert (await call(database, m, TickMonitorUseCase)).events == ()
    with m.output.open("a") as stream:
        stream.write('ne"}\n')
    result = await call(database, m, TickMonitorUseCase)
    assert len(result.events) == 1
    assert result.events[0].state == "done"
    assert result.events[0].notice_status is NoticeStatus.SUBMITTED
    assert not result.events[0].acknowledged and not result.events[0].resolved
    assert "state becomes done" in result.events[0].body
    assert "continue original task" in result.events[0].body
    assert (await task_stored(database, m)).status is TaskStatus.WAITING
    assert (await call(database, m, TickMonitorUseCase)).events[0].attempts == 1


async def test_notification_failure_persists_bounded_retries_reconnect_and_no_executor(
    database, monitored, monkeypatch
):
    m = monitored
    calls = []

    def fail(self, reference, body):
        calls.append(reference)
        raise OSError("notification access denied")

    monkeypatch.setattr(StderrMonitorNotifierService, "submit", fail)
    result = await changed(database, m)
    assert result.events[0].notice_status is NoticeStatus.FAILED
    assert "Check notification access" in result.events[0].error
    before = asdict(result)
    assert asdict(await stored(database, m)) == before
    await native(database, m.actor, "SessionStart", source="resume")
    for _ in range(4):
        result = await call(database, m, TickMonitorUseCase)
    assert len(calls) == result.events[0].attempts == 3
    assert result.events[0].notice_status is NoticeStatus.FAILED
    assert (await task_stored(database, m)).status is TaskStatus.WAITING
    assert result.current_state == "done" and len(result.events) == 1


async def test_exact_event_ack_delivery_confirmation_and_resolution_are_distinct(
    database, monitored
):
    m = monitored
    event = (await changed(database, m)).events[0]
    with pytest.raises(ContextNotFound):
        await call(
            database,
            m,
            AcknowledgeMonitorEventUseCase,
            AcknowledgeMonitorEventCommand,
            event_number=9,
        )
    result = await call(
        database, m, AcknowledgeMonitorEventUseCase, AcknowledgeMonitorEventCommand, event_number=1
    )
    assert result.events[0].acknowledged and not result.events[0].resolved
    assert (await task_stored(database, m)).waits[-1].resolution is None
    result = await call(
        database,
        m,
        RecordMonitorNoticeUseCase,
        RecordMonitorNoticeCommand,
        event_number=1,
        attempt=event.attempts,
        status=NoticeStatus.DELIVERED,
    )
    assert result.events[0].notice_status is NoticeStatus.DELIVERED
    with pytest.raises(ValueError):
        await call(
            database,
            m,
            ResolveMonitorEventUseCase,
            ResolveMonitorEventCommand,
            event_number=1,
            resolution=" ",
        )
    result = await call(
        database,
        m,
        ResolveMonitorEventUseCase,
        ResolveMonitorEventCommand,
        event_number=1,
        resolution="output:done verified original condition",
    )
    task = await task_stored(database, m)
    assert task.status is TaskStatus.ACTIVE and task.current_attempt_number == 1
    assert task.waits[-1].condition == "state becomes done"
    assert result.events[0].resolved and not result.active
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            m,
            ResolveMonitorEventUseCase,
            ResolveMonitorEventCommand,
            event_number=1,
            resolution="cannot resolve twice",
        )


async def test_cancel_recovery_and_late_observation_do_not_restart_or_notify(database, monitored):
    m = monitored
    prepared = await call(database, m, PrepareMonitorPollUseCase)
    assert prepared.poll_id.version == 7
    assert await call(database, m, PrepareMonitorPollUseCase) is None
    cancelled = await call(database, m, CancelMonitorUseCase)
    assert not cancelled.active and cancelled.poll_id == prepared.poll_id
    for liveness in (Liveness.RUNNING, Liveness.UNKNOWN):
        with pytest.raises(InvalidTaskState):
            await call(
                database,
                m,
                RecoverMonitorUseCase,
                RecoverMonitorCommand,
                poll_id=prepared.poll_id,
                liveness=liveness,
            )
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            m,
            RecoverMonitorUseCase,
            RecoverMonitorCommand,
            poll_id=uuid7(),
            liveness=Liveness.STOPPED,
        )
    recovered = await call(
        database,
        m,
        RecoverMonitorUseCase,
        RecoverMonitorCommand,
        poll_id=prepared.poll_id,
        liveness=Liveness.STOPPED,
    )
    assert not recovered.active and recovered.poll_id is None
    assert recovered.remaining_polls == prepared.remaining_polls and recovered.generation == 2
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            m,
            RecordMonitorObservationUseCase,
            RecordMonitorObservationCommand,
            poll_id=prepared.poll_id,
            state="done",
            reference="late",
        )
    m.monitor = recovered
    assert (await call(database, m, TickMonitorUseCase)).events == ()


async def test_real_hook_interrupt_and_explicit_cancel_stop_new_observation(
    database, monitored, monkeypatch
):
    m = monitored
    await native(database, m.actor, "Interrupt")
    assert not (await stored(database, m)).active
    assert (await call(database, m, TickMonitorUseCase)).initial_state is None
    from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
    from neurath.domain.enums.hook_event import HookEvent

    await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="codex",
            host_session_id="monitor-owner",
            working_directory=m.actor.session.working_directory,
            event=HookEvent.USER_PROMPT_SUBMIT,
            turn_id="next-turn",
        ),
        database_path=database,
    )
    assert not (await call(database, m, TickMonitorUseCase)).active


async def test_explicit_execution_cancel_persists_monitor_stop_before_host_confirmation(
    database, monitored
):
    m = monitored
    await run(
        CancelExecutionUseCase,
        CancelExecutionCommand(execution_id=m.owner.uid, turn_id="turn"),
        database_path=database,
    )
    assert not (await stored(database, m)).active
    assert (await call(database, m, TickMonitorUseCase)).initial_state is None


async def test_external_observation_and_notice_are_after_commit_without_sqlite_write_lock(
    database, monitored, monkeypatch
):
    m = monitored
    original_observe = SubprocessMonitorObserverService.observe
    original_submit = StderrMonitorNotifierService.submit
    checked = []

    def unlocked():
        with closing(sqlite3.connect(database, timeout=0)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        checked.append(True)

    def observe(self, kind, target):
        unlocked()
        return original_observe(self, kind, target)

    def submit(self, reference, body):
        unlocked()
        return original_submit(self, reference, body)

    monkeypatch.setattr(SubprocessMonitorObserverService, "observe", observe)
    monkeypatch.setattr(StderrMonitorNotifierService, "submit", submit)
    await changed(database, m)
    assert len(checked) == 3


async def test_failed_preflight_commit_never_observes_or_notifies(database, monitored, monkeypatch):
    m = monitored
    before = snapshot(database)

    async def fail(*args):
        raise RuntimeError("commit failed")

    def forbidden(*args):
        raise AssertionError("external call before commit")

    monkeypatch.setattr(AsyncSession, "commit", fail)
    monkeypatch.setattr(SubprocessMonitorObserverService, "observe", forbidden)
    with pytest.raises(RuntimeError, match="commit failed"):
        await call(database, m, TickMonitorUseCase)
    assert snapshot(database) == before


async def test_lost_notice_result_stays_submitting_and_never_retries(
    database, monitored, monkeypatch
):
    m = monitored
    await call(database, m, TickMonitorUseCase)
    m.output.write_text('{"state":"done"}\n')
    original = RecordMonitorNoticeUseCase.run

    async def fail(*args):
        raise RuntimeError("lost result")

    monkeypatch.setattr(RecordMonitorNoticeUseCase, "run", fail)
    with pytest.raises(RuntimeError, match="lost result"):
        await call(database, m, TickMonitorUseCase)
    result = await stored(database, m)
    assert result.events[0].notice_status is NoticeStatus.SUBMITTING
    monkeypatch.setattr(RecordMonitorNoticeUseCase, "run", original)
    assert (await call(database, m, TickMonitorUseCase)).events[0].attempts == 1


async def test_handoff_preserves_pending_events_budget_and_refuses_live_resource(
    database, monitored
):
    m = monitored
    await changed(database, m)
    prepared = await call(database, m, PrepareMonitorPollUseCase)
    target = await register_session(
        m.actor.session.working_directory, "claude", "successor", database_path=database
    )
    await native(database, target, "UserPromptSubmit")
    await native(database, m.actor, "SessionEnd")
    handoff = ResumeSessionCommand(
        project_id=m.task.project_id,
        source_session_id=m.actor.session.uid,
        target_session_id=target.session.uid,
        expected_revision=1,
        turn_id="turn",
    )
    before = snapshot(database)
    with pytest.raises(InvalidTaskState, match="resources"):
        await run(ResumeSessionUseCase, handoff, database_path=database)
    assert snapshot(database) == before
    recovered = await call(
        database,
        m,
        RecoverMonitorUseCase,
        RecoverMonitorCommand,
        poll_id=prepared.poll_id,
        liveness=Liveness.STOPPED,
    )
    await run(ResumeSessionUseCase, handoff, database_path=database)
    m.task = replace_task_owner(m.task, target.session.uid)
    current = await stored(database, m)
    assert current.owner_execution_id == (await execution(database, target)).uid
    assert current.remaining_polls == recovered.remaining_polls
    assert current.generation == recovered.generation + 1
    assert len(current.events) == 1 and not current.events[0].acknowledged
    assert current.initial_state == "waiting" and current.current_state == "done"


def replace_task_owner(task, session_id):
    task.owner_session_id = session_id
    return task


async def test_monitor_cli_query_and_tick_real_scan_preserve_failures(database, monitored):
    m = monitored
    base = [
        "--project-id",
        str(m.task.project_id),
        "--session-id",
        str(m.task.owner_session_id),
        "--task-id",
        str(m.task.uid),
        "--monitor-number",
        "1",
    ]
    result = await invoke(
        database,
        ["monitor", "tick", *base, "--execution-id", str(m.owner.uid), "--generation", "1"],
    )
    assert result.exit_code == 0, result.exception
    assert json.loads(result.stdout)["initial_state"] == "waiting"
    m.output.unlink()
    await call(database, m, TickMonitorUseCase)
    result = await invoke(database, ["monitor", "status", *base])
    assert result.exit_code == 0
    assert "Check the target" in json.loads(result.stdout)["error"]
    assert (await stored(database, m)).events == ()


async def test_migration_empty_roundtrip_and_monitor_history_downgrade_refusal(database, monitored):
    before = snapshot(database)
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="Monitor history"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda c: alembic_command.downgrade(migration_config(c), "core_0010")
                )
    finally:
        await engine.dispose()
    assert snapshot(database) == before


def bare_monitor(**fields):
    return TaskMonitor(
        number=1,
        wait_number=1,
        definition_number=1,
        owner_execution_id=uuid7(),
        kind=MonitorKind.OUTPUT,
        target="/output.jsonl",
        remaining_polls=5,
        **fields,
    )


def test_domain_exact_resource_event_notice_and_handoff_guards():
    monitor = bare_monitor()
    with pytest.raises(ContextNotFound):
        monitor.event(1)
    with pytest.raises(InvalidTaskState):
        monitor.require_owner(uuid7(), 1)
    assert replace(monitor, remaining_polls=0).begin_poll().stop_reason
    prepared = monitor.begin_poll()
    assert prepared.begin_poll() is prepared
    assert prepared.observe(uuid7(), "done", "ref", "", "body") is prepared
    failed = prepared.observe(
        prepared.poll_id, None, "ref", "observer failed; inspect access", "body"
    )
    assert failed.error and failed.poll_id is None
    fragment = prepared.observe(prepared.poll_id, None, "ref", "", "body")
    assert fragment.initial_state is None
    for state, reference in ((" ", "ref"), ("done", " "), ("x" * 16385, "ref")):
        with pytest.raises(ValueError):
            prepared.observe(prepared.poll_id, state, reference, "", "body")
    first = prepared.observe(prepared.poll_id, "waiting", "ref", "", "body")
    pending = first.begin_poll()
    monitor = pending.observe(pending.poll_id, "done", "ref", "", "authorized body")
    event = monitor.event(1)
    assert event.notice_status is NoticeStatus.WRITTEN
    submitting = monitor.begin_notice(1)
    assert submitting.begin_notice(1) is submitting
    assert submitting.notice_result(1, 9, NoticeStatus.FAILED, "old") is submitting
    for status, error in ((NoticeStatus.WRITTEN, ""), (NoticeStatus.FAILED, " ")):
        with pytest.raises(ValueError):
            submitting.notice_result(1, 1, status, error)
    failed = submitting.notice_result(1, 1, NoticeStatus.FAILED, "necessary action")
    assert failed.notice_result(1, 1, NoticeStatus.DELIVERED, "") is failed
    cancelled = monitor.cancel("cancel")
    assert cancelled.cancel("again") is cancelled
    assert cancelled.event(1).notice_status is NoticeStatus.DISCARDED
    assert cancelled.begin_notice(1) is cancelled
    assert cancelled.notice_result(1, 0, NoticeStatus.DELIVERED, "") is cancelled
    with pytest.raises(InvalidTaskState):
        submitting.transfer(uuid7())
    pending = monitor.begin_poll()
    with pytest.raises(InvalidTaskState):
        pending.transfer(uuid7())
    assert not pending.cancel("stop").observe(pending.poll_id, "other", "ref", "", "body").active
    transferred = cancelled.transfer(uuid7())
    assert not transferred.active and transferred.events == cancelled.events


@pytest.mark.parametrize(
    "fields",
    [
        dict(remaining_polls=-1),
        dict(remaining_polls=10001),
        dict(kind=MonitorKind.PULL_REQUEST, target="https://evil.invalid/a/b/pull/1"),
        dict(target="relative"),
        dict(kind="other"),
    ],
)
def test_invalid_monitor_target_and_budget(fields):
    values = asdict(bare_monitor())
    values.update(fields)
    with pytest.raises(ValueError):
        TaskMonitor(**values)


def test_observer_pr_normalization_and_output_fragment_contract(tmp_path, monkeypatch):
    observer = SubprocessMonitorObserverService()
    data = dict(
        state="OPEN",
        headRefOid="sha",
        reviewDecision="",
        mergeStateStatus="CLEAN",
        statusCheckRollup=[
            dict(name="check", status="COMPLETED", conclusion="SUCCESS", startedAt="old")
        ],
    )

    def read(args, **kwargs):
        assert args[0:3] == ["gh", "pr", "view"] and kwargs["timeout"] == 30
        return SimpleNamespace(stdout=json.dumps(data))

    monkeypatch.setattr(subprocess, "run", read)
    first = observer.observe(MonitorKind.PULL_REQUEST, "https://github.com/owner/repo/pull/1")
    data["statusCheckRollup"][0]["startedAt"] = "new"
    assert observer.observe(MonitorKind.PULL_REQUEST, first.reference).state == first.state
    data["statusCheckRollup"] = None
    assert observer.observe(MonitorKind.PULL_REQUEST, first.reference).error == ""
    output = tmp_path / "output"
    output.write_bytes(b'{"state":"part')
    assert observer.observe(MonitorKind.OUTPUT, str(output)).state is None
    output.write_bytes(b"x" * 70000 + b'\n{"state":"done"}\n{"state":"fragment')
    assert observer.observe(MonitorKind.OUTPUT, str(output)).state == "done"
    output.write_bytes(b"{}\n")
    assert "string state" in observer.observe(MonitorKind.OUTPUT, str(output)).error
    assert observer.observe("unsupported", str(output)).error

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("gh", 30)

    monkeypatch.setattr(subprocess, "run", fail)
    assert "TimeoutExpired" in observer.observe(MonitorKind.PULL_REQUEST, first.reference).error
    valid = TaskMonitor(
        number=1,
        wait_number=1,
        definition_number=1,
        owner_execution_id=uuid7(),
        kind=MonitorKind.PULL_REQUEST,
        target=first.reference,
        remaining_polls=1,
    )
    assert valid.kind is MonitorKind.PULL_REQUEST


def test_ports_fail_explicitly():
    with pytest.raises(NotImplementedError):
        IMonitorObserverService.observe(object(), MonitorKind.OUTPUT, "/output")
    with pytest.raises(NotImplementedError):
        IMonitorNotifierService.submit(object(), "ref", "body")


async def test_registration_scope_revision_duplicate_and_current_owner_guards(database, monitored):
    m = monitored
    task = await task_stored(database, m)
    values = dict(
        project_id=task.project_id,
        session_id=task.owner_session_id,
        task_id=task.uid,
        expected_revision=task.revision,
        execution_id=m.owner.uid,
        kind=MonitorKind.OUTPUT,
        target=str(m.output),
        budget=3,
    )
    before = snapshot(database)
    with pytest.raises(RevisionConflict):
        await run(
            RegisterMonitorUseCase,
            RegisterMonitorCommand(**dict(values, expected_revision=0)),
            database_path=database,
        )
    with pytest.raises(InvalidTaskState, match="existing"):
        await run(RegisterMonitorUseCase, RegisterMonitorCommand(**values), database_path=database)
    assert snapshot(database) == before
    other = await register_session(
        m.actor.session.working_directory, "claude", "different-owner", database_path=database
    )
    await native(database, other, "UserPromptSubmit")
    other_execution = await execution(database, other)
    with pytest.raises(ContextNotFound):
        await run(
            RegisterMonitorUseCase,
            RegisterMonitorCommand(**dict(values, execution_id=other_execution.uid)),
            database_path=database,
        )
    await native(database, m.actor, "SessionEnd")
    with pytest.raises(InvalidTaskState, match="stopped"):
        await run(RegisterMonitorUseCase, RegisterMonitorCommand(**values), database_path=database)
    assert await call(database, m, PrepareMonitorPollUseCase) is not None
    async with storage_scope(database) as scope:
        task = await scope.get(ITaskRepository).get(m.task.uid)
        task.update_monitor(replace(task.monitor(1), owner_execution_id=other_execution.uid))
        await scope.get(ITaskRepository).save(task)
    m.monitor = replace(m.monitor, owner_execution_id=other_execution.uid)
    with pytest.raises(ContextNotFound, match="another session"):
        await call(database, m, PrepareMonitorPollUseCase)


async def test_domain_registration_wait_scope_reconcile_and_selective_cancel(database, monitored):
    m = monitored
    task = await task_stored(database, m)
    with pytest.raises(ContextNotFound):
        task.monitor(99)
    for target, budget in (("/wrong", 1), (str(m.output), 0)):
        with pytest.raises(InvalidTaskState):
            task.register_monitor(m.owner.uid, MonitorKind.OUTPUT, target, budget)
    task.cancel_monitors("unrelated execution", uuid7())
    assert task.monitor(1).active
    task.cancel_monitors("explicit cancellation")
    next_monitor = task.register_monitor(m.owner.uid, MonitorKind.OUTPUT, str(m.output), 2)
    assert next_monitor.number == 2
    task.update_monitor(replace(next_monitor, definition_number=999))
    assert not task.reconcile_monitor(2, cancelled=False).active
    task.update_monitor(replace(next_monitor, wait_number=999))
    assert not task.reconcile_monitor(2, cancelled=False).active
    task.status = TaskStatus.ACTIVE
    with pytest.raises(InvalidTaskState):
        task.register_monitor(m.owner.uid, MonitorKind.OUTPUT, str(m.output), 2)


async def test_old_changed_state_event_cannot_resolve_latest_wait(database, monitored):
    m = monitored
    await changed(database, m)
    m.output.write_text('{"state":"waiting-again"}\n')
    latest = await call(database, m, TickMonitorUseCase)
    assert len(latest.events) == 2
    before = snapshot(database)
    with pytest.raises(InvalidTaskState, match="latest"):
        await call(
            database,
            m,
            ResolveMonitorEventUseCase,
            ResolveMonitorEventCommand,
            event_number=1,
            resolution="stale done observation",
        )
    assert snapshot(database) == before
    assert (await task_stored(database, m)).status is TaskStatus.WAITING


async def test_cancel_between_reservation_and_observer_makes_no_external_call(
    database, monitored, monkeypatch
):
    m = monitored

    def forbidden(*args):
        raise AssertionError("cancelled reservation cannot observe")

    monkeypatch.setattr(SubprocessMonitorObserverService, "observe", forbidden)
    current = await cancel_after_reservation(database, m, "prepare")
    assert not current.active and current.poll_id is None and current.initial_state is None


async def test_observer_exception_is_recorded_without_new_event_or_resource_leak(
    database, monitored, monkeypatch
):
    def fail(*args):
        raise RuntimeError("observer plugin failed")

    monkeypatch.setattr(SubprocessMonitorObserverService, "observe", fail)
    current = await call(database, monitored, TickMonitorUseCase)
    assert current.poll_id is None and current.events == ()
    assert "Inspect the observer" in current.error


async def test_cancel_between_notice_reservation_and_submit_preserves_unsubmitted_outcome(
    database, monitored, monkeypatch
):
    m = monitored
    await call(database, m, TickMonitorUseCase)
    m.output.write_text('{"state":"done"}\n')

    def forbidden(*args):
        raise AssertionError("cancelled reservation cannot notify")

    monkeypatch.setattr(StderrMonitorNotifierService, "submit", forbidden)
    current = await cancel_after_reservation(database, m, "prepare_notice")
    assert not current.active and current.events[0].notice_status is NoticeStatus.FAILED
    assert "Cancelled before submission" in current.events[0].error
    assert len(current.events[0].delivery_errors) == 1
    assert current.transfer(uuid7()).events == current.events


async def test_submitted_failure_history_survives_success_and_ended_owner_never_submits(
    database, monitored, monkeypatch
):
    m = monitored

    def fail(*args):
        return MonitorDelivery(status=NoticeStatus.FAILED, error="restore notification access")

    original = StderrMonitorNotifierService.submit
    monkeypatch.setattr(StderrMonitorNotifierService, "submit", fail)
    current = await changed(database, m)
    assert current.events[0].delivery_errors == ("restore notification access",)
    monkeypatch.setattr(StderrMonitorNotifierService, "submit", original)
    current = await call(database, m, TickMonitorUseCase)
    assert current.events[0].notice_status is NoticeStatus.SUBMITTED
    assert current.events[0].delivery_errors == ("restore notification access",)
    await native(database, m.actor, "SessionEnd")
    assert (
        await call(
            database, m, PrepareMonitorNoticeUseCase, PrepareMonitorNoticeCommand, event_number=1
        )
        is None
    )


async def test_cancel_during_observation_discards_late_state_and_releases_exact_resource(
    database, monitored, monkeypatch
):
    m = monitored

    def cancel(self, kind, target):
        asyncio.run(call(database, m, CancelMonitorUseCase))
        return MonitorObservation(state="done", reference="actual late observation")

    monkeypatch.setattr(SubprocessMonitorObserverService, "observe", cancel)
    current = await call(database, m, TickMonitorUseCase)
    assert not current.active and current.poll_id is None and current.events == ()


async def test_single_poll_reservation_survives_independent_concurrent_requests(
    database, monitored
):
    results = await asyncio.gather(
        call(database, monitored, PrepareMonitorPollUseCase),
        call(database, monitored, PrepareMonitorPollUseCase),
        return_exceptions=True,
    )
    reserved = [item for item in results if isinstance(item, TaskMonitor)]
    assert len(reserved) == 1
    assert (await stored(database, monitored)).remaining_polls == 19


def test_observer_rejects_oversized_and_blank_complete_states(tmp_path, monkeypatch):
    observer = SubprocessMonitorObserverService()
    output = tmp_path / "output"
    for state in (" ", "x" * 16385):
        output.write_text(json.dumps(dict(state=state)) + "\n")
        assert "Output state" in observer.observe(MonitorKind.OUTPUT, str(output)).error
    data = dict(
        state="OPEN",
        headRefOid="x" * 17000,
        reviewDecision="",
        mergeStateStatus="CLEAN",
        statusCheckRollup=[],
    )
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(data))
    )
    assert (
        "PR state exceeds"
        in observer.observe(MonitorKind.PULL_REQUEST, "https://github.com/a/b/pull/1").error
    )


async def cancel_after_reservation(database, m, selected):
    async with scanned_application(sqlite_url(database, "rw")) as app:
        scanned = app.container.get(TickMonitorUseCase)
        dependencies = {
            name: getattr(scanned, name)
            for name in (
                "prepare",
                "record",
                "query",
                "prepare_notice",
                "record_notice",
                "observer",
                "notifier",
            )
        }
        reservation = dependencies[selected]

        async def interleave(request):
            result = await reservation.run(request)
            await call(database, m, CancelMonitorUseCase)
            return result

        dependencies[selected] = SimpleNamespace(run=interleave)
        return await TickMonitorUseCase(**dependencies).run(command(m))


async def test_monitor_context_is_injected_through_its_port_and_shares_framework_repositories(
    database,
):
    from neurath.application.ports.repositories.execution import IExecutionRepository
    from neurath.application.ports.services.monitor_context import IMonitorContextService
    from neurath.infrastructure.services.monitor_context import SQLAlchemyMonitorContextService
    from tests.support.application import spakky_context

    async with spakky_context(database) as container:
        context = container.get(IMonitorContextService)
        assert isinstance(context, SQLAlchemyMonitorContextService)
        assert context.tasks is container.get(ITaskRepository)
        assert context.executions is container.get(IExecutionRepository)
        for usecase in (
            PrepareMonitorPollUseCase,
            RecordMonitorObservationUseCase,
            AcknowledgeMonitorEventUseCase,
            ResolveMonitorEventUseCase,
            CancelMonitorUseCase,
            RecoverMonitorUseCase,
            PrepareMonitorNoticeUseCase,
            RecordMonitorNoticeUseCase,
        ):
            assert container.get(usecase).context is context


async def test_monitor_context_abstract_fallback_fails_explicitly():
    from neurath.application.ports.services.monitor_context import IMonitorContextService

    with pytest.raises(TypeError):
        IMonitorContextService()
    with pytest.raises(NotImplementedError):
        await IMonitorContextService.load(
            None,
            project_id=uuid7(),
            session_id=uuid7(),
            task_id=uuid7(),
            monitor_number=1,
            execution_id=uuid7(),
            generation=1,
        )


@pytest.mark.parametrize(
    "status,allowed,cancelled",
    [
        ("running", True, False),
        ("paused", True, False),
        ("cancelled", False, True),
        ("ended", True, False),
    ],
)
def test_execution_owns_monitoring_permission_and_session_scope(status, allowed, cancelled):
    from neurath.domain.aggregates.execution import Execution
    from neurath.domain.enums.execution_status import ExecutionStatus

    owner = Execution.create(uuid7())
    owner.status = ExecutionStatus(status)
    owner.require_session(owner.session_id)
    with pytest.raises(ContextNotFound, match="another session"):
        owner.require_session(uuid7())
    assert owner.allows_monitoring is allowed
    assert owner.is_cancelled is cancelled
    if allowed and status != "ended":
        owner.require_monitoring()
    else:
        with pytest.raises(InvalidTaskState):
            owner.require_monitoring()
