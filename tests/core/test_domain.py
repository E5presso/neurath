"""The replacement core enforces user work and skill order without old state layers."""

from uuid import uuid4

import pytest

from neurath.core.domain import (
    Assignment,
    Condition,
    CoreError,
    Evidence,
    Phase,
    Skill,
    Source,
    Task,
    admit_effects,
    quote,
    select_execution,
    stop_reasons,
)


def skill():
    return Skill(
        "implement",
        "1",
        (
            Phase("understand", (Condition("scope", frozenset({"report"})),), frozenset({"read"})),
            Phase(
                "implement",
                (Condition("change", frozenset({"report"})),),
                frozenset({"read", "edit", "check", "execute"}),
            ),
            Phase(
                "review",
                (Condition("review", frozenset({"review"})),),
                frozenset({"read", "delegate"}),
                restart_from="implement",
            ),
        ),
        acceptance_restart_from="implement",
    )


def task():
    return Task(
        "t1",
        "session",
        "owner",
        "Deliver the requested change",
        ("user-source",),
        (Condition("works", frozenset({"check"})),),
    )


def evidence(kind="report", subject="rev1", passed=True):
    identifier = uuid4().hex
    return Evidence("e-" + identifier, kind, "source-" + identifier, "observer", subject, passed)


def complete_phase(value, name, condition, kind="report", subject="rev1"):
    return value.complete_phase(
        name, {condition: (evidence(kind, subject),)}, {"revision": subject}
    )


def reviewed_task():
    value = task().start().attach_skill(skill())
    value = complete_phase(value, "understand", "scope")
    value = complete_phase(value, "implement", "change")
    return complete_phase(value, "review", "review", "review")


def test_skill_requires_a_task_and_has_one_current_phase():
    value = task().start().attach_skill(skill())
    assert value.current_phase.id == "understand"
    assert value.skill_run.skill.id == "implement"
    assert value.goal == task().goal and value.id == "t1"


def test_phase_cannot_jump_forward_or_skip():
    value = task().start().attach_skill(skill())
    with pytest.raises(CoreError, match="phase-order"):
        complete_phase(value, "review", "review", "review")
    assert value.current_phase.id == "understand"


def test_failed_or_wrong_kind_evidence_cannot_complete_phase():
    value = task().start().attach_skill(skill())
    with pytest.raises(CoreError, match="condition-unmet"):
        value.complete_phase("understand", {"scope": (evidence(passed=False),)}, {})
    with pytest.raises(CoreError, match="evidence-kind"):
        value.complete_phase("understand", {"scope": (evidence("check"),)}, {})
    assert value.current_phase.id == "understand"


def test_last_phase_does_not_complete_user_acceptance():
    value = reviewed_task()
    assert value.skill_run.complete and value.state == "running"
    with pytest.raises(CoreError, match="condition-unmet"):
        value.complete({})
    finished = value.complete({"works": (evidence("check"),)})
    assert finished.state == "completed"


def test_task_cannot_complete_before_all_phases():
    value = task().start().attach_skill(skill())
    with pytest.raises(CoreError, match="phases-unfinished"):
        value.complete({"works": (evidence("check"),)})


def test_failure_is_an_attempt_not_task_completion():
    value = task().start().attach_skill(skill()).wait("Missing remote response", "failure-source")
    assert value.state == "waiting" and value.current_phase.id == "understand"
    assert stop_reasons("session", "owner", (value,))
    assert value.resume().id == value.id


def test_late_review_failure_restarts_defined_phase_in_same_task():
    value = task().start().attach_skill(skill())
    value = complete_phase(value, "understand", "scope")
    value = complete_phase(value, "implement", "change")
    repair = value.restart("failed-review", changed_inputs=())
    assert repair.id == value.id and repair.current_phase.id == "implement"
    assert repair.skill_run.attempt == 2
    assert len(repair.skill_run.history) == 1
    assert repair.skill_run.history[0].completions[-1].phase_id == "implement"
    with pytest.raises(CoreError, match="phase-order"):
        complete_phase(repair, "review", "review", "review", "rev2")
    repair = complete_phase(repair, "implement", "change", subject="rev2")
    repair = complete_phase(repair, "review", "review", "review", "rev2")
    assert repair.complete({"works": (evidence("check", "rev2"),)}).state == "completed"


