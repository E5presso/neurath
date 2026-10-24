"""실제 SQLite와 프로세스로 호스트 제어·작성 충돌·미완료 보존을 검증한다."""

import asyncio
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command as alembic_command
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import select, text

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.application.ports.services.writer_observer import IWriterObserverService
from neurath.application.usecases.interrupt_execution import InterruptExecutionUseCase
from neurath.application.usecases.observe_writer import ObserveWriterUseCase
from neurath.application.usecases.recover_writer import RecoverWriterCommand, RecoverWriterUseCase
from neurath.domain.aggregates.execution import Execution
from neurath.domain.aggregates.writer import Writer
from neurath.domain.enums.execution_status import ExecutionStatus
from neurath.domain.enums.hook_action import HookAction
from neurath.domain.enums.liveness import Liveness
from neurath.domain.errors import InvalidExecutionState
from neurath.infrastructure.models.execution import ExecutionModel
from neurath.infrastructure.models.writer import WriterModel
from neurath.infrastructure.services.process_observer import PosixWriterObserverService
from tests.conftest import storage_scope
from tests.support.application import spakky_context
from tests.support.hook_cli import HookCliClient
from tests.support.session_requests import register_session
from tests.test_task_migrations import migration_config
from tests.test_task_requests import create


@pytest.fixture
async def native(database, tmp_path):
    folder = tmp_path / "runtime-project"
    folder.mkdir()
    actor = await register_session(str(folder), "codex", "native-session", database_path=database)
    payload = dict(
        session_id="native-session",
        cwd=str(folder),
        turn_id="turn-1",
        hook_event_name="UserPromptSubmit",
    )
    adapter = HookCliClient("codex", database)
    assert (await adapter.handle(payload)) == {}
    return actor, adapter, payload


async def send(native, event, **fields):
    actor, adapter, payload = native
    return await adapter.handle(dict(payload, hook_event_name=event, **fields))


async def execution(database, actor, agent=""):
    async with storage_scope(database, write=False) as scope:
        row = await scope.get(AsyncSessionManager).session.scalar(
            select(ExecutionModel).where(
                ExecutionModel.session_id == actor.session.uid, ExecutionModel.agent_id == agent
            )
        )
        return None if row is None else row.to_domain()


async def writer(database, native):
    async with storage_scope(database, write=False) as scope:
        row = await scope.get(AsyncSessionManager).session.scalar(
            select(WriterModel).where(WriterModel.resource == native[2]["cwd"])
        )
        return None if row is None else row.to_domain()


async def test_stop_feedback_once_preserves_tasks_and_cancelled_turn(database, native):
    actor = native[0]
    task = await create(database, actor)
    feedback = await send(native, "Stop", stop_hook_active=False)
    assert feedback["decision"] == "block"
    assert str(task.uid) in feedback["reason"]
    paused = await send(native, "Stop", stop_hook_active=True)
    assert paused["continue"] is False
    assert "No progress" in paused["stopReason"]
    assert (await execution(database, actor)).status is ExecutionStatus.PAUSED
    assert (await send(native, "Stop"))["continue"] is False
    assert "hookSpecificOutput" in await send(native, "SessionStart", source="resume")
    assert (await execution(database, actor)).status is ExecutionStatus.PAUSED
    assert (await send(native, "UserPromptSubmit", turn_id="turn-2")) == {}
    assert (await send(native, "Interrupt", turn_id="turn-2"))["continue"] is False
    assert (await execution(database, actor)).status is ExecutionStatus.CANCELLED
    assert (await send(native, "UserPromptSubmit", turn_id="turn-2")) == {}
    assert (
        await send(native, "PreToolUse", turn_id="turn-2", tool_name="Edit", tool_use_id="edit")
    )["continue"] is False
    assert (await writer(database, native)) is None
    assert (
        await send(native, "PreToolUse", turn_id="turn-2", tool_name="Read", tool_use_id="read")
    ) == {}
    assert (await send(native, "Stop", turn_id="turn-1"))["continue"] is False
    assert (await execution(database, actor)).turn_id == "turn-2"
    assert (await send(native, "SessionEnd", reason="prompt_input_exit")) == {}
    assert (await execution(database, actor)).status is ExecutionStatus.ENDED


