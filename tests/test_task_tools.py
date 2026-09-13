"""Task tools preserve native authority and share operations with CLI adapters."""

import argparse
import json

import pytest

from tests.test_agent_hooks import sessions  # noqa: F401
from neurath.agents import mcp


def bound_call(sessions, name, inputs, invocation="task-1", host="codex", session="api"):
    root, invoke = sessions
    code, output, diagnostic = invoke(host, session, "PreToolUse",
        tool_name=f"mcp__neurath_collaboration__{name}", tool_use_id=invocation,
        tool_input=inputs)
    assert code == 0, diagnostic
    return output["hookSpecificOutput"]["updatedInput"]


def test_inventory_is_task_shaped_and_preserves_legacy():
    result = mcp.response(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {tool["name"]: tool for tool in result["result"]["tools"]}
    assert set(tools) == {
        "harness_bypass",
        "adaptive_override_goal",
        "adaptive_preflight",
        "adaptive_read",
        "adaptive_replace",
        "artifact_put",
        "artifact_read",
        "collaboration_accept",
        "collaboration_ack",
        "collaboration_assign",
        "collaboration_close",
        "collaboration_conversation",
        "collaboration_discover",
        "collaboration_forward",
        "collaboration_inbox",
        "collaboration_message",
        "collaboration_publish",
        "collaboration_register",
        "collaboration_reply",
        "collaboration_report",
        "collaboration_send",
        "collaboration_submitted",
        "collaboration_subscribe",
        "collaboration_task",
        "collaboration_unsubscribe",
        "delegation_assign",
        "delegation_prepare",
        "delivery_redrive",
        "delivery_status",
        "diagnostics_continuation",
        "diagnostics_integrity",
        "diagnostics_profile",
        "diagnostics_project",
        "enclave_delete",
        "enclave_read",
        "enclave_set",
        "evaluation_consume",
        "evaluation_execute",
        "evaluation_loop_close",
        "evaluation_loop_open",
        "evaluation_loop_read",
        "evaluation_loop_round",
        "evaluation_prepare",
        "evaluation_read",
        "evaluation_report",
        "incident_escalate",
        "incident_record",
        "incident_refresh",
        "incident_resolve",
        "incident_supersede",
        "incident_validate",
        "installation_apply",
        "installation_plan",
        "installation_recover",
        "learning_defer",
        "learning_history",
        "learning_pending",
        "learning_status",
        "maintenance_choice_prepare",
        "maintenance_choice_read",
        "memory_checkpoint",
        "memory_recall",
        "monitor_ack",
        "monitor_cancel",
        "monitor_event",
        "monitor_external_wait",
        "monitor_handoff",
        "monitor_readback",
        "monitor_recover",
        "monitor_start",
        "monitor_status",
        "newsroom_comment",
        "newsroom_headlines",
        "newsroom_peers",
        "newsroom_publish",
        "newsroom_read",
        "newsroom_revise",
        "newsroom_seen",
        "phase_complete",
        "phase_current",
        "phase_evidence_prepare",
        "phase_finalize",
        "phase_start",
        "process_evidence_record",
        "provider_cancel",
        "provider_capabilities",
        "provider_models",
        "provider_plan",
        "provider_plan_read",
        "provider_recover",
        "provider_route",
        "provider_run",
        "provider_status",
        "releases_apply",
        "releases_check",
        "releases_choose",
        "releases_notice",
        "releases_prepare",
        "releases_recover",
        "releases_status",
        "reporting_approve",
        "reporting_consent",
        "reporting_list",
        "reporting_prepare",
        "reporting_read",
        "reporting_reconcile",
        "reporting_status",
        "reporting_submit",
        "review_abort",
        "review_begin",
        "review_comments",
        "review_consume",
        "review_publish",
        "review_report",
        "session_inspect",
        "session_status",
        "turn_inspect",
        "task_define",
        "task_list",
        "task_start",
        "task_resolve",
        "turn_yield",
        "workflow_advance",
        "workflow_finalize",
        "workflow_start",
        "worktree_claim",
        "worktree_cleanup",
        "worktree_inspect",
        "worktree_isolation",
        "worktree_release",
    }
    assert mcp.TOOL_NAME in mcp.TOOL_NAMES  # Explicit saved-call compatibility remains bound.
    for name, tool in tools.items():
        if name != "agent":
            assert "argv" not in tool["inputSchema"]["properties"]
            assert tool["inputSchema"]["additionalProperties"] is False
            assert tool["outputSchema"]["type"] == "object"


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
def test_structured_publish_shares_cli_result_without_parser(sessions, monkeypatch, host, session):
    from neurath.agents import newsroom_cli

    root, _ = sessions
    inputs = {"title": "Task contract", "body": "One operation", "key": "contract"}
    bound = bound_call(sessions, "newsroom_publish", inputs, host=host, session=session)
    identity = mcp.AgentIdentity(host, session, f"{host}:session:{session}", True)
    expected = newsroom_cli.run(root, argparse.Namespace(command="newsroom",
        newsroom_command="publish", **inputs), identity=identity)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args",
                        lambda *a, **k: pytest.fail("structured call used CLI parsing"))
    monkeypatch.setattr(newsroom_cli, "run",
                        lambda *a, **k: pytest.fail("structured call used CLI execution"))
    assert mcp.call_tool(root, bound, name="newsroom_publish") == expected
    assert mcp.call_tool(root, bound, name="newsroom_publish") == expected
    with pytest.raises(ValueError, match="fields"):
        mcp.call_tool(root, bound, name="memory_checkpoint")


