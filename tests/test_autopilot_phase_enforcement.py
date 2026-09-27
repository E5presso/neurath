"""Autopilot phases are mandatory at both the runner and workflow writer boundary."""

from dataclasses import replace
import hashlib
from types import SimpleNamespace

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


def _sourced_task(goal, prompt):
    source = SimpleNamespace(kind="prompt", reference="prompt:" + prompt,
                             revision=hashlib.sha256(prompt.encode()).hexdigest())
    return SimpleNamespace(definition=SimpleNamespace(goal=goal, sources=(source,)),
                           status=SimpleNamespace(value="pending"))


def test_followup_ticket_task_still_requires_original_pending_autopilot_phase(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError

    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #90, #91\n"), ("user", "Continue the issues\n")])
    original = _sourced_task("Complete #90 and #91", "$autopilot #90, #91")
    ticket = SimpleNamespace(definition=SimpleNamespace(goal="Implement #91",
        sources=(SimpleNamespace(kind="ticket", revision="91"),)),
        status=SimpleNamespace(value="pending"))
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={}), "root", ticket,
            SimpleNamespace(tasks=(original, ticket)))


def test_ticket_only_followup_still_requires_unstarted_autopilot_phase(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError

    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #90, #91\n"), ("user", "Continue the issues\n")])
    ticket = SimpleNamespace(definition=SimpleNamespace(goal="Implement #91",
        sources=(SimpleNamespace(kind="ticket", revision="91"),)),
        status=SimpleNamespace(value="pending"))
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={}), "root", ticket,
            SimpleNamespace(tasks=(ticket,)))


def test_autopilot_name_in_question_is_not_a_new_invocation(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices

    question = "Why did $autopilot fail?"
    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "Implement parser fix\n"), ("user", question + "\n")])
    receipt = SimpleNamespace(prompt_digest=hashlib.sha256(question.encode()).hexdigest())
    process = SimpleNamespace(workflows={}, foreground_turns={
        "root": SimpleNamespace(user_prompt_receipt=receipt)})
    task_ledger_tasks._require_autopilot_phase(
        "/project", SimpleNamespace(host="codex", session="native"), process,
        "root", _sourced_task("Implement parser fix", "Implement parser fix"))


def test_missing_native_transcript_does_not_silently_admit_task_start(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError

    def missing(*_, **__):
        raise ValueError("registered native transcript is unavailable")
    monkeypatch.setattr(user_choices, "native_messages", missing)
    with pytest.raises(TaskError, match="transcript"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={}), "root",
            _sourced_task("Complete issues", "$autopilot #90, #91"))


@pytest.mark.parametrize("text,invoked", [
    ("Please handle these issues:\n$autopilot #90, #91", True),
    ("다음 이슈를 처리해.\n[$autopilot](/skill/SKILL.md) #90, #91", True),
    ("이제 $autopilot #90, #91", True),
    ("Use autopilot for #90 and #91", True),
    ("Why did you use $autopilot?", False),
    ("How do I use $autopilot?", False),
    ("Can we run /autopilot later?", False),
    ("Should I invoke $autopilot?", False),
])
def test_invocation_parser_distinguishes_commands_from_questions(text, invoked):
    from neurath.runtime.task_ledger_tasks import _explicit_autopilot_invocation
    assert _explicit_autopilot_invocation(text) is invoked