async def test_writer_exclusion_and_child_read_regression_133(database, native):
    assert (await send(native, "PreToolUse", tool_name="Edit", tool_use_id="root-edit")) == {}
    first = await writer(database, native)
    assert first.generation == 1
    assert (await send(native, "PreToolUse", tool_name="Edit", tool_use_id="root-edit")) == {}
    assert (await writer(database, native)).generation == 1
    assert (await send(native, "SubagentStart", agent_id="native-child")) == {}
    assert (
        await send(
            native,
            "PreToolUse",
            agent_id="native-child",
            tool_name="Read",
            tool_use_id="child-read",
        )
    ) == {}
    child = await execution(database, native[0], "native-child")
    assert child.turn_id == "turn-1"
    assert child.uid != first.execution_id
    assert (
        await send(
            native,
            "PreToolUse",
            agent_id="native-child",
            tool_name="Write",
            tool_use_id="child-write",
        )
    )["continue"] is False
    assert (await send(native, "SubagentStop", agent_id="native-child")) == {}
    assert (await writer(database, native)).execution_id == first.execution_id
    assert (
        await send(
            native,
            "PostToolUse",
            agent_id="native-child",
            tool_name="Write",
            tool_use_id="root-edit",
        )
    ) == {}
    assert (await writer(database, native)).execution_id == first.execution_id
    assert (await send(native, "PostToolUse", tool_name="Edit", tool_use_id="root-edit")) == {}
    assert (await writer(database, native)).execution_id is None
    assert (
        await send(
            native,
            "PreToolUse",
            agent_id="native-child",
            tool_name="Write",
            tool_use_id="child-write",
        )
    ) == {}
    assert (await writer(database, native)).generation == 2
    assert (await send(native, "PostToolUse", tool_name="Edit", tool_use_id="root-edit")) == {}
    assert (await writer(database, native)).execution_id == child.uid


async def test_unconfirmed_shell_completion_does_not_release_and_failure_cancels(database, native):
    assert (await send(native, "PreToolUse", tool_name="exec_command", tool_use_id="shell")) == {}
    assert (
        await send(
            native,
            "PostToolUse",
            tool_name="exec_command",
            tool_use_id="shell",
            tool_response={"session_id": 42},
        )
    ) == {}
    assert (await writer(database, native)).execution_id is not None
    assert (
        await send(
            native,
            "PostToolUse",
            tool_name="exec_command",
            tool_use_id="shell",
            tool_response={"exit_code": 0},
        )
    ) == {}
    assert (await writer(database, native)).execution_id is None
    assert (await send(native, "PreToolUse", tool_name="Write", tool_use_id="write")) == {}
    assert (
        await send(
            native,
            "PostToolUseFailure",
            tool_name="Write",
            tool_use_id="write",
            is_interrupt=True,
            error="user abort",
        )
    ) == {}
    assert (await execution(database, native[0])).status is ExecutionStatus.CANCELLED
    assert (await writer(database, native)).execution_id is None


async def test_two_actual_requests_have_only_one_writer(database, native):
    def claim(call):
        import json
        import os
        from pathlib import Path

        from neurath.infrastructure.database import sqlite_url

        payload = dict(native[2], hook_event_name="PreToolUse", tool_name="Write", tool_use_id=call)
        result = subprocess.run(
            [
                str(Path(sys.executable).with_name("neurath")),
                "hook",
                "handle",
                "--provider",
                "codex",
            ],
            env={
                **os.environ,
                "SPAKKY_SQLALCHEMY__CONNECTION_STRING": sqlite_url(database, "rw").render_as_string(
                    hide_password=False
                ),
            },
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, ("a", "b")))
    assert results.count({}) == 1
    assert sum(r.get("continue") is False for r in results) == 1
    assert (await writer(database, native)).generation == 1