def test_changed_earlier_input_restarts_at_earliest_affected_phase():
    value = reviewed_task().restart("acceptance-failed", changed_inputs=("revision",))
    assert value.current_phase.id == "understand"


def test_unknown_rework_impact_restarts_first_phase():
    value = reviewed_task().restart("acceptance-failed", changed_inputs=None)
    assert value.current_phase.id == "understand"


@pytest.mark.parametrize("state", ["issued", "active", "reported", "cancel-requested"])
def test_restart_cannot_leave_previous_phase_worker_unsettled(state):
    value = task().start().attach_skill(skill())
    assignment = Assignment(
        "worker",
        "subagent",
        "Inspect current scope",
        "owner",
        "child",
        "rev1",
        state=state,
        run_index=0,
        phase_id="understand",
        attempt=1,
    )
    value = value.with_assignment(assignment)
    with pytest.raises(CoreError, match="assignments-unsettled"):
        value.restart("changed-input", [])
    assert value.skill_run.attempt == 1


def test_restart_preserves_executor_but_requires_settled_bounded_work():
    value = task().start().attach_skill(skill())
    executor = Assignment(
        "executor",
        "subagent",
        "Execute the skill",
        "owner",
        "executor",
        "rev1",
        role="executor",
        state="active",
        run_index=0,
        phase_id="understand",
        attempt=1,
    )
    value = value.with_assignment(executor)
    worker = Assignment(
        "worker",
        "subagent",
        "Inspect scope",
        "executor",
        "child",
        "rev1",
        run_index=0,
        phase_id="understand",
        attempt=1,
    ).report("child", "failed-source", "failed", "rev1")
    value = value.with_assignment(worker.reject("executor", "failed-source"))
    repair = value.restart("changed-input", [])
    assert repair.skill_run.attempt == 2
    assert repair.assignments == value.assignments


def test_phase_effect_gate_blocks_native_edit_before_implementation():
    value = task().start().attach_skill(skill())
    admit_effects(value, frozenset({"read"}))
    with pytest.raises(CoreError, match="effect-out-of-phase"):
        admit_effects(value, frozenset({"edit"}))
    with pytest.raises(CoreError, match="effect-out-of-phase"):
        admit_effects(value, frozenset({"read", "publish"}))
    value = complete_phase(value, "understand", "scope")
    admit_effects(value, frozenset({"edit", "check"}))


def test_child_report_settles_child_return_but_not_owner_task():
    assignment = Assignment(
        "a1", "subagent", "A bounded independent review", "owner", "child", "rev1"
    ).start("child")
    value = task().start().with_assignment(assignment)
    assert stop_reasons("session", "child", (value,))
    value = value.with_assignment(assignment.report("child", "result-source", "pass", "rev1"))
    assert not stop_reasons("session", "child", (value,))
    assert stop_reasons("session", "owner", (value,))
    with pytest.raises(CoreError, match="assignments-unsettled"):
        value.complete({"works": (evidence("check"),)})


def test_failed_child_report_cannot_be_accepted_as_success():
    value = Assignment("a1", "subagent", "Review", "owner", "child", "rev1").start("child")
    value = value.report("child", "failure-source", "failed", "rev1")
    with pytest.raises(CoreError, match="assignment-unsuccessful"):
        value.accept("owner", "failure-source", "rev1")
    assert value.reject("owner", "failure-source").state == "rejected"


