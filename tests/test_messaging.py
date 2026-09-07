"""Peer communication crosses sessions, never their state authority."""

import concurrent.futures
import json
import subprocess

import pytest

from neurath.agents.store import AgentIdentity, MessageStore


@pytest.fixture
def peers(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = MessageStore(tmp_path)
    identities = [
        AgentIdentity("codex", "api", "api-root"),
        AgentIdentity("claude-code", "ui", "ui-root"),
        AgentIdentity("codex", "qa", "qa-child"),
    ]
    for identity, name in zip(identities, ("API", "UI", "QA")):
        store.register(identity, name=name)
    return store, *(i.address for i in identities)


def test_round_trip_survives_reopening_and_requires_recipient_ack(peers):
    store, a, b, c = peers
    sent = store.send(a, b, "Response schema?", key="question-1")
    reopened = MessageStore(store.worktree)
    assert reopened.inbox(b)[0]["id"] == sent["id"]
    assert reopened.message(a, sent["id"])["status"] == "queued"
    with pytest.raises(ValueError, match="recipient"):
        reopened.acknowledge(c, sent["id"])
    answer = reopened.reply(b, sent["id"], "Use cursor pagination", key="answer-1")
    assert answer["conversation"] == sent["conversation"]
    assert answer["reply_to"] == sent["id"]
    assert reopened.inbox(a)[0]["body"] == "Use cursor pagination"
    assert reopened.inbox(b) == []
    assert reopened.message(a, sent["id"])["status"] == "replied"


def test_retry_is_idempotent_under_concurrent_senders(peers):
    store, a, b, _ = peers

    def send(_):
        return MessageStore(store.worktree).send(a, b, "Once", key="same")["id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        assert len(set(pool.map(send, range(12)))) == 1
    assert len(store.inbox(b)) == 1
    with pytest.raises(ValueError, match="reused"):
        store.send(a, b, "Changed", key="same")


def test_conversation_scope_budget_and_close(peers):
    store, a, b, c = peers
    first = store.send(a, b, "Question", key="one", max_messages=2)
    with pytest.raises(ValueError, match="participant"):
        store.conversation(c, first["conversation"])
    answer = store.reply(b, first["id"], "Answer", key="two")
    with pytest.raises(ValueError, match="budget"):
        store.reply(a, answer["id"], "Again", key="three")
    store.close(b, first["conversation"])
    with pytest.raises(ValueError, match="closed"):
        store.reply(a, answer["id"], "Again", key="four")


def test_unknown_and_cross_project_destinations_rejected(peers, tmp_path):
    store, a, b, _ = peers
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    with pytest.raises(ValueError, match="unknown"):
        MessageStore(other).send(a, b, "Cross project", key="x")
    with pytest.raises(ValueError, match="unknown"):
        store.send(a, "missing", "Unknown", key="x")


def test_subscription_delivers_changes_only_to_subscribers(peers):
    store, a, b, c = peers
    store.subscribe(b, a)
    store.publish(a, "API schema changed", key="change-1")
    store.publish(a, "API schema changed", key="change-1")
    assert len(store.inbox(b)) == 1
    assert store.inbox(c) == []
    store.subscribe(b, a, enabled=False)
    store.publish(a, "Another change", key="change-2")
    assert len(store.inbox(b)) == 1


def test_native_transport_is_submission_not_receipt(peers):
    store, a, b, _ = peers
    question = store.send(b, a, "Review UI API", key="q")
    delivery = store.forward(b, question["id"])
    assert delivery["tool"] == "send_message_to_thread"
    assert delivery["arguments"]["threadId"] == "api"
    assert "peer-request" in delivery["arguments"]["prompt"]
    store.submitted(b, question["id"], transport="codex-app")
    assert store.message(b, question["id"])["status"] == "submitted"
    assert store.inbox(a)[0]["id"] == question["id"]
    store.acknowledge(a, question["id"])
    assert store.message(b, question["id"])["status"] == "received"
    reply = store.reply(a, question["id"], "OK", key="r")
    assert store.forward(a, reply["id"])["status"] == "discovery-required"
    assert store.message(a, reply["id"])["status"] == "queued"


def test_hook_delivery_is_bounded_and_does_not_acknowledge(peers):
    store, a, b, _ = peers
    sent = store.send(a, b, "x" * 30000, key="long")
    context = store.context(b, max_bytes=6000)
    assert len(context.encode()) <= 6000
    assert sent["id"] in context
    assert "peer-request" in context
    assert store.message(a, sent["id"])["status"] == "queued"


def test_symlink_database_is_rejected(peers, tmp_path):
    store, *_ = peers
    store.path.unlink()
    target = tmp_path / "do-not-write"
    target.write_text("private")
    store.path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        MessageStore(store.worktree)
    assert target.read_text() == "private"


def test_targeted_inbox_filters_before_limit_and_closed_conversation_cannot_wake(peers):
    store, a, b, _ = peers
    for i in range(4):
        store.send(a, b, "Earlier", key=f"earlier-{i}")
    last = store.send(a, b, "Targeted", key="targeted")
    assert store.inbox(b, limit=1, conversation=last["conversation"])[0]["id"] == last["id"]
    store.close(b, last["conversation"])
    with pytest.raises(ValueError, match="closed"):
        store.forward(a, last["id"])


def test_shared_worktree_control_root(peers):
    store, a, b, _ = peers
    subprocess.run(
        [
            "git",
            "-C",
            str(store.worktree),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "Init",
        ],
        check=True,
    )
    linked = store.worktree / "linked"
    subprocess.run(
        ["git", "-C", str(store.worktree), "worktree", "add", "--detach", str(linked)],
        check=True,
        capture_output=True,
    )
    MessageStore(linked).send(a, b, "From linked worktree", key="linked")
    assert store.inbox(b)[0]["body"] == "From linked worktree"


def test_install_exposes_peer_tools_without_changing_permissions(tmp_path):
    from neurath.install.transaction import apply_plan, make_plan

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    config = tmp_path / ".claude/settings.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"permissions": {"deny": ["Bash(rm *)"]}}))
    apply_plan(tmp_path, make_plan(tmp_path))
    assert "agent send" in (tmp_path / ".neurath/policy.md").read_text()
    assert "delegate run" in (tmp_path / ".neurath/policy.md").read_text()
    assert json.loads(config.read_text())["permissions"] == {"deny": ["Bash(rm *)"]}
