"""외부 관찰과 저장 사이의 원장 변경·명시 재시도·회고 철회 경계를 검증한다."""

from dataclasses import replace
from uuid import UUID, uuid7

import pytest

from neurath.application.usecases.get_evaluation import GetEvaluationQuery, GetEvaluationUseCase
from neurath.application.usecases.record_evaluation import (
    RecordEvaluationCommand,
    RecordEvaluationUseCase,
)
from neurath.application.usecases.record_evaluation_binding import (
    RecordEvaluationBindingCommand,
    RecordEvaluationBindingUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.save_lesson import SaveLessonCommand, SaveLessonUseCase
from neurath.domain.errors import InvalidWorkflowState
from tests.support.requests import run
from tests.test_host_flow import delegate_review, finish_review, invoke, prepare_review
from tests.test_host_flow import host as host


@pytest.mark.parametrize("operation", ["binding", "consumption", "lesson"])
@pytest.mark.parametrize("change", ["definition", "original_source"])
async def test_external_observation_cannot_save_against_changed_ledger(
    database, host, operation, change
):
    task, flow, artifact = await prepare_review(database, host)
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    snapshot = await run(
        GetEvaluationUseCase,
        GetEvaluationQuery(
            project_id=scope.session.project_id,
            session_id=scope.session.uid,
            run_id=UUID(flow["id"]),
            phase_key="result-review",
        ),
        database_path=database,
    )
    if change == "definition":
        from neurath.application.usecases.revise_workflow import (
            ReviseWorkflowCommand,
            ReviseWorkflowUseCase,
        )

        current = snapshot.run
        phases = tuple(
            replace(phase, purpose=phase.purpose + " clarified")
            if phase.key == "result-review"
            else phase
            for phase in current.definition.phases
        )
        await run(
            ReviseWorkflowUseCase,
            ReviseWorkflowCommand(
                project_id=current.project_id,
                session_id=current.session_id,
                run_id=current.uid,
                expected_revision=current.revision,
                definition=replace(current.definition, phases=phases),
                reason="Method clarification during file observation",
            ),
            database_path=database,
        )
    else:
        await host[1].handle(dict(host[2], prompt="Also preserve the second requested output"))
    arguments = dict(
        project_id=scope.session.project_id,
        session_id=scope.session.uid,
        run_id=snapshot.run.uid,
        phase_key="result-review",
        observed=snapshot.context,
        run_version=snapshot.run.version,
    )
    if operation == "binding":
        usecase, command = (
            RecordEvaluationBindingUseCase,
            RecordEvaluationBindingCommand(**arguments, delegation_id=uuid7()),
        )
    elif operation == "consumption":
        usecase, command = (
            RecordEvaluationUseCase,
            RecordEvaluationCommand(
                **arguments,
                accepted=True,
                rationale="observed old candidate",
                references=(str(artifact),),
            ),
        )
    else:
        usecase, command = (
            SaveLessonUseCase,
            SaveLessonCommand(**arguments, content="old lesson", references=(str(artifact),)),
        )
    before = database.read_bytes()
    with pytest.raises(InvalidWorkflowState, match="metadata changed"):
        await run(usecase, command, database_path=database)
    assert database.read_bytes() == before


async def test_same_candidate_explicit_retry_is_distinct_and_retry_is_idempotent(
    database, host, monkeypatch
):
    task, flow, artifact = await prepare_review(database, host)
    first = await delegate_review(database, task, artifact)
    arguments = [
        "collaboration",
        "delegate",
        "--task-id",
        task["id"],
        "--role",
        "reviewer",
        "--scope",
        "Compare original request and actual output",
        "--recipient",
        "native-reviewer",
        "--artifact",
        str(artifact),
        "--verification",
        str(artifact),
        "--retry-of",
        first["id"],
    ]
    await invoke(database, arguments, succeeds=False)
    await finish_review(database, first, artifact, monkeypatch)
    second = await invoke(database, arguments)
    assert second["id"] != first["id"]
    assert (await invoke(database, arguments))["id"] == second["id"]
    previous = await invoke(database, ["collaboration", "observe", "--delegation-id", first["id"]])
    assert previous["report"] and previous["status"] == "completed"


async def test_result_storage_rejects_workflow_changed_after_observation(database, host):
    from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
    from neurath.application.usecases.record_task_result import (
        RecordTaskResultCommand,
        RecordTaskResultUseCase,
    )
    from neurath.domain.values.task_attempt import Outcome, TaskResult

    task, flow, artifact = await prepare_review(database, host)
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    stored = (
        await run(
            GetTaskUseCase,
            GetTaskQuery(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                task_id=UUID(task["id"]),
            ),
            database_path=database,
        )
    ).task
    before = database.read_bytes()
    with pytest.raises(InvalidWorkflowState, match="Workflow changed"):
        await run(
            RecordTaskResultUseCase,
            RecordTaskResultCommand(
                project_id=stored.project_id,
                session_id=stored.owner_session_id,
                task_id=stored.uid,
                expected_revision=stored.revision,
                attempt_number=stored.current_attempt_number,
                result=TaskResult(
                    outcome=Outcome.SUCCEEDED,
                    summary="actual result",
                    observations=(str(artifact),),
                ),
                workflow_version=uuid7(),
                evaluations=(),
            ),
            database_path=database,
        )
    assert database.read_bytes() == before


async def test_retry_history_cannot_be_downgraded_to_single_assignment_constraint(
    database, host, monkeypatch
):
    from alembic import command as migration

    from neurath.infrastructure.database import create_database_engine
    from tests.test_task_migrations import migration_config

    task, flow, artifact = await prepare_review(database, host)
    first = await delegate_review(database, task, artifact)
    await finish_review(database, first, artifact, monkeypatch)
    await invoke(
        database,
        [
            "collaboration",
            "delegate",
            "--task-id",
            task["id"],
            "--scope",
            "review same candidate again",
            "--role",
            "reviewer",
            "--recipient",
            "native-reviewer",
            "--artifact",
            str(artifact),
            "--verification",
            str(artifact),
            "--retry-of",
            first["id"],
        ],
    )
    before = database.read_bytes()
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="history"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: migration.downgrade(migration_config(sync), "core_0013")
                )
    finally:
        await engine.dispose()
    assert database.read_bytes() == before


