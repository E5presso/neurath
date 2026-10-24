"""원문·전체 TODO의 독립 평가와 선택 회고·교훈을 실제 저장 경계로 검증한다."""

from dataclasses import replace
from uuid import uuid7

import pytest

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.usecases.choose_reflection import (
    ChooseReflectionCommand,
    ChooseReflectionUseCase,
)
from neurath.application.usecases.consume_evaluation import (
    ConsumeEvaluationCommand,
    ConsumeEvaluationUseCase,
)
from neurath.application.usecases.create_lesson import CreateLessonCommand, CreateLessonUseCase
from neurath.application.usecases.get_evaluation import GetEvaluationQuery, GetEvaluationUseCase
from neurath.application.usecases.observe_lesson import ObserveLessonCommand, ObserveLessonUseCase
from neurath.application.usecases.report_result import ReportResultCommand, ReportResultUseCase
from neurath.application.usecases.request_evaluation import (
    RequestEvaluationCommand,
    RequestEvaluationUseCase,
)
from neurath.application.usecases.start_workflow import StartWorkflowCommand, StartWorkflowUseCase
from neurath.domain.aggregates.memory import MemoryKind
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.enums.delegation_route import DelegationRoute
from neurath.domain.enums.reflection_choice import ReflectionChoice
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import InvalidTaskState, InvalidWorkflowState
from neurath.domain.values.delegation_report import DelegationReport
from neurath.domain.values.evaluation_target import EvaluationKind, EvaluationTarget
from neurath.domain.values.lesson_observation import LessonObservation, LessonState
from neurath.domain.values.phase_attempt import PhaseStatus
from neurath.domain.values.task_attempt import Outcome, TaskResult
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.test_collaboration import call
from tests.test_collaboration import collaboration as collaboration
from tests.test_provider import provider_environment as provider_environment


@pytest.fixture
async def evaluation(database, collaboration, tmp_path):
    actor, sender, receiver, recipient, task = collaboration
    phase = PhaseDefinition(
        key="review",
        purpose="원문 요구와 전체 결과 대조",
        arguments=("review",),
        directory=str(tmp_path),
        target_revision="head:one",
        checks=("intent",),
        evaluation=EvaluationTarget(
            kind=EvaluationKind.RESULT,
            task_ids=(task.uid,),
            artifacts=("artifact:report",),
            verification=("test:passed",),
        ),
    )
    flow = (
        await run(
            StartWorkflowUseCase,
            StartWorkflowCommand(
                project_id=actor.project.uid,
                session_id=actor.session.uid,
                task_id=task.uid,
                expected_task_revision=task.revision,
                definition=WorkflowDefinition(
                    skill="finish-session", version="1", phases=(phase,), inputs=()
                ),
            ),
            database_path=database,
        )
    ).run
    return collaboration, flow


def scope(flow):
    return dict(project_id=flow.project_id, session_id=flow.session_id, run_id=flow.uid)


async def request(database, context, flow):
    return await run(
        RequestEvaluationUseCase,
        RequestEvaluationCommand(
            **scope(flow),
            phase_key="review",
            sender_id=context[1].uid,
            recipient_id=context[3].uid,
            route=DelegationRoute.PEER,
        ),
        database_path=database,
    )


async def report(database, context, assignment, *, remaining=None):
    await call(database, "accept_delegation", "AcceptDelegation", assignment.uid, context[3].uid)
    return await call(
        database,
        "report_delegation",
        "ReportDelegation",
        assignment.uid,
        context[3].uid,
        DelegationReport(
            summary="원문과 대조한 실제 평가 보고",
            references=("artifact:report",),
            remaining_work=remaining,
        ),
    )


async def consume(database, flow, *, accepted=True):
    return await run(
        ConsumeEvaluationUseCase,
        ConsumeEvaluationCommand(
            **scope(flow),
            phase_key="review",
            accepted=accepted,
            rationale="원문과 실제 검사에 대조한 판단",
            references=("source:original",),
        ),
        database_path=database,
    )