async def test_codec_validation_failure_bypass_and_claude_prompt_identity(database, native):
    actor, adapter, payload = native
    with pytest.raises(ValueError):
        HookCliClient("unknown", database)
    for bad in (
        {},
        dict(payload, session_id=None),
        dict(payload, stop_hook_active="true"),
        dict(payload, is_interrupt=1),
        dict(payload, hook_event_name="PreToolUse"),
    ):
        result = await adapter.handle(bad)
        assert result["continue"] is False
        assert "hook failure" in result["stopReason"]
    assert "systemMessage" in (await adapter.handle({}, bypass=True))
    assert (await execution(database, actor)).status is ExecutionStatus.RUNNING
    missing = HookCliClient("claude", database.parent / "missing.db")
    assert (await missing.handle(payload))["continue"] is False
    assert "systemMessage" in (await missing.handle({}, bypass=True))
    claude = HookCliClient("claude", database)
    cp = dict(payload, prompt_id="prompt-actual", hook_event_name="UserPromptSubmit")
    assert (await claude.handle(cp)) == {}
    cp["hook_event_name"] = "Stop"
    assert (await claude.handle(cp)) == {}
    cp.pop("prompt_id")
    assert (await claude.handle(cp))["continue"] is False
    assert (await send(native, "UnrecognizedEvent"))["continue"] is False
    assert (await send(native, "StopFailure", error="provider unavailable"))["continue"] is False
    assert (await execution(database, actor)).reason == "provider unavailable"


@pytest.mark.parametrize(
    "event,tool,response,expected",
    [
        ("PreToolUse", "Write", None, False),
        ("PostToolUseFailure", "Write", None, True),
        ("PostToolUseFailure", "Bash", None, False),
        ("PostToolUse", "Write", {}, True),
        ("PostToolUse", "Bash", None, False),
        ("PostToolUse", "Bash", {"backgroundTaskId": "x"}, False),
        ("PostToolUse", "exec_command", {"session_id": 3, "exit_code": 0}, False),
        ("PostToolUse", "exec_command", {"exit_code": True}, False),
        ("PostToolUse", "exec_command", {"exit_code": 1}, True),
    ],
)
def test_codec_only_confirms_observed_termination(
    database, native, event, tool, response, expected
):
    command = native[1].decode(
        dict(
            native[2],
            hook_event_name=event,
            tool_name=tool,
            tool_use_id="id",
            tool_response=response,
        )
    )
    assert command.finished is expected


def test_writer_domain_rejects_stale_release_and_unknown_liveness():
    lease = Writer.create("/workspace")
    for keys in (("", "turn", "tool"), ("owner", "", "tool"), ("owner", "turn", "")):
        with pytest.raises(InvalidExecutionState):
            lease.acquire(*keys)
    assert lease.acquire("owner", "turn", "tool") == 1
    assert lease.acquire("owner", "turn", "tool") == 1
    with pytest.raises(InvalidExecutionState):
        lease.acquire("other", "turn", "tool")
    for owner, generation, live in [
        ("other", 1, Liveness.STOPPED),
        ("owner", 2, Liveness.STOPPED),
        ("owner", 1, Liveness.UNKNOWN),
        ("owner", 1, Liveness.RUNNING),
    ]:
        with pytest.raises(InvalidExecutionState):
            lease.release(owner, generation, live)
    lease.release("owner", 1, Liveness.STOPPED)
    lease.acquire("owner", "turn", "next")
    with pytest.raises(InvalidExecutionState):
        lease.release("owner", 1, Liveness.STOPPED)
    lease.release("owner", 2, Liveness.STOPPED)


def test_execution_domain_does_not_resume_cancelled_or_ended_and_empty_is_not_success():
    current = Execution.create("session")
    with pytest.raises(InvalidExecutionState):
        current.begin_turn("")
    current.begin_turn("one")
    assert current.decide_stop((), repeated=False) is HookAction.ALLOW
    current.cancel("one", "cancelled by host")
    current.pause("do not overwrite")
    assert current.status is ExecutionStatus.CANCELLED
    current.begin_turn("one")
    assert current.status is ExecutionStatus.CANCELLED
    current.end("host ended")
    current.pause("do not overwrite")
    assert current.status is ExecutionStatus.ENDED
    current.begin_turn("two")
    assert current.status is ExecutionStatus.ENDED
    current.resume("two")
    assert current.status is ExecutionStatus.RUNNING


