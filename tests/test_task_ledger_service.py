"""Task mutations use canonical process authority and one durable transaction."""
import pytest


@pytest.fixture
def service(tmp_path):
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness import session_kernel as sk
    from scripts.agent_harness.task_service import TaskService
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding

    locator = sk.SessionLocator(tmp_path)
    kernel = sk.SessionKernel(locator)
    kernel.apply(sk.SessionStarted(session_id=sk.SessionId("one"), resume_id=sk.ResumeId("resume"),
        root_actor_id=sk.ActorId("owner"), runtime=sk.SessionRuntime.CODEX, idempotency_key="start"))
    kernel.apply(sk.ForegroundTurnProvisioned(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
                                             idempotency_key="provision"))
    kernel.apply(sk.ForegroundTurnPrompted(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        vendor_turn_id="turn", prompt_digest="a" * 64, idempotency_key="prompt"))
    handle = StateHandle.attach(locator, RuntimeIdentityBinding(runtime=sk.SessionRuntime.CODEX,
        session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"), root_actor_id=sk.ActorId("owner")))
    return TaskService(handle), kernel, sk


def item(key="fix"):
    return {"key": key, "title": "Fix " + key, "goal": "Verified result " + key,
            "sources": [], "acceptance": ["Observable result is verified"],
            "evidence_contract": "work-" + key, "dependencies": []}


def test_task_service_defines_before_workflow_and_retains_prompt_source(service):
    store, _, _ = service
    assert not store.list()["all_terminal"]
    result = store.define([item()], expected_revision=0, key="define")
    task = result["tasks"][0]
    assert result["revision"] == 1
    assert task["definition"]["sources"][0]["kind"] == "prompt"
    assert task["definition"]["sources"][0]["revision"] == "a" * 64
    assert store.list()["tasks"] == result["tasks"]
    assert store.define([item()], expected_revision=0, key="define")["revision"] == 1


def test_task_service_rejects_unresolved_or_foreign_workflow_evidence(service):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, kernel, sk = service
    result = store.define([item()], expected_revision=0, key="define")
    kernel.apply(sk.WorkflowStarted(session_id=sk.SessionId("one"), workflow_id=sk.WorkflowId("work-fix"),
        owner_actor_id=sk.ActorId("owner"), kind="autopilot", goal="Verified result fix",
        payload={}, idempotency_key="work"))
    with pytest.raises(TaskLedgerError):
        store.resolve(result["tasks"][0]["id"], expected_revision=1, expected_task_revision=1,
                      key="resolve", references=["workflow:work-fix:0"], status="succeeded",
                      assessment={"summary": "Reported result", "acceptance": [{
                          "condition": item()["acceptance"][0], "outcome": "met",
                          "explanation": "Reported workflow result",
                          "reference": "workflow:work-fix:0"}]})
    assert store.list()["revision"] == 1


def test_task_admission_rechecks_current_process_inside_transaction(service):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, kernel, sk = service
    observed = kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")].user_prompt_receipt

    def admission(process):
        current = process.foreground_turns[sk.ActorId("owner")].user_prompt_receipt
        if current != observed:
            raise TaskLedgerError("native prompt changed")

    store.admission = admission
    kernel.apply(sk.ForegroundTurnPrompted(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        vendor_turn_id="turn", prompt_digest="b" * 64, idempotency_key="next-prompt"))
    with pytest.raises(TaskLedgerError, match="prompt changed"):
        store.define([item()], expected_revision=0, key="stale-define")
    with store.database.transaction() as tx:
        assert tx.get("task-ledger", "one") is None


def test_task_service_dynamic_append_preserves_running_task(service):
    store, _, _ = service
    first = store.define([item()], expected_revision=0, key="define")
    active = store.start(first["tasks"][0]["id"], expected_revision=1,
                         expected_task_revision=1, key="start")
    expanded = store.define([item("second")], expected_revision=2, key="append")
    assert expanded["tasks"][0] == active["tasks"][0]
    assert not expanded["all_terminal"]


def test_task_mcp_surface_has_no_caller_identity_or_verified_outcome():
    from neurath.runtime.task_schema import TASKS, TaskError, arguments
    for name in ("task_define", "task_list", "task_start", "task_resolve"):
        assert name in TASKS
        schema = TASKS[name][3]
        assert not {"actor_id", "session_id", "database", "verified", "derived_status"} & schema.keys()
    with pytest.raises(TaskError):
        arguments("task_list", {"session_id": "other"})
    for forbidden in ("verified", "review_required", "derived_status"):
        with pytest.raises(TaskError):
            arguments("task_resolve", {
                "task_id": "task-id", "expected_revision": 1,
                "expected_task_revision": 1, "key": "resolve",
                "references": ["workflow:work:1"], "status": "succeeded",
                "assessment": {"summary": "Observed", "acceptance": [{
                    "condition": "Condition", "outcome": "met",
                    "explanation": "Observed in workflow",
                    "reference": "workflow:work:1"}]},
                forbidden: True})


def test_prompt_bound_root_decision_invalidates_without_child(service):
    store, _, _ = service
    defined = store.define([item()], expected_revision=0, key="define")
    task, source = defined["tasks"][0], defined["current_prompt_source"]
    reference = f"prompt:{source['reference']}:{source['revision']}"
    decision = {"source_reference": source["reference"],
        "source_digest": source["revision"], "disposition": "cancelled",
        "reason": "The authenticated instruction cancels this exact task.",
        "covering_sources": [], "covering_workflows": []}
    result = store.resolve(task["id"], expected_revision=1,
        expected_task_revision=1, key="invalidate-root",
        references=[reference], status="invalidated",
        assessment=None, decision=decision)
    resolved = result["tasks"][0]
    assert resolved["status"] == "invalidated"
    assert resolved["assurance"] == "agent-assessment"
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    report = SessionArtifactStore(store.handle).read_json(
        resolved["result_report_reference"])
    assert report["decision"] == decision
    assert report["result_references"] == [reference]


def test_native_replacement_preserves_pending_tasks_and_next_stop_gate(service):
    store, kernel, sk = service
    store.define([item()], expected_revision=0, key="define")
    with store.database.transaction() as tx:
        original = tx.get("task-ledger", "one").payload
    turn = kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")]
    ready = kernel.apply(sk.ForegroundTurnYielded(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=turn.revision,
        receipt=sk.ForegroundTurnReceipt(sk.ForegroundTurnOutcome.COMPLETED, summary="Side answer"),
        idempotency_key="old-yield")).foreground_turns[sk.ActorId("owner")]
    replaced = kernel.apply(sk.ForegroundTurnReplaced(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=ready.revision, replacement_reference="codex-turn:next", idempotency_key="replace"))
    assert replaced.foreground_turns[sk.ActorId("owner")].receipt.outcome is sk.ForegroundTurnOutcome.INCOMPLETE
    next_state = kernel.apply(sk.ForegroundTurnPrompted(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        vendor_turn_id="next", prompt_digest="b" * 64, idempotency_key="next-prompt"))
    next_turn = next_state.foreground_turns[sk.ActorId("owner")]
    assert next_turn.generation == turn.generation + 1
    with store.database.transaction() as tx:
        assert tx.get("task-ledger", "one").payload == original
    with pytest.raises(sk.TransitionRejected, match="task"):
        kernel.apply(sk.ForegroundTurnClosed(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
            expected_turn_revision=next_turn.revision, idempotency_key="cannot-stop-pending-task"))


def test_pending_task_rejects_normal_foreground_close(service):
    store, kernel, sk = service
    store.define([item()], expected_revision=0, key="define")
    turn = kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")]
    ready = kernel.apply(sk.ForegroundTurnYielded(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=turn.revision,
        receipt=sk.ForegroundTurnReceipt(sk.ForegroundTurnOutcome.COMPLETED, summary="side answer"),
        idempotency_key="yield"))
    with pytest.raises(sk.TransitionRejected, match="task"):
        kernel.apply(sk.ForegroundTurnClosed(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
                                             expected_turn_revision=ready.foreground_turns[sk.ActorId("owner")].revision,
                                             idempotency_key="close"))
    assert kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")].status is sk.ForegroundTurnStatus.READY_TO_STOP


def test_append_after_stop_snapshot_invalidates_close_in_same_database(service):
    store, kernel, sk = service
    store.define([item()], expected_revision=0, key="define")
    _terminal_fixture(store, kernel, sk)
    assert store.list()["all_terminal"]
    # Materialize the root close candidate before a later task-list mutation.
    turn = kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")]
    yielded = kernel.apply(sk.ForegroundTurnYielded(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=turn.revision,
        receipt=sk.ForegroundTurnReceipt(sk.ForegroundTurnOutcome.COMPLETED, summary="done"),
        idempotency_key="yield"))
    state_store = store.session_store
    event = sk.ForegroundTurnClosed(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
                                    expected_turn_revision=yielded.foreground_turns[sk.ActorId("owner")].revision,
                                    idempotency_key="close")
    candidate = sk.SessionStateReducer().reduce(yielded, event)
    from scripts.agent_harness.task_ledger import TaskDefinition, TaskSource
    from scripts.agent_harness.task_service import read_ledger
    with store.database.transaction() as tx:
        record, ledger = read_ledger(tx, yielded)
        appended = ledger.define((TaskDefinition(key="late", title="Late", goal="Late work",
            sources=(TaskSource("prompt", "observed", "revision"),), acceptance=("Verified",),
            producer="canonical", evidence_contract="late"),), expected_revision=2, key="late")
        tx.put("task-ledger", "one", appended.encode(), expected_revision=record.revision)
    with pytest.raises(sk.TransitionRejected, match="task"):
        state_store._compare_and_commit(sk.SessionId("one"), yielded.revision, candidate)


def _terminal_fixture(store, kernel, sk):
    """Install a typed terminal ledger fixture; this is not a native evidence producer."""
    from scripts.agent_harness.task_ledger import TaskEvidence, TaskStatus
    from scripts.agent_harness.task_service import read_ledger
    process = kernel.inspect(sk.SessionId("one"))
    with store.database.transaction() as tx:
        record, ledger = read_ledger(tx, process)
        task = ledger.tasks[0]
        proof = TaskEvidence(TaskStatus.SUCCEEDED, task.id, "owner", task.definition.digest,
            "canonical", ("fixture:result",), "fixture", "a" * 64)
        done = ledger.resolve(task.id, expected_revision=1, expected_task_revision=1,
            key="fixture-complete", references=proof.references, resolver=lambda *_: proof)
        tx.put("task-ledger", "one", done.encode(), expected_revision=record.revision)


def test_all_terminal_tasks_allow_normal_close(service):
    store, kernel, sk = service
    store.define([item()], expected_revision=0, key="define")
    _terminal_fixture(store, kernel, sk)
    turn = kernel.inspect(sk.SessionId("one")).foreground_turns[sk.ActorId("owner")]
    ready = kernel.apply(sk.ForegroundTurnYielded(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=turn.revision,
        receipt=sk.ForegroundTurnReceipt(sk.ForegroundTurnOutcome.COMPLETED, summary="done"),
        idempotency_key="yield"))
    closed = kernel.apply(sk.ForegroundTurnClosed(session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"),
        expected_turn_revision=ready.foreground_turns[sk.ActorId("owner")].revision, idempotency_key="close"))
    assert closed.foreground_turns[sk.ActorId("owner")].status is sk.ForegroundTurnStatus.CLOSED


def _invalidation_review(service, *, consumed=True, source_digest="a" * 64):
    """Model a host-attested independent report through the actual delegation reducer."""
    import json
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    from scripts.agent_harness.task_service import read_ledger
    store, kernel, sk = service
    defined = store.define([item()], expected_revision=0, key="define")
    process = kernel.inspect(sk.SessionId("one"))
    prompt = process.foreground_turns[sk.ActorId("owner")].user_prompt_receipt
    with store.database.transaction() as tx:
        _, ledger = read_ledger(tx, process)
        task = ledger.tasks[0]
    assignment = {"kind": "task-invalidation", "task_id": task.id,
        "definition_digest": task.definition.digest, "source_reference": prompt.authority_reference,
        "source_digest": source_digest}
    kernel.apply(sk.ActorStarted(session_id=sk.SessionId("one"), actor_id=sk.ActorId("reviewer"),
        parent_actor_id=sk.ActorId("owner"), kind=sk.ActorKind.SUBAGENT,
        lineage_assurance=sk.ActorLineageAssurance.HOST_ATTESTED, idempotency_key="reviewer"))
    kernel.apply(sk.DelegationAssigned(session_id=sk.SessionId("one"), delegation_id=sk.DelegationId("decision"),
        owner_actor_id=sk.ActorId("owner"), target_actor_id=sk.ActorId("reviewer"),
        topology_policy=sk.DelegationTopologyPolicy.DIRECT_CHILD,
        assignment=json.dumps(assignment), idempotency_key="assign"))
    artifact = SessionArtifactStore(store.handle).put_json({"kind": "task-invalidation-result",
        "assignment": assignment, "verdict": "pass", "disposition": "cancelled",
        "reason": "The authenticated user decision cancels this exact task.",
        "covering_sources": [], "covering_workflows": []})
    kernel.apply(sk.DelegationReported(session_id=sk.SessionId("one"), delegation_id=sk.DelegationId("decision"),
        reporter_actor_id=sk.ActorId("reviewer"), result=sk.DelegationResult(verdict="pass",
        summary="The authenticated user decision cancels this exact task.",
        outcome_ref=artifact.reference, blocking_findings=()), idempotency_key="report"))
    if consumed:
        kernel.apply(sk.DelegationConsumed(session_id=sk.SessionId("one"), delegation_id=sk.DelegationId("decision"),
            consumer_actor_id=sk.ActorId("owner"), idempotency_key="consume"))
    return defined["tasks"][0]["id"]


def test_authenticated_consumed_task_decision_can_invalidate(service):
    task_id = _invalidation_review(service)
    store, _, _ = service
    result = store.resolve(task_id, expected_revision=1, expected_task_revision=1, key="invalidate",
                           references=["delegation:decision"], status="invalidated")
    assert result["tasks"][0]["status"] == "invalidated"
    assert result["all_terminal"]


def test_unconsumed_task_decision_cannot_invalidate(service):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    task_id = _invalidation_review(service, consumed=False)
    store, _, _ = service
    with pytest.raises(TaskLedgerError):
        store.resolve(task_id, expected_revision=1, expected_task_revision=1, key="invalidate",
                      references=["delegation:decision"], status="invalidated")
    assert store.list()["tasks"][0]["status"] == "pending"


def test_task_decision_cannot_substitute_user_prompt_content(service):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    task_id = _invalidation_review(service, source_digest="b" * 64)
    store, _, _ = service
    with pytest.raises(TaskLedgerError):
        store.resolve(task_id, expected_revision=1, expected_task_revision=1, key="invalidate",
                      references=["delegation:decision"], status="invalidated")

def test_task_invalidation_uses_immutable_prompt_after_later_active_input(service):
    task_id = _invalidation_review(service)
    store, kernel, sk = service
    kernel.apply(sk.ForegroundTurnPrompted(
        session_id=sk.SessionId("one"),
        actor_id=sk.ActorId("owner"),
        vendor_turn_id="turn",
        prompt_digest="c" * 64,
        authority_context=None,
        idempotency_key="later-unrelated-prompt",
    ))
    result = store.resolve(
        task_id,
        expected_revision=1,
        expected_task_revision=1,
        key="invalidate-after-later-prompt",
        references=["delegation:decision"],
        status="invalidated",
    )
    assert result["tasks"][0]["status"] == "invalidated"
