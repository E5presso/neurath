"""Typed faces retain the underlying CLI services and reject arbitrary argv."""
import pytest


def test_builtin_verifier_and_continuation_have_closed_named_faces():
    from neurath.runtime.task_schema import arguments
    assert arguments("verification_builtin",{"check":"harness-lint","key":"lint"})["check"] == "harness-lint"
    assert arguments("diagnostics_continuation",{}) == {}
    with pytest.raises(ValueError):
        arguments("verification_builtin",{"check":"arbitrary-shell","key":"invalid"})
from neurath.runtime.task_schema import arguments
from tests.test_workflow_tasks import call
pytest_plugins = ["tests.test_agent_hooks"]


def test_named_execution_inventory_has_closed_inputs():
    examples = {
        "verification_nodes": {"nodes": ["tests/test_example.py::test_example"], "key": "verify"},
        "incident_record": {"rule_id": "mcp-protocol", "symptom": "Observed protocol failure", "key": "record"},
        "incident_validate": {},
        "review_begin": {"workflow_id": "workflow", "to": "codex:child", "kind": "review-code",
                         "label": "reviewer", "scope": "Exact reviewed source", "key": "review"},
        "review_publish": {"workflow_id": "workflow", "repo": "example/project", "pr_number": 1, "key": "publish"},
        "review_comments": {"repo": "example/project", "pr_number": 1},
    }
    for name, inputs in examples.items():
        arguments(name, inputs)
        with pytest.raises(ValueError):
            arguments(name, {**inputs, "argv": ["sh", "-c", "anything"]})


def test_incident_record_face_uses_real_session_and_does_not_self_resolve(sessions):
    result = call(sessions, "incident_record", {"rule_id": "mcp-protocol",
        "symptom": "Observed source fixture mismatch", "key": "record"})
    assert result["status"] == "open"
    assert result["rule_id"] == "mcp-protocol"
    with pytest.raises(ValueError):
        call(sessions, "incident_validate", {})


def test_named_execution_checks_policy_before_backend(sessions, monkeypatch):
    import neurath.runtime.execution_tasks as execution
    monkeypatch.setattr(execution, "_dispatch", lambda *a: pytest.fail("backend executed before policy"))
    with pytest.raises(ValueError, match="policy|native|MCP|claim|own"):
        call(sessions, "verification_nodes", {"nodes": ["tests/test_example.py::test_example"], "key": "blocked"})


def test_review_report_does_not_accept_caller_identity():
    with pytest.raises(ValueError):
        arguments("review_report", {"workflow_id": "workflow", "delegation_id": "review",
            "verdict": "pass", "summary": "claimed", "key": "report", "actor": "foreign"})


def test_review_face_uses_discovered_child_then_reports_and_consumes(sessions):
    import json
    from neurath.agents import mcp
    from neurath.agents.store import MessageStore
    from tests.test_workflow_tasks import start
    root, invoke = sessions
    call(sessions, "worktree_claim", {})
    start(sessions)
    assert invoke("codex", "api", "PreToolUse", tool_name="spawn_agent", tool_use_id="spawn-review",
        turn_id="api-turn", tool_input={"task_name": "reviewer", "message": "Review fixture"})[0] == 0
    assert invoke("codex", "api", "PostToolUse", tool_name="spawn_agent", tool_use_id="spawn-review",
        turn_id="api-turn", tool_response={"agent_id": "child", "task_name": "/root/reviewer"})[0] == 0
    transcript = root / "host-storage/child.jsonl"
    transcript.write_text(json.dumps({"type": "session_meta", "payload": {"id": "child", "session_id": "api",
        "parent_thread_id": "api", "agent_path": "/root/reviewer",
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "api"}}}}}) + "\n")
    assert invoke("codex", "api", "SubagentStart", agent_id="child", transcript_path=str(transcript), turn_id="child-turn")[0] == 0
    peer = next(p for p in MessageStore(root).discover() if p["actor"] == "codex:child")
    claim = call(sessions, "review_begin", {"workflow_id": "phase", "to": peer["address"],
        "kind": "documentation", "label": "reviewer", "scope": "Fixture source", "key": "begin"})
    inputs = {"workflow_id": "phase", "delegation_id": claim["delegation_id"],
        "verdict": "pass", "summary": "Fixture source checked", "key": "report"}
    code, output, diagnostic = invoke("codex", "api", "PreToolUse", agent_id="child", transcript_path=str(transcript),
        turn_id="child-turn", tool_name="mcp__neurath_collaboration__review_report", tool_use_id="review-report", tool_input=inputs)
    assert code == 0, diagnostic
    report = mcp.call_tool(root, output["hookSpecificOutput"]["updatedInput"], name="review_report")
    result = call(sessions, "review_consume", {"workflow_id": "phase", "delegation_id": claim["delegation_id"],
        "outcome_ref": report["outcome_ref"], "key": "consume"})
    assert result["outcome"] == "result-applied"


def test_comment_face_can_read_all_pages_and_controls_ambient_filters(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    from neurath.runtime.execution_tasks import _comments
    calls = []
    def collect(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return SimpleNamespace(returncode=0, stderr="", stdout="\n".join([
            "CH1_COUNT=3", "CH2_COUNT=0", "CH3_COUNT=0", "UNRESOLVED_THREADS_COUNT=0", "TOTAL=3",
            "CH1_DATA=" + json.dumps([{"id": n} for n in (1,2,3)])]))
    monkeypatch.setattr("neurath.runtime.execution_tasks.subprocess.run", collect)
    monkeypatch.setenv("STALE_HANDLED_IDS", "999")
    fields = arguments("review_comments", {"repo": "example/project", "pr_number": 1,
        "limit": 2, "stale_handled_ids": [2], "last_seen": {"inline_comments": 1}})
    first = _comments(tmp_path, fields)
    assert first["next_offset"] == 2
    second = _comments(tmp_path, {**fields, "offset": first["next_offset"]})
    assert [c["id"] for c in first["inline_comments"]+second["inline_comments"]] == [1,2,3]
    assert second["next_offset"] is None
    assert calls[0][1]["STALE_HANDLED_IDS"] == "2"
    assert calls[0][1]["LAST_SEEN_CH1"] == "1"
    assert "--help" not in calls[0][0]
