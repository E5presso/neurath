"""A created transport handle cannot grant activation, permissions or ownership."""

import json

import pytest

from neurath.providers import readiness
from tests.test_identity import runtime, start, native_turn_started  # noqa: F401


def stage(status="verified", reason=None):
    return {"status": status, "reason": reason, "evidence": {}}


def test_each_missing_stage_prevents_implementation_even_when_other_stages_pass():
    for key in ("installation", "activation", "policy", "ownership"):
        stages = {name: stage() for name in ("installation", "activation", "policy", "ownership")}
        stages[key] = stage("unobserved", "missing")
        assert readiness._assess(stages)["implementation_ready"] is False


def test_observation_and_approval_failures_coexist_without_becoming_generic_blocked():
    stages = {"installation": stage(), "activation": stage("failed", "registration-missing"),
              "policy": stage("unobserved", "policy-unobservable"),
              "ownership": stage("failed", "claim-conflict")}
    result = readiness._assess(stages, waiting="waiting-on-approval")
    assert result["waiting"] == "waiting-on-approval"
    assert result["stages"] == stages
    assert result["implementation_ready"] is False
    assert result["authority"] == "diagnostic"


def test_require_ready_rechecks_instead_of_accepting_a_saved_ready_object(monkeypatch):
    calls = []
    def inspect(root, *, requested_policy=None):
        calls.append(root)
        return {"implementation_ready": len(calls) == 1, "stages": {}}
    monkeypatch.setattr(readiness, "inspect_readiness", inspect)
    readiness.require_ready("/work")
    with pytest.raises(readiness.SessionNotReady):
        readiness.require_ready("/work")
    assert len(calls) == 2


@pytest.mark.parametrize("wrong", ["turn", "cwd", "missing"])
def test_policy_readback_requires_exact_current_native_turn_and_workspace(tmp_path, wrong):
    path = tmp_path / "native.jsonl"
    payload = {"turn_id": "current", "cwd": str(tmp_path), "approval_policy": "never",
               "sandbox_policy": {"type": "workspace-write", "network_access": False}}
    if wrong == "turn":
        payload["turn_id"] = "other"
    elif wrong == "cwd":
        payload["cwd"] = str(tmp_path.parent)
    else:
        del payload["sandbox_policy"]
    path.write_text(json.dumps({"type": "turn_context", "payload": payload}) + "\n")
    result = readiness._codex_policy(path, "current", tmp_path)
    assert result["status"] == "unobserved"


def test_policy_readback_reports_exact_values_without_normalizing_auto_review(tmp_path):
    path = tmp_path / "native.jsonl"
    payload = {"turn_id": "current", "cwd": str(tmp_path), "approval_policy": "on-request",
               "approvals_reviewer": "auto_review", "sandbox_policy": {"type": "danger-full-access"}}
    path.write_text(json.dumps({"type": "turn_context", "payload": payload}) + "\n")
    result = readiness._codex_policy(path, "current", tmp_path)
    assert result["status"] == "verified"
    assert result["evidence"]["approval_policy"] == "on-request"
    assert result["evidence"]["approvals_reviewer"] == "auto_review"
    assert result["evidence"]["sandbox_policy"] == {"type": "danger-full-access"}


def test_native_claude_policy_requires_current_invocation_binding():
    from neurath.agents.store import AgentIdentity
    identity = AgentIdentity("claude-code", "session", "actor")
    evidence = {"host": "claude-code", "session": "session", "actor": "actor",
                "turn": "turn", "tool_use_id": "tool-1", "permission_mode": "default"}
    observed = readiness._claude_policy(evidence, identity, "turn")
    assert observed["status"] == "verified"
    assert observed["evidence"]["sandbox_observation"] == "unobserved"
    for field in ("session", "actor", "turn", "host", "tool_use_id", "permission_mode"):
        bad = {**evidence, field: ""}
        assert readiness._claude_policy(bad, identity, "turn")["status"] == "failed"
    assert readiness._claude_policy(None, identity, "turn")["status"] == "unobserved"


def test_model_and_reasoning_are_observed_from_the_current_turn(tmp_path):
    path = tmp_path / "native.jsonl"
    payload = {"turn_id": "current", "cwd": str(tmp_path), "approval_policy": "never",
               "sandbox_policy": {"type": "danger-full-access"}, "model": "actual-model",
               "effort": "high"}
    path.write_text(json.dumps({"type": "turn_context", "payload": payload}) + "\n")
    evidence = readiness._codex_policy(path, "current", tmp_path)["evidence"]
    assert evidence["model"] == "actual-model"
    assert evidence["reasoning_effort"] == "high"


@pytest.mark.parametrize("policy", [
    {"permission_mode": "plan"}, {"sandbox_policy": {"type": "read-only"}},
    {"sandbox_policy": {"type": "danger-full-access"}, "collaboration_mode": "plan"},
])
def test_observed_plan_or_read_only_mode_is_not_implementation_permission(policy):
    stages = {name: stage() for name in ("installation", "activation", "policy", "ownership")}
    stages["policy"]["evidence"] = policy
    report = readiness._assess(stages)
    assert report["observation_ready"] is True
    assert report["implementation_ready"] is False


def test_new_claude_prompt_invalidates_same_generation_binding():
    from types import SimpleNamespace
    turn = SimpleNamespace(generation=1, vendor_turn_id=None,
        user_prompt_receipt=SimpleNamespace(turn_revision=2, prompt_digest="new"))
    evidence = {"user_prompt_receipt": {"turn_revision": 1, "prompt_digest": "old"}}
    assert readiness._prompt_matches(evidence, turn) is False
    assert readiness._prompt_matches({}, turn) is False
    evidence["user_prompt_receipt"] = {"turn_revision": 2, "prompt_digest": "new"}
    assert readiness._prompt_matches(evidence, turn) is True


