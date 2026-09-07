"""Adversarial simulated host records; live host evidence is recorded separately."""

import json
import subprocess

import pytest

from neurath.runtime.engine import activate
from neurath.hosts.hooks import hook
from neurath.install.transaction import apply_plan, make_plan


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from neurath.hosts import identity

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    activate(tmp_path)
    storage = tmp_path / "host-storage"
    storage.mkdir()
    monkeypatch.setattr(identity, "host_storage", lambda host, env: storage)
    transcript = storage / "root.jsonl"
    transcript.write_text("")
    env = {}

    def send(host, event, **fields):
        return hook(
            tmp_path,
            host,
            json.dumps(
                {
                    "session_id": "root",
                    "cwd": str(tmp_path),
                    "transcript_path": str(transcript),
                    "hook_event_name": event,
                    **fields,
                }
            ),
            env,
        )

    return tmp_path, storage, transcript, send


def start(send, host):
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert (
        send(host, "UserPromptSubmit", prompt="Review the fixture", turn_id="parent-turn")[0] == 0
    )


def test_claude_spawn_nonce_binds_only_one_child_and_current_turn(runtime):
    from neurath.hosts.identity import attest_child, snapshot

    root, storage, transcript, send = runtime
    start(send, "claude-code")
    code, reply, _ = send(
        "claude-code",
        "PreToolUse",
        tool_name="Agent",
        tool_use_id="spawn-1",
        tool_input={"prompt": "Inspect only", "subagent_type": "general-purpose"},
    )
    assert code == 0
    updated = reply["hookSpecificOutput"]
    assert "permissionDecision" not in updated
    child_file = storage / "root/subagents/agent-child.jsonl"
    child_file.parent.mkdir(parents=True)
    child_file.write_text(
        json.dumps(
            {
                "type": "user",
                "agentId": "child",
                "sessionId": "root",
                "isSidechain": True,
                "message": {"content": updated["updatedInput"]["prompt"]},
            }
        )
        + "\n"
    )
    payload = {"session_id": "root", "agent_id": "child", "transcript_path": str(transcript)}
    proof = attest_child(root, "claude-code", payload, {})
    assert proof["parent"] == "claude-code:session:root"
    assert proof["call_id"] == "spawn-1"
    other = child_file.with_name("agent-other.jsonl")
    other.write_text(child_file.read_text().replace('"child"', '"other"'))
    assert attest_child(root, "claude-code", {**payload, "agent_id": "other"}, {}) is None
    assert (
        send("claude-code", "Stop", stop_hook_active=False, last_assistant_message="Finished")[0]
        == 0
    )
    assert (
        send(
            "claude-code",
            "UserPromptSubmit",
            prompt="Different foreground request",
            turn_id="next-turn",
        )[0]
        == 0
    )
    assert attest_child(root, "claude-code", payload, {}) is None
    assert snapshot(root, "root")["spawns"]["spawn-1"]["child"] == "child"


def test_codex_requires_host_parent_metadata_and_matching_spawn_receipt(runtime):
    from neurath.hosts.identity import attest_child, resolve_native_codex

    root, storage, _transcript, send = runtime
    start(send, "codex")
    send(
        "codex",
        "PreToolUse",
        tool_name="collaborationspawn_agent",
        tool_use_id="spawn-1",
        turn_id="parent-turn",
        tool_input={"task_name": "worker", "message": "opaque"},
    )
    send(
        "codex",
        "PostToolUse",
        tool_name="collaborationspawn_agent",
        tool_use_id="spawn-1",
        turn_id="parent-turn",
        tool_response='{"task_name":"/root/worker"}',
    )
    child = storage / "child.jsonl"
    meta = {
        "type": "session_meta",
        "payload": {
            "id": "child",
            "session_id": "root",
            "parent_thread_id": "root",
            "agent_path": "/root/worker",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}},
        },
    }
    child.write_text(json.dumps(meta) + "\n")
    payload = {
        "session_id": "root",
        "agent_id": "child",
        "transcript_path": str(child),
        "turn_id": "child-turn",
    }
    assert attest_child(root, "codex", payload, {})["parent"] == "codex:session:root"
    assert (
        send(
            "codex",
            "SubagentStart",
            parent_thread_id="conflicting-root",
            **{k: v for k, v in payload.items() if k != "session_id"},
        )[0]
        == 2
    )
    assert (
        send("codex", "SubagentStart", **{k: v for k, v in payload.items() if k != "session_id"})[0]
        == 0
    )
    binding = resolve_native_codex({"CODEX_THREAD_ID": "child"})
    assert str(binding.session_id) == "root"
    assert str(binding.actor_id) == "codex:child"
    assert not binding.is_root
    meta["payload"]["parent_thread_id"] = "other-parent"
    child.write_text(json.dumps(meta) + "\n")
    assert attest_child(root, "codex", payload, {}) is None


@pytest.mark.parametrize("returned", ["child", "other-child", None])
def test_codex_pathless_child_requires_exact_returned_id(runtime, returned):
    from neurath.hosts.identity import attest_child

    root, storage, _, send = runtime
    start(send, "codex")
    send("codex", "PreToolUse", tool_name="spawn_agent", tool_use_id="spawn-1",
         turn_id="parent-turn", tool_input={"message": "Review"})
    send("codex", "PostToolUse", tool_name="spawn_agent", tool_use_id="spawn-1",
         turn_id="parent-turn", tool_response={"agent_id": returned})
    child = storage / "child.jsonl"
    child.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "child", "session_id": "root", "parent_thread_id": "root",
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root", "agent_path": None}}},
    }}) + "\n")
    payload = {"session_id": "root", "agent_id": "child", "transcript_path": str(child)}
    proof = attest_child(root, "codex", payload, {})
    assert bool(proof) == (returned == "child")
    if returned == "child":
        send("codex", "SubagentStart", agent_id="child", transcript_path=str(child), turn_id="child")
        native_turn_started(child, "actual-child-turn")
        code, _, diagnostic = send("codex", "UserPromptSubmit", agent_id="child",
                                  transcript_path=str(child), turn_id="actual-child-turn", prompt="Review")
        assert code == 0, diagnostic


def test_unregistered_child_prompt_waits_for_proof_without_root_authority(runtime):
    root, storage, _, send = runtime
    start(send, "codex")
    child = storage / "child.jsonl"
    child.write_text("")
    code, output, _ = send("codex", "UserPromptSubmit", agent_id="child",
                          transcript_path=str(child), turn_id="child-turn", prompt="Review")
    assert code == 0
    assert "pending" in output["hookSpecificOutput"]["additionalContext"]
    code, _, diagnostic = send("codex", "PreToolUse", agent_id="child",
                              transcript_path=str(child), tool_name="Bash",
                              tool_input={"command": "true"}, tool_use_id="child-call")
    assert code != 0 and "child-identity-unverified" in diagnostic