@pytest.mark.parametrize("inputs", [
    {"query": "x", "actor": "forged"}, {"query": []}, {"query": "x", "limit": True},
    {"query": "x", "limit": -1}, {"query": "x", "limit": 100000},
])
def test_invalid_task_input_is_rejected_before_binding(sessions, inputs):
    root, _ = sessions
    result = mcp.response(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "memory_recall", "arguments": inputs}})["result"]
    assert result["isError"]
    error = result["structuredContent"]["error"]
    assert error["code"] == "invalid-input"
    assert error["state"] == "not-started"
    assert error["next_action"]


def test_checkpoint_retry_conflict_and_native_session(sessions):
    from neurath.memory.store import ProjectMemory

    root, _ = sessions
    inputs = {"summary": "Saved handoff", "key": "handoff"}
    first = bound_call(sessions, "memory_checkpoint", inputs)
    saved = mcp.call_tool(root, first, name="memory_checkpoint")
    assert saved["session"] == "api" and saved["authority"] == "agent-report"
    retry = bound_call(sessions, "memory_checkpoint", inputs, invocation="retry")
    assert mcp.call_tool(root, retry, name="memory_checkpoint") == saved
    assert "Saved handoff" in json.dumps(ProjectMemory(root).recall("Saved"))
    conflict = bound_call(sessions, "memory_checkpoint", {**inputs, "summary": "different"},
                          invocation="conflict")
    with pytest.raises(ValueError, match="different memory content"):
        mcp.call_tool(root, conflict, name="memory_checkpoint")


def test_task_binding_retires_at_native_post(sessions):
    root, invoke = sessions
    bound = bound_call(sessions, "memory_recall", {"query": "contract"})
    mcp.call_tool(root, bound, name="memory_recall")
    invoke("codex", "api", "PostToolUse", tool_name="mcp__neurath_collaboration__memory_recall",
           tool_use_id="task-1", tool_input=bound)
    with pytest.raises(ValueError, match="closed|expired"):
        mcp.call_tool(root, bound, name="memory_recall")


def test_unbound_task_has_recovery_information(sessions):
    root, _ = sessions
    result = mcp.response(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "memory_recall", "arguments": {"query": "x"}}})["result"]
    assert result["isError"]
    error = result["structuredContent"]["error"]
    assert error["code"] == "native-binding-required"
    assert error["retryable"] is False
    assert "hook" in error["next_action"].lower()


def test_binding_includes_tool_name_even_with_identical_fields(sessions):
    root, _ = sessions
    bound = bound_call(sessions, "newsroom_headlines", {"limit": 5})
    with pytest.raises(ValueError, match="binding"):
        mcp.call_tool(root, bound, name="collaboration_discover")