async def test_result_evaluation_reuses_report_and_only_owner_completes_task(database, evaluation):
    context, flow = evaluation
    before = await run(
        GetEvaluationUseCase,
        GetEvaluationQuery(**scope(flow), phase_key="review"),
        database_path=database,
    )
    assert "Full current TODO" in before.context.scope
    assert "Source " in before.context.scope and "out-of-scope" in before.context.scope
    assignment = await request(database, context, flow)
    assert assignment.role is DelegationRole.REVIEWER and assignment.candidate
    repeated = await request(database, context, flow)
    assert repeated.uid == assignment.uid
    with pytest.raises(InvalidTaskState, match="completed report"):
        await consume(database, flow)
    await report(database, context, assignment)
    async with storage_scope(database, write=False) as container:
        active = await container.get(ITaskRepository).get(context[4].uid)
    assert active.status is TaskStatus.WAITING
    report_command = ReportResultCommand(
        project_id=flow.project_id,
        session_id=flow.session_id,
        task_id=active.uid,
        expected_revision=active.revision,
        attempt_number=active.current_attempt_number,
        result=TaskResult(
            outcome=Outcome.SUCCEEDED, summary="완료", observations=("artifact:report",)
        ),
    )
    with pytest.raises(InvalidWorkflowState):
        await run(ReportResultUseCase, report_command, database_path=database)
    consumed = await consume(database, flow)
    assert consumed.current is None
    assert (await consume(database, flow)).attempts == consumed.attempts
    assert (await request(database, context, flow)).uid == assignment.uid
    async with storage_scope(database, write=False) as container:
        active = await container.get(ITaskRepository).get(context[4].uid)
    completed = await run(
        ReportResultUseCase,
        replace(report_command, expected_revision=active.revision),
        database_path=database,
    )
    assert completed.task.status is TaskStatus.SUCCEEDED


async def test_failed_review_retains_same_todo_and_requires_changed_candidate(database, evaluation):
    context, flow = evaluation
    assignment = await request(database, context, flow)
    await report(database, context, assignment, remaining="원문에 있는 부록 누락")
    failed = await consume(database, flow, accepted=False)
    assert failed.current.key == "review" and failed.attempts[-1].status is PhaseStatus.FAILED
    assert (await request(database, context, flow)).uid == assignment.uid
    with pytest.raises(InvalidWorkflowState, match="overwritten"):
        await consume(database, flow)
    async with storage_scope(database) as container:
        changed = await container.get(IWorkflowRepository).get(flow.uid)
        changed.revise(
            replace(
                changed.definition,
                phases=(replace(changed.definition.phases[0], target_revision="head:two"),),
            ),
            changed.revisions[-1].task_definition_number,
            "누락 보완 결과",
        )
        await container.get(IWorkflowRepository).save(changed)
    new = await request(database, context, flow)
    assert new.uid != assignment.uid
    await report(database, context, new)
    assert (await consume(database, flow)).current is None


async def test_wrong_finding_can_be_rejected_with_original_evidence(database, evaluation):
    context, flow = evaluation
    assignment = await request(database, context, flow)
    await report(database, context, assignment, remaining="조사 요청인데 배포하라는 잘못된 지적")
    consumed = await consume(database, flow)
    assert consumed.attempts[-1].result.summary == "원문과 실제 검사에 대조한 판단"
    async with storage_scope(database, write=False) as container:
        tasks = await container.get(ITaskRepository).find_by_project_id(flow.project_id)
    assert len(tasks) == 1 and tasks[0].status is TaskStatus.ACTIVE