def stopped_native_child(runtime):
    from scripts.agent_harness import session_kernel as k

    root, storage, _, send = runtime
    start(send, "codex")
    send("codex", "PreToolUse", tool_name="spawn_agent", tool_use_id="spawn-resume",
         turn_id="parent-turn", tool_input={"message": "Review"})
    send("codex", "PostToolUse", tool_name="spawn_agent", tool_use_id="spawn-resume",
         turn_id="parent-turn", tool_response={"agent_id": "child"})
    child = storage / "child.jsonl"
    child.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "child", "session_id": "root", "parent_thread_id": "root",
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}},
    }}) + "\n")
    native_turn_started(child, "child-first")
    assert send("codex", "SubagentStart", agent_id="child", transcript_path=str(child),
                turn_id="child-first")[0] == 0
    assert send("codex", "UserPromptSubmit", agent_id="child", transcript_path=str(child),
                turn_id="child-first", prompt="Review")[0] == 0
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    actor = k.ActorId("codex:child")
    delegation = k.DelegationId("completed-review")
    kernel.apply(k.DelegationAssigned(session_id=state.session.id, delegation_id=delegation,
        owner_actor_id=state.session.root_actor_id, target_actor_id=actor,
        assignment="Read the current source", idempotency_key="assign-first-review",
        topology_policy=k.DelegationTopologyPolicy.DIRECT_CHILD))
    kernel.apply(k.DelegationReported(session_id=state.session.id, delegation_id=delegation,
        reporter_actor_id=actor, result=k.DelegationResult(verdict="blocked",
            summary="Fix the observed installation failure", outcome_ref="sha256:" + "a" * 64,
            blocking_findings=("installation failure",)), idempotency_key="report-first-review"))
    kernel.apply(k.ForegroundTurnClosed(
        session_id=state.session.id, actor_id=actor,
        expected_turn_revision=state.foreground_turns[actor].revision,
        idempotency_key="close-child-first"))
    kernel.apply(k.ActorStopped(session_id=state.session.id, actor_id=actor,
                               terminal_status=k.ActorStatus.STOPPED,
                               idempotency_key="stop-child-first"))
    with child.open("a") as file:
        file.write(json.dumps({"type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "child-first"}}) + "\n")
    return child, kernel, actor


def test_native_child_followup_reopens_same_actor_with_new_turn(runtime):
    from scripts.agent_harness import session_kernel as k

    child, kernel, actor = stopped_native_child(runtime)
    before = kernel.inspect(k.SessionId("root"))
    native_turn_started(child, "child-followup")
    code, _, diagnostic = runtime[3](
        "codex", "UserPromptSubmit", agent_id="child", transcript_path=str(child),
        turn_id="child-followup", prompt="Recheck the repaired source")
    assert code == 0, diagnostic
    state = kernel.inspect(k.SessionId("root"))
    assert state.actors[actor].status is k.ActorStatus.ACTIVE
    assert state.foreground_turns[actor].vendor_turn_id == "child-followup"
    assert state.foreground_turns[actor].generation == before.foreground_turns[actor].generation + 1
    assert state.to_payload()["delegations"] == before.to_payload()["delegations"]
    assert state.material_actions == before.material_actions


@pytest.mark.parametrize("race", ["already-resumed", "cas"])
def test_native_child_resume_race_reuses_only_same_attested_turn(runtime, monkeypatch, race):
    import os

    from neurath.hosts.identity import resume_child
    from scripts.agent_harness import session_kernel as k

    child, kernel, actor = stopped_native_child(runtime)
    before = kernel.inspect(k.SessionId("root"))
    native_turn_started(child, "child-followup")
    payload = {"session_id": "root", "agent_id": "child", "transcript_path": str(child),
               "turn_id": "child-followup"}
    if race == "already-resumed":
        assert resume_child(runtime[0], "codex", payload, os.environ)
    else:
        original = k.SessionKernel.apply

        def concurrent_apply(self, event, **kwargs):
            result = original(self, event, **kwargs)
            if isinstance(event, k.ActorResumed):
                raise k.RevisionConflict("another native hook committed this resume")
            return result

        monkeypatch.setattr(k.SessionKernel, "apply", concurrent_apply)
    assert resume_child(runtime[0], "codex", payload, os.environ)
    state = kernel.inspect(k.SessionId("root"))
    assert state.foreground_turns[actor].generation == before.foreground_turns[actor].generation + 1
    assert state.to_payload()["delegations"] == before.to_payload()["delegations"]
    assert not resume_child(runtime[0], "codex", {**payload, "turn_id": "other"}, os.environ)


@pytest.mark.parametrize("invalid", ["replayed", "foreign", "retired", "parent-closed"])
def test_child_followup_rejects_replayed_or_foreign_native_turn(runtime, invalid):
    from scripts.agent_harness import session_kernel as k

    child, kernel, actor = stopped_native_child(runtime)
    if invalid != "replayed":
        native_turn_started(child, "child-followup")
    if invalid == "foreign":
        child.write_text(child.read_text().replace('"parent_thread_id": "root"',
                                                   '"parent_thread_id": "foreign"'))
    state = kernel.inspect(k.SessionId("root"))
    if invalid == "retired":
        kernel.apply(k.ActorStopped(session_id=state.session.id, actor_id=actor,
                                   terminal_status=k.ActorStatus.RETIRED, idempotency_key="retire"))
    if invalid == "parent-closed":
        parent = state.session.root_actor_id
        kernel.apply(k.ForegroundTurnClosed(session_id=state.session.id, actor_id=parent,
            expected_turn_revision=state.foreground_turns[parent].revision,
            idempotency_key="parent-finished"))
    before = kernel.inspect(k.SessionId("root"))
    result = runtime[3]("codex", "PreToolUse", agent_id="child", transcript_path=str(child),
                       turn_id="child-followup", tool_name="Bash", tool_use_id="followup-tool",
                       tool_input={"command": "true"})
    assert result[0] != 0
    assert kernel.inspect(k.SessionId("root")).to_payload()["actors"] == before.to_payload()["actors"]


def test_root_tool_binding_is_scoped_and_revoked_on_post(runtime):
    from neurath.hosts.identity import finish_tool, issue_tool_binding, resolve_binding

    root, _storage, _transcript, send = runtime
    start(send, "codex")
    payload = {"session_id": "root", "tool_use_id": "call-1", "tool_input": {"command": "echo ok"}}
    token = issue_tool_binding(root, "codex", payload)
    env = {"NEURATH_TOOL_BINDING": token, "CODEX_THREAD_ID": "root"}
    from neurath.hosts.process import bind_tool_process

    bind_tool_process(env)
    binding = resolve_binding(env)
    assert binding.is_root
    with pytest.raises(ValueError):
        resolve_binding({**env, "CODEX_THREAD_ID": "different"})
    with pytest.raises(ValueError):
        resolve_binding({**env, "NEURATH_AGENT_ACTOR_ID": "codex:forged"})
    finish_tool(root, "codex", payload)
    with pytest.raises(ValueError):
        resolve_binding(env)


def test_nested_native_spawn_is_denied_without_root_fallback(runtime):
    _root, _storage, _transcript, send = runtime
    start(send, "claude-code")
    code, _, _ = send(
        "claude-code",
        "PreToolUse",
        agent_id="child",
        tool_name="Agent",
        tool_use_id="nested",
        tool_input={"prompt": "nested"},
    )
    assert code != 0


def test_prepared_delegation_binds_to_attested_child_not_caller_selected_actor(
    runtime, monkeypatch
):
    from neurath.hosts.identity import prepare_delegation

    root, storage, _transcript, send = runtime
    start(send, "claude-code")
    from neurath.hosts.identity import issue_tool_binding
    from neurath.hosts.process import bind_tool_process

    token = issue_tool_binding(
        root,
        "claude-code",
        {
            "session_id": "root",
            "tool_use_id": "prepare",
            "tool_input": {"command": "prepare review"},
        },
    )
    env = {"CLAUDE_CODE_SESSION_ID": "root", "NEURATH_TOOL_BINDING": token}
    bind_tool_process(env)
    prepare_delegation(root, "review-1", "Check the fixture independently", env)
    _, response, _ = send(
        "claude-code",
        "PreToolUse",
        tool_name="Agent",
        tool_use_id="spawn-1",
        tool_input={"prompt": "Perform review-1"},
    )
    path = storage / "root/subagents/agent-child.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "root",
                "agentId": "child",
                "isSidechain": True,
                "message": {"content": response["hookSpecificOutput"]["updatedInput"]["prompt"]},
            }
        )
        + "\n"
    )
    from neurath.hosts import identity

    with monkeypatch.context() as interrupted:
        interrupted.setattr(identity, "attach_delegation", lambda *args: None)
        assert send("claude-code", "SubagentStart", agent_id="child")[0] == 0
    # Registration survived a process interruption before its delegation commit.
    assert (
        send(
            "claude-code",
            "PreToolUse",
            agent_id="child",
            tool_name="Bash",
            tool_use_id="child-read",
            tool_input={"command": "pwd"},
        )[0]
        == 0
    )
    state = json.loads((root / ".neurath/local/runs/root/.process-state.json").read_text())
    delegation = state["delegations"]["review-1"]
    assert delegation["target_actor_id"] == "claude-code:child"
    assert delegation["topology_policy"] == "direct-child"
    assert delegation["status"] == "pending"


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_resuming_interrupted_foreground_accepts_next_prompt_without_completing_work(runtime, host):
    from scripts.agent_harness.session_kernel import (
        ActorId,
        SessionId,
        SessionKernel,
        SessionLocator,
        WorkflowId,
        WorkflowStarted,
    )

    root, _storage, _transcript, send = runtime
    start(send, host)
    kernel = SessionKernel(SessionLocator.from_worktree(root))
    kernel.apply(
        WorkflowStarted(
            session_id=SessionId("root"),
            workflow_id=WorkflowId("unfinished"),
            owner_actor_id=ActorId(host + ":session:root"),
            kind="checkpoint",
            goal="Keep unfinished work",
            payload={},
            idempotency_key="unfinished",
        )
    )
    assert send(host, "SessionStart", source="resume")[0] == 0
    code, _reply, diagnostic = send(
        host, "UserPromptSubmit", prompt="Clean up the failed run", turn_id="resumed-turn"
    )
    assert code == 0, diagnostic
    state = kernel.inspect(SessionId("root"))
    assert state.workflows[WorkflowId("unfinished")].status.value == "active"
    assert state.foreground_turns[state.session.root_actor_id].generation == 2


