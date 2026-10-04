"""Public commands cannot manufacture native evidence, ownership or phase progress."""

import pytest

from neurath.core.commands import Context
from neurath.core.domain import CoreError


def call(core, name, fields, actor="root", key="command"):
    service, _ = core
    return service.call(Context(actor, "session", "native-" + key), name, {"key": key, **fields})


def test_task_binding_uses_id_not_goal_text(core):
    _, identifier = core
    result = call(core, "task_start", {"task_id": identifier, "expected_revision": 1})
    assert result["task"]["state"] == "running"
    result = call(
        core,
        "skill_start",
        {"task_id": identifier, "expected_revision": 2, "skill": "test"},
        key="skill",
    )
    assert result["task"]["skill_runs"][0]["skill"]["id"] == "test"
    with pytest.raises(CoreError, match="unexpected-fields"):
        call(
            core,
            "skill_start",
            {
                "task_id": identifier,
                "expected_revision": 3,
                "skill": "test",
                "north_star": "another phrase",
            },
        )


def test_replay_does_not_bypass_native_actor_binding(core):
    service, identifier = core
    fields = {"task_id": identifier, "expected_revision": 1, "key": "start"}
    service.call(Context("root", "session", "real"), "task_start", fields)
    with pytest.raises(CoreError, match="native-actor-required"):
        service.call(Context("root", "foreign-session", "forged"), "task_start", fields)


def test_child_can_read_unknown_policy_without_writer_claim(core):
    service, identifier = core
    result = service.call(Context("child", "session", "read"), "task_read", {"task_id": identifier})
    assert result["task"]["id"] == identifier
    assert (
        service.call(Context("child", "session", "status"), "session_status", {})["actor"]["id"]
        == "child"
    )
    with pytest.raises(CoreError, match="stale-owner"):
        call(core, "task_start", {"task_id": identifier, "expected_revision": 1}, actor="child")


def test_agent_report_cannot_impersonate_native_user_or_check(core):
    _, identifier = core
    report = call(
        core,
        "report_record",
        {"task_id": identifier, "body": "The check passed", "subject": "rev1", "passed": True},
    )
    assert report["evidence"]["kind"] == "report"
    with pytest.raises(CoreError, match="unexpected-fields"):
        call(
            core,
            "report_record",
            {"task_id": identifier, "body": "Fake", "kind": "check", "passed": True},
            key="fake",
        )
    with pytest.raises(CoreError, match="unexpected-fields"):
        call(
            core,
            "task_start",
            {"task_id": identifier, "expected_revision": 1, "actor": "root"},
            actor="child",
        )


def test_phase_order_and_check_evidence_are_enforced_through_real_store(core):
    service, identifier = core
    call(core, "task_start", {"task_id": identifier, "expected_revision": 1}, key="start")
    call(
        core,
        "skill_start",
        {"task_id": identifier, "expected_revision": 2, "skill": "test"},
        key="skill",
    )
    report = call(
        core,
        "report_record",
        {"task_id": identifier, "body": "Scope observed", "subject": "rev1", "passed": True},
        key="report",
    )
    result = call(
        core,
        "phase_complete",
        {
            "task_id": identifier,
            "expected_revision": 3,
            "phase_id": "analysis",
            "outcomes": {"scope": [report["evidence"]["id"]]},
            "inputs": {"revision": "rev1"},
        },
        key="phase1",
    )
    assert len(result["task"]["skill_runs"][0]["completions"]) == 1
    with pytest.raises(CoreError, match="evidence-kind"):
        call(
            core,
            "phase_complete",
            {
                "task_id": identifier,
                "expected_revision": 4,
                "phase_id": "check",
                "outcomes": {"tested": [report["evidence"]["id"]]},
                "inputs": {},
            },
            key="fake-check",
        )
    observed = service.provenance.observe_tool(
        Context("root", "session", "check-result"),
        identifier,
        "actual-check",
        {"exit_code": 0, "stdout": "ok"},
        kind="check",
        subject="rev1",
    )
    call(
        core,
        "phase_complete",
        {
            "task_id": identifier,
            "expected_revision": 4,
            "phase_id": "check",
            "outcomes": {"tested": [observed.id]},
            "inputs": {"revision": "rev1"},
        },
        key="phase2",
    )
    assert service.sessions.stop(Context("root", "session", "stop"))["allowed"] is False
    call(
        core,
        "task_complete",
        {"task_id": identifier, "expected_revision": 5, "outcomes": {"works": [observed.id]}},
        key="complete",
    )
    assert service.sessions.stop(Context("root", "session", "stop2"))["allowed"] is True


