"""Durable lifecycle reports are messages, not recurring status scans."""

import subprocess

import pytest

from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import AgentIdentity, MessageStore


@pytest.fixture
def lifecycle(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = MessageStore(tmp_path)
    for host, session in (("codex", "issuer"), ("claude-code", "worker"), ("codex", "other")):
        store.register(AgentIdentity(host, session, f"{host}:session:{session}"))
    return store, TaskLifecycle(store)


def test_binding_is_durable_and_does_not_claim_execution_started(lifecycle):
    store, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    assert task["state"] == "assigned"
    assert store.inbox("codex:issuer") == []
    assert TaskLifecycle(MessageStore(store.worktree)).read("codex:issuer", task["id"]) == task


def test_actual_lifecycle_events_return_to_issuer_in_order(lifecycle):
    store, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    for event in ("started", "waiting", "started", "completed"):
        tasks.emit("claude-code:worker", task["id"], event, key=f"{event}-{len(store.inbox('codex:issuer'))}")
    reports = store.inbox("codex:issuer")
    assert len(reports) == 4
    assert all(row["sender"] == "claude-code:worker" for row in reports)
    assert "completed" in reports[-1]["body"]
    assert "not result acceptance" in reports[-1]["body"]
    assert tasks.read("codex:issuer", task["id"])["state"] == "completed"


def test_replayed_completion_is_one_message_and_ack_is_separate(lifecycle):
    store, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    first = tasks.emit("claude-code:worker", task["id"], "completed", key="terminal")
    assert tasks.emit("claude-code:worker", task["id"], "completed", key="terminal") == first
    assert len(store.inbox("codex:issuer")) == 1
    store.acknowledge("codex:issuer", first["message"]["id"])
    assert tasks.read("codex:issuer", task["id"])["reports"][-1]["delivery"] == "received"


def test_only_bound_executor_can_report(lifecycle):
    _, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    with pytest.raises(ValueError, match="executor"):
        tasks.emit("codex:other", task["id"], "completed", key="spoof")
    with pytest.raises(ValueError, match="participant"):
        tasks.read("codex:other", task["id"])


def test_idempotency_cannot_retarget_assignment_or_change_event(lifecycle):
    _, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    with pytest.raises(ValueError, match="changed"):
        tasks.bind("codex:issuer", "codex:other", key="assignment-1", transport="native")
    tasks.emit("claude-code:worker", task["id"], "failed", key="terminal")
    with pytest.raises(ValueError, match="changed"):
        tasks.emit("claude-code:worker", task["id"], "completed", key="terminal")


def test_late_start_cannot_revive_completed_assignment(lifecycle):
    _, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    tasks.emit("claude-code:worker", task["id"], "cancelled", key="terminal")
    with pytest.raises(ValueError, match="terminal"):
        tasks.emit("claude-code:worker", task["id"], "started", key="late-start")


def test_idle_creator_keeps_report_and_exact_existing_thread_notification(lifecycle):
    store, tasks = lifecycle
    store.register(AgentIdentity("codex", "issuer", "codex:session:issuer"), status="idle")
    task = tasks.bind("codex:issuer", "claude-code:worker", key="assignment-1", transport="native")
    report = tasks.emit("claude-code:worker", task["id"], "failed", key="failure")
    forward = store.forward("claude-code:worker", report["message"]["id"])
    assert forward["arguments"]["threadId"] == "issuer"
    assert forward["tool"] == "send_message_to_thread"
    assert report["message"]["status"] == "queued"


def test_unrelated_message_does_not_implicitly_create_an_assignment(lifecycle):
    store, tasks = lifecycle
    store.send("codex:issuer", "claude-code:worker", "A question", key="question")
    assert tasks.active("claude-code:worker") == []


def test_failed_acceptance_does_not_bind_a_turn(lifecycle, monkeypatch):
    store, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="atomic", transport="native")
    monkeypatch.setattr(store, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("outbox unavailable")))
    with pytest.raises(RuntimeError, match="outbox"):
        tasks.accept("claude-code:worker", task["id"], "actual-turn")
    saved = tasks.read("codex:issuer", task["id"])
    assert saved["turn"] == ""
    assert saved["state"] == "assigned"


