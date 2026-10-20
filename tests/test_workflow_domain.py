"""절차의 순서·검증·정정·재시도·결과 불명에 대한 도메인 전이를 검증한다."""

from dataclasses import replace

import pytest

from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.errors import ContextNotFound, InvalidWorkflowState, RevisionConflict
from neurath.domain.workflow_records import (
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    WorkflowDefinition,
)


def phase(key="build", **changes):
    return PhaseDefinition(
        key=key,
        purpose="검증 결과 생성",
        arguments=("true",),
        directory="/tmp",
        target_revision="source-1",
        **changes,
    )


def definition(*phases):
    return WorkflowDefinition(
        skill="implement-spec",
        version="1",
        phases=phases or (phase(),),
        inputs=(("request", "검증"),),
    )


def workflow(*phases):
    return WorkflowRun.create("project", "session", "task", 1, definition(*phases))


def outcome(status=PhaseStatus.SUCCEEDED, **changes):
    values = dict(
        status=status,
        target_revision="source-1",
        summary="실행 결과",
        evidence=("execution:1",),
        checks=("exit:0",),
        exit_code=0,
    )
    values.update(changes)
    return PhaseResult(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"key": " "},
        {"purpose": ""},
        {"directory": ""},
        {"target_revision": ""},
        {"arguments": ()},
        {"arguments": ("",)},
        {"checks": ()},
        {"checks": (" ",)},
        {"checks": ("x", "x")},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"output_limit": 0},
        {"max_attempts": 0},
        {"skip_condition": " "},
    ],
)
def test_invalid_phase_definitions_are_rejected(changes):
    with pytest.raises(ValueError):
        replace(phase(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"skill": ""},
        {"version": ""},
        {"phases": ()},
        {"phases": (phase(), phase())},
        {"inputs": (("x", "1"), ("x", "2"))},
        {"inputs": ((" ", "1"),)},
    ],
)
def test_invalid_workflow_definitions_are_rejected(changes):
    with pytest.raises(ValueError):
        replace(definition(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"target_revision": ""},
        {"summary": " "},
        {"status": PhaseStatus.RUNNING},
        {"status": PhaseStatus.PENDING},
        {"status": PhaseStatus.SKIPPED},
        {"evidence": ()},
        {"exit_code": 7},
    ],
)
def test_invalid_report_shapes_are_rejected(changes):
    with pytest.raises(ValueError):
        outcome(**changes)


def test_run_requires_a_definition_and_checks_scope_and_revision():
    run = workflow()
    with pytest.raises(InvalidWorkflowState):
        WorkflowRun(
            uid="bad", project_id="project", session_id="session", task_id="task", revisions=()
        )
    run.require_scope("project", "session")
    run.require_revision(1)
    with pytest.raises(ContextNotFound):
        run.require_scope("wrong", "session")
    with pytest.raises(ContextNotFound):
        run.require_scope("project", "wrong")
    with pytest.raises(RevisionConflict):
        run.require_revision(2)
    assert run.current.key == "build"
    assert run.status_for(run.current) is PhaseStatus.PENDING


def test_definition_inputs_and_arguments_are_detached_from_callers():
    arguments = ["true"]
    phases = [replace(phase(), arguments=arguments)]
    inputs = [("x", "1")]
    run = WorkflowRun.create(
        "p", "s", "t", 1, WorkflowDefinition(skill="s", version="v", phases=phases, inputs=inputs)
    )
    arguments.append("changed")
    inputs.append(("y", "2"))
    phases.clear()
    assert tuple(run.definition.phases[0].arguments) == ("true",)
    assert tuple(run.definition.inputs) == (("x", "1"),)


def test_success_advances_only_after_required_checks_and_finalization_is_idempotent():
    run = workflow(phase(), phase("review"))
    first = run.begin()
    with pytest.raises(InvalidWorkflowState):
        run.begin()
    with pytest.raises(InvalidWorkflowState):
        run.report(first.number, outcome(checks=()))
    with pytest.raises(InvalidWorkflowState):
        run.require_complete(1)
    run.report(first.number, outcome())
    run.report(first.number, outcome())
    assert run.current.key == "review"
    second = run.begin()
    run.report(second.number, outcome())
    run.require_complete(1)
    run.require_complete(1)
    assert run.current is None
    with pytest.raises(InvalidWorkflowState):
        run.begin()
    with pytest.raises(InvalidWorkflowState):
        run.require_complete(2)


