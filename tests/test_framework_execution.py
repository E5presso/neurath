"""실제 주입·AOP·CLI 경계에서 작업 원자성과 값 보존을 검증한다."""

import asyncio
import json

import pytest
from spakky.plugins.sqlalchemy.persistency.session_manager import (
    AsyncSessionManager,
    SessionNotInitializedError,
)
from typer import Typer
from typer.testing import CliRunner

from neurath.application.usecases.get_session_context import (
    GetSessionContextQuery,
    GetSessionContextUseCase,
)
from neurath.application.usecases.register_session import (
    RegisterSessionCommand,
    RegisterSessionUseCase,
)
from neurath.domain.observations import DirectoryObservation
from neurath.domain.task_records import Outcome, SubmittedResult, TaskResult
from neurath.domain.workflow_records import (
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    WorkflowDefinition,
)
from tests.support.application import spakky_context
from tests.test_task_requests import snapshot


async def test_public_usecase_commits_and_rolls_back_without_caller_transaction(database):
    async with spakky_context(database) as scope:
        register = scope.get(RegisterSessionUseCase)
        result = await register.run(
            RegisterSessionCommand(DirectoryObservation("/registered"), "codex", "native")
        )
        with pytest.raises(SessionNotInitializedError):
            _ = scope.get(AsyncSessionManager).session
        before = snapshot(database)
        with pytest.raises(ValueError):
            await register.run(
                RegisterSessionCommand(DirectoryObservation("/must-rollback"), "", "invalid")
            )
        assert snapshot(database) == before
        restored = await scope.get(GetSessionContextUseCase).run(
            GetSessionContextQuery(result.project.uid, result.session.uid)
        )
        assert restored.session == result.session


async def test_same_application_keeps_concurrent_usecase_requests_separate(database):
    async with spakky_context(database) as scope:
        register = scope.get(RegisterSessionUseCase)

        async def request(name):
            scope.clear_context()
            result = await register.run(
                RegisterSessionCommand(DirectoryObservation("/" + name), "codex", name)
            )
            with pytest.raises(SessionNotInitializedError):
                _ = scope.get(AsyncSessionManager).session
            return result

        first, second = await asyncio.gather(request("first"), request("second"))
        assert first.project.uid != second.project.uid
        assert first.session.uid != second.session.uid
        assert first.session.host_session_id == "first"
        assert second.session.host_session_id == "second"


async def test_repeated_cli_commands_do_not_register_more_groups_or_retain_db_session(
    database, tmp_path
):
    payload = json.dumps(
        dict(
            session_id="repeat",
            turn_id="one",
            cwd=str(tmp_path),
            hook_event_name="UserPromptSubmit",
        )
    )
    async with spakky_context(database) as scope:
        cli = scope.get(Typer)
        initial_groups = len(cli.registered_groups)
        for _ in range(3):
            result = await asyncio.to_thread(
                CliRunner().invoke, cli, ["hook", "handle", "--provider", "codex"], input=payload
            )
            assert result.exit_code == 0
            assert json.loads(result.stdout) == {}
            assert len(cli.registered_groups) == initial_groups
        with pytest.raises(SessionNotInitializedError):
            _ = scope.get(AsyncSessionManager).session


def test_value_object_fields_cannot_be_reassigned():
    from dataclasses import FrozenInstanceError

    submission = SubmittedResult(summary="candidate", references=["evidence"])
    with pytest.raises(FrozenInstanceError):
        submission.references = ["replacement"]
    result = TaskResult(outcome=Outcome.SUCCEEDED, summary="verified", observations=["evidence"])
    with pytest.raises(FrozenInstanceError):
        result.observations = []


def test_workflow_value_objects_accept_sequence_inputs_without_rewriting_them():
    from dataclasses import FrozenInstanceError

    arguments = ["program"]
    checks = ["exit:0"]
    phase = PhaseDefinition(
        key="check",
        purpose="check",
        arguments=arguments,
        directory="/tmp",
        target_revision="head",
        checks=checks,
    )
    definition = WorkflowDefinition(skill="check", version="1", phases=[phase], inputs=[])
    result = PhaseResult(
        status=PhaseStatus.SUCCEEDED,
        target_revision="head",
        summary="verified",
        evidence=["actual:output"],
        checks=checks,
    )
    assert phase.arguments is arguments
    assert phase.checks is checks
    assert definition.phases == [phase]
    assert result.checks is checks
    with pytest.raises(FrozenInstanceError):
        phase.arguments = ["replacement"]
