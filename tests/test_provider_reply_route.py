"""Supervisor reports keep their sender and route follow-ups to observed native executors."""

from dataclasses import asdict
import json
import os

import pytest

from neurath.agents.store import AgentIdentity, MessageStore
from neurath.providers import jobs
from neurath.providers.contracts import Session

pytest_plugins = ["tests.test_agent_hooks"]


def run_report(sessions, monkeypatch, *, provider="claude-code", native="ui", issuer_host="codex", issuer_session="api", register_only=False, legacy=False, closure=True):
    root, invoke = sessions
    owner = AgentIdentity(issuer_host, issuer_session, issuer_host + ":session:" + issuer_session)
    monkeypatch.setattr(jobs, "validate_target", lambda *args: root)
    monkeypatch.setattr(jobs, "_launch", lambda *args, **kwargs: None)
    if register_only:
        MessageStore(root).register(AgentIdentity(provider, native, provider + ":session:" + native))
    if legacy:
        monkeypatch.setattr(jobs, "bind_executor", lambda *args: None)
        monkeypatch.setattr(jobs, "observe_created", lambda *args: None)
    created = Session(provider, "claude-agent-sdk" if provider == "claude-code" else "codex-app-server",
        native, str(root), None, "fixture-model", {"requested": {"mode": "read-only"}})
    def execute(*args, event_callback, **kwargs):
        event_callback("native-created", {"created": asdict(created)})
        event_callback("started", {"native_session": native})
        if not register_only:
            assert invoke(provider, native, "SessionEnd")[0] == 0
        result = {"status": "completed", "created": asdict(created), "text": "CHILD_REPORT_OK"}
        if closure:
            result["closure"] = {"native_session": native, "transport": created.transport,
                "connection_closed": True, "native_process_exited": True,
                "source": "owned-sdk-disconnect" if provider == "claude-code" else "owned-app-server-close",
                "reason": "transport-closed"}
        return result
    monkeypatch.setattr(jobs, "execute_session", execute)
    fields = {"provider": provider, "worktree": str(root), "assignment": "Observe", "mode": "read-only"}
    started = jobs.start(root, owner, fields, key="provider-report")
    jobs.worker(root, started["run_id"])
    store = MessageStore(root)
    report = [item for item in store.inbox(owner.address) if '"state":"completed"' in item["body"]][-1]
    return store, owner, report, started["run_id"]


@pytest.mark.parametrize("provider,native,issuer_host,issuer_session", [
    ("claude-code", "ui", "codex", "api"),
    ("codex", "api", "claude-code", "ui"),
])
def test_reply_to_completed_provider_report_reaches_actual_offline_executor(sessions, monkeypatch, provider, native, issuer_host, issuer_session):
    store, owner, report, _ = run_report(sessions, monkeypatch, provider=provider, native=native,
        issuer_host=issuer_host, issuer_session=issuer_session)
    assert report["sender"] == report["recipient"] == owner.address
    store.acknowledge(owner.address, report["id"])
    reply = store.reply(owner.address, report["id"], "Proceed with the follow-up", key="follow-up")
    assert reply["recipient"] == provider + ":" + native
    assert reply["sender"] == owner.address
    assert reply["conversation"] != report["conversation"]
    assert reply["reply_to"] == report["id"]
    assert reply["status"] == "queued"


def test_routed_reply_preserves_cause_idempotency_and_participant_privacy(sessions, monkeypatch):
    store, owner, report, _ = run_report(sessions, monkeypatch)
    reply = store.reply(owner.address, report["id"], "Follow up", key="next")
    assert store.reply(owner.address, report["id"], "Follow up", key="next") == reply
    with pytest.raises(ValueError, match="another message"):
        store.reply(owner.address, report["id"], "Changed", key="next")
    with pytest.raises(ValueError, match="participant"):
        store.message("claude-code:ui", report["id"])
    with pytest.raises(ValueError, match="participant"):
        store.conversation("claude-code:ui", report["conversation"])
    messages = store.inbox("claude-code:ui")
    assert [item["id"] for item in messages] == [reply["id"]]
    answer = store.reply("claude-code:ui", reply["id"], "Handled", key="handled")
    assert answer["recipient"] == owner.address
    assert answer["conversation"] == reply["conversation"]


def test_registry_entry_without_native_registration_cannot_establish_reply_route(sessions, monkeypatch):
    store, owner, report, _ = run_report(sessions, monkeypatch, native="unobserved", register_only=True)
    with pytest.raises(ValueError, match="reply route"):
        store.reply(owner.address, report["id"], "Do not guess identity", key="blocked")