@pytest.fixture(params=["codex", "claude-code"])
def native_child(runtime, request):
    from neurath.agents import mcp
    from neurath.hosts.identity import _state
    from neurath.memory.store import canonical

    root, storage, transcript, send = runtime
    host = request.param
    start(send, host)
    if host == "codex":
        code, _, diagnostic = send(host, "PreToolUse", tool_name="spawn_agent", tool_use_id="spawn",
             turn_id="parent-turn", tool_input={"task_name": "worker", "message": "Inspect only"})
        assert code == 0, diagnostic
        code, _, diagnostic = send(host, "PostToolUse", tool_name="spawn_agent", tool_use_id="spawn",
             turn_id="parent-turn",
             tool_input={"task_name": "worker", "message": "Inspect only"},
             tool_response='{"agent_id":"child"}')
        assert code == 0, diagnostic
        transcript = storage / "child.jsonl"
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "child", "session_id": "root", "parent_thread_id": "root",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}}}) + "\n")
    else:
        code, output, diagnostic = send(host, "PreToolUse", tool_name="Agent", tool_use_id="spawn",
            tool_input={"prompt": "Inspect only", "subagent_type": "general-purpose"})
        assert code == 0, diagnostic
        path = storage / "root/subagents/agent-child.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "user", "agentId": "child", "sessionId": "root",
            "isSidechain": True, "message": {"content": output["hookSpecificOutput"]["updatedInput"]["prompt"]}}) + "\n")
    code, _, diagnostic = send(host, "SubagentStart", agent_id="child",
                               transcript_path=str(transcript), turn_id="child")
    assert code == 0, diagnostic
    if host == "codex":
        native_turn_started(transcript, "child-turn")
        code, _, diagnostic = send(host, "UserPromptSubmit", agent_id="child",
            transcript_path=str(transcript), turn_id="child-turn", prompt="Inspect only")
        assert code == 0, diagnostic
    code, output, diagnostic = send(host, "PreToolUse", agent_id="child",
        transcript_path=str(transcript), tool_name="mcp__neurath_collaboration__session_status",
        tool_use_id="child-status", tool_input={}, permission_mode="default")
    assert code == 0, diagnostic
    state = _state(root, "root")
    actor = state.actors[f"{host}:child"]
    turn = state.foreground_turns[actor.id]
    return root, mcp.AgentIdentity(host, "root", str(actor.id), False), canonical([
        turn.generation, turn.vendor_turn_id]), output["hookSpecificOutput"]["updatedInput"]


def test_child_status_observes_attestation_without_borrowing_root_authority(native_child):
    from neurath.agents import mcp
    from neurath.runtime.tasks import _verification_owner
    from neurath.runtime.task_schema import TaskError

    root, identity, _, bound = native_child
    report = mcp.call_tool(root, bound, name="session_status")
    assert report["stages"]["activation"]["status"] == "verified"
    assert report["stages"]["activation"]["evidence"]["actor"] == identity.actor
    assert report["implementation_ready"] is False
    assert report["stages"]["ownership"]["status"] != "verified"
    if identity.host == "codex":
        assert report["mode"]["status"] == "unobserved"  # Do not copy the parent's policy.
    else:
        assert report["mode"]["effective"]["permission_mode"] == "default"
    operations = report["capabilities"][0]["operations"]
    assert operations["memory_recall"]["available"] is True
    for name in ("memory_checkpoint", "verification_run", "provider_run"):
        assert operations[name]["available"] is False
    assert not any(action["stage"] == "activation" for action in report["next_actions"])
    with pytest.raises(TaskError, match="native root"):
        _verification_owner(root, identity)


@pytest.mark.parametrize("invalid", ["stale-turn", "disconnected", "unattested", "wrong-parent", "stopped"])
def test_child_diagnostics_reject_stale_or_unattested_activation(native_child, monkeypatch, invalid):
    from neurath.hosts import identity as host_identity
    from scripts.agent_harness import session_kernel as kernel
    from neurath.runtime.tasks import session_status

    root, identity, turn, _ = native_child
    if invalid == "stale-turn":
        turn = "stale"
    elif invalid == "disconnected":
        monkeypatch.setattr(host_identity, "active_connection", lambda *_: False)
    else:
        state = host_identity._state(root, identity.session)
        actor = state.actors[identity.actor]
        fields = ({"lineage_assurance": kernel.ActorLineageAssurance.UNATTESTED}
                  if invalid == "unattested" else {"parent_actor_id": None}
                  if invalid == "wrong-parent" else {"status": kernel.ActorStatus.STOPPED})
        changed = kernel.ActorRecord(**{**{("actor_id" if name == "id" else name): getattr(actor, name)
            for name in actor.__slots__}, **fields})
        state = kernel.ProcessState(**{**{name: getattr(state, name) for name in state.__slots__},
                                       "actors": {**state.actors, actor.id: changed}})
        monkeypatch.setattr(kernel.SessionKernel, "inspect", lambda *_: state)
    report = session_status(root, identity=identity, expected_turn=turn)
    assert report["stages"]["activation"]["status"] == "failed"
    assert report["implementation_ready"] is False
    assert report["capabilities"][0]["operations"]["memory_recall"]["available"] is False
