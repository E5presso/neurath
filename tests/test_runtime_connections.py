"""실제 상태 연결의 실패·복구·경합을 정상 경로와 함께 검증한다."""

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.application.usecases.read_native_liveness import (
    ReadNativeLivenessQuery,
    ReadNativeLivenessUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.domain.enums.execution_status import ExecutionStatus
from neurath.domain.enums.liveness import Liveness
from neurath.domain.errors import RevisionConflict
from neurath.infrastructure.services.host_environment import PosixHostEnvironmentService
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.test_host_flow import create, invoke
from tests.test_host_flow import host as host


async def test_dependency_resolution_resumes_execution_and_peer_without_new_prompt(database, host):
    _, client, payload = host
    task = await create(database)
    await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "wait",
            "--task-id",
            task["id"],
            "--target",
            "external-job",
            "--condition",
            "done",
            "--resume-scope",
            "verify",
            "--reason",
            "running",
        ],
    )
    assert (await client.handle(dict(payload, hook_event_name="Stop")))["continue"] is False
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    assert scope.execution.status is ExecutionStatus.PAUSED and not scope.peer.active
    # 존재하지 않는 감시 사건을 지정한 요청을 일반 재개로 바꾸지 않는다.
    before = database.read_bytes()
    await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "resume",
            "--task-id",
            task["id"],
            "--reason",
            "invalid event",
            "--monitor-event",
            "1",
        ],
        succeeds=False,
    )
    assert database.read_bytes() == before
    await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "resume",
            "--task-id",
            task["id"],
            "--reason",
            "observed completion",
        ],
    )
    after = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    assert after.execution.status is ExecutionStatus.RUNNING and after.peer.active
    assert after.execution.turn_id == scope.execution.turn_id


async def test_native_file_liveness_and_late_outcome_preserve_correct_call(database, host):
    directory, client, payload = host
    call = dict(
        payload,
        hook_event_name="PreToolUse",
        tool_name="Write",
        tool_use_id="observed-call",
        tool_input={"file_path": str(directory / "result.txt")},
    )
    assert await client.handle(call) == {}
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    query = ReadNativeLivenessQuery(
        execution_id=scope.execution.uid,
        turn_id=scope.execution.turn_id,
        tool_use_id="observed-call",
    )
    assert await run(ReadNativeLivenessUseCase, query, database_path=database) is Liveness.RUNNING
    async with storage_scope(database) as container:
        execution = await container.get(IExecutionRepository).get(scope.execution.uid)
        execution.pause("actual observed interruption pending")
        await container.get(IExecutionRepository).save(execution)
    assert await run(ReadNativeLivenessUseCase, query, database_path=database) is Liveness.UNKNOWN
    async with storage_scope(database) as container:
        execution = await container.get(IExecutionRepository).get(scope.execution.uid)
        execution.end("actual observed closed connection")
        await container.get(IExecutionRepository).save(execution)
    assert await run(ReadNativeLivenessUseCase, query, database_path=database) is Liveness.STOPPED
    await client.handle(dict(payload, prompt="A new request"))
    async with storage_scope(database) as container:
        writer = await container.get(IWriterRepository).find_by_resource(
            str(directory / "result.txt")
        )
        assert writer.execution_id is None
    assert await client.handle(dict(call, hook_event_name="PostToolUse")) == {}


async def test_patch_paths_are_atomic_and_shell_is_not_a_writer(database, host):
    directory, client, payload = host
    patch = "*** Begin Patch\n*** Add File: one.txt\n+x\n*** Update File: two.txt\n*** Move to: renamed.txt\n*** Delete File: one.txt\n*** End Patch\n"
    decoded = client.decode(
        dict(
            payload,
            hook_event_name="PreToolUse",
            tool_name="apply_patch",
            tool_use_id="patch",
            tool_input=patch,
        )
    )
    assert decoded.write_targets == ("one.txt", "two.txt", "renamed.txt")
    assert (
        await client.handle(
            dict(
                payload,
                hook_event_name="PreToolUse",
                tool_name="apply_patch",
                tool_use_id="patch",
                tool_input={"command": patch},
            )
        )
        == {}
    )
    assert (
        await client.handle(
            dict(
                payload,
                hook_event_name="PreToolUse",
                tool_name="Bash",
                tool_use_id="diagnostic",
                tool_input={"command": "pwd"},
            )
        )
        == {}
    )
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    async with storage_scope(database) as container:
        writers = await container.get(IWriterRepository).find_by_execution_id(scope.execution.uid)
        assert {item.resource for item in writers} == {
            str(directory / name) for name in decoded.write_targets
        }
    await client.handle(
        dict(
            payload,
            hook_event_name="PostToolUseFailure",
            tool_name="apply_patch",
            tool_use_id="patch",
            tool_input=patch,
        )
    )
    async with storage_scope(database) as container:
        assert (
            await container.get(IWriterRepository).find_by_execution_id(scope.execution.uid) == ()
        )
    for value in (None, {}, {"command": 1}, "*** Add File: \nnot a header"):
        assert (
            client.decode(
                dict(
                    payload,
                    hook_event_name="PreToolUse",
                    tool_name="apply_patch",
                    tool_use_id="empty",
                    tool_input=value,
                )
            ).write_targets
            == ()
        )
    assert (
        client.decode(
            dict(
                payload,
                hook_event_name="PreToolUse",
                tool_name="Write",
                tool_use_id="empty",
                tool_input={"file_path": 1},
            )
        ).write_target
        == ""
    )