@pytest.mark.parametrize(
    "choice",
    [
        ReflectionChoice.UNASKED,
        ReflectionChoice.OFFERED,
        ReflectionChoice.DECLINED,
        ReflectionChoice.UNANSWERED,
    ],
)
async def test_optional_reflection_does_not_block_original_completion(database, evaluation, choice):
    context, flow = evaluation
    async with storage_scope(database) as container:
        run_flow = await container.get(IWorkflowRepository).get(flow.uid)
        phase = replace(
            run_flow.definition.phases[0],
            evaluation=replace(
                run_flow.definition.phases[0].evaluation, kind=EvaluationKind.REFLECTION
            ),
        )
        run_flow.revise(replace(run_flow.definition, phases=(phase,)), 1, "선택 회고 분기")
        await container.get(IWorkflowRepository).save(run_flow)
    if choice is not ReflectionChoice.UNASKED:
        run_flow = await run(
            ChooseReflectionUseCase,
            ChooseReflectionCommand(
                **scope(flow), choice=choice, reason="사용자 선택 또는 관찰 문제"
            ),
            database_path=database,
        )
    assert run_flow.current is None
    run_flow.require_complete(1)
    with pytest.raises(InvalidWorkflowState):
        await request(database, context, flow)
    async with storage_scope(database, write=False) as container:
        active = await container.get(ITaskRepository).get(context[4].uid)
    completed = await run(
        ReportResultUseCase,
        ReportResultCommand(
            project_id=flow.project_id,
            session_id=flow.session_id,
            task_id=active.uid,
            expected_revision=active.revision,
            attempt_number=active.current_attempt_number,
            result=TaskResult(
                outcome=Outcome.SUCCEEDED,
                summary="선택 회고 미실행으로 원 작업 완료",
                observations=("actual:result",),
            ),
        ),
        database_path=database,
    )
    assert completed.task.status is TaskStatus.SUCCEEDED


async def test_requested_reflection_lesson_validation_application_defer_and_withdrawal(
    database, evaluation, tmp_path
):
    context, flow = evaluation
    async with storage_scope(database) as container:
        current = await container.get(IWorkflowRepository).get(flow.uid)
        phase = replace(
            current.definition.phases[0],
            evaluation=replace(
                current.definition.phases[0].evaluation, kind=EvaluationKind.REFLECTION
            ),
        )
        current.revise(replace(current.definition, phases=(phase,)), 1, "문제 회고")
        await container.get(IWorkflowRepository).save(current)
    lesson_command = CreateLessonCommand(
        **scope(flow),
        phase_key="review",
        content="문제 원인과 관련 범위의 개선 후보",
        references=("source:user-reflection",),
    )
    with pytest.raises(ValueError):
        await run(CreateLessonUseCase, lesson_command, database_path=database)
    await run(
        ChooseReflectionUseCase,
        ChooseReflectionCommand(
            **scope(flow),
            choice=ReflectionChoice.REQUESTED,
            reason="사용자: 이번 실패 원인을 회고하고 개선해 주세요",
        ),
        database_path=database,
    )
    assignment = await request(database, context, flow)
    await report(database, context, assignment)
    await consume(database, flow)
    lesson = await run(CreateLessonUseCase, lesson_command, database_path=database)
    assert lesson.kind is MemoryKind.LESSON and lesson.lessons[-1].state is LessonState.PROPOSED
    for state in (
        LessonState.DEFERRED,
        LessonState.VALIDATED,
        LessonState.APPLIED,
        LessonState.WITHDRAWN,
    ):
        lesson = await run(
            ObserveLessonUseCase,
            ObserveLessonCommand(
                project_id=flow.project_id,
                session_id=context[2].session.uid,
                memory_id=lesson.uid,
                observation=LessonObservation(
                    state=state,
                    reason="관련 수행에서 실제 관찰한 효과",
                    references=("test:failure", "test:normal"),
                    failure_case="원 실패 개선 확인",
                    normal_case="정상 대조 유지",
                    effective=False if state is LessonState.WITHDRAWN else None,
                ),
            ),
            database_path=database,
        )
    assert [item.state for item in lesson.lessons] == [
        LessonState.PROPOSED,
        LessonState.DEFERRED,
        LessonState.VALIDATED,
        LessonState.APPLIED,
        LessonState.WITHDRAWN,
    ]