async def test_real_process_liveness_recovery_and_generation_recheck(database, native):
    (await send(native, "PreToolUse", tool_name="exec_command", tool_use_id="process"))
    lease = await writer(database, native)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    observer = PosixWriterObserverService(
        {(lease.execution_id, lease.turn_id, lease.tool_use_id): process}
    )
    assert (
        PosixWriterObserverService({}).observe(lease.execution_id, lease.turn_id, lease.tool_use_id)
        is Liveness.UNKNOWN
    )
    assert (
        observer.observe(lease.execution_id, lease.turn_id, lease.tool_use_id) is Liveness.RUNNING
    )
    try:
        async with spakky_context(database, write=True) as scope:
            scope.get(ObserveWriterUseCase).observer = observer
            recovery = scope.get(RecoverWriterUseCase)
            with pytest.raises(InvalidExecutionState):
                (
                    await recovery.run(
                        RecoverWriterCommand(writer_id=lease.uid, generation=lease.generation + 1)
                    )
                )
            await recovery.run(
                RecoverWriterCommand(writer_id=lease.uid, generation=lease.generation)
            )
            assert (await writer(database, native)).execution_id == lease.execution_id
            process.terminate()
            process.wait(timeout=5)
            assert (
                observer.observe(lease.execution_id, lease.turn_id, lease.tool_use_id)
                is Liveness.STOPPED
            )
            await recovery.run(
                RecoverWriterCommand(writer_id=lease.uid, generation=lease.generation)
            )
            assert (await writer(database, native)).execution_id is None
            with pytest.raises(InvalidExecutionState):
                (
                    await recovery.run(
                        RecoverWriterCommand(writer_id=lease.uid, generation=lease.generation)
                    )
                )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


async def test_recovery_cannot_release_new_generation_during_external_observation(database, native):
    (await send(native, "PreToolUse", tool_name="Write", tool_use_id="first"))
    lease = await writer(database, native)

    class RacingObserver(IWriterObserverService):
        def observe(self, execution_id, turn_id, tool_use_id):
            asyncio.run(send(native, "PostToolUse", tool_name="Write", tool_use_id="first"))
            asyncio.run(send(native, "PreToolUse", tool_name="Write", tool_use_id="second"))
            return Liveness.STOPPED

    async with spakky_context(database, write=True) as scope:
        scope.get(ObserveWriterUseCase).observer = RacingObserver()
        recovery = scope.get(RecoverWriterUseCase)
        await recovery.run(RecoverWriterCommand(writer_id=lease.uid, generation=lease.generation))
    assert (await writer(database, native)).generation == 2
    assert (await writer(database, native)).execution_id == lease.execution_id


async def test_migration_preserves_runtime_history_and_empty_downgrade(database, native, tmp_path):
    from neurath.infrastructure.database import create_database_engine, initialize_database

    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="history"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: alembic_command.downgrade(
                        migration_config(sync_connection), "core_0004"
                    )
                )
    finally:
        (await engine.dispose())
    assert (await execution(database, native[0])).turn_id == "turn-1"
    empty = tmp_path / "empty.db"
    (await initialize_database(empty))
    engine = create_database_engine(empty, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: alembic_command.downgrade(
                    migration_config(sync_connection), "core_0004"
                )
            )
            await connection.run_sync(
                lambda sync_connection: alembic_command.upgrade(
                    migration_config(sync_connection), "head"
                )
            )
        async with storage_scope(empty) as scope:
            (
                await scope.get(AsyncSessionManager).session.execute(
                    text(
                        "INSERT INTO core_writers (id, version, created_at, updated_at, revision, resource, turn_id, tool_use_id, generation) VALUES ('11111111111111111111111111111111', '00000000000000000000000000000000', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, '/w', '', '', 0)"
                    )
                )
            )
        with pytest.raises(RuntimeError, match="history"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: alembic_command.downgrade(
                        migration_config(sync_connection), "core_0004"
                    )
                )
    finally:
        (await engine.dispose())


async def test_abstract_contracts_fail_explicitly():
    for port in (IExecutionRepository, IWriterRepository):
        with pytest.raises(TypeError):
            port()
    with pytest.raises(NotImplementedError):
        IWriterObserverService.observe(None, None, None, None)