def prepare_interrupted_action(runtime, host, outcome="succeeded"):
    from scripts.agent_harness import session_kernel as k
    from scripts.agent_harness import material_action as m

    root, _, transcript, send = runtime
    start(send, host)
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    actor = state.session.root_actor_id
    turn = state.foreground_turns[actor]
    target = str(root / "result.txt")
    kernel.apply(
        k.WorkflowStarted(
            session_id=state.session.id,
            workflow_id=k.WorkflowId("unfinished"),
            owner_actor_id=actor,
            kind="checkpoint",
            goal="Preserve work",
            payload={},
            idempotency_key="workflow",
        )
    )
    kernel.apply(
        k.MaterialActionPrepared(
            session_id=state.session.id,
            actor_id=actor,
            batch_id="resume-write",
            sequence=1,
            expected_turn_generation=turn.generation,
            expected_turn_revision=turn.revision,
            kind=k.MaterialActionKind.LOCAL_MUTATION,
            targets=(target,),
            expectations=(
                m.ObservableExpectation(
                    observable_id=target,
                    baseline_digest=None,
                    expected_delta=m.ObservableDeltaKind.CREATED,
                    expected_digest="b" * 64,
                ),
            ),
            adaptive_binding=None,
            idempotency_key="prepare",
        )
    )
    if outcome != "unexecuted":
        kernel.apply(
            k.MaterialActionToolStarted(
                session_id=state.session.id,
                actor_id=actor,
                batch_id="resume-write",
                expected_batch_revision=0,
                invocation_id="write",
                tool_name="Write",
                request_digest="c" * 64,
                targets=(target,),
                idempotency_key="tool-start",
            )
        )
        if outcome != "in-flight":
            kernel.apply(
                k.MaterialActionToolObserved(
                    session_id=state.session.id,
                    actor_id=actor,
                    batch_id="resume-write",
                    expected_batch_revision=1,
                    invocation_id="write",
                    receipt=m.ToolReceipt(
                        receipt_id="post:write",
                        request_digest="c" * 64,
                        outcome=m.ToolReceiptOutcome(outcome),
                        output_digest="d" * 64,
                        observations=(m.ObservableObservation(target, "b" * 64),),
                    ),
                    idempotency_key="observed",
                )
            )
    return (
        kernel,
        actor,
        {
            "session_id": "root",
            "transcript_path": str(transcript),
            "turn_id": "parent-turn",
            "prompt": "Review the fixture",
        },
    )