@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_or_interrupted_call_is_not_reexecuted(sessions, monkeypatch, interrupted):
    from neurath.runtime import tasks

    root, _ = sessions
    bound = bound_call(sessions, "memory_recall", {"query": "failure"})
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        if interrupted:
            raise KeyboardInterrupt()
        raise OSError("fixture write may have partially completed")

    monkeypatch.setattr(tasks, "execute", fail)
    with pytest.raises(KeyboardInterrupt if interrupted else ValueError):
        mcp.call_tool(root, bound, name="memory_recall")
    with pytest.raises(ValueError, match="running|partially"):
        mcp.call_tool(root, bound, name="memory_recall")
    assert len(calls) == 1


def claim_fixture(root, host="codex", session="api"):
    from scripts.agent_harness.session_kernel import ActorId, SessionId, SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeClaim, WorktreeIdentityResolver, WorktreeRegistry

    identity = WorktreeIdentityResolver().resolve(root)
    return WorktreeRegistry(SessionLocator.from_worktree(root)).claim(WorktreeClaim(
        worktree_id=identity.worktree_id, path=identity.path,
        session_id=SessionId(session), actor_id=ActorId(f"{host}:session:{session}")))


def test_verification_requires_owner_and_pins_approved_config(sessions, monkeypatch):
    import sys

    root, _ = sessions
    # Protocol fixtures have no host process policy; test that observer separately.
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *args: None)
    path = root / ".neurath/project.json"
    path.write_text(json.dumps({"verification": {"probe": {"argv": [sys.executable, "-c", "print('checked')"]}}}))
    with pytest.raises((ValueError, RuntimeError)):
        bound_call(sessions, "verification_run", {"check": "probe"})
    claim_fixture(root)
    bound = bound_call(sessions, "verification_run", {"check": "probe"}, invocation="owned")
    result = mcp.call_tool(root, bound, name="verification_run")
    assert result["status"] == "passed" and result["exit_code"] == 0
    assert mcp.call_tool(root, bound, name="verification_run") == result
    path.write_text(json.dumps({"verification": {"probe": {"argv": [sys.executable, "-c", "raise Exception()"]}}}))
    with pytest.raises(ValueError, match="binding"):
        mcp.call_tool(root, bound, name="verification_run")


def test_cli_and_mcp_verification_use_same_result_contract(sessions, monkeypatch):
    from neurath.cli import main
    from neurath.runtime import verification

    root, _ = sessions
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *args: None)
    claim_fixture(root)
    (root / ".neurath/project.json").write_text(json.dumps({"verification": {"probe": {"argv": ["true"]}}}))
    native = mcp.AgentIdentity("codex", "api", "codex:session:api")
    monkeypatch.setattr("neurath.agents.identity.current_agent", lambda root: native)
    receipt = {"status": "failed", "exit_code": 7, "timed_out": False}
    monkeypatch.setattr(verification, "verify", lambda *a, **k: receipt)
    emitted = []
    monkeypatch.setattr("neurath.cli.emit", emitted.append)
    assert main(["--root", str(root), "verify", "probe"]) == 1
    bound = bound_call(sessions, "verification_run", {"check": "probe"})
    assert mcp.call_tool(root, bound, name="verification_run") == emitted[-1] == receipt


def test_structured_and_legacy_messaging_share_conversation(sessions):
    root, _ = sessions
    inputs = {"to": "claude-code:ui", "message": "Review contract", "key": "one"}
    bound = bound_call(sessions, "collaboration_send", inputs)
    sent = mcp.call_tool(root, bound, name="collaboration_send")
    legacy = bound_call(sessions, "agent", {"argv": ["agent", "send", "--to", inputs["to"],
        "--message", inputs["message"], "--key", inputs["key"]]}, invocation="legacy")
    assert mcp.call_tool(root, legacy) == sent
    lookup = bound_call(sessions, "collaboration_message", {"message_id": sent["id"]},
                        invocation="body", host="claude-code", session="ui")
    assert mcp.call_tool(root, lookup, name="collaboration_message")["body"] == inputs["message"]
    reply = bound_call(sessions, "collaboration_reply", {"message_id": sent["id"], "message": "Reviewed", "key": "answer"},
                       invocation="reply", host="claude-code", session="ui")
    result = mcp.call_tool(root, reply, name="collaboration_reply")
    assert result["conversation"] == sent["conversation"]


