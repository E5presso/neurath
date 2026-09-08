"""Monitor faces expose owned jobs without supplying native identities or commands."""
import pytest
from neurath.runtime.task_schema import arguments
from tests.test_workflow_tasks import call
pytest_plugins = ["tests.test_agent_hooks"]


def test_monitor_tool_inputs_are_closed_and_do_not_accept_identity_or_resume_commands():
    inputs = {"workflow_id": "workflow", "repo": "example/project", "pr_number": 1, "key": "start"}
    arguments("monitor_start", inputs)
    for extra in ({"actor": "foreign"}, {"session_id": "foreign"}, {"resume_command": "anything"},
                  {"pid": 1}, {"state_path": "/foreign/state.json"}):
        with pytest.raises(ValueError):
            arguments("monitor_start", {**inputs, **extra})


def test_monitor_launch_is_not_attempted_before_native_policy(sessions, monkeypatch):
    import neurath.runtime.monitor_runtime as runtime
    monkeypatch.setattr(runtime, "start", lambda *a, **k: pytest.fail("unapproved launch"))
    with pytest.raises(ValueError, match="policy|native|MCP|claim|own"):
        call(sessions, "monitor_start", {"workflow_id": "workflow", "repo": "example/project", "pr_number": 1, "key": "start"})


def test_monitor_grant_rejects_unissued_run_and_secret(tmp_path):
    from neurath.runtime.monitor_runtime import accept_grant
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(ValueError, match="grant"):
        accept_grant(tmp_path, "0"*32, "not-issued")


