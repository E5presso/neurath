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
            "dependencies": []}


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