def test_wrong_actor_or_changed_review_revision_cannot_report_or_accept():
    value = Assignment("a1", "subagent", "Review", "owner", "child", "rev1").start("child")
    with pytest.raises(CoreError, match="actor-mismatch"):
        value.report("owner", "result-source", "pass", "rev1")
    value = value.report("child", "result-source", "pass", "rev1")
    with pytest.raises(CoreError, match="subject-changed"):
        value.accept("owner", "result-source", "rev2")


def test_reader_does_not_need_ownership_or_a_policy_snapshot():
    value = task().start().attach_skill(skill())
    admit_effects(value, frozenset({"read"}))
    assert "lease" not in value.__dataclass_fields__


def test_three_execution_choices_are_about_need_not_worktree():
    assert select_execution("subagent", "codex", "codex", "") == "subagent"
    assert (
        select_execution("session", "codex", "codex", "Separate user-facing lifetime") == "session"
    )
    assert (
        select_execution("cross-provider", "codex", "claude-code", "Different analysis capability")
        == "cross-provider"
    )
    with pytest.raises(CoreError, match="execution-choice"):
        select_execution("worktree-worker", "codex", "codex", "Root checkout")
    with pytest.raises(CoreError, match="execution-reason"):
        select_execution("session", "codex", "codex", "")


def test_quote_resolves_actual_source_span_and_digest():
    source = Source.create("s1", "user", "Please publish version 2.", "host-event-1")
    assert quote(source, 7, 14, source.digest) == "publish"
    with pytest.raises(CoreError, match="source-changed"):
        quote(source, 7, 14, "invented-digest")
    with pytest.raises(CoreError, match="quote-range"):
        quote(source, 0, 999, source.digest)


def test_user_withdrawal_is_not_completion_and_requires_user_source():
    value = task().start()
    fake = Source.create("s2", "report", "Cancel the task", "agent-call")
    with pytest.raises(CoreError, match="user-source-required"):
        value.withdraw(fake)
    withdrawn = value.withdraw(Source.create("s3", "user", "Cancel this task", "host-event-2"))
    assert withdrawn.state == "withdrawn"
    assert not stop_reasons("session", "owner", (withdrawn,))


def test_stopped_owner_adoption_preserves_task_and_fences_old_generation():
    value = task().start()
    directive = Source.create("s3", "user", "Continue this existing task", "host-event-2")
    adopted = value.adopt("new-session", "new-owner", directive, previous_owner_stopped=True)
    assert adopted.id == value.id and adopted.ownership_generation == 2
    with pytest.raises(CoreError, match="stale-owner"):
        adopted.require_owner("owner", 1)
    adopted.require_owner("new-owner", 2)
    with pytest.raises(CoreError, match="owner-still-active"):
        value.adopt("new-session", "new-owner", directive, previous_owner_stopped=False)


def test_duplicate_phases_or_invalid_restart_target_are_rejected():
    with pytest.raises(CoreError, match="skill-definition"):
        Skill("bad", "1", (Phase("a"), Phase("a")))
    with pytest.raises(CoreError, match="skill-definition"):
        Skill("bad", "1", (Phase("a", restart_from="missing"),))


def test_declared_nested_skill_returns_to_parent_without_completing_it():
    outer = Skill(
        "outer",
        "1",
        (
            Phase("inspect", (), frozenset({"read"}), subskills=frozenset({"inner"})),
            Phase("deliver"),
        ),
    )
    inner = Skill("inner", "1", (Phase("read"), Phase("report")))
    value = task().start().attach_skill(outer).attach_skill(inner)
    assert value.current_phase.id == "read"
    with pytest.raises(CoreError, match="phase-order"):
        value.complete_phase("inspect", {}, {})
    value = value.complete_phase("read", {}, {}).complete_phase("report", {}, {})
    assert value.current_phase.id == "inspect"
    with pytest.raises(CoreError, match="phases-unfinished"):
        value.complete({"works": (evidence("check"),)})
    value = value.complete_phase("inspect", {}, {}).complete_phase("deliver", {}, {})
    assert value.complete({"works": (evidence("check"),)}).state == "completed"