@pytest.mark.parametrize("host", ["codex", "claude-code"])
@pytest.mark.parametrize("source", ["resume", "compact"])
@pytest.mark.parametrize(
    "outcome,expected",
    [("succeeded", "completed"), ("failed", "blocked"), ("unexecuted", "blocked")],
)
def test_resume_settles_only_observed_material_before_prompt(
    runtime, host, source, outcome, expected
):
    from neurath.hosts.identity import record_start, resume_foreground
    from scripts.agent_harness.session_kernel import SessionId

    root, _, _, send = runtime
    kernel, actor, payload = prepare_interrupted_action(runtime, host, outcome)
    before = kernel.inspect(SessionId("root"))
    record_start(root, host, {**payload, "source": source}, {})
    resume_foreground(
        root, host, {**payload, "turn_id": "new-turn", "prompt": "Continue validation"}, {}
    )
    state = kernel.inspect(SessionId("root"))
    assert state.material_actions[actor].resolution.value == expected
    assert state.material_actions[actor].invocations == before.material_actions[actor].invocations
    assert {k: v.to_payload() for k, v in state.workflows.items()} == {
        k: v.to_payload() for k, v in before.workflows.items()
    }
    assert state.foreground_turns[actor].status.value == "closed"
    assert send(host, "UserPromptSubmit", prompt="Continue validation", turn_id="new-turn")[0] == 0


@pytest.mark.parametrize("source", ["resume", "compact"])
@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_resume_preserves_same_native_turn_or_idless_prompt(runtime, source, host):
    from neurath.hosts.identity import record_start, resume_foreground
    from scripts.agent_harness.session_kernel import SessionId

    root = runtime[0]
    kernel, actor, payload = prepare_interrupted_action(runtime, host)
    before = kernel.inspect(SessionId("root"))
    record_start(root, host, {**payload, "source": source}, {})
    prompt = (
        {**payload, "prompt": "New steering"} if host == "codex" else {**payload, "turn_id": None}
    )
    resume_foreground(root, host, prompt, {})
    assert kernel.inspect(SessionId("root")).revision == before.revision


@pytest.mark.parametrize("invalid", ["foreign", "runtime", "missing-turn", "in-flight", "stale"])
def test_resume_rejects_invalid_provenance_without_settlement(runtime, invalid):
    from neurath.hosts.identity import record_start, resume_foreground
    from scripts.agent_harness import session_kernel as k

    root = runtime[0]
    kernel, actor, payload = prepare_interrupted_action(
        runtime, "codex", "in-flight" if invalid == "in-flight" else "succeeded"
    )
    record_start(root, "codex", {**payload, "source": "resume"}, {})
    prompt = {**payload, "turn_id": "new-turn", "prompt": "New prompt"}
    if invalid == "foreign":
        prompt["transcript_path"] = str(runtime[1] / "foreign.jsonl")
    if invalid == "missing-turn":
        prompt.pop("turn_id")
    if invalid == "stale":
        state = kernel.inspect(k.SessionId("root"))
        kernel.apply(
            k.ForegroundTurnPrompted(
                session_id=state.session.id,
                actor_id=actor,
                vendor_turn_id="parent-turn",
                prompt_digest="e" * 64,
                idempotency_key="steering",
            )
        )
    before = kernel.inspect(k.SessionId("root"))
    with pytest.raises((ValueError, k.TransitionRejected)):
        resume_foreground(root, "claude-code" if invalid == "runtime" else "codex", prompt, {})
    assert kernel.inspect(k.SessionId("root")).revision == before.revision


def test_native_claude_cannot_drop_tool_receipt(runtime):
    from scripts.agent_harness.state_handle import (
        RuntimeEnvironmentResolver,
        RuntimeIdentityConflict,
    )

    start(runtime[3], "claude-code")
    with pytest.raises(RuntimeIdentityConflict):
        RuntimeEnvironmentResolver().resolve({"CLAUDE_CODE_SESSION_ID": "root"})


@pytest.mark.parametrize(
    "response",
    [
        {"backgroundTaskId": "task"},
        {"background_task_id": "task"},
        "Command running in background with ID: task",
    ],
)
def test_background_start_preserves_live_tool_receipt(runtime, response):
    from neurath.hosts.identity import issue_tool_binding, finish_tool, snapshot

    root = runtime[0]
    start(runtime[3], "claude-code")
    payload = {
        "session_id": "root",
        "tool_use_id": "bg",
        "tool_input": {"command": "sleep 1"},
        "hook_event_name": "PostToolUse",
        "tool_response": response,
    }
    issue_tool_binding(root, "claude-code", payload)
    finish_tool(root, "claude-code", payload)
    assert snapshot(root, "root")["tools"]["bg"]["active"]
    finish_tool(root, "claude-code", {**payload, "hook_event_name": "PostToolUseFailure"})
    assert not snapshot(root, "root")["tools"]["bg"]["active"]


