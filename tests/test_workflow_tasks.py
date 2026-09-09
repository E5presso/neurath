"""Named workflow tools retain typed transitions and evaluator authority."""

import json

import pytest

from neurath.agents import mcp
from tests.test_task_tools import bound_call

pytest_plugins = ["tests.test_agent_hooks"]


def call(sessions, name, inputs, invocation=None, host="codex", session="api"):
    bound = bound_call(sessions, name, inputs, invocation=invocation or name, host=host, session=session)
    return mcp.call_tool(sessions[0], bound, name=name)


def define_task(sessions):
    result = call(sessions, "task_define", {"tasks": [{"key": "commit-task",
        "title": "Commit the approved change", "goal": "Review an authorized change",
        "sources": [], "acceptance": ["The approved change is committed with observed Git evidence"],
        "evidence_contract": "phase", "dependencies": []}], "expected_revision": 0, "key": "define-task"})
    return result["tasks"][0]["id"]


def assess_task(sessions, task_id, workflow_revision, status):
    """Attach a root assessment to the actual observed phase result."""
    from tests.test_task_acceptance_review import assessment
    tasks = call(sessions, "task_list", {}, invocation="assessment-read")["tasks"]
    task = next(task for task in tasks if task["id"] == task_id)
    return assessment(task, f"workflow:phase:{workflow_revision}", status)


def test_named_workflow_inventory_is_closed():
    from neurath.runtime.task_schema import definitions
    tools = {row["name"]: row for row in definitions()}
    required = {"workflow_start", "workflow_advance", "workflow_finalize", "phase_start",
        "phase_current", "phase_complete", "phase_finalize", "adaptive_read", "adaptive_preflight",
        "adaptive_replace", "adaptive_override_goal", "delegation_prepare", "delegation_assign",
        "evaluation_prepare", "evaluation_read", "evaluation_execute", "evaluation_report", "evaluation_consume"}
    assert required <= tools.keys()
    for name in required:
        schema = tools[name]["inputSchema"]
        assert schema["additionalProperties"] is False
        assert not {"argv", "actor", "session", "payload", "root", "cwd"} & schema["properties"].keys()


def test_session_artifacts_roundtrip_without_file_or_identity_input(sessions):
    document = {"phase_evidence": ["source_evidence: current source"], "details": {"passed": True}}
    stored = call(sessions, "artifact_put", {"document": document, "key": "report"})
    assert stored["reference"].startswith("sha256:")
    assert call(sessions, "artifact_read", {"reference": stored["reference"]})["document"] == document
    replay = call(sessions, "artifact_put", {"document": document, "key": "report"}, invocation="artifact-replay")
    assert replay == stored
    with pytest.raises(ValueError, match="key|different"):
        call(sessions, "artifact_put", {"document": {"changed": True}, "key": "report"}, invocation="artifact-changed")


def test_artifact_schema_bounds_data_without_promoting_it_to_authority():
    from neurath.runtime.task_schema import arguments
    with pytest.raises(ValueError):
        arguments("artifact_put", {"document": {"x": "a" * 70000}, "key": "large"})
    with pytest.raises(ValueError):
        arguments("artifact_put", {"document": {}, "key": "path", "path": ".process-state.json"})


def test_missing_evaluator_rejection_does_not_poison_initialization_key(sessions):
    from neurath.agents.store import MessageStore
    call(sessions, "worktree_claim", {})
    for invocation in ("missing-first", "missing-second"):
        with pytest.raises(ValueError, match="evaluator"):
            call(sessions, "phase_start", {"workflow_id": "unstarted", "skill": "sync-docs",
                "north_star": "Review documentation", "run_id": "run", "key": "same-key"}, invocation=invocation)
    with MessageStore(sessions[0]).connection() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_task_requests'").fetchone()
        if exists:
            assert db.execute("SELECT count(*) FROM workflow_task_requests WHERE key='same-key'").fetchone()[0] == 0


