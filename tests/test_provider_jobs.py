"""Nonblocking acceptance and event-based recovery, without native model calls."""

import subprocess
from types import SimpleNamespace

import pytest

from neurath.agents.store import AgentIdentity, MessageStore
from neurath.providers import jobs


@pytest.fixture
def owner(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    identity = AgentIdentity("codex", "creator", "codex:session:creator")
    MessageStore(tmp_path).register(identity)
    monkeypatch.setattr(jobs, "validate_target", lambda root, fields: tmp_path)
    return tmp_path, identity


def test_start_returns_without_waiting_for_provider_exit(owner, monkeypatch):
    root, identity = owner
    calls = []
    def launch(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(jobs, "_launch", launch)
    result = jobs.start(root, identity, {"worktree": str(root), "assignment": "Read", "mode": "read-only"}, key="one")
    assert result["status"] == "accepted"
    assert result["implementation_dispatched"] is False
    assert len(calls) == 1
    assert calls[0][1]["start_new_session"] is True
    assert result["run_id"]
    assert jobs.status(root, identity, result["run_id"])["status"] == "accepted"


def test_retry_has_one_worker_and_cannot_change_request(owner, monkeypatch):
    root, identity = owner
    calls = []
    from neurath.providers.job_recovery import JobRecovery
    leases = []
    def launch(argv, **kwargs):
        calls.append(argv)
        # A running worker owns its lease. An empty launch mock leaves admission
        # unconsumed, which is now intentionally eligible for reconciliation.
        leases.append(JobRecovery(jobs._store(root)).claim_worker(
            identity.address, argv[argv.index("--run-id") + 1]))
    monkeypatch.setattr(jobs, "_launch", launch)
    fields = {"worktree": str(root), "assignment": "Read", "mode": "read-only"}
    try:
        first = jobs.start(root, identity, fields, key="one")
        second = jobs.start(root, identity, fields, key="one")
        assert second["run_id"] == first["run_id"]
        assert len(calls) == 1
        with pytest.raises(ValueError, match="changed"):
            jobs.start(root, identity, {**fields, "assignment": "Different"}, key="one")
    finally:
        for lease in leases:
            lease.close()


def test_cancel_before_worker_start_is_durable_and_does_not_kill_arbitrary_pid(owner, monkeypatch):
    root, identity = owner
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: None)
    result = jobs.start(root, identity, {"worktree": str(root), "assignment": "Read", "mode": "read-only"}, key="one")
    assert jobs.cancel(root, identity, result["run_id"])["cancel_requested"] is True
    report = jobs.worker(root, result["run_id"])
    assert report["status"] == "cancelled"
    assert jobs.status(root, identity, result["run_id"])["status"] == "cancelled"
    assert "cancelled" in MessageStore(root).inbox(identity.address)[-1]["body"]


def test_other_actor_cannot_cancel_or_read_result(owner, monkeypatch):
    root, identity = owner
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: None)
    result = jobs.start(root, identity, {"worktree": str(root), "assignment": "Read", "mode": "read-only"}, key="one")
    other = AgentIdentity("codex", "other", "codex:session:other")
    for operation in (jobs.status, jobs.cancel):
        with pytest.raises(ValueError, match="owner"):
            operation(root, other, result["run_id"])


def test_worker_failure_is_persisted_and_returned_as_message(owner, monkeypatch):
    root, identity = owner
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: None)
    result = jobs.start(root, identity, {"worktree": str(root), "assignment": "Read", "mode": "read-only"}, key="one")
    def fail(*a, **k):
        raise RuntimeError("fixture transport failure")
    monkeypatch.setattr(jobs, "execute_session", fail)
    assert jobs.worker(root, result["run_id"])["status"] == "failed"
    saved = jobs.status(root, identity, result["run_id"])
    assert saved["result"]["status"] == "failed"
    assert "fixture transport failure" in MessageStore(root).inbox(identity.address)[-1]["body"]
    with pytest.raises(ValueError, match="already"):
        jobs.worker(root, result["run_id"])


def test_terminal_result_and_message_rollback_together(owner, monkeypatch):
    root, identity = owner
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: None)
    run = jobs.start(root, identity, {"worktree": str(root), "assignment": "Read"}, key="atomic")
    store = MessageStore(root)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("outbox unavailable")))
        with pytest.raises(RuntimeError, match="outbox"):
            jobs._finish(store, run["run_id"], {"status": "completed"})
    assert jobs.status(root, identity, run["run_id"])["status"] == "accepted"
    assert store.inbox(identity.address) == []
    jobs._finish(store, run["run_id"], {"status": "completed"})
    jobs._finish(store, run["run_id"], {"status": "failed"})
    assert jobs.status(root, identity, run["run_id"])["status"] == "completed"
    assert len(store.inbox(identity.address)) == 1


def test_launch_error_retains_run_id_and_failed_report(owner, monkeypatch):
    root, identity = owner
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: (_ for _ in ()).throw(OSError("launch failed")))
    run = jobs.start(root, identity, {"worktree": str(root), "assignment": "Read"}, key="launch")
    assert run["status"] == "failed"
    assert jobs.status(root, identity, run["run_id"])["result"]["run_id"] == run["run_id"]
    assert len(MessageStore(root).inbox(identity.address)) == 1


def test_launcher_reaps_its_exact_process_without_blocking_request(monkeypatch):
    import threading

    exited, reaped = threading.Event(), threading.Event()
    def wait():
        assert exited.wait(5)
        reaped.set()
    monkeypatch.setattr(jobs, "Popen", lambda *a, **k: SimpleNamespace(wait=wait))
    jobs._launch(["fixture"])
    assert not reaped.is_set()
    exited.set()
    assert reaped.wait(5)


def test_claude_native_writes_require_separate_worktree_target(monkeypatch):
    from neurath.providers import execution

    modes = []
    monkeypatch.setattr(execution, "_target", lambda root, worktree, mode: modes.append(mode))
    fields = {"provider": "claude-code", "worktree": "/work", "mode": "native", "permission_mode": "dontAsk"}
    jobs.validate_target("/root", fields)
    jobs.validate_target("/root", {**fields, "permission_mode": "plan"})
    assert modes == ["workspace-write", "read-only"]