def test_tool_evidence_from_another_task_cannot_complete_current_task(core):
    service, identifier = core
    original = service.call(
        Context("root", "session", "read"), "task_read", {"task_id": identifier}
    )["task"]
    other = call(
        core,
        "task_define",
        {
            "goal": "Another result",
            "source_ids": original["instruction_sources"],
            "acceptance": [{"id": "other"}],
        },
        key="other",
    )["task"]["id"]
    observed = service.provenance.observe_tool(
        Context("root", "session", "result"),
        other,
        "other-check",
        {"exit_code": 0},
        kind="check",
        subject="rev1",
    )
    call(core, "task_start", {"task_id": identifier, "expected_revision": 1}, key="start")
    with pytest.raises(CoreError, match="evidence-task-mismatch"):
        call(
            core,
            "task_complete",
            {"task_id": identifier, "expected_revision": 2, "outcomes": {"works": [observed.id]}},
            key="complete",
        )


@pytest.mark.parametrize(
    "result", [{"session_id": 123, "exit_code": None}, {"exit_code": False}, {"stdout": "passed"}]
)
def test_incomplete_or_untyped_tool_results_are_not_check_evidence(core, result):
    service, task_id = core
    with pytest.raises(CoreError, match="check-not-terminal"):
        service.provenance.observe_tool(
            Context("root", "session", "result"), task_id, "launch", result, kind="check"
        )


def test_retained_native_input_supports_task_intake_as_agent_interpretation(tmp_path):
    from neurath.core.service import Core

    service = Core(tmp_path)
    service.sessions.observe_actor("root", "session", "codex")
    context = Context("root", "session", "input")
    source = service.provenance.observe_input(context, "Implement the requested behavior", "prompt")
    task = service.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Behavior works",
            "source_ids": [source.id],
            "acceptance": [{"id": "works"}],
        },
    )["task"]
    assert task["instruction_sources"] == [source.id]
    assert service.call(context, "source_read", {"source_id": source.id})["kind"] == "native_input"
    peer = service.provenance.observe_input(context, "I approve publication", "peer", origin="peer")
    with pytest.raises(CoreError, match="non-user-instruction"):
        service.call(
            context,
            "task_define",
            {
                "key": "peer-task",
                "goal": "Publish",
                "source_ids": [peer.id],
                "acceptance": [{"id": "published"}],
            },
        )


def test_publication_approval_records_exact_quote_and_target_not_human_attestation(core):
    service, task_id = core
    source = service.provenance.observe_input(
        Context("root", "session", "prompt"), "Review and publish the change.", "publish-prompt"
    )
    target = {
        "tool": "Bash",
        "input": {"command": "git push origin branch"},
        "cwd": str(service.store.root),
    }
    fields = {
        "task_id": task_id,
        "source_id": source.id,
        "start": 0,
        "end": len(source.text),
        "digest": source.digest,
        "action": "publish",
        "target": target,
        "reason": "The current user requested publication.",
    }
    result = call(core, "approval_record", fields, key="approve")
    assert result["approval"]["assurance"] == "agent-interpretation"
    assert result["approval"]["quote"] == source.text
    assert result["approval"]["target"] == target
    with pytest.raises(CoreError, match="source-changed"):
        call(core, "approval_record", {**fields, "digest": "invented"}, key="fake-quote")


def test_task_adoption_preserves_obligations_and_fences_previous_owner(core):
    service, task_id = core
    service.sessions.observe_actor("new-owner", "new-session", "codex")
    context = Context("new-owner", "new-session", "adopt")
    source = service.provenance.observe_input(context, "Continue this unfinished task.", "continue")
    fields = {
        "key": "adopt",
        "task_id": task_id,
        "expected_revision": 1,
        "source_id": source.id,
        "start": 0,
        "end": len(source.text),
        "digest": source.digest,
        "reason": "User requested continuation.",
    }
    with pytest.raises(CoreError, match="owner-still-active"):
        service.call(context, "task_adopt", fields)
    with service.store.transaction() as tx:
        actor = tx.record("actor", "root")
        tx.put_record("actor", "root", {**actor["value"], "status": "stopped"}, actor["revision"])
    adopted = service.call(context, "task_adopt", fields)["task"]
    assert adopted["id"] == task_id and adopted["ownership_generation"] == 2
    assert not service.sessions.stop(context)["allowed"]
    with pytest.raises(CoreError, match="stale-owner"):
        call(
            core,
            "task_start",
            {"task_id": task_id, "expected_revision": adopted["revision"]},
            key="old-owner",
        )


def test_explicit_withdrawal_is_not_success_but_does_not_fake_task_completion(core):
    service, task_id = core
    source = service.provenance.observe_input(
        Context("root", "session", "cancel"), "Cancel this task.", "cancel"
    )
    result = call(
        core,
        "task_withdraw",
        {
            "task_id": task_id,
            "expected_revision": 1,
            "source_id": source.id,
            "start": 0,
            "end": len(source.text),
            "digest": source.digest,
            "reason": "User explicitly cancelled the work.",
        },
        key="withdraw",
    )["task"]
    assert result["state"] == "withdrawn"
    assert result["completion_evidence"] == []
    assert result["withdrawal_source"] == source.id