async def test_waiting_only_yields_but_independent_work_continues(database, native):
    from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
    from neurath.application.usecases.wait_task import WaitTaskCommand, WaitTaskUseCase
    from neurath.domain.values.external_wait import ExternalWait
    from tests.support.requests import run

    task = await create(database, native[0])
    active = (
        await run(
            StartTaskUseCase,
            StartTaskCommand(
                project_id=native[0].project.uid,
                session_id=native[0].session.uid,
                task_id=task.uid,
                expected_revision=task.revision,
            ),
            database_path=database,
        )
    ).task
    condition = ExternalWait(
        target="external job",
        condition="job has finished",
        resume_scope="read its result",
        observation="job status running",
    )
    (
        await run(
            WaitTaskUseCase,
            WaitTaskCommand(
                project_id=native[0].project.uid,
                session_id=native[0].session.uid,
                task_id=active.uid,
                expected_revision=active.revision,
                condition=condition,
            ),
            database_path=database,
        )
    )
    assert (await send(native, "Stop"))["continue"] is False
    assert "External dependencies" in (await execution(database, native[0])).reason
    (await send(native, "UserPromptSubmit", turn_id="turn-2"))
    from neurath.application.usecases.resume_execution import (
        ResumeExecutionCommand,
        ResumeExecutionUseCase,
    )

    current = await execution(database, native[0])
    (
        await run(
            ResumeExecutionUseCase,
            ResumeExecutionCommand(execution_id=current.uid, turn_id="turn-2"),
            database_path=database,
        )
    )
    other = await create(database, native[0], title="independent")
    result = await send(native, "Stop", turn_id="turn-2")
    assert result["decision"] == "block"
    assert str(other.uid) in result["reason"]


async def test_finished_event_without_writer_and_fresh_child_without_start(database, native):
    assert (await send(native, "PostToolUse", tool_name="Write", tool_use_id="unknown")) == {}
    assert (
        await send(
            native, "PreToolUse", agent_id="child-from-host", tool_name="Read", tool_use_id="r"
        )
    ) == {}
    assert (await execution(database, native[0], "child-from-host")).turn_id == "turn-1"


async def test_read_only_query_stays_available_when_other_execution_writes(database, native):
    from neurath.application.usecases.get_session_context import (
        GetSessionContextQuery,
        GetSessionContextUseCase,
    )
    from tests.support.requests import run

    assert (await send(native, "PreToolUse", tool_name="Write", tool_use_id="writing")) == {}
    context = await run(
        GetSessionContextUseCase,
        GetSessionContextQuery(project_id=native[0].project.uid, session_id=native[0].session.uid),
        database_path=database,
    )
    assert context.session.uid == native[0].session.uid


def test_workspace_normalization_and_missing_git(database, repository, monkeypatch):
    child = repository / "nested"
    child.mkdir()
    from neurath.infrastructure.services.directory_observer import GitDirectoryObserverService

    service = GitDirectoryObserverService()
    assert service.workspace(str(child)) == str(repository)

    def missing(*args, **kwargs):
        raise FileNotFoundError("no git")

    monkeypatch.setattr(subprocess, "run", missing)
    from neurath.domain.errors import NeurathError

    with pytest.raises(NeurathError, match="Cannot inspect"):
        service.workspace(str(child))


async def test_real_targeted_cancellation_preserves_other_process_and_writes(database, native):
    from neurath.application.usecases.cancel_execution import (
        CancelExecutionCommand,
        CancelExecutionUseCase,
    )

    (await send(native, "PreToolUse", tool_name="exec_command", tool_use_id="process"))
    current = await execution(database, native[0])
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    controller = PosixWriterObserverService(
        {(current.uid, current.turn_id, "process"): process, ("other", "other-turn", "call"): other}
    )
    try:
        async with spakky_context(database, write=True) as scope:
            scope.get(InterruptExecutionUseCase).controller = controller
            cancel = scope.get(CancelExecutionUseCase)
            result = await cancel.run(
                CancelExecutionCommand(execution_id=current.uid, turn_id=current.turn_id)
            )
            assert result.status is ExecutionStatus.PAUSED
            assert (await execution(database, native[0])).status is ExecutionStatus.CANCELLED
        assert process.poll() is not None
        assert other.poll() is None
        assert (await writer(database, native)).execution_id == current.uid
        assert controller.interrupt(current.uid, current.turn_id) is Liveness.STOPPED
        assert (
            PosixWriterObserverService({}).interrupt(current.uid, current.turn_id)
            is Liveness.UNKNOWN
        )
    finally:
        for child in (process, other):
            if child.poll() is None:
                child.kill()
            child.wait()