async def test_provider_fixture_receives_originals_todo_and_actual_candidate(
    database, evaluation, provider_environment
):
    from neurath.application.usecases.recover_provider import (
        RecoverProviderCommand,
        RecoverProviderUseCase,
    )
    from neurath.domain.enums.provider_status import ProviderStatus
    from neurath.infrastructure.services.provider import SubprocessProviderService
    from tests.test_provider import executable, finished

    context, flow = evaluation
    binpath, plan = provider_environment
    executable(
        binpath,
        "codex",
        """import json,sys
prompt=sys.stdin.read()
print(json.dumps({"type":"thread.started","thread_id":"independent-review-session"}),flush=True)
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":prompt}}),flush=True)
print(json.dumps({"type":"turn.completed"}),flush=True)
""",
    )
    command = RequestEvaluationCommand(
        **scope(flow),
        phase_key="review",
        sender_id=context[1].uid,
        route=DelegationRoute.PROVIDER,
        plan=replace(plan, parent_session_id=flow.session_id),
    )
    assignment = await run(RequestEvaluationUseCase, command, database_path=database)
    observed = finished(SubprocessProviderService(), assignment.uid)
    assert observed.status is ProviderStatus.COMPLETED
    await run(
        RecoverProviderUseCase,
        RecoverProviderCommand(delegation_id=assignment.uid, peer_id=context[1].uid),
        database_path=database,
    )
    actual = await run(RequestEvaluationUseCase, command, database_path=database)
    assert actual.uid == assignment.uid and actual.provider_output
    assert (
        "Full current TODO" in actual.provider_output
        and "original requirement text" in actual.provider_output
    )
    assert "artifact:report" in actual.provider_output and "test:passed" in actual.provider_output
    assert (await consume(database, flow)).current is None


async def test_related_request_change_invalidates_only_relevant_candidate(database, evaluation):
    from neurath.application.usecases.correct_task import CorrectTaskCommand, CorrectTaskUseCase
    from neurath.domain.aggregates.request_source import SourceKind
    from tests.test_task_requests import create, record

    context, flow = evaluation
    unrelated = await create(database, context[0], title="무관한 별도 작업")
    assignment = await request(database, context, flow)
    await report(database, context, assignment)
    before = await consume(database, flow)
    correction = await record(
        database, context[0], SourceKind.CORRECTION, corrects_id=unrelated.definition.source_id
    )
    await run(
        CorrectTaskUseCase,
        CorrectTaskCommand(
            project_id=flow.project_id,
            session_id=flow.session_id,
            task_id=unrelated.uid,
            expected_revision=unrelated.revision,
            source_id=correction.uid,
            title="무관한 정정",
        ),
        database_path=database,
    )
    assert (await request(database, context, flow)).uid == assignment.uid
    assert (await consume(database, flow)).attempts == before.attempts


async def test_candidate_change_while_waiting_preserves_old_assignment_and_starts_new_once(
    database, evaluation
):
    context, flow = evaluation
    first = await request(database, context, flow)
    async with storage_scope(database) as container:
        current = await container.get(IWorkflowRepository).get(flow.uid)
        current.revise(
            replace(
                current.definition,
                phases=(replace(current.definition.phases[0], target_revision="changed-head"),),
            ),
            1,
            "실제 산출물 변경",
        )
        await container.get(IWorkflowRepository).save(current)
    second = await request(database, context, flow)
    assert second.uid != first.uid
    assert (await request(database, context, flow)).uid == second.uid
    await report(database, context, first)
    with pytest.raises(InvalidTaskState):
        await consume(database, flow)
    await report(database, context, second)
    assert (await consume(database, flow)).current is None


async def test_evaluation_migration_preserves_old_work_and_refuses_loss(database, evaluation):
    from alembic import command

    from neurath.infrastructure.database import create_database_engine
    from tests.test_task_migrations import migration_config
    from tests.test_task_requests import snapshot

    context, flow = evaluation
    before = snapshot(database)
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="preserved"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda c: command.downgrade(migration_config(c), "core_0012")
                )
    finally:
        await engine.dispose()
    assert snapshot(database) == before


async def test_empty_evaluation_migration_roundtrips(database):
    from alembic import command
    from sqlalchemy import text

    from neurath.infrastructure.database import create_database_engine, initialize_database
    from tests.test_task_migrations import migration_config

    engine = create_database_engine(database, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: command.downgrade(migration_config(c), "core_0012"))
            assert (
                await connection.scalar(text("SELECT version_num FROM core_schema_revision"))
                == "core_0012"
            )
        await initialize_database(database)
    finally:
        await engine.dispose()


