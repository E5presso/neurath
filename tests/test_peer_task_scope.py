"""Native child scope on peer turns must come from an explicit existing user task."""
import json

import pytest

from tests.test_identity import start, peer_root_metadata, native_peer_delivery, native_turn_started
from tests.test_task_ledger_service import item

pytest_plugins = ["tests.test_identity"]


def setup_peer(runtime):
    from scripts.agent_harness import session_kernel as sk
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    from scripts.agent_harness.task_service import TaskService

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    locator = sk.SessionLocator.from_worktree(root)
    kernel = sk.SessionKernel(locator)
    state = kernel.inspect(sk.SessionId("root"))
    handle = StateHandle.attach(locator, RuntimeIdentityBinding(runtime=sk.SessionRuntime.CODEX,
        session_id=state.session.id, actor_id=state.session.root_actor_id,
        root_actor_id=state.session.root_actor_id))
    store = TaskService(handle, worktree=root)
    first = store.define([item()], expected_revision=0, key="original")
    source = first["tasks"][0]["definition"]["sources"][0]
    store.resolve(first["tasks"][0]["id"], expected_revision=1, expected_task_revision=1,
        key="old-result", references=["test:old"], status="succeeded", summary="Original result")
    assert send("codex", "Stop", stop_hook_active=False, last_assistant_message="Done")[0] == 0
    native_turn_started(transcript, "peer-turn")
    native_peer_delivery(transcript, "peer-turn")
    code, _, diagnostic = send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="peer-read",
        tool_name="mcp__codex_app__read_thread", tool_input={})
    assert code == 0, diagnostic
    new = item("continuation"); new["sources"] = [source]
    defined = store.define([new], expected_revision=2, key="continue")
    task = defined["tasks"][-1]
    started = store.start(task["id"], expected_revision=3, expected_task_revision=1, key="start")
    return store, kernel, started["tasks"][-1]


def prepare(store, task):
    from neurath.hosts.identity import prepare_bound_delegation
    return prepare_bound_delegation(store.worktree, store.handle, "inspect", "Inspect the user task",
        task_id=task["id"], expected_task_revision=task["revision"])


def spawn(send, event="PreToolUse"):
    return send("codex", event, turn_id="peer-turn", tool_name="collaborationspawn_agent",
        tool_use_id="spawn", tool_input={"task_name": "child", "message": "Inspect the user task"},
        **({"tool_response": '{"task_name":"/root/child"}'} if event == "PostToolUse" else {}))


def test_scoped_peer_task_prepares_spawns_and_attests_without_user_prompt(runtime):
    from neurath.hosts.identity import attest_child, snapshot
    root, storage, _, send = runtime
    store, _, task = setup_peer(runtime)
    assert prepare(store, task)["status"] == "prepared"
    assert spawn(send)[0] == 0
    assert spawn(send, "PostToolUse")[0] == 0
    child = storage / "child.jsonl"
    child.write_text(json.dumps({"type": "session_meta", "payload": {"id": "child",
        "session_id": "root", "parent_thread_id": "root", "agent_path": "/root/child",
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}}}) + "\n")
    proof = attest_child(root, "codex", {"session_id": "root", "agent_id": "child",
        "transcript_path": str(child), "turn_id": "child-turn"}, {})
    assert proof is not None
    assert proof["foreground"]["prompt"] is None
    assert proof["foreground"]["task_scope"]["task_id"] == task["id"]
    assert store.list()["current_prompt_source"] is None
    assert snapshot(root, "root")["intents"]["inspect"]["call_id"] == "spawn"
    code, _, diagnostic = send("codex", "SubagentStart", agent_id="child",
        transcript_path=str(child), turn_id="child-turn")
    assert code == 0, diagnostic
    from neurath.hosts.identity import _state, attach_delegation
    assert "inspect" in _state(root, "root").delegations
    store.resolve(task["id"], expected_revision=4, expected_task_revision=2, key="finished",
        references=["test:done"], status="succeeded", summary="Task complete")
    with pytest.raises(ValueError, match="task scope"):
        attach_delegation(root, "codex", {"session_id": "root", "agent_id": "child"})
    # An already-issued child must still be able to return its result after
    # the parent task ends; this does not authorize further task execution.
    assert attach_delegation(root, "codex", {"session_id": "root", "agent_id": "child",
        "tool_name": "mcp__neurath_collaboration__evaluation_report"}) == "inspect"