def test_autopilot_workflow_rechecks_prompt_binding_at_kernel_commit(tmp_path):
    activate(tmp_path)
    from scripts.agent_harness.session_kernel import (
        ActorId, ForegroundTurnPrompted, ForegroundTurnProvisioned, ResumeId,
        SessionId, SessionKernel, SessionLocator, SessionRuntime, SessionStarted,
        TransitionRejected, WorkflowId, WorkflowStarted,
    )
    from scripts.skill_harness.phase_runner import PhaseRunState, SkillContractRepository

    session, actor = SessionId("autopilot-binding"), ActorId("root")
    kernel = SessionKernel(SessionLocator(tmp_path))
    kernel.apply(SessionStarted(session_id=session, resume_id=ResumeId("resume"),
        root_actor_id=actor, runtime=SessionRuntime.CODEX, idempotency_key="session"))
    kernel.apply(ForegroundTurnProvisioned(session_id=session, actor_id=actor,
        idempotency_key="turn"))
    kernel.apply(ForegroundTurnPrompted(session_id=session, actor_id=actor,
        vendor_turn_id="native-turn", prompt_digest="b" * 64, idempotency_key="prompt"))
    phase = PhaseRunState.initialize(SkillContractRepository(BUNDLE).get("autopilot"),
                                     "run", "Complete issues")
    event = WorkflowStarted(session_id=session, workflow_id=WorkflowId("autopilot"),
        owner_actor_id=actor, kind="autopilot", goal="Complete issues",
        payload={"phase_run": phase.as_payload(), "skill_state": {},
                 "invocation_prompt_digest": "a" * 64}, idempotency_key="start")
    with pytest.raises(TransitionRejected, match="prompt"):
        kernel.apply(event)


def test_old_unstarted_autopilot_does_not_block_later_unrelated_task(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices

    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #89, #90\n"),
        ("assistant", "Completed the original request"),
        ("user", "Audit recent harness failures\n"),
    ])
    completed = _sourced_task("Complete #89 and #90", "$autopilot #89, #90")
    completed.status.value = "succeeded"
    audit = _sourced_task("Audit recent harness failures", "Audit recent harness failures")
    task_ledger_tasks._require_autopilot_phase(
        "/project", SimpleNamespace(host="codex", session="native"),
        SimpleNamespace(workflows={}), "root",
        audit, SimpleNamespace(tasks=(completed, audit)),
    )


def test_matching_active_autopilot_admits_ticket_followup(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices

    original_prompt = "$autopilot #90, #91"
    digest = hashlib.sha256(original_prompt.encode()).hexdigest()
    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", original_prompt + "\n"), ("user", "Continue the issues\n")])
    original = _sourced_task("Complete #90 and #91", original_prompt)
    ticket = SimpleNamespace(definition=SimpleNamespace(goal="Implement #91",
        sources=(SimpleNamespace(kind="ticket", revision="91"),)),
        status=SimpleNamespace(value="pending"))
    workflow = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="active"),
        owner_actor_id="root", goal=original.definition.goal,
        payload={"invocation_prompt_digest": digest,
                 "invocation_prompt_reference": original.definition.sources[0].reference})
    task_ledger_tasks._require_autopilot_phase(
        "/project", SimpleNamespace(host="codex", session="native"),
        SimpleNamespace(workflows={"current": workflow}), "root", ticket,
        SimpleNamespace(tasks=(original, ticket)))


def test_phase_started_on_followup_can_resume_original_autopilot(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices

    original_prompt, followup = "$autopilot #90", "Continue #90"
    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", original_prompt + "\n"), ("user", followup + "\n")])
    task = _sourced_task("Complete #90", original_prompt)
    receipt = SimpleNamespace(prompt_digest=hashlib.sha256(followup.encode()).hexdigest())
    workflow = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="active"),
        owner_actor_id="root", goal=task.definition.goal,
        payload={"invocation_prompt_digest": receipt.prompt_digest,
                 "invocation_prompt_reference": "prompt:followup"})
    process = SimpleNamespace(workflows={"resumed": workflow}, foreground_turns={
        "root": SimpleNamespace(user_prompt_receipt=receipt)})
    task_ledger_tasks._require_autopilot_phase(
        "/project", SimpleNamespace(host="codex", session="native"), process,
        "root", task, SimpleNamespace(tasks=(task,)))