def test_tool_receipt_requires_its_live_process_tree(runtime):
    import os
    import shlex
    import sys
    from neurath.hosts.identity import issue_tool_binding, rewrite_tool, resolve_binding

    root = runtime[0]
    start(runtime[3], "claude-code")
    script = f"from neurath.runtime.engine import activate; activate({str(root)!r}); import os,sys; from neurath.hosts.identity import resolve_binding; assert resolve_binding(os.environ).is_root; print('BOUND',flush=True); sys.stdin.readline()"
    command = shlex.join([sys.executable, "-I", "-c", script])
    payload = {
        "session_id": "root",
        "tool_use_id": "real-process",
        "tool_input": {"command": command},
    }
    token = issue_tool_binding(root, "claude-code", payload)
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CODEX_", "CLAUDE", "NEURATH_"))
    }
    env["CLAUDE_CODE_SESSION_ID"] = "root"
    proc = subprocess.Popen(
        ["bash", "-c", rewrite_tool(payload["tool_input"], token)["command"]],
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "BOUND"
        with pytest.raises(ValueError):
            resolve_binding({"CLAUDE_CODE_SESSION_ID": "root", "NEURATH_TOOL_BINDING": token})
    finally:
        stdout, stderr = proc.communicate("\n", timeout=15)
    assert proc.returncode == 0, stderr
    with pytest.raises(ValueError):
        resolve_binding({"CLAUDE_CODE_SESSION_ID": "root", "NEURATH_TOOL_BINDING": token})


def test_native_hook_identity_is_distinct_from_shell_process_receipt(runtime):
    root, _, transcript, send = runtime
    start(send, "claude-code")
    code, _, diagnostic = hook(
        root,
        "claude-code",
        json.dumps(
            {
                "session_id": "root",
                "cwd": str(root),
                "transcript_path": str(transcript),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Review the fixture",
            }
        ),
        {"CLAUDE_CODE_SESSION_ID": "root"},
    )
    assert code == 0, diagnostic


def test_foreign_session_start_cannot_mutate_before_identity_validation(runtime):
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    root, storage, _, send = runtime
    start(send, "claude-code")
    kernel = SessionKernel(SessionLocator.from_worktree(root))
    before = kernel.inspect(SessionId("root")).revision
    with pytest.raises(ValueError):
        hook(
            root,
            "claude-code",
            json.dumps(
                {
                    "session_id": "root",
                    "cwd": str(root),
                    "transcript_path": str(storage / "foreign.jsonl"),
                    "hook_event_name": "SessionStart",
                    "source": "resume",
                }
            ),
            {},
        )
    assert kernel.inspect(SessionId("root")).revision == before


def test_resume_retries_after_settlement_before_foreground_close(runtime, monkeypatch):
    from neurath.hosts.identity import record_start, resume_foreground
    from scripts.agent_harness import session_kernel as k

    root = runtime[0]
    kernel, actor, payload = prepare_interrupted_action(runtime, "codex")
    record_start(root, "codex", {**payload, "source": "resume"}, {})
    before = kernel.inspect(k.SessionId("root"))
    original = k.SessionKernel.apply

    def interrupted(self, command, *args, **kwargs):
        if isinstance(command, k.ForegroundTurnClosed):
            raise OSError("interrupted between typed commits")
        return original(self, command, *args, **kwargs)

    prompt = {**payload, "turn_id": "next-turn", "prompt": "Continue verification"}
    with monkeypatch.context() as m:
        m.setattr(k.SessionKernel, "apply", interrupted)
        with pytest.raises(OSError):
            resume_foreground(root, "codex", prompt, {})
    middle = kernel.inspect(k.SessionId("root"))
    assert middle.material_actions[actor].resolution.value == "completed"
    assert middle.foreground_turns[actor].status.value == "active"
    resume_foreground(root, "codex", prompt, {})
    after = kernel.inspect(k.SessionId("root"))
    assert after.foreground_turns[actor].status.value == "closed"
    assert after.material_actions[actor].invocations == before.material_actions[actor].invocations
    assert after.workflows[k.WorkflowId("unfinished")].status.value == "active"


def rotated_root_transcript(runtime, **changes):
    root, storage, _, _ = runtime
    path = storage / "resumed-root.jsonl"
    meta = {
        "id": "root",
        "session_id": "root",
        "cwd": str(root),
        "source": "vscode",
        "thread_source": "user",
    }
    meta.update(changes)
    path.write_text(json.dumps({"type": "session_meta", "payload": meta}) + "\n")
    return path


def native_turn_started(transcript, turn_id):
    with transcript.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "task_started",
                        "turn_id": turn_id,
                    },
                }
            )
            + "\n"
        )


@pytest.mark.parametrize("large_record", [False, True])
def test_native_lifecycle_outlives_memory_tail_budget(tmp_path, large_record):
    from neurath.hosts.identity import _latest_codex_turn

    path = tmp_path / "long.jsonl"
    native_turn_started(path, "current")
    with path.open("a") as stream:
        for _ in range(1 if large_record else 40):
            stream.write(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": "assistant", "content": "x" * (3_000_000 if large_record else 65536),
            }}) + "\n")
    assert path.stat().st_size > 2 * 1024 * 1024
    assert _latest_codex_turn(path) == "current"
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "old-unrelated-turn",
        }}) + "\n")
    assert _latest_codex_turn(path) == "current"
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "current",
        }}) + "\n")
    assert _latest_codex_turn(path) == ""


@pytest.mark.parametrize("source", [None, "resume", "compact"])
@pytest.mark.parametrize("same_prompt", [False, True])
def test_codex_new_native_turn_replaces_unclosed_foreground(runtime, source, same_prompt):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    kernel, actor, _ = prepare_interrupted_action(runtime, "codex")
    before = kernel.inspect(k.SessionId("root"))
    if source:
        assert send("codex", "SessionStart", source=source)[0] == 0
    native_turn_started(transcript, "next-turn")
    prompt = "Review the fixture" if same_prompt else "Continue verification"
    code, _, diagnostic = send("codex", "UserPromptSubmit", turn_id="next-turn", prompt=prompt)
    assert code == 0, diagnostic
    after = kernel.inspect(k.SessionId("root"))
    assert after.foreground_turns[actor].generation == before.foreground_turns[actor].generation + 1
    assert after.foreground_turns[actor].vendor_turn_id == "next-turn"
    assert after.material_actions[actor].resolution.value == "completed"
    assert after.material_actions[actor].invocations == before.material_actions[actor].invocations
    assert (
        after.workflows[k.WorkflowId("unfinished")].to_payload()
        == before.workflows[k.WorkflowId("unfinished")].to_payload()
    )
    assert snapshot(root, "root").get("resume_pending") is None
    assert send("codex", "UserPromptSubmit", turn_id="next-turn", prompt=prompt)[0] == 0
    assert kernel.inspect(k.SessionId("root")).to_payload() == after.to_payload()


@pytest.mark.parametrize("invalid", ["missing", "stale", "context-only", "foreign", "completed"])
def test_unannounced_native_turn_requires_current_host_evidence(runtime, invalid):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness import session_kernel as k

    root, storage, transcript, send = runtime
    kernel, _, _ = prepare_interrupted_action(runtime, "codex")
    if invalid == "context-only":
        transcript.write_text(
            json.dumps({"type": "turn_context", "payload": {"turn_id": "next-turn"}}) + "\n"
        )
    elif invalid != "missing":
        native_turn_started(transcript, "next-turn")
    if invalid == "stale":
        native_turn_started(transcript, "newer-turn")
    if invalid == "completed":
        with transcript.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "turn_id": "next-turn",
                        },
                    }
                )
                + "\n"
            )
    if invalid == "foreign":
        transcript = storage / "foreign.jsonl"
        native_turn_started(transcript, "next-turn")
    before = kernel.inspect(k.SessionId("root")).to_payload()
    receipt = snapshot(root, "root")
    code, _, diagnostic = send(
        "codex",
        "UserPromptSubmit",
        transcript_path=str(transcript),
        turn_id="next-turn",
        prompt="New input",
    )
    assert code == 0
    assert "deferred" in diagnostic
    assert kernel.inspect(k.SessionId("root")).to_payload() == before
    assert snapshot(root, "root") == receipt


