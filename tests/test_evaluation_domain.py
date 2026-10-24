"""독립 평가의 후보·보고·선택과 교훈 적용 경계의 실패 반례를 검증한다."""

from dataclasses import replace
from uuid import uuid7

import pytest

from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.enums.delegation_route import DelegationRoute
from neurath.domain.enums.delegation_status import DelegationStatus
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.domain.enums.provider_status import ProviderStatus
from neurath.domain.enums.reflection_choice import ReflectionChoice
from neurath.domain.errors import InvalidTaskState, InvalidWorkflowState
from neurath.domain.values.delegation_report import DelegationReport
from neurath.domain.values.evaluation_target import EvaluationKind, EvaluationTarget
from neurath.domain.values.lesson_observation import LessonObservation, LessonState
from neurath.domain.values.provider_plan import ProviderPlan
from tests.test_workflow_domain import outcome, phase, workflow


def review_phase(kind=EvaluationKind.RESULT, **kwargs):
    return phase(
        "review",
        evaluation=EvaluationTarget(kind=kind, artifacts=("report",), verification=("tests",)),
        **kwargs,
    )


def assignment(**kwargs):
    values = dict(
        uid=uuid7(),
        task_id=uuid7(),
        source_id=uuid7(),
        definition_number=1,
        sender_id=uuid7(),
        recipient_id=uuid7(),
        role=DelegationRole.REVIEWER,
        scope="독립 검토 범위",
        route=DelegationRoute.PEER,
        candidate="one",
    )
    values.update(kwargs)
    return Delegation(**values)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"artifacts": ()},
        {"verification": ()},
        {"artifacts": (" ",)},
        {"task_ids": ("same", "same")},
    ],
)
def test_evaluation_target_rejects_missing_actual_inputs(kwargs):
    with pytest.raises(ValueError):
        replace(review_phase().evaluation, **kwargs)


def test_review_cannot_use_generic_report_execution_or_optional_skip():
    flow = workflow(review_phase())
    attempt = flow.begin()
    with pytest.raises(InvalidWorkflowState):
        flow.report(attempt.number, outcome())
    with pytest.raises(InvalidWorkflowState):
        flow.request_execution(attempt, fresh=True)
    with pytest.raises(ValueError):
        review_phase(skip_condition="optional")
    with pytest.raises(InvalidWorkflowState):
        flow.evaluation_phase("other")
    with pytest.raises(InvalidWorkflowState):
        flow.require_evaluation(phase())
    with pytest.raises(InvalidWorkflowState):
        flow.require_evaluation(review_phase(output_limit=5))


def test_reflection_offered_once_requested_without_token_and_no_reconfirmation():
    flow = workflow(review_phase(EvaluationKind.REFLECTION))
    with pytest.raises(InvalidWorkflowState):
        flow.choose_reflection(ReflectionChoice.UNASKED, "reason")
    with pytest.raises(InvalidWorkflowState):
        flow.choose_reflection(ReflectionChoice.OFFERED, " ")
    flow.choose_reflection(ReflectionChoice.OFFERED, "문제 근거")
    flow.choose_reflection(ReflectionChoice.OFFERED, "반복 제안")
    assert flow.reflection_context == "문제 근거" and flow.current is None
    flow.choose_reflection(ReflectionChoice.REQUESTED, "사용자 요청")
    flow.choose_reflection(ReflectionChoice.OFFERED, "다시 확인")
    assert flow.reflection_context == "사용자 요청" and flow.current is not None
    with pytest.raises(InvalidWorkflowState):
        flow.choose_reflection(ReflectionChoice.UNANSWERED, "이미 요청함")


def test_evaluation_order_and_nonrecursive_assignment():
    flow = workflow(phase(), review_phase())
    with pytest.raises(InvalidWorkflowState):
        flow.require_evaluation(flow.definition.phases[1])
    flow.report(flow.begin().number, outcome())
    flow.require_evaluation(flow.definition.phases[1])
    with pytest.raises(ValueError):
        assignment(role=DelegationRole.EXECUTOR)
    with pytest.raises(InvalidTaskState):
        assignment().require_redelegation(None, uuid7())
    optional = workflow(
        review_phase(EvaluationKind.REFLECTION), replace(review_phase(), key="result")
    )
    optional.require_evaluation(optional.definition.phases[1])


def test_bind_candidate_identity_reuse_and_order():
    flow = workflow(review_phase())
    delegated = assignment()
    with pytest.raises(InvalidWorkflowState):
        flow.bind_evaluation(phase(), delegated, "one")
    with pytest.raises(InvalidWorkflowState):
        flow.bind_evaluation(flow.current, delegated, "other")
    attempt = flow.bind_evaluation(flow.current, delegated, "one")
    assert flow.bind_evaluation(flow.current, delegated, "one") == attempt
    with pytest.raises(InvalidWorkflowState):
        flow.bind_evaluation(flow.current, assignment(), "one")


