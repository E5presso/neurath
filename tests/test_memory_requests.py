"""실제 SQLite·CLI·호스트 입력으로 현재 맥락과 과거 자료의 경계를 검증한다."""

import asyncio
import json
from dataclasses import asdict
from uuid import UUID, uuid7

import pytest
from typer import Typer
from typer.testing import CliRunner

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.usecases.preview_session import PreviewSessionQuery, PreviewSessionUseCase
from neurath.application.usecases.read_memory import ReadMemoryQuery, ReadMemoryUseCase
from neurath.application.usecases.save_checkpoint import (
    SaveCheckpointCommand,
    SaveCheckpointUseCase,
)
from neurath.application.usecases.search_memory import SearchMemoryQuery, SearchMemoryUseCase
from neurath.application.usecases.update_enclave import (
    RemoveEnclaveFact,
    SetEnclaveFact,
    UpdateEnclaveCommand,
    UpdateEnclaveUseCase,
)
from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.errors import (
    ContextNotFound,
    RevisionConflict,
)
from neurath.domain.values.enclave_fact import EnclaveFact, EnclaveKind
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition
from neurath.infrastructure.database import sqlite_url
from neurath.transport.cli.memory import MemoryCliController
from tests.conftest import storage_scope
from tests.support.application import scanned_application
from tests.support.hook_cli import HookCliClient
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_task_requests import create, snapshot


def fact(value="current", key="rule", kind=EnclaveKind.FACT):
    return EnclaveFact(key=key, value=value, kind=kind, references=["source:original"])


@pytest.fixture
async def memory_actor(database, tmp_path):
    return await register_session(str(tmp_path), "codex", "memory-source", database_path=database)


async def update(database, actor, revision=0, changes=None, task_id=None):
    return await run(
        UpdateEnclaveUseCase,
        UpdateEnclaveCommand(
            project_id=actor.project.uid,
            session_id=actor.session.uid,
            task_id=task_id,
            expected_revision=revision,
            changes=[SetEnclaveFact(fact=fact())] if changes is None else changes,
        ),
        database_path=database,
    )


async def preview(database, actor):
    return await run(
        PreviewSessionUseCase,
        PreviewSessionQuery(project_id=actor.project.uid, session_id=actor.session.uid),
        database_path=database,
    )


async def native(database, actor, event, **extra):
    return await HookCliClient(actor.session.provider, database).handle(
        dict(
            session_id=actor.session.host_session_id,
            cwd=actor.session.working_directory,
            turn_id="turn",
            prompt_id="turn",
            hook_event_name=event,
            **extra,
        )
    )


async def cli(database, args, payload=None):
    async with scanned_application(sqlite_url(database, "rw")) as app:
        return await asyncio.to_thread(
            CliRunner().invoke,
            app.container.get(Typer),
            [str(value) for value in args],
            input=payload,
        )


async def test_update_memory_roundtrip_atomicity_and_scoped_search(database, memory_actor):
    actor = memory_actor
    task = await create(database, actor)
    enclave = await update(
        database,
        actor,
        changes=[SetEnclaveFact(fact=fact(), details="long details %_")],
        task_id=task.uid,
    )
    assert enclave.revision == 1
    memory_id = UUID(enclave.facts[0].references[-1].removeprefix("memory:"))
    memory = await run(
        ReadMemoryUseCase,
        ReadMemoryQuery(project_id=actor.project.uid, memory_id=memory_id),
        database_path=database,
    )
    assert memory.content == "long details %_" and memory.kind is MemoryKind.ARTIFACT
    assert list(
        await run(
            SearchMemoryUseCase,
            SearchMemoryQuery(
                project_id=actor.project.uid,
                text="%_",
                session_id=actor.session.uid,
                task_id=task.uid,
            ),
            database_path=database,
        )
    ) == [memory_id]
    assert not await run(
        SearchMemoryUseCase, SearchMemoryQuery(project_id=uuid7()), database_path=database
    )
    with pytest.raises(ContextNotFound):
        await run(
            ReadMemoryUseCase,
            ReadMemoryQuery(project_id=uuid7(), memory_id=memory_id),
            database_path=database,
        )
    for limit in (0, 101):
        with pytest.raises(ValueError):
            await run(
                SearchMemoryUseCase,
                SearchMemoryQuery(project_id=actor.project.uid, limit=limit),
                database_path=database,
            )
    before = snapshot(database)
    with pytest.raises(RevisionConflict):
        await update(database, actor, 0, task_id=task.uid)
    with pytest.raises(ContextNotFound):
        await update(
            database,
            actor,
            1,
            [
                SetEnclaveFact(fact=fact("changed"), details="must rollback"),
                RemoveEnclaveFact(key="missing"),
            ],
            task.uid,
        )
    assert snapshot(database) == before
    with pytest.raises(ValueError):
        await update(database, actor, 1, [], task.uid)
    corrected = await update(database, actor, 1, [SetEnclaveFact(fact=fact("corrected"))], task.uid)
    cleared = await update(
        database, actor, corrected.revision, [RemoveEnclaveFact(key="rule")], task.uid
    )
    assert cleared.facts == () and len(cleared.history) == 3
    assert (await preview(database, actor)).enclaves[0].history == cleared.history