def test_failure_retry_limit_and_late_previous_success():
    run = workflow(phase(max_attempts=2))
    first = run.begin()
    failure = outcome(PhaseStatus.FAILED, exit_code=7)
    run.report(first.number, failure)
    second = run.begin()
    with pytest.raises(InvalidWorkflowState):
        run.report(first.number, outcome())
    assert run.latest(run.current).number == second.number
    run.report(second.number, failure)
    with pytest.raises(InvalidWorkflowState):
        run.begin()
    assert len(run.attempts) == 2


def test_unknown_result_requires_reconciliation_without_new_attempt():
    run = workflow()
    attempt = run.begin()
    unknown = outcome(PhaseStatus.WAITING, exit_code=None)
    run.report(attempt.number, unknown)
    with pytest.raises(InvalidWorkflowState):
        run.begin()
    run.report(attempt.number, outcome())
    assert len(run.attempts) == 1
    assert run.current is None


def test_optional_skip_requires_matching_condition_and_reason():
    run = workflow(phase(skip_condition="no-ui"), phase("check"))
    for condition, reason in [("wrong", "근거"), ("no-ui", " ")]:
        with pytest.raises(InvalidWorkflowState):
            run.skip(condition, reason)
    run.skip("no-ui", "화면 변경 없음")
    assert run.current.key == "check"
    with pytest.raises(InvalidWorkflowState):
        run.report(1, outcome())
    with pytest.raises(InvalidWorkflowState):
        run.skip("no-ui", "근거")
    run.report(run.begin().number, outcome())
    with pytest.raises(InvalidWorkflowState):
        run.skip("no-ui", "근거")
    active = workflow(phase(skip_condition="no-ui"))
    active.begin()
    with pytest.raises(InvalidWorkflowState):
        active.skip("no-ui", "근거")


def test_wrong_attempt_target_and_oversized_output_do_not_advance():
    run = workflow(phase(output_limit=2))
    a = run.begin()
    with pytest.raises(ContextNotFound):
        run.report(99, outcome())
    with pytest.raises(InvalidWorkflowState):
        run.report(a.number, outcome(target_revision="other"))
    with pytest.raises(InvalidWorkflowState):
        run.report(a.number, outcome(output="abc"))
    assert run.current is not None


def test_revision_preserves_unaffected_waiting_attempt_and_rejects_required_removal():
    run = workflow(phase(), phase("docs"))
    a = run.begin()
    run.report(a.number, outcome(PhaseStatus.WAITING))
    changed = definition(phase(), replace(phase("docs"), target_revision="source-2"))
    with pytest.raises(InvalidWorkflowState):
        run.revise(changed, 1, "")
    with pytest.raises(InvalidWorkflowState):
        run.revise(definition(phase()), 1, "단계 제거")
    with pytest.raises(InvalidWorkflowState):
        run.revise(definition(phase(skip_condition="skip"), phase("docs")), 1, "필수 조건 제거")
    run.revise(changed, 2, "문서 요구만 정정")
    run.report(a.number, outcome())
    assert run.current.key == "docs"
    assert run.attempts[0].definition_number == 1
    run.revise(changed, 2, "같은 정의")
    assert len(run.revisions) == 2
    run.revise(definition(phase()), 3, "태스크 범위 정정")
    run.require_complete(3)


def test_changed_target_invalidates_success_and_old_running_result_stays_history():
    run = workflow()
    a = run.begin()
    changed = definition(replace(phase(), target_revision="source-2"))
    run.revise(changed, 1, "소스 변경")
    with pytest.raises(InvalidWorkflowState):
        run.begin()
    run.report(a.number, outcome())
    assert run.current.target_revision == "source-2"
    b = run.begin()
    run.report(b.number, outcome(target_revision="source-2"))
    assert run.current is None and len(run.revisions) == 2


def test_changed_target_allows_progress_after_unchanged_attempt_budget_is_exhausted():
    step = phase(max_attempts=1)
    run = workflow(step)
    run.report(run.begin().number, outcome(PhaseStatus.FAILED, exit_code=7))
    with pytest.raises(InvalidWorkflowState):
        run.begin()
    changed = replace(step, target_revision="fixed-source")
    run.revise(definition(changed), 1, "실패 원인을 수정한 소스")
    attempt = run.begin()
    run.report(attempt.number, outcome(target_revision="fixed-source"))
    assert run.current is None and len(run.attempts) == 2