def native_peer_delivery(transcript, turn_id, *, completed=True, completion_changes=None, **changes):
    """Mirror Codex's incoming peer envelope, not an ordinary tool response."""
    item = {
        "type": "function_call_output",
        "id": "fco_native_delivery",
        "name": "send_message_to_thread",
        "namespace": "codex_app",
        "output": "<codex_delegation><source_thread_id>peer</source_thread_id>"
                  "<input>Review the result</input></codex_delegation>",
        "internal_chat_message_metadata_passthrough": {"turn_id": turn_id},
        **changes,
    }
    with transcript.open("a") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": item}) + "\n")
        if completed:
            stream.write(json.dumps({"type": "event_msg", "payload": {
                "type": "item_completed", "thread_id": "root", "turn_id": turn_id,
                "item": {key: value for key, value in {
                    **item, "type": "FunctionCallOutput",
                }.items() if key != "internal_chat_message_metadata_passthrough"},
                **(completion_changes or {}),
            }}) + "\n")


def peer_root_metadata(root, transcript, **changes):
    transcript.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "root", "session_id": "root", "source": "vscode",
        "thread_source": "user", "cwd": str(root), **changes,
    }}) + "\n")


@pytest.mark.parametrize("previous", ["closed", "interrupted", "in-flight"])
def test_native_peer_turn_reconciles_without_user_authority(runtime, previous):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    if previous == "closed":
        start(send, "codex")
        assert send("codex", "Stop", stop_hook_active=False,
                    last_assistant_message="Finished")[0] == 0
        kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    else:
        kernel, _, _ = prepare_interrupted_action(
            runtime, "codex", "in-flight" if previous == "in-flight" else "succeeded",
        )
    before = kernel.inspect(k.SessionId("root"))
    native_turn_started(transcript, "peer-turn")
    native_peer_delivery(transcript, "peer-turn")
    code, _, diagnostic = send(
        "codex", "PreToolUse", turn_id="peer-turn", tool_use_id="peer-read",
        tool_name="mcp__codex_app__read_thread", tool_input={"threadId": "peer"},
    )
    assert code == 0, diagnostic
    after = kernel.inspect(k.SessionId("root"))
    turn = after.foreground_turns[after.session.root_actor_id]
    assert turn.vendor_turn_id == "peer-turn"
    assert turn.generation == before.foreground_turns[after.session.root_actor_id].generation + 1
    assert turn.user_prompt_receipt is None
    assert {key: value.to_payload() for key, value in after.workflows.items()} == {
        key: value.to_payload() for key, value in before.workflows.items()
    }
    if previous == "in-flight":
        batch = after.material_actions[after.session.root_actor_id]
        assert batch.resolution.value == "blocked"
        assert batch.invocations[0].receipt.outcome.value == "unknown"
    journal = snapshot(root, "root")
    assert send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="peer-retry",
                tool_name="mcp__codex_app__read_thread", tool_input={})[0] == 0
    assert kernel.inspect(k.SessionId("root")).to_payload() == after.to_payload()
    assert snapshot(root, "root") == journal


@pytest.mark.parametrize("invalid", [
    "no-start", "stale", "completed", "wrong-turn", "wrong-name", "wrong-namespace",
    "called-tool", "missing-id", "user-text", "foreign-root", "child-root",
    "foreign-cwd", "human-prompt", "ordinary-output", "missing-ingress",
    "missing-completion", "completion-thread", "completion-turn", "completion-item",
])
def test_peer_turn_requires_exact_native_ingress(runtime, invalid):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    if invalid in {"foreign-root", "child-root", "foreign-cwd"}:
        peer_root_metadata(root, transcript, **{
            "foreign-root": {"id": "foreign"},
            "child-root": {"parent_thread_id": "another-root"},
            "foreign-cwd": {"cwd": str(root.parent)},
        }[invalid])
    if invalid != "no-start":
        native_turn_started(transcript, "peer-turn")
    changes = {
        "wrong-turn": {"internal_chat_message_metadata_passthrough": {"turn_id": "old"}},
        "wrong-name": {"name": "exec_command"},
        "wrong-namespace": {"namespace": "other"},
        "called-tool": {"call_id": "call_echoed_tool_output"},
        "missing-id": {"id": None},
        "user-text": {"type": "message", "role": "user"},
        "ordinary-output": {"type": "custom_tool_call_output"},
    }.get(invalid, {})
    if invalid != "missing-ingress":
        native_peer_delivery(transcript, "peer-turn", **changes,
            completed=invalid != "missing-completion",
            completion_changes={
                "completion-thread": {"thread_id": "foreign"},
                "completion-turn": {"turn_id": "old"},
                "completion-item": {"item": {"id": "other"}},
            }.get(invalid))
    if invalid == "human-prompt":
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": "user", "content": "Unreconciled correction",
            }}) + "\n")
    if invalid == "stale":
        native_turn_started(transcript, "newer-turn")
    if invalid == "completed":
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {
                "type": "task_complete", "turn_id": "peer-turn",
            }}) + "\n")
    before = kernel.inspect(k.SessionId("root")).to_payload()
    journal = snapshot(root, "root")
    with pytest.raises(ValueError, match="not reconciled"):
        send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="unverified",
             tool_name="mcp__codex_app__read_thread", tool_input={})
    assert kernel.inspect(k.SessionId("root")).to_payload() == before
    assert snapshot(root, "root") == journal



@pytest.mark.parametrize("ended", [False, True])
def test_peer_retry_after_journal_failure_uses_canonical_provenance(runtime, monkeypatch, ended):
    from neurath.hosts import identity
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    native_turn_started(transcript, "peer-turn")
    native_peer_delivery(transcript, "peer-turn")
    original = identity.os.replace

    def failed_flush(source, target):
        if str(target).endswith(".neurath-host.json"):
            raise OSError("fixture journal flush failure")
        return original(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(identity.os, "replace", failed_flush)
        with pytest.raises(OSError, match="journal flush"):
            send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="crashed-read",
                 tool_name="mcp__codex_app__read_thread", tool_input={})
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    assert state.foreground_turns[state.session.root_actor_id].vendor_turn_id == "peer-turn"
    assert state.foreground_turns[state.session.root_actor_id].user_prompt_receipt is None
    if ended:
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {
                "type": "task_complete", "turn_id": "peer-turn",
            }}) + "\n")
        with pytest.raises(ValueError, match="no longer active"):
            send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="stale-read",
                 tool_name="mcp__codex_app__read_thread", tool_input={})
    else:
        assert send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="retry-read",
                    tool_name="mcp__codex_app__read_thread", tool_input={})[0] == 0
    assert kernel.inspect(k.SessionId("root")).to_payload() == state.to_payload()


def test_peer_ingress_cannot_skip_oversized_unclassified_input(runtime):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    native_turn_started(transcript, "peer-turn")
    native_peer_delivery(transcript, "peer-turn")
    with transcript.open("a") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": "x" * 3_000_000,
        }}) + "\n")
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    before = kernel.inspect(k.SessionId("root")).to_payload()
    with pytest.raises(ValueError, match="not reconciled"):
        send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="unclassified-read",
             tool_name="mcp__codex_app__read_thread", tool_input={})
    assert kernel.inspect(k.SessionId("root")).to_payload() == before