async def test_checkpoint_is_report_and_preview_never_changes_ownership(database, memory_actor):
    actor = memory_actor
    task = await create(database, actor)
    before = await preview(database, actor)
    assert before.tasks[0].uid == task.uid and before.sources and not before.memory_ids
    report = await run(
        SaveCheckpointUseCase,
        SaveCheckpointCommand(
            project_id=actor.project.uid,
            session_id=actor.session.uid,
            content="remaining work",
            references=[str(task.definition.source_id)],
            task_id=task.uid,
        ),
        database_path=database,
    )
    current = snapshot(database)
    result = await preview(database, actor)
    assert result.tasks == before.tasks and result.memory_ids == (report.uid,)
    assert snapshot(database) == current
    await run(
        SaveCheckpointUseCase,
        SaveCheckpointCommand(
            project_id=actor.project.uid,
            session_id=actor.session.uid,
            content="general report",
            references=["source"],
        ),
        database_path=database,
    )
    peer = await register_session(
        actor.session.working_directory, "claude", "peer", database_path=database
    )
    with pytest.raises(ContextNotFound):
        await run(
            SaveCheckpointUseCase,
            SaveCheckpointCommand(
                project_id=actor.project.uid,
                session_id=peer.session.uid,
                content="wrong scope",
                references=["source"],
                task_id=task.uid,
            ),
            database_path=database,
        )
    with pytest.raises(ContextNotFound):
        await update(database, peer, task_id=task.uid)


@pytest.mark.parametrize("provider", ["codex", "claude"])
async def test_compact_restore_uses_latest_scope_and_never_revives_deleted_facts(
    database, tmp_path, provider
):
    actor = await register_session(str(tmp_path), provider, "source", database_path=database)
    assert await native(database, actor, "SessionStart", source="compact") == {}
    current = await update(
        database,
        actor,
        changes=[
            SetEnclaveFact(fact=fact("old")),
            SetEnclaveFact(fact=fact("assumption", "guess", EnclaveKind.ASSUMPTION)),
        ],
    )
    current = await update(
        database,
        actor,
        current.revision,
        [SetEnclaveFact(fact=fact("new")), RemoveEnclaveFact(key="guess")],
    )
    peer = await register_session(str(tmp_path), provider, "other", database_path=database)
    await update(database, peer, changes=[SetEnclaveFact(fact=fact("UNRELATED"))])
    task = await create(database, actor)
    await update(
        database, actor, task_id=task.uid, changes=[SetEnclaveFact(fact=fact("task detail"))]
    )
    async with storage_scope(database) as scope:
        run_ = WorkflowRun.create(
            actor.project.uid,
            actor.session.uid,
            task.uid,
            1,
            WorkflowDefinition(
                skill="build",
                version="1",
                phases=[
                    PhaseDefinition(
                        key="check",
                        purpose="check",
                        arguments=["true"],
                        directory=str(tmp_path),
                        target_revision="head",
                    )
                ],
                inputs=[],
            ),
        )
        await scope.get(IWorkflowRepository).save(run_)
    output = await native(database, actor, "SessionStart", source="compact")
    text = output["hookSpecificOutput"]["additionalContext"]
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "new" in text and "old" not in text and "guess" not in text and "UNRELATED" not in text
    assert "task detail" in text and "Workflow" in text and str(task.definition.source_id) in text
    assert await native(database, actor, "SessionStart", source="fork") == {}
    await update(database, actor, current.revision, [RemoveEnclaveFact(key="rule")])
    assert (
        "[fact] rule: new"
        not in (await native(database, actor, "SessionStart", source="resume"))[
            "hookSpecificOutput"
        ]["additionalContext"]
    )