def test_host_environment_uses_real_values_and_preserves_claude_file(tmp_path, monkeypatch):
    service = PosixHostEnvironmentService()
    monkeypatch.setenv("CODEX_THREAD_ID", "real-codex")
    assert service.read().provider == "codex" and service.read().session == "real-codex"
    monkeypatch.delenv("CODEX_THREAD_ID")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "real-claude")
    assert service.read().session == "real-claude"
    environment = tmp_path / "environment"
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(environment))
    monkeypatch.setenv("SPAKKY_SQLALCHEMY__CONNECTION_STRING", "sqlite+aiosqlite:///")
    service.publish("claude", "real session; literal $value")
    content = environment.read_text()
    assert "'real session; literal $value'" in content
    environment.write_text("export USER_VALUE=keep\n" + content)
    service.publish("claude", "real session; literal $value")
    assert environment.read_text() == "export USER_VALUE=keep\n" + content
    monkeypatch.delenv("SPAKKY_SQLALCHEMY__CONNECTION_STRING")
    service.publish("claude", "next-real-session")
    assert "next-real-session" in environment.read_text()
    assert "USER_VALUE=keep" in environment.read_text()


async def test_registration_retries_only_rolled_back_conflicts(database, host):
    from neurath.application.ports.repositories.project import IProjectRepository
    from neurath.application.usecases.record_session import RecordSessionResult
    from neurath.application.usecases.register_session import (
        RegisterSessionCommand,
        RegisterSessionUseCase,
    )
    from neurath.infrastructure.services.directory_observer import GitDirectoryObserverService

    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    async with storage_scope(database) as container:
        project = await container.get(IProjectRepository).get(scope.session.project_id)
    result = RecordSessionResult(project=project, session=scope.session)
    recorder = type("Recorder", (), {})()
    recorder.run = AsyncMock(
        side_effect=[RevisionConflict("busy"), RevisionConflict("busy"), result]
    )
    command = RegisterSessionCommand(
        observation=GitDirectoryObserverService().observe(str(host[0])),
        provider="codex",
        host_session_id=scope.session.host_session_id,
    )
    registered = await RegisterSessionUseCase(recorder).run(command)
    assert registered.session.uid == scope.session.uid and recorder.run.await_count == 3
    recorder.run = AsyncMock(side_effect=RevisionConflict("still busy"))
    with pytest.raises(RevisionConflict):
        await RegisterSessionUseCase(recorder).run(command)
    assert recorder.run.await_count == 3


@pytest.mark.parametrize(
    "arguments",
    [
        ["collaboration", "send", "--recipient", "other", "--title", "title", "--body", "body"],
        ["collaboration", "read", "--message-id", "00000000-0000-0000-0000-000000000001"],
        ["collaboration", "observe", "--delegation-id", "00000000-0000-0000-0000-000000000001"],
        [
            "collaboration",
            "delegate",
            "--task-id",
            "00000000-0000-0000-0000-000000000001",
            "--scope",
            "scope",
            "--recipient",
            "other",
        ],
        [
            "task",
            "update",
            "--action",
            "accept",
            "--delegation-id",
            "00000000-0000-0000-0000-000000000001",
        ],
        [
            "task",
            "report",
            "--delegation-id",
            "00000000-0000-0000-0000-000000000001",
            "--summary",
            "result",
            "--reference",
            "actual",
        ],
        ["newsroom", "list"],
        ["newsroom", "subscribe"],
    ],
)
async def test_missing_observed_peer_does_not_invent_identity(
    database, host, monkeypatch, arguments
):
    original = ResolveSessionContextUseCase.run

    async def without_peer(self, query):
        return replace(await original(self, query), peer=None)

    monkeypatch.setattr(ResolveSessionContextUseCase, "run", without_peer)
    before = database.read_bytes()
    await invoke(database, arguments, succeeds=False)
    assert before == database.read_bytes()
    assert await invoke(database, ["context", "show", "--section", "collaboration"]) is None