def test_memory_checkpoint_is_atomic_reference_data_not_task_completion(core):
    service, task_id = core
    result = call(
        core,
        "memory_checkpoint",
        {
            "summary": "An attributed completion claim",
            "status": "completed",
            "decisions": ["Keep the actual task unfinished"],
            "next_steps": ["Finish the user goal"],
        },
        key="checkpoint",
    )
    assert result["authority"] == "agent-report"
    recalled = service.call(
        Context("root", "session", "recall"), "memory_recall", {"query": "completion claim"}
    )
    assert recalled["authority"] == "reference-only"
    assert recalled["entries"][0]["id"] == result["reference"]
    assert (
        service.call(Context("root", "session", "read"), "task_read", {"task_id": task_id})["task"][
            "state"
        ]
        == "open"
    )
    assert service.sessions.stop(Context("root", "session", "stop"))["allowed"] is False


def test_memory_pull_reads_stopped_work_without_adopting_or_claiming(core):
    service, task_id = core
    service.sessions.observe_actor("reader", "other", "claude-code")
    result = service.call(
        Context("reader", "other", "pull"), "memory_pull", {"source_actor": "root"}
    )
    assert result["authority"] == "reference-only"
    assert result["unfinished_tasks"][0]["id"] == task_id
    assert result["unfinished_tasks"][0]["owner_actor"] == "root"
    with service.store.transaction() as tx:
        assert tx.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


def test_approval_record_preserves_quote_and_target_without_granting_host_permission(core):
    service, task_id = core
    context = Context("root", "session", "approval")
    source = service.provenance.observe_input(context, "Apply the prepared update.", "actual-input")
    target = {"offer": "selected-offer"}
    result = call(
        core,
        "approval_record",
        {
            "task_id": task_id,
            "source_id": source.id,
            "start": 0,
            "end": len(source.text),
            "digest": source.digest,
            "action": "update",
            "target": target,
            "reason": "Interpreted current user instruction",
        },
        key="approval-record",
    )
    with service.store.transaction() as tx:
        record = tx.records("approval")[0]["value"]
    assert record["target"] == target
    assert record["assurance"] == "agent-interpretation"
    assert result


def test_task_dependencies_require_fulfilled_goal_before_start(core):
    service, predecessor = core
    context = Context("root", "session", "dependencies")
    source = service.provenance.observe_input(
        context, "Deliver the dependent result after the prerequisite.", "dependency-input"
    )
    dependent = call(
        core,
        "task_define",
        {
            "goal": "Dependent result",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
            "dependencies": [predecessor],
        },
        key="dependent",
    )["task"]
    fields = {"task_id": dependent["id"], "expected_revision": dependent["revision"]}
    with pytest.raises(CoreError, match="dependencies-unfinished"):
        call(core, "task_start", fields, key="early-start")
    started = call(
        core, "task_start", {"task_id": predecessor, "expected_revision": 1}, key="start-first"
    )["task"]
    observed = service.provenance.observe_tool(
        context, predecessor, "native-prerequisite", {"exit_code": 0}, kind="check"
    )
    call(
        core,
        "task_complete",
        {
            "task_id": predecessor,
            "expected_revision": started["revision"],
            "outcomes": {"works": [observed.id]},
        },
        key="finish-first",
    )
    assert call(core, "task_start", fields, key="start-dependent")["task"]["state"] == "running"


def test_unknown_or_duplicate_dependency_does_not_create_a_task(core):
    service, predecessor = core
    context = Context("root", "session", "dependency-validation")
    source = service.provenance.observe_input(
        context, "Deliver the next result.", "dependency-input"
    )
    fields = {"goal": "Next result", "source_ids": [source.id], "acceptance": [{"id": "done"}]}
    for dependencies in [["missing"], [predecessor, predecessor]]:
        with pytest.raises(CoreError):
            call(
                core,
                "task_define",
                {**fields, "dependencies": dependencies},
                key="invalid-" + str(len(dependencies)),
            )
    assert len(service.call(context, "task_list", {})["tasks"]) == 1


def test_task_listing_defaults_to_actual_owner_or_recipient(core):
    service, task_id = core
    context = Context("child", "session", "inspection")
    assert service.call(context, "task_list", {})["tasks"] == []
    assert service.call(context, "task_list", {"all_project": True})["tasks"][0]["id"] == task_id
    assert service.call(context, "task_read", {"task_id": task_id})["task"]["id"] == task_id