def test_undeclared_nested_skill_cannot_replace_parent_phase():
    value = task().start().attach_skill(skill())
    with pytest.raises(CoreError, match="subskill-not-declared"):
        value.attach_skill(
            Skill("escape", "1", (Phase("publish", effects=frozenset({"publish"})),))
        )


def test_nested_skill_does_not_expand_parent_phase_effects():
    outer = Skill("outer", "1", (Phase("inspect", subskills=frozenset({"inner"})),))
    inner = Skill("inner", "1", (Phase("edit", effects=frozenset({"edit"})),))
    value = task().start().attach_skill(outer).attach_skill(inner)
    with pytest.raises(CoreError, match="effect-out-of-phase"):
        admit_effects(value, frozenset({"edit"}))


def test_rework_reuse_requires_same_condition_and_all_inputs():
    definition = Skill(
        "rework",
        "1",
        (
            Phase("first", (Condition("first-check", frozenset({"check"}), "input"),)),
            Phase(
                "second",
                (Condition("second-check", frozenset({"check"}), "input"),),
                restart_from="first",
            ),
        ),
    )
    old = evidence("check")
    value = (
        task()
        .start()
        .attach_skill(definition)
        .complete_phase("first", {"first-check": (old,)}, {"input": "rev1", "configuration": "old"})
    )
    restarted = value.restart("changed-configuration", ["configuration"])
    with pytest.raises(CoreError, match="evidence-input-changed"):
        restarted.complete_phase(
            "first", {"first-check": (old,)}, {"input": "rev1", "configuration": "new"}
        )
    same = value.restart("retry", []).complete_phase(
        "first", {"first-check": (old,)}, {"input": "rev1", "configuration": "old"}
    )
    with pytest.raises(CoreError, match="evidence-condition-changed"):
        same.complete_phase(
            "second", {"second-check": (old,)}, {"input": "rev1", "configuration": "old"}
        )


def test_nested_skill_cannot_relabel_parent_history_evidence():
    outer = Skill(
        "outer",
        "1",
        (
            Phase(
                "first",
                (Condition("outer-check", frozenset({"check"})),),
                subskills=frozenset({"inner"}),
            ),
            Phase("last", restart_from="first"),
        ),
    )
    inner = Skill(
        "inner", "1", (Phase("inner", (Condition("inner-check", frozenset({"check"})),)),)
    )
    old = evidence("check")
    value = (
        task()
        .start()
        .attach_skill(outer)
        .complete_phase("first", {"outer-check": (old,)}, {"configuration": "old"})
    )
    value = value.restart("changed", ["configuration"]).attach_skill(inner)
    with pytest.raises(CoreError, match="evidence-condition-changed"):
        value.complete_phase("inner", {"inner-check": (old,)}, {"configuration": "new"})


def test_skill_defined_conditional_path_still_requires_phase_and_decision_evidence():
    definition = Skill(
        "conditional",
        "1",
        (
            Phase(
                "test",
                (
                    Condition("policy"),
                    Condition(
                        "failed-test",
                        frozenset({"check"}),
                        expected_pass=False,
                        when=("testing", "required"),
                    ),
                ),
                choices=(("testing", ("required", "not-required")),),
            ),
            Phase("implement"),
        ),
    )
    value = task().start().attach_skill(definition)
    with pytest.raises(CoreError, match="phase-choice-required"):
        value.complete_phase("test", {"policy": (evidence(),)}, {})
    with pytest.raises(CoreError, match="condition-unmet"):
        value.complete_phase("test", {}, {"testing": "not-required"})
    value = value.complete_phase("test", {"policy": (evidence(),)}, {"testing": "not-required"})
    assert value.current_phase.id == "implement"
    with pytest.raises(CoreError, match="phases-unfinished"):
        value.complete({"works": (evidence("check"),)})