def test_context_file_failure_leaves_no_partial_artifact(tmp_path, monkeypatch):
    from neurath.infrastructure.services.context_output import PosixContextOutputService

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        PosixContextOutputService().preserve("complete body")
    directory = Path(os.environ["XDG_DATA_HOME"]) / "neurath/context"
    assert list(directory.iterdir()) == []


async def test_abstract_boundaries_fail_instead_of_silently_succeeding():
    from neurath.application.ports.repositories.memory import IMemoryRepository
    from neurath.application.ports.repositories.request_source import IRequestSourceRepository
    from neurath.application.ports.services.context_output import IContextOutputService
    from neurath.application.ports.services.host_environment import IHostEnvironmentService
    from neurath.application.ports.services.installation import IInstallationService
    from neurath.application.ports.services.skill_catalog import ISkillCatalogService

    for operation in (
        IMemoryRepository.find_by_project_id_and_kind(None, uuid7(), "lesson"),
        IRequestSourceRepository.find_by_session_id(None, uuid7()),
        IInstallationService.initialize(None, None),
        IInstallationService.install(None, "codex", "/tmp", None),
    ):
        with pytest.raises(NotImplementedError):
            await operation
    for contract, name, arguments in (
        (IContextOutputService, "preserve", ("content",)),
        (IHostEnvironmentService, "read", ()),
        (IHostEnvironmentService, "publish", ("claude", "real")),
        (ISkillCatalogService, "load", ("qa", "/tmp")),
        (ISkillCatalogService, "list", ("/tmp",)),
    ):
        with pytest.raises(NotImplementedError):
            getattr(contract, name)(None, *arguments)


async def test_hook_conflict_retry_is_bounded_and_does_not_repeat_output():
    from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookResult
    from neurath.domain.enums.hook_action import HookAction
    from neurath.domain.enums.hook_event import HookEvent
    from neurath.transport.cli.hooks import HookCliController

    usecase = type("FixtureHook", (), {})()
    result = ReceiveHookResult(action=HookAction.ALLOW, message="")
    usecase.run = AsyncMock(
        side_effect=[RevisionConflict("busy"), RevisionConflict("busy"), result]
    )
    controller = HookCliController(usecase, None, None, None, None, None, None, None)
    command = ReceiveHookCommand(
        provider="codex",
        host_session_id="observed",
        working_directory="/tmp",
        event=HookEvent.SESSION_START,
    )
    assert await controller._receive(command) is result
    assert usecase.run.await_count == 3
    usecase.run = AsyncMock(side_effect=RevisionConflict("busy"))
    with pytest.raises(RevisionConflict):
        await controller._receive(command)
    assert usecase.run.await_count == 3


async def test_observe_wait_bound_and_missing_callback_peer_do_not_start_work(
    database, host, monkeypatch
):
    from neurath.application.usecases.observe_delegation import (
        ObserveDelegationCommand,
        ObserveDelegationUseCase,
    )

    for seconds in (-1, 301):
        with pytest.raises(ValueError):
            await ObserveDelegationUseCase(None, None).run(
                ObserveDelegationCommand(
                    delegation_id=uuid7(), peer_id=uuid7(), wait_seconds=seconds
                )
            )
    task = await create(database)
    original = ResolveSessionContextUseCase.run

    async def without_peer(self, query):
        return replace(await original(self, query), peer=None)

    monkeypatch.setattr(ResolveSessionContextUseCase, "run", without_peer)
    before = database.read_bytes()
    response = await host[1].handle(dict(host[2], prompt=f"NEURATH_MONITOR_TICK {task['id']} 1"))
    assert response["continue"] is False
    assert before == database.read_bytes()