def start(sessions, *, alias=False, workflow="phase", key="start", skill="commit", host="codex", session="api"):
    ledger = call(sessions, "task_list", {}, invocation="intake-read:" + key + ":" + skill,
                  host=host, session=session)
    if not any(task["definition"]["evidence_contract"] == workflow for task in ledger["tasks"]):
        call(sessions, "task_define", {"tasks": [{"key": "task-" + workflow,
            "title": "Review authorized change", "goal": "Review an authorized change",
            "sources": [], "acceptance": ["The authorized workflow reaches its stated outcome"],
            "evidence_contract": workflow, "dependencies": []}],
            "expected_revision": ledger["revision"], "key": "intake-" + workflow},
            invocation="intake-define:" + key + ":" + skill, host=host, session=session)
    if alias:
        return call(sessions, "workflow_start", {"workflow_id": workflow, "kind": skill,
            "goal": "Review an authorized change", "initial_state": {"run_id": "run"}, "key": key}, invocation="start:" + key + ":" + skill, host=host, session=session)
    return call(sessions, "phase_start", {"workflow_id": workflow, "skill": skill,
        "north_star": "Review an authorized change", "run_id": "run", "key": key}, invocation="start:" + key + ":" + skill, host=host, session=session)


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
@pytest.mark.parametrize("alias", [False, True])
def test_registered_phase_initializes_without_cli_and_replays(sessions, monkeypatch, host, session, alias):
    from scripts.skill_harness.phase_runner import PhaseRunnerApplication
    monkeypatch.setattr(PhaseRunnerApplication, "run", lambda *a, **k: pytest.fail("CLI gateway"))
    call(sessions, "worktree_claim", {}, host=host, session=session)
    initialized = start(sessions, alias=alias, host=host, session=session)
    assert initialized["workflow_revision"] == 0
    assert initialized["current_phase"]["id"] == 1
    current = call(sessions, "phase_current", {"workflow_id": "phase"}, host=host, session=session)
    assert current["phase_id"] == 1
    assert "git_status" in current["required_evidence"]


def test_start_requires_registered_contract_and_owner(sessions):
    with pytest.raises(ValueError):
        start(sessions)
    call(sessions, "worktree_claim", {})
    with pytest.raises(ValueError, match="contracted|UNKNOWN"):
        start(sessions, skill="unregistered-command")
    with pytest.raises(ValueError, match="own"):
        start(sessions, host="claude-code", session="ui", key="other-owner")


def test_adaptive_phase_start_preserves_independent_evaluator_gate(sessions):
    call(sessions, "worktree_claim", {})
    with pytest.raises(ValueError, match="evaluator"):
        start(sessions, skill="plan-issues")
    state = call(sessions, "session_inspect", {})
    assert "phase" not in state["workflows"]


def test_phase_cannot_certify_completion_with_raw_string_evidence(sessions, monkeypatch):
    call(sessions, "worktree_claim", {})
    start(sessions)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    with pytest.raises(ValueError, match="evidence must reference"):
        call(sessions, "phase_complete", {"workflow_id": "phase", "expected_revision": 0,
            "phase_id": 1, "status": "completed", "summary": "claimed", "key": "complete",
            "evidence_refs": ["git_status=clean", "diff_review=passed"]})
    assert call(sessions, "phase_current", {"workflow_id": "phase"})["workflow_revision"] == 0


def test_phase_checks_execution_policy_before_semantic_helpers(sessions, monkeypatch):
    from scripts.skill_harness.phase_runner import PhaseRunner
    call(sessions, "worktree_claim", {})
    start(sessions)
    monkeypatch.setattr(PhaseRunner, "complete", lambda *a, **k: pytest.fail("unapproved execution"))
    with pytest.raises(ValueError, match="policy|native|MCP"):
        call(sessions, "phase_complete", {"workflow_id": "phase", "expected_revision": 0,
            "phase_id": 1, "status": "completed", "summary": "claimed", "key": "complete"})


