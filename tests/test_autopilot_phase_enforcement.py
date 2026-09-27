"""Autopilot phases are mandatory at both the runner and workflow writer boundary."""

from dataclasses import replace

import pytest

from neurath.resources import BUNDLE
from neurath.runtime.engine import activate


def _components():
    activate()
    from scripts.skill_harness.phase_runner import (
        PhaseRunState, PhaseRunner, PhaseRunnerError, SkillContractRepository,
    )
    from scripts.agent_harness.workflow_terminal import (
        WorkflowTerminalPolicy, WorkflowTerminalError,
    )
    contract = SkillContractRepository(BUNDLE).get("autopilot")
    state = PhaseRunState.initialize(contract, "required-phases", "Complete all issues")
    return state, PhaseRunner(SkillContractRepository(BUNDLE)), PhaseRunnerError, WorkflowTerminalPolicy(), WorkflowTerminalError


def test_every_autopilot_phase_rejects_skipped_status():
    state, runner, error, _, _ = _components()
    assert [phase.name for phase in state.phases] == [
        "collect_issues", "dependency_dag", "execute_waves", "recovery",
        "meta_detection", "intent_audit", "sync_docs", "terminal_report",
    ]
    for phase in state.phases:
        current = replace(state, current_phase_id=phase.id)
        with pytest.raises(error, match="skip|SKIP"):
            runner._assert_phase_can_complete(current, phase.id, "skipped", "skip", None)


def test_workflow_writer_rejects_skipped_autopilot_phase():
    state, _, _, policy, error = _components()
    before = {"phase_run": state.as_payload()}
    after = {"phase_run": state.as_payload()}
    after["phase_run"]["phases"][0]["status"] = "skipped"
    after["phase_run"]["current_phase_id"] = state.phases[1].id
    with pytest.raises(error, match="skip"):
        policy.validate_transition(before, after)


def test_workflow_writer_rejects_successful_autopilot_finalization_with_skip():
    state, _, _, policy, _ = _components()
    before = {"phase_run": state.as_payload()}
    for phase in before["phase_run"]["phases"]:
        phase["status"] = "completed"
    before["phase_run"]["phases"][0]["status"] = "skipped"
    before["phase_run"]["current_phase_id"] = None
    after = {"phase_run": {**before["phase_run"], "terminal_state": "merged"}}
    with pytest.raises(ValueError, match="skip|incomplete"):
        policy.validate_phase(before, after, completed=True)


@pytest.mark.parametrize("invocation", [
    "[$autopilot](/project/.agents/skills/autopilot/SKILL.md) #90, #91",
    "$autopilot #90, #91",
    "Please use /autopilot #90, #91",
])
def test_explicit_autopilot_invocation_requires_phase_start_before_task_mutation(
    monkeypatch, invocation,
):
    from types import SimpleNamespace
    from neurath.runtime import task_ledger_tasks
    from neurath.runtime.task_schema import TaskError
    from neurath.runtime import user_choices

    monkeypatch.setattr(user_choices, "native_messages", lambda *_: [("user", invocation)])
    identity = SimpleNamespace(host="codex", session="native")
    process = SimpleNamespace(workflows={})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase("/project", identity, process, "root")


def test_autopilot_followup_still_requires_missing_phase_start(monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError
    monkeypatch.setattr(user_choices, "native_messages", lambda *_: [
        ("user", "$autopilot #90, #91"),
        ("assistant", "Working"),
        ("user", "Continue the issues"),
    ])
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={}), "root")


def test_inflight_seven_phase_autopilot_keeps_its_original_phase_ids():
    from scripts.skill_harness.phase_runner import PhaseRecord
    state, runner, _, _, _ = _components()
    legacy = replace(state, phases=(*state.phases[:5],
        PhaseRecord(6, "intent_audit_and_docs", "pending", (), None, None),
        PhaseRecord(7, "terminal_report", "pending", (), None, None)),
        current_phase_id=7)
    contract = runner._contract_for_state(legacy)
    assert contract.phase(7).name == "terminal_report"
    assert contract.next_phase_after(7) is None