async def test_wait_registration_requires_observed_execution_and_resume_handles_missing_peer(
    database, tmp_path
):
    from neurath.application.ports.repositories.peer import IPeerRepository
    from neurath.application.ports.repositories.task import ITaskRepository
    from neurath.application.usecases.resume_task import ResumeTaskCommand, ResumeTaskUseCase
    from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
    from neurath.application.usecases.wait_task import WaitTaskCommand, WaitTaskUseCase
    from neurath.domain.aggregates.execution import Execution
    from neurath.domain.enums.execution_pause_cause import ExecutionPauseCause
    from neurath.domain.errors import InvalidExecutionState
    from neurath.domain.values.external_wait import ExternalWait
    from neurath.domain.values.task_monitor import MonitorKind
    from tests.support.session_requests import register_session
    from tests.test_task_requests import create as create_task

    actor = await register_session(
        str(tmp_path), "codex", "fixture-no-execution", database_path=database
    )
    task = await create_task(database, actor)
    task = (
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
    condition = ExternalWait(
        target=str(tmp_path / "external.jsonl"),
        condition="done",
        resume_scope="verify",
        observation="running",
    )
    before = database.read_bytes()
    with pytest.raises(InvalidExecutionState, match="observed"):
        await run(
            WaitTaskUseCase,
            WaitTaskCommand(
                project_id=task.project_id,
                session_id=task.owner_session_id,
                task_id=task.uid,
                expected_revision=task.revision,
                condition=condition,
                monitor=MonitorKind.OUTPUT,
            ),
            database_path=database,
        )
    assert database.read_bytes() == before
    task = (
        await run(
            WaitTaskUseCase,
            WaitTaskCommand(
                project_id=task.project_id,
                session_id=task.owner_session_id,
                task_id=task.uid,
                expected_revision=task.revision,
                condition=condition,
            ),
            database_path=database,
        )
    ).task
    async with storage_scope(database) as scope:
        execution = Execution.create(actor.session.uid)
        execution.begin_turn("fixture-observed-turn")
        execution.pause("normal external wait", ExecutionPauseCause.WAITING)
        await scope.get(IExecutionRepository).save(execution)
    await run(
        ResumeTaskUseCase,
        ResumeTaskCommand(
            project_id=task.project_id,
            session_id=task.owner_session_id,
            task_id=task.uid,
            expected_revision=task.revision,
            resolution="external job completed",
        ),
        database_path=database,
    )
    async with storage_scope(database, write=False) as scope:
        assert (
            await scope.get(IExecutionRepository).get(execution.uid)
        ).status is ExecutionStatus.RUNNING
        assert (
            await scope.get(IPeerRepository).find_by_session_id_and_agent_id(actor.session.uid, "")
            is None
        )
        assert (await scope.get(ITaskRepository).get(task.uid)).status.value == "active"


async def test_native_writer_observation_preserves_active_claim_and_unknown_result(database, host):
    from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
    from neurath.application.usecases.recover_writer import (
        RecoverWriterCommand,
        RecoverWriterUseCase,
    )
    from neurath.domain.enums.hook_event import HookEvent

    directory, client, payload = host
    path = directory / "claimed.txt"
    await client.handle(
        dict(
            payload,
            hook_event_name="PreToolUse",
            turn_id="known",
            tool_name="Write",
            tool_use_id="write",
            tool_input={"file_path": str(path)},
        )
    )
    # 실제 새 턴을 먼저 관찰한 다음 같은 파일의 작성 호출을 연결한다.
    await client.handle(dict(payload, turn_id="known"))
    await client.handle(dict(payload, turn_id="known"))
    await client.handle(
        dict(
            payload,
            hook_event_name="PreToolUse",
            turn_id="known",
            tool_name="Write",
            tool_use_id="write",
            tool_input={"file_path": str(path)},
        )
    )
    async with storage_scope(database, write=False) as scope:
        lease = await scope.get(IWriterRepository).find_by_resource(str(path))
    await run(
        RecoverWriterUseCase,
        RecoverWriterCommand(writer_id=lease.uid, generation=lease.generation),
        database_path=database,
    )
    command = ReceiveHookCommand(
        provider="codex",
        host_session_id=payload["session_id"],
        working_directory=str(directory),
        event=HookEvent.POST_TOOL_USE,
        turn_id="known",
        tool_use_id="write",
        writes=True,
        write_target=str(path),
        write_targets=(str(path),),
        finished=False,
    )
    await run(ReceiveHookUseCase, command, database_path=database)
    async with storage_scope(database, write=False) as scope:
        assert (
            await scope.get(IWriterRepository).get(lease.uid)
        ).execution_id == lease.execution_id
    await client.handle(dict(payload, hook_event_name="SessionEnd"))
    # 같은 native_sync=False 외부 작성은 연결 종료만으로 회수하지 않는다.
    async with storage_scope(database) as scope:
        from neurath.domain.aggregates.writer import Writer

        execution = await scope.get(IExecutionRepository).get(lease.execution_id)
        managed = Writer.create(str(directory / "managed.txt"))
        managed.acquire(execution.uid, execution.turn_id, "managed")
        await scope.get(IWriterRepository).save(managed)
    await client.handle(
        dict(payload, prompt="Start new work without claiming old managed writes ended")
    )
    await client.handle(dict(payload, hook_event_name="SessionEnd"))
    async with storage_scope(database, write=False) as scope:
        assert (await scope.get(IWriterRepository).get(managed.uid)).execution_id == execution.uid


async def test_stop_bookkeeping_failure_yields_without_repeated_model_work(tmp_path):
    from tests.support.hook_cli import HookCliClient

    response = await HookCliClient("codex", tmp_path / "missing.db").handle(
        {
            "session_id": "fixture",
            "cwd": str(tmp_path),
            "turn_id": "observed",
            "hook_event_name": "Stop",
        }
    )
    assert (
        response["continue"] is False and "unfinished work is preserved" in response["stopReason"]
    )