def test_phase_failure_terminal_and_revision_are_enforced(sessions, monkeypatch):
    call(sessions, "worktree_claim", {})
    task_id = define_task(sessions)
    start(sessions)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    with pytest.raises(ValueError, match="revision"):
        call(sessions, "phase_complete", {"workflow_id": "phase", "expected_revision": 77,
            "phase_id": 1, "status": "blocked", "summary": "not executed", "reason": "fixture blocker", "key": "stale"})
    completed = call(sessions, "workflow_advance", {"workflow_id": "phase", "expected_revision": 0,
        "transition": {"phase_id": 1, "status": "blocked", "summary": "not executed", "reason": "fixture blocker"}, "key": "blocked"})
    finalized = call(sessions, "workflow_finalize", {"workflow_id": "phase", "expected_revision": completed["workflow_revision"], "terminal_state": "blocked", "key": "finalize"})
    assert finalized["terminal_state"] == "blocked"
    assessment = assess_task(sessions, task_id, finalized["workflow_revision"], "failed")
    resolved = call(sessions, "task_resolve", {"task_id": task_id, "expected_revision": 1,
        "expected_task_revision": 1, "key": "task-failed", "status": "failed",
        "references": [f"workflow:phase:{finalized['workflow_revision']}"], "assessment": assessment})
    assert resolved["tasks"][0]["status"] == "failed"
    assert resolved["all_terminal"]


def test_delegation_prepare_uses_bound_native_actor_and_conflicts(sessions, monkeypatch):
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver
    monkeypatch.setattr(RuntimeEnvironmentResolver, "resolve", lambda *a, **k: pytest.fail("MCP reused process environment"))
    prepared = call(sessions, "delegation_prepare", {"delegation_id": "child", "assignment": "Review a bounded change", "key": "prepare"})
    assert prepared["session_id"] == "api" and prepared["status"] == "prepared"
    with pytest.raises(ValueError, match="already waiting"):
        call(sessions, "delegation_prepare", {"delegation_id": "another", "assignment": "Other", "key": "another"}, invocation="another")


def test_independent_session_cannot_be_assigned_as_native_child(sessions):
    call(sessions, "worktree_claim", {})
    start(sessions)
    with pytest.raises(ValueError, match="separate peer"):
        call(sessions, "delegation_assign", {"workflow_id": "phase", "delegation_id": "forged-child",
            "target": "claude-code:ui", "assignment": "Review", "key": "assign"})


def test_report_and_consume_cannot_manufacture_missing_delegation(sessions):
    with pytest.raises(ValueError):
        call(sessions, "evaluation_report", {"delegation_id": "absent", "verdict": "pass", "summary": "claimed", "outcome_ref": "sha256:" + "a" * 64, "key": "report"})
    with pytest.raises(ValueError):
        call(sessions, "evaluation_consume", {"delegation_id": "absent", "key": "consume"})


def adaptive_candidate():
    from tests.runtime.agent_harness.test_adaptive_control_store import AdaptiveControlStoreTest
    return dict(AdaptiveControlStoreTest()._complete_state().to_payload())


def test_adaptive_schema_roundtrip_and_nested_injection():
    from neurath.runtime.task_schema import arguments
    candidate = adaptive_candidate()
    inputs = {"workflow_id": "phase", "expected_revision": 0, "state": candidate, "key": "replace"}
    assert arguments("adaptive_replace", inputs)["state"] == candidate
    candidate["contract"]["actor"] = "forged"
    with pytest.raises(ValueError, match="fields"):
        arguments("adaptive_replace", inputs)


def test_adaptive_unknown_receipts_do_not_become_authority(sessions):
    call(sessions, "worktree_claim", {})
    start(sessions)
    with pytest.raises(ValueError):
        call(sessions, "adaptive_replace", {"workflow_id": "phase", "expected_revision": 0,
            "state": adaptive_candidate(), "key": "forged-authority"})
    with pytest.raises(ValueError):
        call(sessions, "adaptive_read", {"workflow_id": "phase"})