def test_closed_peer_turn_cannot_be_reopened_by_replayed_tools(runtime):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    native_turn_started(transcript, "peer-turn")
    native_peer_delivery(transcript, "peer-turn")
    assert send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="first-read",
                tool_name="mcp__codex_app__read_thread", tool_input={})[0] == 0
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    turn = state.foreground_turns[state.session.root_actor_id]
    kernel.apply(k.ForegroundTurnClosed(
        session_id=state.session.id, actor_id=state.session.root_actor_id,
        expected_turn_revision=turn.revision, idempotency_key="fixture-peer-close",
    ))
    before = kernel.inspect(k.SessionId("root")).to_payload()
    with pytest.raises(ValueError, match="no longer active"):
        send("codex", "PreToolUse", turn_id="peer-turn", tool_use_id="stale-read",
             tool_name="mcp__codex_app__read_thread", tool_input={})
    assert kernel.inspect(k.SessionId("root")).to_payload() == before



@pytest.mark.parametrize("ingress", ["human", "peer"])
@pytest.mark.parametrize("native", ["current", "missing", "completed"])
def test_stale_stop_preserves_new_foreground(runtime, ingress, native):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    native_turn_started(transcript, "new-turn")
    if ingress == "human":
        assert send("codex", "UserPromptSubmit", turn_id="new-turn", prompt="Continue")[0] == 0
    else:
        native_peer_delivery(transcript, "new-turn")
        assert send("codex", "PreToolUse", turn_id="new-turn", tool_use_id="peer-read",
                    tool_name="mcp__codex_app__read_thread", tool_input={})[0] == 0
    if native == "missing":
        peer_root_metadata(root, transcript)
    elif native == "completed":
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {
                "type": "task_complete", "turn_id": "new-turn",
            }}) + "\n")
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    before = kernel.inspect(k.SessionId("root")).to_payload()
    local = fixture_local_bytes(root)
    code, _, diagnostic = send("codex", "Stop", turn_id="parent-turn")
    assert code == (0 if native == "current" else 2), diagnostic
    assert "Stop" in diagnostic
    assert kernel.inspect(k.SessionId("root")).to_payload() == before
    assert fixture_local_bytes(root) == local


@pytest.mark.parametrize("ingress", ["human", "peer"])
@pytest.mark.parametrize("field", ["cwd", "parent_thread_id", "actor_id", "thread_id", "runtime"])
def test_stale_stop_invalid_identity_cannot_fall_through(runtime, ingress, field):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    native_turn_started(transcript, "new-turn")
    if ingress == "human":
        assert send("codex", "UserPromptSubmit", turn_id="new-turn", prompt="Continue")[0] == 0
    else:
        native_peer_delivery(transcript, "new-turn")
        assert send("codex", "PreToolUse", turn_id="new-turn", tool_use_id="peer-read",
                    tool_name="mcp__codex_app__read_thread", tool_input={})[0] == 0
    if field == "cwd":
        (root / "subdir").mkdir()
    value = str(root / "subdir") if field == "cwd" else "foreign"
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    before = kernel.inspect(k.SessionId("root")).to_payload()
    local = fixture_local_bytes(root)
    code, _, _ = send("codex", "Stop", turn_id="parent-turn", **{field: value})
    assert code == 2
    assert kernel.inspect(k.SessionId("root")).to_payload() == before
    assert fixture_local_bytes(root) == local


def fixture_local_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in (root / ".neurath/local").rglob("*") if p.is_file()}


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_retired_root_stop_has_no_state_or_bookkeeping_effect(runtime, host):
    from scripts.agent_harness import session_kernel as k

    root, _, _, send = runtime
    start(send, host)
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    kernel.apply(k.SessionEnded(session_id=state.session.id, actor_id=state.session.root_actor_id,
                                idempotency_key="explicit-fixture-end"))
    before = fixture_local_bytes(root)
    assert any(p.endswith(".neurath-host.json") for p in before)
    assert any(p.endswith("project.sqlite3") for p in before)
    for _ in range(2):
        code, output, diagnostic = send(host, "Stop", turn_id="unadmitted-turn")
        assert code == 0 and output == {}, diagnostic
        assert "already ended" in diagnostic
        assert fixture_local_bytes(root) == before
    with pytest.raises(ValueError, match="active session"):
        send(host, "SessionStart", source="resume")
    try:
        code, _, diagnostic = send(host, "PreToolUse", turn_id="parent-turn",
            tool_name="exec_command", tool_input={"cmd": "true"}, tool_use_id="after-end")
    except ValueError as error:
        assert "active session" in str(error)
    else:
        assert code != 0, diagnostic
    assert fixture_local_bytes(root) == before


@pytest.mark.parametrize("change", [
    {"agent_id": "child"}, {"agent_id": ""}, {"actor_id": "codex:session:root"},
    {"parent_thread_id": "parent"}, {"parent_actor_id": "parent"},
    {"thread_id": "foreign"}, {"session_id": "missing"}, {"session_id": None},
    {"cwd": "/"}, {"runtime": "claude-code"},
])
def test_retired_stop_rejects_foreign_or_child_payload(runtime, change):
    from scripts.agent_harness import session_kernel as k

    root, _, _, send = runtime
    start(send, "codex")
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    kernel.apply(k.SessionEnded(session_id=state.session.id, actor_id=state.session.root_actor_id,
                                idempotency_key="explicit-fixture-end"))
    before = fixture_local_bytes(root)
    code, _, diagnostic = send("codex", "Stop", **change)
    assert code != 0
    assert "already ended" not in diagnostic
    assert fixture_local_bytes(root) == before


def test_peer_message_in_same_native_turn_preserves_user_receipt(runtime):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    start(send, "codex")
    native_turn_started(transcript, "parent-turn")
    native_peer_delivery(transcript, "parent-turn")
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    before = kernel.inspect(k.SessionId("root")).to_payload()
    assert send("codex", "PreToolUse", turn_id="parent-turn", tool_use_id="same-turn",
                tool_name="mcp__codex_app__read_thread", tool_input={})[0] == 0
    assert kernel.inspect(k.SessionId("root")).to_payload() == before