def test_native_policy_context_is_bound_and_not_task_input(sessions, monkeypatch):
    from neurath.runtime import tasks
    from neurath.providers.readiness import _claude_policy

    root, invoke = sessions
    _, output, _ = invoke("claude-code", "ui", "PreToolUse",
        tool_name="mcp__neurath_collaboration__memory_recall", tool_use_id="policy-call",
        tool_input={"query": "policy"}, permission_mode="plan")
    bound = output["hookSpecificOutput"]["updatedInput"]
    observed = {}

    def capture(root, name, inputs, **context):
        observed.update(context)
        return {}

    monkeypatch.setattr(tasks, "execute", capture)
    mcp.call_tool(root, bound, name="memory_recall")
    evidence = observed["verified_policy_evidence"]
    assert evidence["permission_mode"] == "plan"
    assert evidence["tool_use_id"] == "policy-call"
    stage = _claude_policy(evidence, observed["identity"], observed["expected_turn"])
    assert stage["status"] == "verified"
    assert stage["evidence"]["sandbox_observation"] == "unobserved"
    assert _claude_policy({**evidence, "turn": "forged"}, observed["identity"],
                          observed["expected_turn"])["status"] == "failed"
    with pytest.raises(ValueError, match="unexpected task fields"):
        mcp.call_tool(root, {**bound, "permission_mode": "bypassPermissions"}, name="memory_recall")


def test_old_binding_schema_migrates_without_lending_policy(sessions):
    root, _ = sessions
    store = mcp._store(root)
    with store.connection() as db:
        db.execute("ALTER TABLE collaboration_calls DROP COLUMN context")
        db.execute("INSERT INTO collaboration_calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("old", "invocation", str(root), "codex", "api", "codex:session:api", 1,
             "turn", "request", "issued", None, 1))
    mcp._store(root)
    with store.connection() as db:
        row = db.execute("SELECT * FROM collaboration_calls WHERE token='old'").fetchone()
    assert row["context"] == "{}" and row["status"] == "issued"


@pytest.mark.parametrize("ready,sandbox", [(False, "danger-full-access"),
    (True, "workspace-write"), (True, "read-only"), (True, None)])
def test_mcp_never_substitutes_a_missing_native_execution_policy(monkeypatch, ready, sandbox):
    from neurath.runtime.tasks import _mcp_execution_policy
    from neurath.runtime.task_schema import TaskError

    monkeypatch.setattr("neurath.providers.readiness.inspect_bound_readiness",
        lambda *a, **k: {"implementation_ready": ready,
            "stages": {"policy": {"evidence": {"sandbox_policy": {"type": sandbox}}}}})
    with pytest.raises(TaskError) as error:
        _mcp_execution_policy(None, None, "turn")
    assert error.value.details["code"] == "native-execution-required"
    assert error.value.details["retryable"] is False


@pytest.mark.parametrize("approval,reviewer", [("never", "user"), ("never", None),
    ("on-request", "user"), ("untrusted", "user"), (None, "user"), ("never", "guardian_subagent")])
def test_mcp_observed_unrestricted_execution_policy_can_run(monkeypatch, approval, reviewer):
    from neurath.runtime.tasks import _mcp_execution_policy
    from neurath.runtime.task_schema import TaskError

    monkeypatch.setattr("neurath.providers.readiness.inspect_bound_readiness",
        lambda *a, **k: {"implementation_ready": True,
            "stages": {"policy": {"evidence": {"sandbox_policy": {"type": "danger-full-access"},
                "approval_policy": approval, "approvals_reviewer": reviewer}}}})
    if approval == "never" and reviewer in (None, "user"):
        _mcp_execution_policy(None, None, "turn")
    else:
        with pytest.raises(TaskError, match="execution policy"):
            _mcp_execution_policy(None, None, "turn")


def test_session_status_diagnoses_each_stage_without_claiming(sessions):
    root, _ = sessions
    bound = bound_call(sessions, "session_status", {})
    report = mcp.call_tool(root, bound, name="session_status")
    assert report["authority"] == "diagnostic"
    assert set(report["stages"]) == {"installation", "activation", "policy", "ownership"}
    assert report["implementation_ready"] is False
    assert report["stages"]["ownership"]["status"] != "verified"
    assert report["mode"]["requested"] is None
    assert report["next_actions"]
    assert "capabilities" not in report
    full = mcp.call_tool(root, bound_call(sessions, "session_status", {"detail": "full"},
                                        invocation="full-status"), name="session_status")
    assert all(row["authority"] != "capability" for row in full["capabilities"])
    assert set(full) - {"capabilities"} == set(report)
    assert full["implementation_ready"] == report["implementation_ready"]
    assert {k: v["status"] for k, v in full["stages"].items()} == {
        k: v["status"] for k, v in report["stages"].items()}