async def test_actual_artifact_change_rejects_old_report_and_refreshes_same_phase(
    database, evaluation, tmp_path
):
    context, flow = evaluation
    artifact = tmp_path / "result.txt"
    artifact.write_text("original actual result")
    async with storage_scope(database) as container:
        current = await container.get(IWorkflowRepository).get(flow.uid)
        phase = current.definition.phases[0]
        current.revise(
            replace(
                current.definition,
                phases=(
                    replace(
                        phase, evaluation=replace(phase.evaluation, artifacts=(str(artifact),))
                    ),
                ),
            ),
            1,
            "실제 산출물 연결",
        )
        await container.get(IWorkflowRepository).save(current)
    first = await request(database, context, flow)
    await report(database, context, first)
    artifact.write_text("changed actual result")
    with pytest.raises(InvalidWorkflowState, match="candidate"):
        await consume(database, flow)
    second = await request(database, context, flow)
    assert second.uid != first.uid
    await report(database, context, second)
    await consume(database, flow)
    artifact.write_text("third actual result")
    async with storage_scope(database, write=False) as container:
        active = await container.get(ITaskRepository).get(context[4].uid)
    with pytest.raises(InvalidWorkflowState, match="changed after evaluation"):
        await run(
            ReportResultUseCase,
            ReportResultCommand(
                project_id=flow.project_id,
                session_id=flow.session_id,
                task_id=active.uid,
                expected_revision=active.revision,
                attempt_number=active.current_attempt_number,
                result=TaskResult(
                    outcome=Outcome.SUCCEEDED, summary="완료 주장", observations=("artifact",)
                ),
            ),
            database_path=database,
        )
    third = await request(database, context, flow)
    assert third.uid not in (first.uid, second.uid)


async def test_evaluation_query_missing_scope_and_unassigned_consume_are_read_only(
    database, evaluation
):
    from neurath.application.ports.services.evaluation_artifact import IEvaluationArtifactService
    from neurath.application.ports.services.evaluation_context import IEvaluationContextService
    from neurath.infrastructure.services.evaluation_context import (
        SQLAlchemyEvaluationContextService,
    )
    from tests.support.application import spakky_context

    context, flow = evaluation
    with pytest.raises(ValueError, match="not been assigned"):
        await consume(database, flow)
    with pytest.raises(NotImplementedError):
        await IEvaluationContextService.load(None, flow, flow.definition.phases[0])
    with pytest.raises(NotImplementedError):
        await IEvaluationArtifactService.observe(None, "", ())
    async with spakky_context(database, write=False) as container:
        service = container.get(SQLAlchemyEvaluationContextService)
        with pytest.raises(InvalidWorkflowState, match="no independent"):
            await service.load(flow, replace(flow.definition.phases[0], evaluation=None))
    async with storage_scope(database) as container:
        current = await container.get(IWorkflowRepository).get(flow.uid)
        current.revise(
            replace(
                current.definition,
                phases=(
                    replace(
                        current.definition.phases[0],
                        evaluation=replace(
                            current.definition.phases[0].evaluation, task_ids=(uuid7(),)
                        ),
                    ),
                ),
            ),
            1,
            "잘못된 범위",
        )
        await container.get(IWorkflowRepository).save(current)
    with pytest.raises(InvalidWorkflowState, match="unavailable"):
        await request(database, context, flow)


async def test_invalid_provider_model_does_not_prepare_evaluation(
    database, evaluation, provider_environment
):
    context, flow = evaluation
    _, plan = provider_environment
    with pytest.raises(ValueError, match="does not support"):
        await run(
            RequestEvaluationUseCase,
            RequestEvaluationCommand(
                **scope(flow),
                phase_key="review",
                sender_id=context[1].uid,
                route=DelegationRoute.PROVIDER,
                plan=replace(plan, model="unsupported", parent_session_id=flow.session_id),
            ),
            database_path=database,
        )