def test_native_new_turn_recovers_missing_posttool_as_unknown(runtime):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    kernel, actor, _ = prepare_interrupted_action(runtime, "codex", "in-flight")
    before = kernel.inspect(k.SessionId("root"))
    native_turn_started(transcript, "next-turn")
    code, _, diagnostic = send("codex", "UserPromptSubmit", turn_id="next-turn", prompt="Continue")
    assert code == 0 and not diagnostic
    after = kernel.inspect(k.SessionId("root"))
    assert after.foreground_turns[actor].vendor_turn_id == "next-turn"
    assert after.foreground_turns[actor].generation == before.foreground_turns[actor].generation + 1
    batch = after.material_actions[actor]
    assert batch.resolution.value == "blocked"
    assert batch.in_flight is None
    assert batch.invocations[0].receipt.outcome.value == "unknown"
    assert {key: value.to_payload() for key, value in after.workflows.items()} == {
        key: value.to_payload() for key, value in before.workflows.items()
    }


def test_deferred_new_prompt_cannot_use_previous_turn_tool_authority(runtime):
    root, _, _, send = runtime
    prepare_interrupted_action(runtime, "codex")
    code, _, diagnostic = send(
        "codex", "UserPromptSubmit", turn_id="unverified", prompt="New input"
    )
    assert code == 0 and "deferred" in diagnostic
    with pytest.raises(ValueError, match="not reconciled"):
        send(
            "codex",
            "PreToolUse",
            turn_id="unverified",
            tool_name="Write",
            tool_use_id="new-write",
            tool_input={"file_path": str(root / "result.txt"), "content": "new"},
        )


@pytest.mark.parametrize("stale", [False, True])
def test_native_start_supersedes_stale_resume_but_rejects_replayed_turn(runtime, stale):
    from scripts.agent_harness import session_kernel as k
    from neurath.hosts.identity import snapshot

    root, _, transcript, send = runtime
    start(send, "codex")
    assert send("codex", "SessionStart", source="compact")[0] == 0
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    kernel.apply(
        k.ForegroundTurnPrompted(
            session_id=state.session.id,
            actor_id=state.session.root_actor_id,
            vendor_turn_id="parent-turn",
            prompt_digest="e" * 64,
            idempotency_key="steering",
        )
    )
    native_turn_started(transcript, "next-turn")
    before = kernel.inspect(k.SessionId("root")).to_payload()
    journal_before = snapshot(root, "root")
    code, _, diagnostic = send(
        "codex",
        "UserPromptSubmit",
        turn_id="parent-turn" if stale else "next-turn",
        prompt="Continue",
    )
    assert code == 0
    after = kernel.inspect(k.SessionId("root"))
    if stale:
        assert "deferred" in diagnostic
        assert after.to_payload() == before
        assert snapshot(root, "root") == journal_before
    else:
        assert not diagnostic
        assert after.foreground_turns[after.session.root_actor_id].vendor_turn_id == "next-turn"
        assert snapshot(root, "root")["resume_pending"] is None


@pytest.mark.parametrize("rotation_event", ["SessionStart", "UserPromptSubmit"])
def test_codex_resume_accepts_rotated_native_root_transcript(runtime, rotation_event):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness.session_kernel import SessionId

    root, _, _, send = runtime
    kernel, actor, _ = prepare_interrupted_action(runtime, "codex")
    before = kernel.inspect(SessionId("root"))
    path = rotated_root_transcript(runtime)
    fields = {"transcript_path": str(path)} if rotation_event == "SessionStart" else {}
    assert send("codex", "SessionStart", source="resume", **fields)[0] == 0
    code, _, diagnostic = send(
        "codex",
        "UserPromptSubmit",
        transcript_path=str(path),
        turn_id="next-turn",
        prompt="Continue verification",
    )
    assert code == 0, diagnostic
    state = kernel.inspect(SessionId("root"))
    assert state.foreground_turns[actor].generation == before.foreground_turns[actor].generation + 1
    assert state.material_actions[actor].resolution.value == "completed"
    assert state.material_actions[actor].invocations == before.material_actions[actor].invocations
    assert {k: v.to_payload() for k, v in state.workflows.items()} == {
        k: v.to_payload() for k, v in before.workflows.items()
    }
    assert snapshot(root, "root")["transcript"] == str(path)
    assert snapshot(root, "root")["resume_pending"] is None


@pytest.mark.parametrize("rotate", [False, True])
def test_compaction_then_normal_stop_does_not_block_next_prompt(runtime, rotate):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    root, _, transcript, send = runtime
    start(send, "codex")
    assert send("codex", "SessionStart", source="compact")[0] == 0
    assert send("codex", "Stop", stop_hook_active=False, last_assistant_message="Finished")[0] == 0
    kernel = SessionKernel(SessionLocator.from_worktree(root))
    before = kernel.inspect(SessionId("root"))
    path = rotated_root_transcript(runtime) if rotate else transcript
    code, _, diagnostic = send(
        "codex",
        "UserPromptSubmit",
        transcript_path=str(path),
        turn_id="next-turn",
        prompt="One more question",
    )
    assert code == 0, diagnostic
    after = kernel.inspect(SessionId("root"))
    actor = after.session.root_actor_id
    assert after.foreground_turns[actor].generation == before.foreground_turns[actor].generation + 1
    assert after.foreground_turns[actor].vendor_turn_id == "next-turn"
    assert snapshot(root, "root")["resume_pending"] is None


@pytest.mark.parametrize("rotation_event", ["SessionStart", "UserPromptSubmit"])
@pytest.mark.parametrize(
    "invalid", ["id", "session_id", "cwd", "child", "parent", "malformed", "outside"]
)
def test_rotated_transcript_requires_native_root_proof(runtime, rotation_event, invalid):
    from neurath.hosts.identity import snapshot
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    root, _, _, send = runtime
    start(send, "codex")
    assert send("codex", "SessionStart", source="resume")[0] == 0
    changes = {"id": "foreign"} if invalid == "id" else {}
    if invalid == "session_id":
        changes["session_id"] = "foreign"
    if invalid == "cwd":
        changes["cwd"] = str(root.parent / "foreign")
    if invalid == "child":
        changes["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}
    if invalid == "parent":
        changes["parent_thread_id"] = "another-root"
    path = rotated_root_transcript(runtime, **changes)
    if invalid == "malformed":
        path.write_text("[]\n")
    if invalid == "outside":
        outside = root / "outside.jsonl"
        outside.write_text(path.read_text())
        path = outside
    kernel = SessionKernel(SessionLocator.from_worktree(root))
    before = kernel.inspect(SessionId("root"))
    receipt = snapshot(root, "root")

    def deliver():
        return send(
            "codex",
            rotation_event,
            source="resume",
            transcript_path=str(path),
            turn_id="next-turn",
            prompt="Unauthorized prompt",
        )

    if rotation_event == "UserPromptSubmit":
        code, _, diagnostic = deliver()
        assert code == 0
        assert "deferred" in diagnostic
    else:
        with pytest.raises(ValueError):
            deliver()
    assert kernel.inspect(SessionId("root")).revision == before.revision
    assert snapshot(root, "root") == receipt