def test_identical_second_invocation_cannot_borrow_first_workflow(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError

    prompt = "$autopilot #90"
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", prompt + "\n"), ("assistant", "Working"), ("user", prompt + "\n")])
    first = _sourced_task("Complete #90", prompt)
    first.definition.sources[0].reference = "prompt:first"
    first.status.value = "succeeded"
    second = _sourced_task("Complete #90", prompt)
    second.definition.sources[0].reference = "prompt:second"
    old = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="active"),
        owner_actor_id="root", goal="Complete #90",
        payload={"invocation_prompt_digest": digest,
                 "invocation_prompt_reference": "prompt:first"})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={"old": old}), "root", second,
            SimpleNamespace(tasks=(first, second)))


def test_old_active_autopilot_cannot_cover_new_invocation_goal(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError

    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #10\n"),
        ("user", "$autopilot #90, #91\n"),
    ])
    old = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="active"),
                          owner_actor_id="root", goal="Complete #10", payload={})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={"old": old}), "root",
            _sourced_task("Complete #90 and #91", "$autopilot #90, #91"),
        )


def test_old_active_autopilot_cannot_cover_new_same_goal_invocation(monkeypatch):
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError

    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #90, #91\n"),
        ("user", "$autopilot #90, #91 again\n"),
    ])
    old = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="active"),
                          owner_actor_id="root", goal="Complete #90 and #91",
                          payload={"invocation_prompt_digest": hashlib.sha256(
                              "$autopilot #90, #91".encode()).hexdigest()})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={"old": old}), "root",
            _sourced_task("Complete #90 and #91", "$autopilot #90, #91 again"),
        )


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

    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [("user", invocation)])
    identity = SimpleNamespace(host="codex", session="native")
    process = SimpleNamespace(workflows={})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", identity, process, "root", _sourced_task("Complete issues", invocation))


def test_autopilot_followup_still_requires_missing_phase_start(monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError
    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #90, #91"),
        ("assistant", "Working"),
        ("user", "Continue the issues"),
    ])
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={}), "root",
            _sourced_task("Complete issues", "$autopilot #90, #91"))


def test_new_autopilot_followup_is_not_covered_by_old_completed_run(monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime import task_ledger_tasks, user_choices
    from neurath.runtime.task_schema import TaskError
    monkeypatch.setattr(user_choices, "native_messages", lambda *_, **__: [
        ("user", "$autopilot #10"),
        ("assistant", "Completed"),
        ("user", "$autopilot #90, #91"),
        ("assistant", "Working"),
        ("user", "Continue the issues"),
    ])
    old = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="completed"),
                          owner_actor_id="root", payload={})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={"old": old}), "root",
            _sourced_task("Complete issues", "$autopilot #90, #91"))


def test_old_completed_run_cannot_cover_invocation_beyond_transcript_window(monkeypatch):
    from types import SimpleNamespace
    from neurath.hosts import identity as host_identity
    from neurath.runtime import task_ledger_tasks
    from neurath.runtime.task_schema import TaskError

    def user(text):
        return {"type": "event_msg", "payload": {"type": "user_message", "message": text}}

    def assistant():
        return {"type": "event_msg", "payload": {"type": "agent_message", "message": "Working"}}

    records = [user("$autopilot #90"), *(assistant() for _ in range(2000)),
               user("$autopilot #10")]
    monkeypatch.setattr(host_identity, "snapshot", lambda *_: {"transcript": "/transcript"})
    monkeypatch.setattr(host_identity, "_reverse_native_records", lambda *_: iter(records))
    old = SimpleNamespace(kind="autopilot", status=SimpleNamespace(value="completed"),
                          owner_actor_id="root", payload={})
    with pytest.raises(TaskError, match="phase_start"):
        task_ledger_tasks._require_autopilot_phase(
            "/project", SimpleNamespace(host="codex", session="native"),
            SimpleNamespace(workflows={"old": old}), "root",
            _sourced_task("Complete issues", "$autopilot #90"))


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