def test_invalid_workflow_payload_and_identity_are_rejected(sessions):
    from neurath.runtime.task_schema import arguments
    for extra in ({"payload": {}}, {"actor": "foreign"}, {"argv": ["shell"]}):
        with pytest.raises(ValueError):
            arguments("workflow_start", {"workflow_id": "phase", "kind": "commit", "goal": "go", "initial_state": {"run_id": "run"}, "key": "start", **extra})
    with pytest.raises(ValueError):
        arguments("workflow_start", {"workflow_id": "phase", "kind": "commit", "goal": "go", "initial_state": {"run_id": "run", "adaptive_control": {}}, "key": "start"})


def test_prompt_change_during_phase_initialization_prevents_write(sessions, monkeypatch):
    from scripts.skill_harness.session_phase_store import SessionPhaseStateStore
    _, invoke = sessions
    call(sessions, "worktree_claim", {}, host="claude-code", session="ui")
    original = SessionPhaseStateStore.initialize
    def changed(store, state):
        assert invoke("claude-code", "ui", "UserPromptSubmit", prompt="Changed assignment")[0] == 0
        return original(store, state)
    monkeypatch.setattr(SessionPhaseStateStore, "initialize", changed)
    with pytest.raises(ValueError, match="prompt"):
        start(sessions, host="claude-code", session="ui")
    state = call(sessions, "session_inspect", {}, host="claude-code", session="ui")
    assert "phase" not in state["workflows"]


def test_finished_key_replay_does_not_initialize_twice(sessions, monkeypatch):
    from scripts.skill_harness.phase_runner import PhaseRunner
    call(sessions, "worktree_claim", {})
    initialized = start(sessions)
    monkeypatch.setattr(PhaseRunner, "initialize", lambda *a, **k: pytest.fail("replayed side effect"))
    replay = call(sessions, "phase_start", {"workflow_id": "phase", "skill": "commit", "north_star": "Review an authorized change", "run_id": "run", "key": "start"}, invocation="fresh-call-same-key")
    assert replay == initialized


def test_native_child_assignment_report_and_owner_consumption(sessions):
    root, invoke = sessions
    call(sessions, "worktree_claim", {})
    start(sessions)
    code, output, diagnostic = invoke("codex", "api", "PreToolUse", tool_name="spawn_agent", tool_use_id="spawn-child", turn_id="api-turn", tool_input={"task_name": "reviewer", "message": "Review the change"})
    assert code == 0, (output, diagnostic)
    assert invoke("codex", "api", "PostToolUse", tool_name="spawn_agent", tool_use_id="spawn-child", turn_id="api-turn", tool_response={"agent_id": "child", "task_name": "/root/reviewer"})[0] == 0
    transcript = root / "host-storage" / "child.jsonl"
    transcript.write_text(json.dumps({"type": "session_meta", "payload": {"id": "child", "session_id": "api", "parent_thread_id": "api", "agent_path": "/root/reviewer", "source": {"subagent": {"thread_spawn": {"parent_thread_id": "api"}}}}}) + "\n")
    assert invoke("codex", "api", "SubagentStart", agent_id="child", transcript_path=str(transcript), turn_id="child-turn")[0] == 0
    from neurath.agents.store import MessageStore
    peers = [item for item in MessageStore(root).discover() if item["actor"] == "codex:child"]
    assert len(peers) == 1
    assigned = call(sessions, "delegation_assign", {"workflow_id": "phase", "delegation_id": "review", "target": peers[0]["address"], "assignment": "Review the change", "key": "assign-child"})
    assert assigned["status"] == "pending"
    inputs = {"delegation_id": "review", "verdict": "changes-requested", "summary": "Need verification", "outcome_ref": "fixture-review", "key": "child-report"}
    code, output, diagnostic = invoke("codex", "api", "PreToolUse", agent_id="child", transcript_path=str(transcript), turn_id="child-turn", tool_name="mcp__neurath_collaboration__evaluation_report", tool_use_id="child-report", tool_input=inputs)
    assert code == 0, diagnostic
    result = mcp.call_tool(root, output["hookSpecificOutput"]["updatedInput"], name="evaluation_report")
    assert result["status"] == "reported"
    consumed = call(sessions, "evaluation_consume", {"delegation_id": "review", "key": "consume-child"})
    assert consumed["status"] == "consumed"