async def test_rebinding_same_candidate_is_idempotent_and_stop_yields_without_model(
    database, evaluation, monkeypatch
):
    from neurath.application.usecases.bind_evaluation import (
        BindEvaluationCommand,
        BindEvaluationUseCase,
    )
    from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
    from neurath.domain.enums.hook_action import HookAction
    from neurath.domain.enums.hook_event import HookEvent
    from neurath.infrastructure.services.provider import SubprocessProviderService

    context, flow = evaluation
    assignment = await request(database, context, flow)
    rebound = await run(
        BindEvaluationUseCase,
        BindEvaluationCommand(**scope(flow), phase_key="review", delegation_id=assignment.uid),
        database_path=database,
    )
    assert len(rebound.attempts) == 1
    monkeypatch.setattr(
        SubprocessProviderService,
        "start",
        lambda *a, **k: pytest.fail("Stop must not call a model"),
    )
    result = await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="codex",
            host_session_id="sender",
            working_directory=context[0].session.working_directory,
            event=HookEvent.STOP,
            turn_id="review-turn",
        ),
        database_path=database,
    )
    assert result.action is HookAction.PAUSE
    async with storage_scope(database, write=False) as container:
        task = await container.get(ITaskRepository).get(context[4].uid)
    assert (
        task.status is TaskStatus.WAITING
        and task.attempt(task.current_attempt_number).result is None
    )


async def test_stale_reflection_cannot_create_lesson_and_other_project_cannot_apply(
    database, evaluation, tmp_path
):
    from neurath.domain.errors import ContextNotFound

    context, flow = evaluation
    artifact = tmp_path / "reflection.txt"
    artifact.write_text("original causes and improvements")
    async with storage_scope(database) as container:
        current = await container.get(IWorkflowRepository).get(flow.uid)
        phase = current.definition.phases[0]
        current.revise(
            replace(
                current.definition,
                phases=(
                    replace(
                        phase,
                        evaluation=replace(
                            phase.evaluation,
                            kind=EvaluationKind.REFLECTION,
                            artifacts=(str(artifact),),
                        ),
                    ),
                ),
            ),
            1,
            "요청된 회고 후보",
        )
        current.choose_reflection(ReflectionChoice.REQUESTED, "사용자가 원인과 개선을 요청함")
        await container.get(IWorkflowRepository).save(current)
    delegated = await request(database, context, flow)
    await report(database, context, delegated)
    await consume(database, flow)
    command = CreateLessonCommand(
        **scope(flow), phase_key="review", content="개선 후보와 범위", references=("user:request",)
    )
    lesson = await run(CreateLessonUseCase, command, database_path=database)
    with pytest.raises(ContextNotFound):
        await run(
            ObserveLessonUseCase,
            ObserveLessonCommand(
                project_id=uuid7(),
                session_id=flow.session_id,
                memory_id=lesson.uid,
                observation=LessonObservation(
                    state=LessonState.DEFERRED, reason="보류", references=("reason",)
                ),
            ),
            database_path=database,
        )
    artifact.write_text("changed causes")
    with pytest.raises(ValueError, match="candidate changed"):
        await run(CreateLessonUseCase, command, database_path=database)


async def test_committed_evaluation_recovers_interruption_before_first_dispatch(
    database, evaluation
):
    from neurath.application.usecases.bind_evaluation import (
        BindEvaluationCommand,
        BindEvaluationUseCase,
    )
    from neurath.application.usecases.prepare_delegation import (
        PrepareDelegationCommand,
        PrepareDelegationUseCase,
    )
    from neurath.domain.enums.delegation_status import DelegationStatus

    context, flow = evaluation
    current = await run(
        GetEvaluationUseCase,
        GetEvaluationQuery(**scope(flow), phase_key="review"),
        database_path=database,
    )
    prepared = await run(
        PrepareDelegationUseCase,
        PrepareDelegationCommand(
            task_id=flow.task_id,
            sender_id=context[1].uid,
            recipient_id=context[3].uid,
            role=DelegationRole.REVIEWER,
            route=DelegationRoute.PEER,
            scope=current.context.scope,
            candidate=current.context.candidate,
        ),
        database_path=database,
    )
    await run(
        BindEvaluationUseCase,
        BindEvaluationCommand(**scope(flow), phase_key="review", delegation_id=prepared.uid),
        database_path=database,
    )
    resumed = await request(database, context, flow)
    assert resumed.status is DelegationStatus.ASSIGNED
    assert resumed.uid == prepared.uid
    assert (await request(database, context, flow)).uid == resumed.uid