def test_named_mcp_message_operations_preserve_native_recipient(lifecycle):
    from neurath.runtime.tasks import execute

    store, _ = lifecycle
    issuer = AgentIdentity("codex", "issuer", "codex:session:issuer")
    executor = AgentIdentity("claude-code", "worker", "claude-code:session:worker")
    report = store.send(executor.address, issuer.address, "Finished", key="native-message")
    args = {"message_id": report["id"]}
    route = execute(store.worktree, "collaboration_forward", args, identity=executor)
    assert route["arguments"]["threadId"] == issuer.session
    assert execute(store.worktree, "collaboration_message", args, identity=issuer)["body"] == "Finished"
    assert execute(store.worktree, "collaboration_ack", args, identity=issuer)["status"] == "received"
    with pytest.raises(ValueError):
        execute(store.worktree, "collaboration_ack", args, identity=executor)


def test_assignment_and_initial_message_are_atomic(lifecycle, monkeypatch):
    from neurath.runtime.tasks import execute

    store, tasks = lifecycle
    issuer = AgentIdentity("codex", "issuer", "codex:session:issuer")
    monkeypatch.setattr(MessageStore, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("outbox unavailable")))
    with pytest.raises(RuntimeError, match="outbox"):
        execute(store.worktree, "collaboration_assign",
            {"to": "claude-code:worker", "message": "Read", "key": "atomic-assignment"}, identity=issuer)
    assert tasks.active("claude-code:worker") == []


def test_required_report_survives_offline_issuer_until_ack(lifecycle, monkeypatch):
    import time

    store, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="offline", transport="native")
    report = tasks.emit("claude-code:worker", task["id"], "completed", key="finished")["message"]
    ordinary = store.send("claude-code:worker", "codex:issuer", "Temporary question", key="temporary")
    later = time.time() + 604801
    monkeypatch.setattr(time, "time", lambda: later)
    assert [message["id"] for message in store.inbox("codex:issuer")] == [report["id"], ordinary["id"]]
    assert store.forward("claude-code:worker", report["id"])["status"] == "prepared"
    assert store.forward("claude-code:worker", ordinary["id"])["status"] == "prepared"
    store.acknowledge("codex:issuer", ordinary["id"])
    store.acknowledge("codex:issuer", report["id"])
    assert store.inbox("codex:issuer") == []
    reply = store.reply("codex:issuer", report["id"], "Result reviewed", key="reviewed")
    assert [message["id"] for message in store.inbox("claude-code:worker")] == [reply["id"]]
    assert store.forward("codex:issuer", reply["id"])["status"] == "discovery-required"
    store.acknowledge("claude-code:worker", reply["id"])
    assert store.inbox("claude-code:worker") == []


def test_explicit_accept_after_disconnect_binds_new_turn(lifecycle):
    _, tasks = lifecycle
    task = tasks.bind("codex:issuer", "claude-code:worker", key="resume", transport="peer-assignment")
    tasks.accept("claude-code:worker", task["id"], "turn-1")
    with pytest.raises(ValueError, match="another native turn"):
        tasks.accept("claude-code:worker", task["id"], "turn-2")
    tasks.emit("claude-code:worker", task["id"], "disconnected", key="disconnect-1")
    tasks.accept("claude-code:worker", task["id"], "turn-2")
    assert tasks.read("codex:issuer", task["id"])["turn"] == "turn-2"
    tasks.emit("claude-code:worker", task["id"], "disconnected", key="disconnect-2")
    with pytest.raises(ValueError, match="previous native turn"):
        tasks.accept("claude-code:worker", task["id"], "turn-1")
