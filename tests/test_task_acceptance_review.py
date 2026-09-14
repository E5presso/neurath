"""Task completion records a single owner report, independent of phase history."""
import pytest

from tests.test_task_ledger_service import item
pytest_plugins = ["tests.test_task_ledger_service"]


@pytest.mark.parametrize("status", ["succeeded", "failed", "invalidated"])
def test_resolution_respects_unsettled_dependencies_without_blocking_cleanup(service, status):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, _, _ = service
    first = store.define([item("first")], expected_revision=0, key="first")
    dependent = item("dependent")
    dependent["dependencies"] = [first["tasks"][0]["id"]]
    defined = store.define([dependent], expected_revision=1, key="dependent")
    task = defined["tasks"][1]
    args = dict(expected_revision=2, expected_task_revision=1, key="resolve",
        references=["test:result"], status=status, summary="Observed outcome")
    if status == "succeeded":
        with pytest.raises(TaskLedgerError, match="dependencies are unsettled"):
            store.resolve(task["id"], **args)
        assert store.list()["revision"] == 2
        settled = store.resolve(first["tasks"][0]["id"], expected_revision=2,
            expected_task_revision=1, key="settle-first", references=["test:first"],
            status="succeeded", summary="Prerequisite complete")
        args["expected_revision"] = settled["revision"]
    result = store.resolve(task["id"], **args)
    assert result["tasks"][1]["status"] == status


@pytest.mark.parametrize("status", ["succeeded", "failed", "invalidated"])
def test_result_resolves_without_workflow_or_review(service, status):
    store, _, _ = service
    defined = store.define([item()], expected_revision=0, key="define")
    task = defined["tasks"][0]
    result = store.resolve(task["id"], expected_revision=1, expected_task_revision=1,
        key="resolve", references=["test:observed-result"], status=status,
        summary="Observed the declared outcome and recorded the result.")
    assert result["all_terminal"]
    assert result["all_succeeded"] is (status == "succeeded")
    assert result["unsuccessful_task_ids"] == ([] if status == "succeeded" else [task["id"]])
    resolved = result["tasks"][0]
    assert resolved["status"] == status
    assert resolved["assurance"] == "agent-report"
    assert resolved["evidence"]["references"] == ["test:observed-result"]
    replay = store.resolve(task["id"], expected_revision=1, expected_task_revision=1,
        key="resolve", references=["test:observed-result"], status=status,
        summary="Observed the declared outcome and recorded the result.")
    assert replay["revision"] == result["revision"]


@pytest.mark.parametrize("status", ["failed", "invalidated"])
def test_unsuccessful_outcome_remains_visible_without_permanent_stop_lock(service, status):
    from scripts.agent_harness.task_service import require_settled_tasks
    store, kernel, sk = service
    task = store.define([item()], expected_revision=0, key="define")["tasks"][0]
    store.resolve(task["id"], expected_revision=1, expected_task_revision=1,
        key="observed-failure", references=["test:unavailable-external-service"],
        status=status, summary="External service unavailable; original requirement remains unmet.")
    current = store.list()
    assert current["all_terminal"] and not current["all_succeeded"]
    assert current["tasks"][0]["definition"] == task["definition"]
    process = kernel.inspect(sk.SessionId("one"))
    with store.database.transaction() as tx:
        require_settled_tasks(tx, process)


@pytest.mark.parametrize("summary,references", [("", ["test:result"]), ("Result", [])])
def test_empty_completion_evidence_does_not_finish_task(service, summary, references):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, _, _ = service
    task = store.define([item()], expected_revision=0, key="define")["tasks"][0]
    with pytest.raises(TaskLedgerError):
        store.resolve(task["id"], expected_revision=1, expected_task_revision=1,
            key="resolve", references=references, status="succeeded", summary=summary)
    assert not store.list()["all_terminal"]


def test_active_unrelated_workflow_does_not_veto_task_stop(service):
    from scripts.agent_harness.agent_continuation_hook import AgentContinuationHookApplication
    store, kernel, sk = service
    task = store.define([item()], expected_revision=0, key="define")["tasks"][0]
    kernel.apply(sk.WorkflowStarted(session_id=sk.SessionId("one"), workflow_id=sk.WorkflowId("legacy"),
        owner_actor_id=sk.ActorId("owner"), kind="autopilot", goal="Old bookkeeping",
        payload={}, idempotency_key="legacy"))
    store.resolve(task["id"], expected_revision=1, expected_task_revision=1,
        key="resolve", references=["test:result"], status="succeeded", summary="Observed result")
    state = kernel.inspect(sk.SessionId("one"))
    app = AgentContinuationHookApplication(runtime=sk.SessionRuntime.CODEX)
    assert app._validated_stop_workflows(state, store.handle, store.worktree) == ()
    turn = state.foreground_turns[sk.ActorId("owner")]
    closed = kernel.apply(sk.ForegroundTurnClosed(session_id=sk.SessionId("one"),
        actor_id=sk.ActorId("owner"), expected_turn_revision=turn.revision, idempotency_key="close"))
    assert closed.foreground_turns[sk.ActorId("owner")].status is sk.ForegroundTurnStatus.CLOSED