def test_bound_resume_adapter_never_resolves_identity_from_worker_environment(monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime.monitor_runtime import BoundResumeAdapter
    from neurath.runtime.bundled_services import service
    module = service("monitor_resume")
    monkeypatch.setattr(module.AppServerResumeApplication, "resolve", lambda *a, **k: pytest.fail("worker environment identity"))
    observed = []
    monkeypatch.setattr(module, "resume_thread", lambda args, prompt: observed.append((args.thread_id,prompt)) or {
        "resume_status": "invoked", "turnId": "actual-turn", "completion": {"status": "completed"}})
    adapter = BoundResumeAdapter(SimpleNamespace(session_id="issued-owner", worktree="/fixture", app_server_socket_path="/fixture/socket"), True, policy_guard=lambda: None)
    result = adapter.resume({"claim_id": "claim", "event_id": "event", "snapshot": {"headRefOid": "a"*40}})
    assert result["turnId"] == "actual-turn"
    assert observed[0][0] == "issued-owner"
    assert "claim" in observed[0][1]


def test_owned_monitor_callback_starts_from_grant_and_returns_real_observation(sessions, monkeypatch):
    import os
    import time
    from neurath.runtime import monitor_runtime
    from neurath.runtime.bundled_services import service
    from tests.test_workflow_tasks import start
    root, _ = sessions
    call(sessions, "worktree_claim", {})
    start(sessions, skill="monitor-pr")
    binaries = root / "fixture-bin"
    binaries.mkdir()
    gh = binaries / "gh"
    gh.write_text('#!/usr/bin/env python3\nimport json,sys\nargs=sys.argv[1:]\n'
        'value={"state":"OPEN","headRefOid":"'+'a'*40+'","mergeStateStatus":"BLOCKED","reviewDecision":"REVIEW_REQUIRED","statusCheckRollup":[],"comments":[],"labels":[]} if args[:2]==["pr","view"] else {"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[],"pageInfo":{"hasNextPage":False}}}}}} if "graphql" in args else []\n'
        'print("2026-09-09T00:00:00Z" if "--jq" in args else json.dumps(value))\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries)+os.pathsep+os.environ["PATH"])
    def policy(root, identity, *args, **kwargs):
        return {"implementation_ready": True, "is_root": True, "actor": identity.actor,
            "native_session": identity.session, "provider": identity.host, "worktree": str(root)}
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", policy)
    # Handoff OS retirement has separate domain regressions. Here the native-hook
    # fixture exercises the actual process/grant/lease/readback callback path.
    monkeypatch.setattr(service("monitor_handoff").MonitorRuntimeHandoffService, "prepare", lambda *a, **k: {"state":"completed"})
    admitted = call(sessions, "monitor_start", {"workflow_id":"phase", "repo":"example/project",
        "pr_number":1, "observe_only":True, "once":True, "key":"start"})
    assert admitted["status"] == "accepted"
    store = monitor_runtime._store(root)
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        row = monitor_runtime._row(store, admitted["run_id"])
        if row["state"] in monitor_runtime.TERMINAL:
            break
        time.sleep(0.05)
    assert row["state"] == "completed", row.get("result")
    assert row["secret_hash"] == ""
    state = call(sessions, "session_inspect", {})
    subscription = state["workflows"]["phase"]["payload"]["skill_state"]["monitor_event_subscription"]
    assert subscription["runtime_id"] == admitted["run_id"]+"-1"
    assert subscription["pid"] == row["pid"]
    assert subscription["resume_adapter"] == "unavailable"
    with store.connection() as db:
        states = [r[0] for r in db.execute("SELECT e.state FROM task_events e JOIN task_links t ON t.id=e.task WHERE t.transport='monitor-service' ORDER BY e.sequence")]
        assert states == ["started", "completed"]
        required = db.execute("SELECT count(*) FROM required_messages r JOIN task_events e ON e.message=r.message JOIN task_links t ON t.id=e.task WHERE t.transport='monitor-service'").fetchone()[0]
        assert required == 2


def test_observe_only_adapter_never_inspects_or_resumes_claimed_turn(monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime.monitor_runtime import BoundResumeAdapter
    from neurath.runtime.bundled_services import service
    module = service("monitor_resume")
    monkeypatch.setattr(module, "inspect_turn", lambda *a: pytest.fail("observe-only resumed a thread"))
    monkeypatch.setattr(module, "find_claimed_turn", lambda *a: pytest.fail("observe-only resumed a thread"))
    adapter = BoundResumeAdapter(SimpleNamespace(), False)
    assert adapter.inspect_turn("turn") == {"inspect_status": "unsupported"}
    assert adapter.find_claimed_turn("claim", "event") == {"recovery_status": "unsupported"}


def test_bound_resume_parameters_preserve_native_policy():
    from types import SimpleNamespace
    from neurath.runtime.bundled_services import service
    module = service("monitor_resume")
    args = SimpleNamespace(thread_id="owner", cwd="/fixture", preserve_native_policy=True)
    class Client:
        def request(self, method, fields):
            if method == "thread/resume":
                assert fields == {"threadId": "owner", "cwd": "/fixture"}
            return {}
        def notify(self, *args):
            pass
    module.initialize_and_resume_thread(Client(), args)
    assert module.start_params(args, "event") == {"threadId":"owner", "cwd":"/fixture",
        "input":[{"type":"text", "text":"event"}]}


def test_bound_adapter_rechecks_policy_before_each_backend_action(monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime.monitor_runtime import BoundResumeAdapter
    from neurath.runtime.bundled_services import service
    module = service("monitor_resume")
    for name in ("resume_thread", "inspect_turn", "find_claimed_turn", "probe_thread"):
        monkeypatch.setattr(module, name, lambda *a: pytest.fail("changed policy reached backend"))
    def restricted():
        raise ValueError("native policy changed")
    adapter = BoundResumeAdapter(SimpleNamespace(), True, policy_guard=restricted)
    for action in (lambda: adapter.resume({}), lambda: adapter.inspect_turn("turn"),
                   lambda: adapter.find_claimed_turn("claim", "event"), adapter.probe):
        with pytest.raises(ValueError, match="policy changed"):
            action()


def test_current_monitor_policy_observes_idle_owner_and_rejects_later_restrictions(monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from neurath.runtime.monitor_runtime import _current_resume_policy
    evidence = {"approval_policy":"never", "sandbox_policy":{"type":"danger-full-access"},
                "collaboration_mode":"default"}
    grant = {"stages":{"policy":{"status":"verified", "evidence":evidence}}}
    row = {"worktree":"/fixture", "session":"owner", "host":"codex", "policy":json.dumps(grant), "cancel_requested":0}
    lease = SimpleNamespace(current=lambda: row)
    handle = SimpleNamespace(actor_id="owner", inspect=lambda: SimpleNamespace(foreground_turns={
        "owner":SimpleNamespace(vendor_turn_id="latest", status="idle")}))
    monkeypatch.setattr("neurath.hosts.identity.snapshot", lambda *a: {"host":"codex", "transcript":"native"})
    monkeypatch.setattr("neurath.hosts.identity._transcript", lambda *a: Path("native"))
    observed = []
    def policy(path, turn, root):
        observed.append(turn)
        return {"status":"verified", "evidence":dict(evidence)}
    monkeypatch.setattr("neurath.providers.readiness._codex_policy", policy)
    _current_resume_policy(handle, lease)
    assert observed == ["latest"]
    evidence["sandbox_policy"] = {"type":"read-only"}
    with pytest.raises(ValueError, match="policy changed"):
        _current_resume_policy(handle, lease)
    row["cancel_requested"] = 1
    with pytest.raises(ValueError, match="cancelled before resume"):
        _current_resume_policy(handle, lease)


def test_snapshot_transport_wait_is_bounded(monkeypatch):
    import subprocess
    from neurath.runtime.bundled_services import service
    module = service("monitor")
    def stalled(command, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(module.subprocess,"run",stalled)
    client=module.GitHubSnapshotClient("example/project",1)
    for operation in (client._json_command,client._text_command):
        with pytest.raises(subprocess.TimeoutExpired):
            operation(["gh","api"])