def ready_review():
    flow = workflow(review_phase())
    delegated = assignment(
        status=DelegationStatus.COMPLETED,
        report=DelegationReport(summary="실제 보고", references=("source",)),
    )
    attempt = flow.bind_evaluation(flow.current, delegated, "one")
    return flow, delegated, attempt


@pytest.mark.parametrize(
    "change",
    [
        "number",
        "candidate",
        "delegation",
        "sender",
        "stopped",
        "reason",
        "references",
        "empty-reference",
    ],
)
def test_consume_rejects_wrong_identity_stale_candidate_and_unreasoned_decision(change):
    flow, delegated, attempt = ready_review()
    number = attempt.number
    candidate = "one"
    reason = "원문 대조"
    refs = ("source",)
    if change == "number":
        number = 99
    if change == "candidate":
        candidate = "other"
    if change == "delegation":
        delegated.uid = uuid7()
    if change == "sender":
        delegated.recipient_id = delegated.sender_id
    if change == "stopped":
        delegated.stop_reason = "사용자 취소"
    if change == "reason":
        reason = " "
    if change == "references":
        refs = ()
    if change == "empty-reference":
        refs = (" ",)
    with pytest.raises(InvalidWorkflowState):
        flow.consume_evaluation(
            number, delegated, candidate, accepted=True, rationale=reason, references=refs
        )


def test_provider_report_needs_actual_success_identity_output_and_reference():
    delegated = assignment(status=DelegationStatus.COMPLETED)
    with pytest.raises(InvalidTaskState):
        delegated.evaluation_report()
    plan = ProviderPlan(
        provider=ProviderKind.CODEX,
        model="model",
        policy="read-only",
        directory="/tmp",
        parent_session_id=uuid7(),
    )
    delegated = replace(delegated, plan=plan, route=DelegationRoute.PROVIDER)
    for status, native, reference, output in [
        (ProviderStatus.FAILED, "id", "run", "output"),
        (ProviderStatus.COMPLETED, None, "run", "output"),
        (ProviderStatus.COMPLETED, "id", None, "output"),
        (ProviderStatus.COMPLETED, "id", "run", ""),
    ]:
        delegated.provider_status = status
        delegated.native_session_id = native
        delegated.execution_reference = reference
        delegated.provider_output = output
        with pytest.raises(InvalidTaskState):
            delegated.evaluation_report()


def test_lesson_requires_failure_and_normal_control_then_actual_application():
    for kwargs in [
        dict(reason=""),
        dict(references=()),
        dict(references=(" ",)),
        dict(state=LessonState.VALIDATED),
    ]:
        values = dict(state=LessonState.PROPOSED, reason="원인", references=("evidence",))
        values.update(kwargs)
        with pytest.raises(ValueError):
            LessonObservation(**values)
    memory = Memory.create(uuid7(), uuid7(), None, MemoryKind.ARTIFACT, "원문", ("source",))
    event = LessonObservation(state=LessonState.APPLIED, reason="효과", references=("test",))
    with pytest.raises(ValueError):
        memory.observe_lesson(event)
    memory.kind = MemoryKind.LESSON
    with pytest.raises(ValueError):
        memory.observe_lesson(event)
    with pytest.raises(ValueError):
        memory.observe_lesson(replace(event, state=LessonState.DEFERRED, effective=False))
    memory.observe_lesson(
        replace(
            event,
            state=LessonState.VALIDATED,
            failure_case="실패 재현 개선",
            normal_case="정상 대조",
        )
    )
    memory.observe_lesson(event)
    memory.observe_lesson(replace(event, effective=True))
    assert memory.lessons[-1].effective is True


async def test_actual_artifact_and_explicit_head_observation(repository, tmp_path, monkeypatch):
    import subprocess

    from neurath.infrastructure.services.evaluation_artifact import GitEvaluationArtifactService

    service = GitEvaluationArtifactService()
    (repository / "result.txt").write_text("one")
    before = await service.observe(
        str(repository), ("result.txt", "external:immutable", "missing.txt")
    )
    (repository / "unrelated.txt").write_text("unrelated")
    assert (
        await service.observe(str(repository), ("result.txt", "external:immutable", "missing.txt"))
        == before
    )
    (repository / "result.txt").write_text("two")
    assert (
        await service.observe(str(repository), ("result.txt", "external:immutable", "missing.txt"))
        != before
    )
    head = await service.observe(
        str(repository), ("git:HEAD", "file:" + str(repository / "result.txt"))
    )
    assert head[0].startswith("git-head:")
    assert (await service.observe(str(tmp_path), ("git:HEAD",))) == ("git-head:unavailable",)
    with pytest.raises(ValueError, match="directory"):
        await service.observe(str(tmp_path / "absent"), ())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 128, "", "permission denied"),
    )
    with pytest.raises(ValueError, match="Cannot observe"):
        await service.observe(str(repository), ("git:HEAD",))


def test_missing_evaluation_cannot_attach_after_all_other_phases_completed():
    flow = workflow(phase())
    flow.report(flow.begin().number, outcome())
    with pytest.raises(InvalidWorkflowState, match="not in this workflow"):
        flow.require_evaluation(review_phase())