@pytest.mark.parametrize("invalid", ["missing-scope", "foreign-task", "stale-revision", "completed", "disconnected", "migrated"])
def test_peer_child_preparation_rejects_invalid_task_scope(runtime, invalid):
    from neurath.hosts.identity import prepare_bound_delegation, record_disconnect, snapshot
    store, _, task = setup_peer(runtime)
    kwargs = {"task_id": task["id"], "expected_task_revision": task["revision"]}
    if invalid == "missing-scope": kwargs = {}
    elif invalid == "foreign-task": kwargs["task_id"] = "task-from-another-root"
    elif invalid == "stale-revision": kwargs["expected_task_revision"] += 1
    elif invalid == "completed":
        store.resolve(task["id"], expected_revision=4, expected_task_revision=2, key="finished",
            references=["test:done"], status="succeeded", summary="Task is complete")
    elif invalid == "disconnected":
        record_disconnect(store.worktree, "codex", {"session_id": "root"})
    else:
        with store.database.transaction() as tx:
            tx.put("session-migration", "root", b'{}', expected_revision=None)
    with pytest.raises(ValueError):
        prepare_bound_delegation(store.worktree, store.handle, "inspect", "Inspect", **kwargs)
    assert not snapshot(store.worktree, "root").get("intents")


def test_prepared_task_completion_prevents_later_spawn(runtime):
    store, _, task = setup_peer(runtime)
    prepare(store, task)
    store.resolve(task["id"], expected_revision=4, expected_task_revision=2, key="finished",
        references=["test:done"], status="succeeded", summary="Task is complete")
    assert spawn(runtime[3])[0] != 0


def test_native_api_accepts_optional_exact_task_selector():
    from neurath.runtime.task_schema import arguments
    fields = arguments("delegation_prepare", {"delegation_id": "child", "assignment": "Read",
        "key": "prepare", "task_id": "task-id", "expected_task_revision": 2})
    assert fields["expected_task_revision"] == 2
    original = arguments("delegation_prepare", {"delegation_id": "child", "assignment": "Read",
        "key": "legacy-prepare"})
    assert original["task_id"] is None and original["expected_task_revision"] is None


def test_task_resolution_between_scope_check_and_intent_commit_rejects(runtime, monkeypatch):
    from neurath.hosts import identity
    store, _, task = setup_peer(runtime)
    original = identity._foreground
    fired = False
    def resolve_after_check(*args, **kwargs):
        nonlocal fired
        result = original(*args, **kwargs)
        if kwargs.get("task_scope") and not fired:
            fired = True
            store.resolve(task["id"], expected_revision=4, expected_task_revision=2, key="racing-result",
                references=["test:race"], status="succeeded", summary="Finished concurrently")
        return result
    monkeypatch.setattr(identity, "_foreground", resolve_after_check)
    with pytest.raises(ValueError, match="in-progress task"):
        prepare(store, task)
    assert not identity.snapshot(store.worktree, "root").get("intents")


def test_peer_task_scope_is_not_reused_on_another_native_turn(runtime):
    from neurath.hosts import identity
    from scripts.agent_harness import session_kernel as sk
    store, kernel, task = setup_peer(runtime)
    prepare(store, task)
    before = kernel.inspect(sk.SessionId("root"))
    turn = before.foreground_turns[before.session.root_actor_id]
    replaced = kernel.apply(sk.ForegroundTurnReplaced(session_id=before.session.id,
        actor_id=before.session.root_actor_id, expected_turn_revision=turn.revision,
        replacement_reference="codex-turn:another-peer", idempotency_key="replace"))
    after = kernel.apply(sk.ForegroundTurnPrompted(session_id=before.session.id,
        actor_id=before.session.root_actor_id, vendor_turn_id="another-peer",
        prompt_digest=None, idempotency_key="another-peer"), expected_revision=replaced.revision)
    intent = identity.snapshot(store.worktree, "root")["intents"]["inspect"]
    assert not identity._valid_record_foreground(store.worktree, after, intent)


def test_scope_is_rechecked_atomically_when_registering_delegation(runtime, monkeypatch):
    from scripts.agent_harness import session_kernel as sk
    root, storage, _, send = runtime
    store, kernel, task = setup_peer(runtime)
    prepare(store, task)
    assert spawn(send)[0] == 0
    assert spawn(send, "PostToolUse")[0] == 0
    child = storage / "child.jsonl"
    child.write_text(json.dumps({"type": "session_meta", "payload": {"id": "child",
        "session_id": "root", "parent_thread_id": "root", "agent_path": "/root/child",
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}}}) + "\n")
    original = sk.SessionKernel.apply
    fired = False
    def racing_apply(self, event, *args, **kwargs):
        nonlocal fired
        if isinstance(event, sk.DelegationAssigned) and not fired:
            fired = True
            store.resolve(task["id"], expected_revision=4, expected_task_revision=2,
                key="racing-result", references=["test:race"], status="succeeded", summary="Task finished")
        return original(self, event, *args, **kwargs)
    monkeypatch.setattr(sk.SessionKernel, "apply", racing_apply)
    with pytest.raises(sk.TransitionRejected, match="native task scope"):
        send("codex", "SubagentStart", agent_id="child",
            transcript_path=str(child), turn_id="child-turn")
    assert fired
    assert "inspect" not in kernel.inspect(sk.SessionId("root")).delegations