def test_mcp_common_instructions_are_advertised_once():
    from neurath.runtime.task_schema import definitions
    reply = mcp.response(None, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert "_neurath_binding" in reply["result"]["instructions"]
    assert all("Prefer this task tool over CLI argv" not in row["description"]
               for row in definitions())


def test_ack_schema_accepts_one_or_many_but_not_ambiguous_batches():
    from neurath.runtime.task_schema import arguments
    assert arguments('collaboration_ack', {'message_id': 'one'})['message_id'] == 'one'
    assert arguments('collaboration_ack', {'message_ids': ['one', 'two']})['message_ids'] == ['one', 'two']
    for inputs in ({}, {'message_ids': []}, {'message_id': 'one', 'message_ids': ['two']},
                   {'message_ids': ['one', 'one']}):
        with pytest.raises(ValueError):
            arguments('collaboration_ack', inputs)


@pytest.mark.parametrize("name", ["verification_run", "verification_nodes", "verification_builtin"])
def test_all_verification_faces_mark_completed_failure_as_mcp_error(monkeypatch, name):
    monkeypatch.setattr(mcp, "call_tool", lambda *a, **k: {
        "status": "failed", "exit_code": 1, "diagnostic_tail": "assert 201 <= 3"})
    reply = mcp.response(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": {}}})["result"]
    assert reply["isError"] is True
    assert reply["structuredContent"]["ok"] is False
    assert reply["structuredContent"]["result"]["diagnostic_tail"] == "assert 201 <= 3"


def test_session_status_cli_uses_common_service(sessions, monkeypatch):
    from neurath.cli import main
    from neurath.runtime import tasks

    root, _ = sessions
    report = {"authority": "diagnostic", "implementation_ready": False}
    monkeypatch.setattr(tasks, "session_status", lambda root: report)
    emitted = []
    monkeypatch.setattr("neurath.cli.emit", emitted.append)
    assert main(["--root", str(root), "session-status"]) == 0
    assert emitted == [report]


@pytest.mark.parametrize("completed", [False, True])
def test_claude_prompt_without_turn_id_retires_old_task_binding(sessions, completed):
    from neurath.hosts.identity import _state

    root, invoke = sessions
    assert invoke("claude-code", "no-turn", "SessionStart", source="startup")[0] == 0
    assert invoke("claude-code", "no-turn", "UserPromptSubmit", prompt="first")[0] == 0
    bound = bound_call(sessions, "memory_recall", {}, host="claude-code", session="no-turn")
    if completed:
        mcp.call_tool(root, bound, name="memory_recall")
    before = _state(root, "no-turn").foreground_turns["claude-code:session:no-turn"]
    assert invoke("claude-code", "no-turn", "UserPromptSubmit", prompt="second")[0] == 0
    after = _state(root, "no-turn").foreground_turns["claude-code:session:no-turn"]
    assert (before.generation, before.vendor_turn_id) == (after.generation, after.vendor_turn_id)
    assert before.user_prompt_receipt.turn_revision != after.user_prompt_receipt.turn_revision
    with pytest.raises(ValueError, match="prompt|binding"):
        mcp.call_tool(root, bound, name="memory_recall")


def test_provider_task_route_shares_cli_and_never_creates_a_session(sessions, monkeypatch):
    from neurath.cli import main

    root, _ = sessions
    inputs = {"provider": "codex", "operation": "create", "project_id": "project-from-inventory",
              "requested": {"collaboration_mode": "plan"}}
    bound = bound_call(sessions, "provider_route", inputs)
    report = mcp.call_tool(root, bound, name="provider_route")
    assert report["authority"] == "routing-only"
    assert report["status"] == "preparation-only"
    assert report["next_operation"]["tool"] == "create_thread"
    assert report["mode"]["effective"] is None and report["implementation_dispatched"] is False
    emitted = []
    monkeypatch.setattr("neurath.cli.emit", emitted.append)
    assert main(["--root", str(root), "provider", "route", "codex", "create",
                 "--project-id", inputs["project_id"], "--requested-json", json.dumps(inputs["requested"])]) == 0
    assert emitted == [report]


def test_provider_route_rejects_nested_identity_or_forged_inventory(sessions):
    root, _ = sessions
    for inputs in ({"provider": "codex", "operation": "create", "requested": {"actor": "forged"}},
                   {"provider": "codex", "operation": "create", "available_tools": ["create_thread"]}):
        response = mcp.response(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "provider_route", "arguments": inputs}})["result"]
        assert response["isError"]
        assert response["structuredContent"]["error"]["code"] == "invalid-input"