async def test_lesson_effect_history_rejects_stale_competing_writer(database, evaluation):
    from spakky.data.persistency.repository import VersionConflictError

    from neurath.application.ports.repositories.memory import IMemoryRepository
    from neurath.domain.aggregates.memory import Memory

    context, flow = evaluation
    async with storage_scope(database) as container:
        memory = await container.get(IMemoryRepository).save(
            Memory.create(
                flow.project_id,
                flow.session_id,
                flow.task_id,
                MemoryKind.LESSON,
                "회고 교훈 후보",
                ("source:reflection",),
            )
        )
    async with storage_scope(database, write=False) as container:
        first = await container.get(IMemoryRepository).get(memory.uid)
    async with storage_scope(database, write=False) as container:
        stale = await container.get(IMemoryRepository).get(memory.uid)
    first.observe_lesson(
        LessonObservation(
            state=LessonState.DEFERRED, reason="먼저 확인한 근거", references=("first",)
        )
    )
    async with storage_scope(database) as container:
        await container.get(IMemoryRepository).save(first)
    stale.observe_lesson(
        LessonObservation(
            state=LessonState.DEFERRED, reason="오래된 읽기의 후속 근거", references=("stale",)
        )
    )
    with pytest.raises(VersionConflictError):
        async with storage_scope(database) as container:
            await container.get(IMemoryRepository).save(stale)


async def test_observed_native_child_evaluation_reports_into_same_phase(database, evaluation):
    from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
    from neurath.domain.enums.hook_event import HookEvent

    context, flow = evaluation
    await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="codex",
            host_session_id="sender",
            working_directory=context[0].session.working_directory,
            event=HookEvent.SUBAGENT_START,
            agent_id="fixture-child-evaluator",
        ),
        database_path=database,
    )
    child = await call(
        database, "register_peer", "RegisterPeer", flow.session_id, "fixture-child-evaluator"
    )
    delegated = await run(
        RequestEvaluationUseCase,
        RequestEvaluationCommand(
            **scope(flow),
            phase_key="review",
            sender_id=context[1].uid,
            recipient_id=child.uid,
            route=DelegationRoute.CHILD,
        ),
        database_path=database,
    )
    child_context = (context[0], context[1], context[0], child, context[4])
    await report(database, child_context, delegated)
    assert (await consume(database, flow)).current is None


async def test_confirmed_missing_requirement_uses_original_source_in_same_todo(
    database, evaluation
):
    from neurath.application.ports.repositories.request_source import IRequestSourceRepository
    from tests.test_task_requests import create

    context, flow = evaluation
    delegated = await request(database, context, flow)
    await report(database, context, delegated, remaining="원문 요구에서 처음부터 빠진 결과")
    await consume(database, flow, accepted=False)
    async with storage_scope(database, write=False) as container:
        source = await container.get(IRequestSourceRepository).get(context[4].definition.source_id)
    followup = await create(
        database,
        context[0],
        source=source,
        title="확인한 누락 결과 보완",
        follow_up_of=flow.task_id,
    )
    current = await run(
        GetEvaluationUseCase,
        GetEvaluationQuery(**scope(flow), phase_key="review"),
        database_path=database,
    )
    assert str(followup.uid) in current.context.scope
    assert followup.definition.source_id == context[4].definition.source_id
    assert followup.status is TaskStatus.PENDING
    async with storage_scope(database) as container:
        run_flow = await container.get(IWorkflowRepository).get(flow.uid)
        step = run_flow.definition.phases[0]
        run_flow.revise(
            replace(
                run_flow.definition, phases=(replace(step, checks=(*step.checks, "appendix")),)
            ),
            1,
            "누락 요구 확인 조건",
        )
        await container.get(IWorkflowRepository).save(run_flow)
    changed = await run(
        GetEvaluationUseCase,
        GetEvaluationQuery(**scope(flow), phase_key="review"),
        database_path=database,
    )
    assert changed.context.candidate != current.context.candidate
    assert "appendix" in changed.context.scope