async def test_unknown_cancellation_and_late_response_cannot_cancel_new_turn(database, native):
    from neurath.application.ports.services.execution_controller import IExecutionControllerService
    from neurath.application.usecases.cancel_execution import (
        CancelExecutionCommand,
        CancelExecutionUseCase,
    )

    current = await execution(database, native[0])
    async with spakky_context(database, write=True) as scope:
        scope.get(InterruptExecutionUseCase).controller = PosixWriterObserverService({})
        cancel = scope.get(CancelExecutionUseCase)
        assert (
            await cancel.run(
                CancelExecutionCommand(execution_id=current.uid, turn_id=current.turn_id)
            )
        ).status is ExecutionStatus.PAUSED

    class LateController(IExecutionControllerService):
        def interrupt(self, execution_id, turn_id):
            asyncio.run(send(native, "UserPromptSubmit", turn_id="new-turn"))
            return Liveness.STOPPED

    async with spakky_context(database, write=True) as scope:
        scope.get(InterruptExecutionUseCase).controller = LateController()
        cancel = scope.get(CancelExecutionUseCase)
        await cancel.run(CancelExecutionCommand(execution_id=current.uid, turn_id=current.turn_id))
    assert (await execution(database, native[0])).turn_id == "new-turn"
    assert (await execution(database, native[0])).status is ExecutionStatus.PAUSED
    with pytest.raises(NotImplementedError):
        IExecutionControllerService.interrupt(None, None, None)


async def test_process_control_never_signals_shared_group(database, native):
    current = await execution(database, native[0])
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    controller = PosixWriterObserverService({(current.uid, current.turn_id, "process"): process})
    try:
        assert controller.interrupt(current.uid, current.turn_id) is Liveness.UNKNOWN
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()


def test_process_observation_requires_group_gone_and_handles_os_error(monkeypatch):
    import os

    process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    process.wait()
    monkeypatch.setattr(os, "killpg", lambda *args: None)
    assert PosixWriterObserverService._observe(process) is Liveness.RUNNING

    def inaccessible(*args):
        raise PermissionError("not observable")

    monkeypatch.setattr(os, "killpg", inaccessible)
    assert PosixWriterObserverService._observe(process) is Liveness.UNKNOWN


async def test_process_interrupt_escalates_and_reports_unconfirmed_failure(
    database, native, monkeypatch
):
    import os
    import signal

    current = await execution(database, native[0])
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    controller = PosixWriterObserverService({(current.uid, current.turn_id, "process"): process})
    original_wait = process.wait
    original_signal = os.killpg
    monkeypatch.setattr(
        os, "killpg", lambda pid, sig: None if sig == signal.SIGTERM else original_signal(pid, sig)
    )
    calls = []

    def timeout_once(timeout=None):
        calls.append(timeout)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("owned", timeout)
        return original_wait(timeout)

    monkeypatch.setattr(process, "wait", timeout_once)
    try:
        assert controller.interrupt(current.uid, current.turn_id) is Liveness.STOPPED
        assert len(calls) == 2
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            original_wait()
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    controller = PosixWriterObserverService({(current.uid, current.turn_id, "process"): other})

    def inaccessible(*args):
        raise PermissionError("cannot interrupt")

    with monkeypatch.context() as patch:
        patch.setattr(os, "getpgid", inaccessible)
        assert controller.interrupt(current.uid, current.turn_id) is Liveness.UNKNOWN
    other.kill()
    other.wait()


async def test_actual_normalized_codex_bash_terminal_hook_releases_without_parsing_text(
    database, native
):
    assert (await send(native, "PreToolUse", tool_name="Bash", tool_use_id="shell-real")) == {}
    assert (await writer(database, native)).execution_id is not None
    # Codex는 unified-exec 프로세스가 끝났을 때 이 사건을 발생시킨다.
    # 잘린 출력은 전체 읽음이나 명령 성공의 근거로 사용하지 않는다.
    assert (
        await send(
            native,
            "PostToolUse",
            tool_name="Bash",
            tool_use_id="shell-real",
            tool_response="[truncated output]",
        )
    ) == {}
    assert (await writer(database, native)).execution_id is None