@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_cli_completed_verification_survives_prompt_only_change(sessions, monkeypatch, outcome):
    from neurath.runtime import tasks
    from neurath.hosts.identity import _state

    root, invoke = sessions
    assert invoke("claude-code", "cli-prompt", "SessionStart", source="startup")[0] == 0
    assert invoke("claude-code", "cli-prompt", "UserPromptSubmit", prompt="first")[0] == 0
    claim_fixture(root, "claude-code", "cli-prompt")
    before = _state(root, "cli-prompt").foreground_turns["claude-code:session:cli-prompt"]
    (root / ".neurath/project.json").write_text(json.dumps({"verification": {"probe": {"argv": ["true"]}}}))

    def result_after_new_prompt(*args, **kwargs):
        assert invoke("claude-code", "cli-prompt", "UserPromptSubmit", prompt="new scope")[0] == 0
        after = _state(root, "cli-prompt").foreground_turns["claude-code:session:cli-prompt"]
        assert before.user_prompt_receipt.turn_revision != after.user_prompt_receipt.turn_revision
        return {"status": outcome, "exit_code": 0 if outcome == "passed" else 1}

    monkeypatch.setattr("neurath.runtime.verification.verify", result_after_new_prompt)
    result = tasks.verification(root, "probe", identity=mcp.AgentIdentity("claude-code", "cli-prompt", "claude-code:session:cli-prompt"),
                                require_owner=True)
    assert result["status"] == outcome
    assert result["exit_code"] == (0 if outcome == "passed" else 1)
    assert "verification_status" not in result


def test_verification_admits_once_and_returns_completed_result_unchanged(tmp_path, monkeypatch):
    from neurath.runtime import tasks
    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(json.dumps({
        "verification": {"check": {"argv": ["true"]}}}))
    calls = []
    receipt = {"status": "failed", "exit_code": 1, "timed_out": False,
               "before_fingerprint": "before", "after_fingerprint": "after",
               "worktree_changed": True, "output_sha256": "observed-output"}

    def owner(*_args):
        calls.append("owner")

    def policy(*_args, **_kwargs):
        calls.append("policy")

    def verify(*_args, **_kwargs):
        calls.append("verify")
        return dict(receipt)

    monkeypatch.setattr(tasks, "_verification_owner", owner)
    monkeypatch.setattr(tasks, "_mcp_execution_policy", policy)
    monkeypatch.setattr("neurath.runtime.verification.verify", verify)
    result = tasks.verification(tmp_path, "check", require_owner=True,
        expected_turn='[1,"turn"]', identity=mcp.AgentIdentity(
            "codex", "completed-check", "codex:session:completed-check"),
        verified_policy_evidence={"admitted": True})
    assert calls == ["owner", "policy", "verify"]
    assert result == receipt


def test_public_tools_exclude_internal_material_and_verification_steps():
    from neurath.runtime.task_schema import definitions
    names = {row["name"] for row in definitions()}
    assert not any(name.startswith(("material_", "verification_")) for name in names)
    assert {"task_define", "task_list", "task_start", "task_resolve"} <= names


def test_large_mcp_result_is_not_duplicated_in_text(monkeypatch):
    document = {"status": "saved", "id": "record-one", "body": "x" * 12000}
    monkeypatch.setattr(mcp, "call_tool", lambda *_args, **_kwargs: document)
    result = mcp.response(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "memory_recall", "arguments": {}}})["result"]
    assert result["structuredContent"]["result"] == document
    assert len(result["content"][0]["text"]) < 100
    assert "x" * 100 not in result["content"][0]["text"]