async def test_withdrawing_unassigned_reflection_preserves_original_phase_attempts(database, host):
    from neurath.application.usecases.get_workflow import GetWorkflowQuery, GetWorkflowUseCase
    from neurath.application.usecases.prepare_phase import PreparePhaseCommand, PreparePhaseUseCase

    task, flow, artifact = await prepare_review(database, host, reflection=True)
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    current = (
        await run(
            GetWorkflowUseCase,
            GetWorkflowQuery(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                run_id=UUID(flow["id"]),
            ),
            database_path=database,
        )
    ).run
    await run(
        PreparePhaseUseCase,
        PreparePhaseCommand(
            project_id=current.project_id,
            session_id=current.session_id,
            run_id=current.uid,
            expected_revision=current.revision,
        ),
        database_path=database,
    )
    declined = await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reflection",
            "declined",
            "--reason",
            "User withdrew before assignment",
        ],
    )
    assert declined["steps_complete"]
    again = await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reflection",
            "declined",
            "--reason",
            "Same withdrawal",
        ],
    )
    assert again["steps_complete"]


async def test_another_reviewer_can_evaluate_same_candidate(database, host):
    task, flow, artifact = await prepare_review(database, host)
    first = await delegate_review(database, task, artifact)
    await host[1].handle(dict(host[2], hook_event_name="SubagentStart", agent_id="second-reviewer"))
    second = await invoke(
        database,
        [
            "collaboration",
            "delegate",
            "--task-id",
            task["id"],
            "--scope",
            "Compare original request and actual output",
            "--role",
            "reviewer",
            "--recipient",
            "second-reviewer",
            "--artifact",
            str(artifact),
            "--verification",
            str(artifact),
        ],
    )
    assert second["id"] != first["id"]
    original = await invoke(database, ["collaboration", "observe", "--delegation-id", first["id"]])
    assert original["id"] == first["id"] and original["report"] is None


async def test_completed_workflow_rejects_implicit_new_phase_report(database, host):
    from neurath.application.usecases.report_phase import ReportPhaseCommand, ReportPhaseUseCase
    from neurath.domain.values.phase_attempt import PhaseResult, PhaseStatus

    task, flow, artifact = await prepare_review(database, host)
    definition = [{"key": "only-check", "purpose": "Final verified method"}]
    import json

    await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reason",
            "Explicit method revision",
            "--definition",
            json.dumps(definition),
        ],
    )
    await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Actual final check",
            "--reference",
            str(artifact),
            "--check",
            "done",
        ],
    )
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    with pytest.raises(InvalidWorkflowState, match="already complete"):
        await run(
            ReportPhaseUseCase,
            ReportPhaseCommand(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                run_id=UUID(flow["id"]),
                attempt_number=None,
                result=PhaseResult(
                    status=PhaseStatus.SUCCEEDED,
                    target_revision="current",
                    summary="duplicate report",
                    evidence=(str(artifact),),
                    checks=("done",),
                ),
            ),
            database_path=database,
        )