def test_old_report_route_restores_from_closed_owned_generation_without_execution(sessions, monkeypatch):
    store, owner, report, run_id = run_report(sessions, monkeypatch, legacy=True)
    original = store.message(owner.address, report["id"])
    monkeypatch.setattr(jobs, "execute_session", lambda *a, **k: pytest.fail("route restoration executed a provider"))
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: pytest.fail("route restoration launched a worker"))
    followup = store.reply(owner.address, report["id"], "Continue after recovery", key="legacy-followup")
    assert followup["recipient"] == "claude-code:ui"
    assert followup["reply_to"] == report["id"]
    assert followup["conversation"] != report["conversation"]
    current = store.message(owner.address, report["id"])
    for field in ("id", "sender", "recipient", "conversation", "reply_to", "body"):
        assert current[field] == original[field]
    assert jobs.status(store.worktree, owner, run_id)["status"] == "completed"


def test_old_report_without_native_closure_remains_explicitly_unroutable(sessions, monkeypatch):
    store, owner, report, _ = run_report(sessions, monkeypatch, legacy=True, closure=False)
    with pytest.raises(ValueError, match="closure unverified"):
        store.reply(owner.address, report["id"], "Cannot assume process exit", key="missing-proof")
    assert store.inbox("claude-code:ui") == []


def test_legacy_route_refuses_live_worker_lease(sessions, monkeypatch):
    from neurath.providers.job_recovery import JobRecovery
    store, owner, report, run_id = run_report(sessions, monkeypatch, legacy=True)
    recovery = JobRecovery(store)
    descriptor = recovery._lock(run_id)
    try:
        with pytest.raises(ValueError, match="worker-live"):
            store.reply(owner.address, report["id"], "Do not adopt a live worker", key="live")
    finally:
        os.close(descriptor)
    assert store.reply(owner.address, report["id"], "Do not adopt a live worker", key="live")["recipient"] == "claude-code:ui"


def test_legacy_route_refuses_new_recovery_generation(sessions, monkeypatch):
    from neurath.providers.job_recovery import JobRecovery, ClosedTransportEvidence
    store, owner, report, run_id = run_report(sessions, monkeypatch, legacy=True)
    result = jobs.status(store.worktree, owner, run_id)["result"]
    evidence = ClosedTransportEvidence(generation=result["worker_generation"], issuer_active=True, **result["closure"])
    JobRecovery(store).recover(owner.address, run_id, "new-generation", evidence)
    with pytest.raises(ValueError, match="generation changed"):
        store.reply(owner.address, report["id"], "Do not race a new generation", key="stale")
    assert store.inbox("claude-code:ui") == []


def test_native_executor_is_not_granted_supervisor_reporting_authority(sessions, monkeypatch):
    from neurath.agents.lifecycle import TaskLifecycle
    store, owner, report, _ = run_report(sessions, monkeypatch)
    body = json.loads(report["body"].split(". ", 1)[1])
    assert body["executor"] == owner.address
    assert body["native_executor"] == "claude-code:ui"
    with pytest.raises(ValueError, match="bound executor"):
        TaskLifecycle(store).emit("claude-code:ui", body["task_id"], "error", key="spoofed-supervisor")


def test_routed_report_still_requires_full_body_before_reply(sessions, monkeypatch):
    from neurath.runtime.task_schema import arguments
    with pytest.raises(ValueError, match="unexpected"):
        arguments("collaboration_reply", {"message_id": "x", "message": "x", "key": "x", "reply_recipient": "forged"})
    store, owner, report, _ = run_report(sessions, monkeypatch)
    with pytest.raises(ValueError, match="recipient"):
        store.reply("claude-code:ui", report["id"], "Cannot impersonate parent", key="impersonation")


def test_new_generation_cannot_inherit_prior_created_as_fresh_route(sessions, monkeypatch):
    from neurath.providers.job_recovery import JobRecovery, ClosedTransportEvidence
    from neurath.providers.report_routing import bind_executor
    store, owner, _report, run_id = run_report(sessions, monkeypatch)
    prior = jobs.status(store.worktree, owner, run_id)["result"]
    recovery = JobRecovery(store)
    admission = recovery.recover(owner.address, run_id, "new-worker", ClosedTransportEvidence(
        generation=prior["worker_generation"], issuer_active=True, **prior["closure"]))
    with recovery.claim_worker(owner.address, run_id, generation=admission["admission"]["generation"]) as lease:
        with store.connection() as db:
            row = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
            assert bind_executor(store, row, json.loads(row["result"]), lease, db) is None


def test_reply_route_cannot_change_with_same_message_identity(sessions, monkeypatch):
    store, owner, report, _ = run_report(sessions, monkeypatch)
    with store.connection() as db:
        with pytest.raises(ValueError, match="immutable"):
            store._bind_reply_route(db, report["id"], owner.address)
    assert store.reply(owner.address, report["id"], "Still the same child", key="same-route")["recipient"] == "claude-code:ui"