async def test_restore_failure_does_not_claim_delivery_or_request_retry(
    database, memory_actor, monkeypatch
):
    actor = memory_actor
    await update(database, actor, changes=[SetEnclaveFact(fact=fact("x" * 9000))])
    result = await native(database, actor, "SessionStart", source="compact")
    assert result["continue"] is False and "hookSpecificOutput" not in result
    assert "limit" in result["stopReason"]
    from neurath.infrastructure.repositories.enclave import SQLAlchemyEnclaveRepository

    async def fail(*args):
        raise RuntimeError("memory unavailable")

    monkeypatch.setattr(SQLAlchemyEnclaveRepository, "find_by_session_id", fail)
    result = await native(database, actor, "SessionStart", source="compact")
    assert result["continue"] is False and "memory unavailable" in result["stopReason"]


async def test_memory_group_commands_use_real_registered_usecases(database, memory_actor):
    actor = memory_actor
    args = ["--project-id", actor.project.uid, "--session-id", actor.session.uid]
    help_ = await cli(database, ["--help"])
    assert help_.exit_code == 0 and "memory" in help_.stdout
    group_help = await cli(database, ["memory", "--help"])
    assert group_help.exit_code == 0
    for name in ("read", "update", "search", "checkpoint"):
        assert name in group_help.stdout
    result = await cli(
        database,
        [
            "memory",
            "update",
            *args,
            "--expected-revision",
            "0",
            "--changes",
            json.dumps(
                [{"op": "set", "key": "k", "value": "v", "kind": "fact", "references": ["source"]}]
            ),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["revision"] == 1
    report = await cli(
        database, ["memory", "checkpoint", *args, "--content", "remaining", "--reference", "source"]
    )
    assert report.exit_code == 0, report.output
    memory_id = json.loads(report.stdout)["id"]
    read = await cli(
        database, ["memory", "read", "--project-id", actor.project.uid, "--memory-id", memory_id]
    )
    assert json.loads(read.stdout)["content"] == "remaining"
    before_preview = snapshot(database)
    preview_ = await cli(database, ["session", "preview", *args])
    assert json.loads(preview_.stdout)["session_id"] == str(actor.session.uid)
    assert snapshot(database) == before_preview
    assert (await cli(database, ["memory", "read", *args])).exit_code == 2
    assert (await cli(database, ["memory", "resume", "--help"])).exit_code == 2
    search = await cli(database, ["memory", "search", *args, "--text", "remaining"])
    assert str(memory_id) in json.loads(search.stdout)["memory_ids"]
    assert (
        await cli(database, ["memory", "read", "--project-id", actor.project.uid])
    ).exit_code != 0
    await native(database, actor, "UserPromptSubmit")
    result = await cli(
        database,
        [
            "session",
            "resume",
            "--project-id",
            actor.project.uid,
            "--source-session-id",
            actor.session.uid,
            "--target-session-id",
            actor.session.uid,
            "--expected-revision",
            "1",
            "--turn-id",
            "turn",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["resumed"] is True


@pytest.mark.parametrize(
    "value",
    [
        "{}",
        "[1]",
        "[{}]",
        '[{"op":"x","key":"k"}]',
        '[{"op":"set","key":"k","value":"v","kind":"fact","references":[1]}]',
        '[{"op":"set","key":"k","value":"v","kind":"fact","references":["s"],"details":4}]',
    ],
)
def test_cli_change_decoder_rejects_malformed_input(value):
    with pytest.raises(ValueError):
        MemoryCliController._changes(value)


def test_explicit_remove_is_not_a_null_value():
    assert [
        asdict(change) for change in MemoryCliController._changes('[{"op":"remove","key":"k"}]')
    ] == [{"key": "k"}]


@pytest.mark.parametrize(
    "content,references", [("", ["s"]), ("x" * 1048577, ["s"]), ("body", []), ("body", [" "])]
)
def test_memory_size_and_source_validation(content, references):
    with pytest.raises(ValueError):
        Memory.create("p", "s", None, MemoryKind.ARTIFACT, content, references)


def test_enclave_limit_preserves_current_values():
    enclave = Enclave.create("p", "s")
    enclave.set(fact(), 1)
    with pytest.raises(ValueError):
        enclave.set(fact("한" * 6000), 1)
    assert enclave.facts[0].value == "current"


async def test_handoff_without_checkpoint_preserves_work_and_fences_original_session(
    database, memory_actor
):
    import sys
    from pathlib import Path

    from neurath.application.ports.repositories.execution import IExecutionRepository
    from neurath.application.ports.repositories.workflow import IWorkflowRepository
    from neurath.application.usecases.resume_execution import (
        ResumeExecutionCommand,
        ResumeExecutionUseCase,
    )
    from neurath.application.usecases.resume_session import (
        ResumeSessionCommand,
        ResumeSessionUseCase,
    )
    from neurath.domain.aggregates.workflow import WorkflowRun
    from neurath.domain.errors import InvalidExecutionState
    from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition

    source = memory_actor
    target = await register_session(
        source.session.working_directory, "claude", "target", database_path=database
    )
    task = await create(database, source)
    orphan = await create(database, source, title="no runner")
    await create(database, target, title="target work")
    enclave = await update(database, source)
    await native(database, source, "UserPromptSubmit")
    await native(database, target, "UserPromptSubmit")
    async with storage_scope(database) as scope:
        workflow = await scope.get(IWorkflowRepository).save(
            WorkflowRun.create(
                source.project.uid,
                source.session.uid,
                task.uid,
                1,
                WorkflowDefinition(
                    skill="continue",
                    version="1",
                    phases=[
                        PhaseDefinition(
                            key="build",
                            purpose="build",
                            arguments=[
                                sys.executable,
                                "-c",
                                "from pathlib import Path; Path('handoff-result.txt').write_text('resumed work')",
                            ],
                            directory=source.session.working_directory,
                            target_revision="head",
                        )
                    ],
                    inputs=[],
                ),
            )
        )
    command = ResumeSessionCommand(
        project_id=source.project.uid,
        source_session_id=source.session.uid,
        target_session_id=target.session.uid,
        expected_revision=1,
        turn_id="turn",
    )
    before = snapshot(database)
    with pytest.raises(InvalidExecutionState):
        await run(ResumeSessionUseCase, command, database_path=database)
    assert snapshot(database) == before
    await native(database, source, "SessionEnd", reason="closed")
    before = await preview(database, source)
    assert before.memory_ids == ()
    result = await run(ResumeSessionUseCase, command, database_path=database)
    assert result.uid == target.session.uid
    after = await preview(database, target)
    assert (
        after.tasks[0].uid == task.uid and after.tasks[0].definitions == before.tasks[0].definitions
    )
    assert (
        after.workflows[0].uid == workflow.uid
        and after.workflows[0].revisions == before.workflows[0].revisions
    )
    assert (
        after.enclaves[0].uid == enclave.uid
        and after.enclaves[0].history == before.enclaves[0].history
    )
    assert after.sources[0].uid == task.definition.source_id
    original = await preview(database, source)
    assert original.session.successor_id == target.session.uid and original.tasks == ()
    assert any(item.uid == orphan.uid for item in after.tasks)
    assert original.memory_ids
    assert (await native(database, source, "UserPromptSubmit"))["continue"] is False
    async with storage_scope(database, write=False) as scope:
        execution = await scope.get(IExecutionRepository).find_by_session_id_and_agent_id(
            source.session.uid, ""
        )
    with pytest.raises(InvalidExecutionState):
        await run(
            ResumeExecutionUseCase,
            ResumeExecutionCommand(execution_id=execution.uid, turn_id="turn"),
            database_path=database,
        )
    assert (
        "current"
        in (await native(database, target, "SessionStart", source="compact"))["hookSpecificOutput"][
            "additionalContext"
        ]
    )

    from neurath.application.usecases.execute_phase import ExecutePhaseCommand, ExecutePhaseUseCase
    from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
    from neurath.domain.values.phase_attempt import PhaseStatus

    current_task = next(item for item in after.tasks if item.uid == task.uid)
    await run(
        StartTaskUseCase,
        StartTaskCommand(
            project_id=source.project.uid,
            session_id=target.session.uid,
            task_id=task.uid,
            expected_revision=current_task.revision,
        ),
        database_path=database,
    )
    assert (
        await native(database, target, "PreToolUse", tool_name="Bash", tool_use_id="resumed-phase")
        == {}
    )
    await run(
        ExecutePhaseUseCase,
        ExecutePhaseCommand(
            project_id=source.project.uid,
            session_id=target.session.uid,
            run_id=workflow.uid,
            expected_revision=after.workflows[0].revision,
        ),
        database_path=database,
    )
    observed = await preview(database, target)
    assert observed.workflows[0].attempts[-1].status is PhaseStatus.SUCCEEDED
    assert (
        Path(target.session.working_directory) / "handoff-result.txt"
    ).read_text() == "resumed work"
    assert (
        await native(
            database,
            target,
            "PostToolUse",
            tool_name="Bash",
            tool_use_id="resumed-phase",
            tool_response={"stdout": "", "stderr": "", "interrupted": False},
        )
        == {}
    )


async def test_handoff_refuses_missing_native_execution_active_writer_and_target_context(
    database, memory_actor
):
    from neurath.application.usecases.resume_session import (
        ResumeSessionCommand,
        ResumeSessionUseCase,
    )
    from neurath.domain.errors import InvalidExecutionState

    source = memory_actor
    target = await register_session(
        source.session.working_directory, "claude", "target", database_path=database
    )
    command = ResumeSessionCommand(
        project_id=source.project.uid,
        source_session_id=source.session.uid,
        target_session_id=target.session.uid,
        expected_revision=1,
        turn_id="turn",
    )
    with pytest.raises(InvalidExecutionState, match="Target native"):
        await run(ResumeSessionUseCase, command, database_path=database)
    await native(database, target, "UserPromptSubmit")
    with pytest.raises(InvalidExecutionState, match="Source execution"):
        await run(ResumeSessionUseCase, command, database_path=database)
    await native(database, source, "UserPromptSubmit")
    await native(database, source, "PreToolUse", tool_name="Write", tool_use_id="write")
    await native(database, source, "SessionEnd")
    with pytest.raises(InvalidExecutionState, match="write termination"):
        await run(ResumeSessionUseCase, command, database_path=database)
    from neurath.application.ports.repositories.writer import IWriterRepository
    from neurath.domain.enums.liveness import Liveness

    async with storage_scope(database) as scope:
        writer = await scope.get(IWriterRepository).find_by_resource(
            source.session.working_directory
        )
        writer.release(writer.execution_id, writer.generation, Liveness.STOPPED)
        await scope.get(IWriterRepository).save(writer)
    await update(database, target)
    with pytest.raises(InvalidExecutionState, match="Target enclave"):
        await run(ResumeSessionUseCase, command, database_path=database)


def test_transfer_domain_guards_preserve_owner_and_running_attempt():
    from neurath.domain.aggregates.request_source import RequestSource, SourceKind
    from neurath.domain.aggregates.session import HostSession
    from neurath.domain.aggregates.task import Task
    from neurath.domain.aggregates.workflow import WorkflowRun
    from neurath.domain.aggregates.writer import Writer
    from neurath.domain.errors import InvalidExecutionState, InvalidWorkflowState
    from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition

    source = HostSession.create("project", "codex", "source", "/work")
    target = HostSession.create("project", "claude", "target", "/work")
    with pytest.raises(RevisionConflict):
        source.hand_off(target, 0)
    with pytest.raises(InvalidExecutionState):
        source.hand_off(source, 1)
    task = Task.create(
        "project",
        source.uid,
        RequestSource.create("project", source.uid, SourceKind.PROMPT, "do it"),
        "task",
        "result",
    )
    workflow = WorkflowRun.create(
        "project",
        source.uid,
        task.uid,
        1,
        WorkflowDefinition(
            skill="run",
            version="1",
            phases=[
                PhaseDefinition(
                    key="phase",
                    purpose="work",
                    arguments=["true"],
                    directory="/work",
                    target_revision="head",
                )
            ],
            inputs=[],
        ),
    )
    enclave = Enclave.create("project", source.uid)
    for aggregate in (task, workflow, enclave):
        with pytest.raises(ContextNotFound):
            aggregate.transfer("other", target.uid)
    workflow.begin()
    with pytest.raises(InvalidWorkflowState):
        workflow.require_transferable()
    Writer.create("/work").require_released()


async def test_new_abstract_repository_lookups_fail_explicitly():
    from neurath.application.ports.repositories.enclave import IEnclaveRepository
    from neurath.application.ports.repositories.execution import IExecutionRepository
    from neurath.application.ports.repositories.writer import IWriterRepository

    for call in (
        IExecutionRepository.find_by_session_id,
        IWriterRepository.find_by_execution_id,
        IEnclaveRepository.find_by_session_id,
    ):
        with pytest.raises(NotImplementedError):
            await call(None, "id")


async def test_cli_graph_paths_use_existing_tool_and_record_validated_reference(
    database, memory_actor, monkeypatch
):
    from neurath.infrastructure.services.graph import SubprocessGraphService

    monkeypatch.setattr(
        SubprocessGraphService, "query", lambda self, directory, question: "related document"
    )
    monkeypatch.setattr(
        SubprocessGraphService,
        "update",
        lambda self, directory: "file:///graph.json#sha256=observed",
    )
    actor = memory_actor
    args = ["--project-id", actor.project.uid, "--session-id", actor.session.uid]
    search = await cli(database, ["memory", "search", *args, "--graph-directory", "/graph"])
    assert search.exit_code == 0, search.output
    assert json.loads(search.stdout)["graph"] == "related document"
    result = await cli(
        database,
        [
            "memory",
            "checkpoint",
            *args,
            "--content",
            "checked graph",
            "--reference",
            "source",
            "--graph-directory",
            "/graph",
        ],
    )
    assert result.exit_code == 0, result.output
    memory = await run(
        ReadMemoryUseCase,
        ReadMemoryQuery(
            project_id=actor.project.uid, memory_id=UUID(json.loads(result.stdout)["id"])
        ),
        database_path=database,
    )
    assert memory.references[-1] == "file:///graph.json#sha256=observed"


async def test_completed_workflow_context_and_terminal_task_enclave_scope(database, memory_actor):
    from neurath.application.ports.repositories.workflow import IWorkflowRepository
    from neurath.domain.aggregates.workflow import WorkflowRun
    from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition

    actor = memory_actor
    task = await create(database, actor)
    async with storage_scope(database) as scope:
        workflow = WorkflowRun.create(
            actor.project.uid,
            actor.session.uid,
            task.uid,
            1,
            WorkflowDefinition(
                skill="optional",
                version="1",
                phases=[
                    PhaseDefinition(
                        key="skip",
                        purpose="optional",
                        arguments=["true"],
                        directory="/work",
                        target_revision="head",
                        skip_condition="not needed",
                    )
                ],
                inputs=[],
            ),
        )
        workflow = await scope.get(IWorkflowRepository).save(workflow)
        workflow.skip("not needed", "observed")
        await scope.get(IWorkflowRepository).save(workflow)
    response = await native(database, actor, "SessionStart", source="compact")
    assert "next: none" in response["hookSpecificOutput"]["additionalContext"]


async def test_stdin_reports_and_updates_and_stale_same_session_resume(
    database, memory_actor, monkeypatch
):
    import io
    import sys

    from neurath.application.usecases.resume_session import (
        ResumeSessionCommand,
        ResumeSessionUseCase,
    )

    monkeypatch.setattr(sys, "stdin", io.StringIO('[{"op":"remove","key":"k"}]'))
    assert [asdict(change) for change in MemoryCliController._changes("-")] == [{"key": "k"}]
    actor = memory_actor
    args = ["--project-id", actor.project.uid, "--session-id", actor.session.uid]
    result = await cli(
        database,
        ["memory", "checkpoint", *args, "--content", "-", "--reference", "source"],
        "full stdin report",
    )
    assert result.exit_code == 0, result.output
    memory = await run(
        ReadMemoryUseCase,
        ReadMemoryQuery(
            project_id=actor.project.uid, memory_id=UUID(json.loads(result.stdout)["id"])
        ),
        database_path=database,
    )
    assert memory.content == "full stdin report"
    await native(database, actor, "UserPromptSubmit")
    with pytest.raises(RevisionConflict):
        await run(
            ResumeSessionUseCase,
            ResumeSessionCommand(
                project_id=actor.project.uid,
                source_session_id=actor.session.uid,
                target_session_id=actor.session.uid,
                expected_revision=0,
                turn_id="turn",
            ),
            database_path=database,
        )


async def test_concurrent_enclave_edits_accept_only_one_observed_revision(database, memory_actor):
    actor = memory_actor
    initial = await update(database, actor)
    results = await asyncio.gather(
        update(database, actor, initial.revision, [SetEnclaveFact(fact=fact("first"))]),
        update(database, actor, initial.revision, [SetEnclaveFact(fact=fact("second"))]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, Enclave) for result in results) == 1
    assert sum(isinstance(result, RevisionConflict) for result in results) == 1
    current = (await preview(database, actor)).enclaves[0]
    assert current.revision == initial.revision + 1
    assert len(current.history) == 2
    assert current.facts[0].value in ("first", "second")