async def test_claude_bash_result_shape_interrupt_and_background_are_distinct(database, native):
    adapter = HookCliClient("claude", database)
    base = dict(
        native[2],
        session_id="claude-shell",
        prompt_id="prompt-a",
        hook_event_name="UserPromptSubmit",
    )
    assert (await adapter.handle(base)) == {}
    pre = dict(base, hook_event_name="PreToolUse", tool_name="Bash", tool_use_id="bash")
    assert (await adapter.handle(pre)) == {}
    post = dict(
        pre,
        hook_event_name="PostToolUse",
        tool_response={"stdout": "done", "stderr": "", "interrupted": False},
    )
    assert (await adapter.handle(post)) == {}
    assert (await writer(database, native)).execution_id is None
    post["tool_response"] = {"stdout": "", "stderr": "", "interrupted": True}
    assert (await adapter.handle(dict(pre, tool_use_id="interrupt"))) == {}
    assert (await adapter.handle(dict(post, tool_use_id="interrupt"))) == {}
    assert (await adapter.handle(dict(base, hook_event_name="Stop")))["continue"] is False
    for response in (
        {},
        {"stdout": ""},
        {"stdout": "", "stderr": ""},
        {"stdout": "", "stderr": "", "interrupted": False, "backgroundTaskId": "background"},
    ):
        normalized = adapter.decode(dict(post, tool_response=response))
        assert normalized.finished is False
    # prompt_id가 없는 구형 호스트도 읽기·진단에는 임대를 요구하지 않는다.
    older = dict(base, hook_event_name="PreToolUse", tool_name="Read", tool_use_id="read-only")
    older.pop("prompt_id")
    assert (await adapter.handle(older)) == {}


async def test_resume_keeps_cancelled_work_paused_until_explicit_request(database, native):
    from neurath.application.usecases.resume_execution import (
        ResumeExecutionCommand,
        ResumeExecutionUseCase,
    )
    from tests.support.requests import run

    (await send(native, "Interrupt"))
    (await send(native, "UserPromptSubmit", turn_id="status-question"))
    current = await execution(database, native[0])
    assert current.status is ExecutionStatus.CANCELLED
    assert (
        await send(
            native, "PreToolUse", turn_id="status-question", tool_name="Write", tool_use_id="write"
        )
    )["continue"] is False
    resumed = await run(
        ResumeExecutionUseCase,
        ResumeExecutionCommand(execution_id=current.uid, turn_id=current.turn_id),
        database_path=database,
    )
    assert resumed.status is ExecutionStatus.RUNNING
    assert (
        await send(
            native, "PreToolUse", turn_id="status-question", tool_name="Write", tool_use_id="write"
        )
    ) == {}


async def test_stop_recognizes_actual_phase_progress_without_task_revision_change(
    database, tmp_path
):
    from neurath.application.usecases.prepare_phase import PreparePhaseCommand, PreparePhaseUseCase
    from neurath.application.usecases.start_workflow import (
        StartWorkflowCommand,
        StartWorkflowUseCase,
    )
    from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition
    from tests.support.requests import run

    folder = tmp_path / "phase-progress"
    folder.mkdir()
    actor = await register_session(str(folder), "codex", "phase-progress", database_path=database)
    task = await create(database, actor)
    phase = PhaseDefinition(
        key="check",
        purpose="검사",
        arguments=("true",),
        directory=str(folder),
        target_revision="revision-a",
    )
    workflow = (
        await run(
            StartWorkflowUseCase,
            StartWorkflowCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                task_id=task.uid,
                expected_task_revision=task.revision,
                definition=WorkflowDefinition(
                    skill="implement-spec", version="1", phases=(phase,), inputs=()
                ),
            ),
            database_path=database,
        )
    ).run
    adapter = HookCliClient("codex", database)
    base = dict(
        session_id="phase-progress",
        cwd=str(folder),
        turn_id="turn",
        hook_event_name="UserPromptSubmit",
    )
    assert (await adapter.handle(base)) == {}
    assert (await adapter.handle(dict(base, hook_event_name="Stop")))["decision"] == "block"
    (
        await run(
            PreparePhaseUseCase,
            PreparePhaseCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                run_id=workflow.uid,
                expected_revision=workflow.revision,
            ),
            database_path=database,
        )
    )
    assert (await adapter.handle(dict(base, hook_event_name="Stop", stop_hook_active=True)))[
        "decision"
    ] == "block"
    assert (await adapter.handle(dict(base, hook_event_name="Stop", stop_hook_active=True)))[
        "continue"
    ] is False
