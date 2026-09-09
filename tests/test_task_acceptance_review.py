"""Task acceptance reviews supplement terminal workflow evidence; fixtures are not host proof."""
import json
from copy import deepcopy

import pytest

from tests.test_task_ledger_service import item

pytest_plugins = ["tests.test_task_ledger_service"]


def terminal_work(service, status="succeeded"):
    store, kernel, sk = service
    definition = item()
    definition["acceptance"] = ["Result is correct", "Regression is verified"]
    task = store.define([definition], expected_revision=0, key="define")["tasks"][0]
    phase = {"schema_version": 1, "skill": "fixture-task", "run_id": "work-fix",
             "north_star": definition["goal"], "current_phase_id": 1,
             "terminal_state": None, "adaptive_control_required": False,
             "started_at_epoch": 1.0,
             "phases": [{"id": 1, "name": "observed-result", "status": "pending",
                         "evidence": [], "summary": None, "reason": None,
                         "completed_at_epoch": None, "duration_seconds": None}]}
    kernel.apply(sk.WorkflowStarted(session_id=store.handle.session_id,
        workflow_id=sk.WorkflowId("work-fix"), owner_actor_id=store.handle.actor_id,
        kind="fixture-task", goal=definition["goal"], payload={"phase_run": phase},
        idempotency_key="start-work"))
    terminal = deepcopy(phase)
    terminal["current_phase_id"] = None
    terminal["terminal_state"] = "finished" if status == "succeeded" else "failed"
    terminal["phases"][0].update(status="completed" if status == "succeeded" else "failed",
                                 evidence=["fixture-observed-result"], summary="Observed result")
    kernel.apply(sk.WorkflowFinalized(session_id=store.handle.session_id,
        workflow_id=sk.WorkflowId("work-fix"), actor_id=store.handle.actor_id,
        expected_workflow_revision=0,
        terminal_status=sk.WorkflowStatus.COMPLETED if status == "succeeded" else sk.WorkflowStatus.FAILED,
        payload={"phase_run": terminal}, idempotency_key="finish-work"))
    return task, "workflow:work-fix:1"


def acceptance_review(service, task, workflow_ref, *, status="succeeded", consumed=True, mutate=None):
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    from scripts.agent_harness.task_ledger import _digest
    store, kernel, sk = service
    workflow_id = workflow_ref.removeprefix("workflow:").rpartition(":")[0]
    workflow = kernel.inspect(store.handle.session_id).workflows[sk.WorkflowId(workflow_id)]
    assignment = {"kind": "task-resolution", "task_id": task["id"],
                  "definition_digest": task["definition_digest"], "workflow_id": workflow_id,
                  "workflow_revision": workflow.revision,
                  "workflow_payload_digest": _digest(workflow.to_payload())}
    report = {"kind": "task-resolution-result", "assignment": deepcopy(assignment),
              "verdict": "pass", "status": status, "reason": "Each condition was independently reviewed.",
              "acceptance": [{"condition": condition,
                              "outcome": "met" if status == "succeeded" else "unmet",
                              "references": [workflow_ref]}
                             for condition in task["definition"]["acceptance"]]}
    if mutate is not None:
        mutate(assignment, report)
    kernel.apply(sk.ActorStarted(session_id=store.handle.session_id, actor_id=sk.ActorId("acceptance-reviewer"),
        parent_actor_id=store.handle.actor_id, kind=sk.ActorKind.SUBAGENT,
        lineage_assurance=sk.ActorLineageAssurance.HOST_ATTESTED, idempotency_key="reviewer"))
    kernel.apply(sk.DelegationAssigned(session_id=store.handle.session_id,
        delegation_id=sk.DelegationId("acceptance"), owner_actor_id=store.handle.actor_id,
        target_actor_id=sk.ActorId("acceptance-reviewer"), topology_policy=sk.DelegationTopologyPolicy.DIRECT_CHILD,
        assignment=json.dumps(assignment), idempotency_key="assign-acceptance"))
    artifact = SessionArtifactStore(store.handle).put_json(report)
    kernel.apply(sk.DelegationReported(session_id=store.handle.session_id,
        delegation_id=sk.DelegationId("acceptance"), reporter_actor_id=sk.ActorId("acceptance-reviewer"),
        result=sk.DelegationResult(verdict="pass", summary=report["reason"],
                                   outcome_ref=artifact.reference, blocking_findings=()),
        idempotency_key="report-acceptance"))
    if consumed:
        kernel.apply(sk.DelegationConsumed(session_id=store.handle.session_id,
            delegation_id=sk.DelegationId("acceptance"), consumer_actor_id=store.handle.actor_id,
            idempotency_key="consume-acceptance"))
    return "delegation:acceptance"


def assessment(task, workflow_ref, status="succeeded"):
    return {"summary": "The terminal workflow covers the declared conditions.",
        "acceptance": [{"condition": condition,
            "outcome": "met" if status == "succeeded" else "unmet",
            "explanation": "The exact terminal workflow contains this observed result.",
            "reference": workflow_ref}
            for condition in task["definition"]["acceptance"]]}


def resolve(service, task, references, status="succeeded", value=None):
    workflow_ref = next(ref for ref in references if ref.startswith("workflow:"))
    return service[0].resolve(task["id"], expected_revision=1, expected_task_revision=1,
        key="resolve-acceptance", references=references, status=status,
        assessment=value or assessment(task, workflow_ref, status), decision=None)


def test_terminal_workflow_and_root_assessment_resolve_without_child(service):
    task, workflow = terminal_work(service)
    result = resolve(service, task, [workflow])
    resolved = result["tasks"][0]
    assert resolved["status"] == "succeeded"
    assert resolved["assurance"] == "agent-assessment"
    assert not service[1].inspect(service[0].handle.session_id).delegations
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    reference = resolved["result_report_reference"]
    report = SessionArtifactStore(service[0].handle).read_json(reference)
    assert report["task_id"] == task["id"]
    assert report["definition_digest"] == task["definition_digest"]
    assert report["result_references"] == [workflow]
    assert report["assessment"] == {**assessment(task, workflow), "actor_id": "owner"}
    assert report["optional_review_reference"] is None
    assert resolved["evidence"]["payload_digest"] == reference.removeprefix("sha256:")


def test_task_list_prepares_exact_review_assignment_without_accepting_work(service):
    task, workflow_ref = terminal_work(service)
    result = service[0].list()
    review = result["tasks"][0]["optional_resolution_review"]
    assert review["assignment"]["task_id"] == task["id"]
    assert review["assignment"]["definition_digest"] == task["definition_digest"]
    assert review["workflow_reference"] == workflow_ref
    assert review["acceptance_conditions"] == task["definition"]["acceptance"]
    assert not result["all_terminal"]


def _assert_consumed_review(service, status):
    task, workflow = terminal_work(service, status)
    review = acceptance_review(service, task, workflow, status=status)
    result = resolve(service, task, [review, workflow], status)
    assert result["tasks"][0]["status"] == status
    assert set(result["tasks"][0]["evidence"]["references"]) == {review, workflow}
    assert result["tasks"][0]["evidence"]["reason"]
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    report = SessionArtifactStore(service[0].handle).read_json(
        result["tasks"][0]["result_report_reference"])
    assert report["optional_review_reference"] == review
    assert report["assurance"] == "agent-assessment"


def test_consumed_exact_review_resolves_success(service):
    _assert_consumed_review(service, "succeeded")


def test_consumed_exact_review_resolves_failure(service):
    _assert_consumed_review(service, "failed")


@pytest.mark.parametrize("fault", ["missing-condition", "changed-condition", "foreign-evidence",
                                     "unmet-success", "stale-workflow", "changed-definition", "status"])
def test_acceptance_review_cannot_hide_missing_or_mismatched_evidence(service, fault):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    task, workflow = terminal_work(service)

    def mutate(assignment, report):
        if fault == "missing-condition":
            report["acceptance"].pop()
        elif fault == "changed-condition":
            report["acceptance"][0]["condition"] = "An easier condition"
        elif fault == "foreign-evidence":
            report["acceptance"][0]["references"] = ["workflow:other:1"]
        elif fault == "unmet-success":
            report["acceptance"][0]["outcome"] = "unmet"
        elif fault == "status":
            report["status"] = "failed"
        else:
            field, value = ("workflow_revision", 0) if fault == "stale-workflow" else ("definition_digest", "b" * 64)
            assignment[field] = report["assignment"][field] = value

    review = acceptance_review(service, task, workflow, mutate=mutate)
    with pytest.raises(TaskLedgerError):
        resolve(service, task, [workflow, review])
    assert service[0].list()["revision"] == 1


@pytest.mark.parametrize("fault", ["missing", "changed", "foreign"])
def test_root_assessment_rejects_missing_changed_or_wrong_coverage(service, fault):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    task, workflow = terminal_work(service)
    value = assessment(task, workflow)
    if fault == "missing":
        value["acceptance"].pop()
    elif fault == "changed":
        value["acceptance"][0]["condition"] = "Easier condition"
    else:
        value["acceptance"][0]["reference"] = "workflow:other:1"
    with pytest.raises(TaskLedgerError):
        resolve(service, task, [workflow], value=value)
    assert service[0].list()["tasks"][0]["status"] == "pending"


def test_unconsumed_acceptance_report_cannot_resolve_task(service):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    task, workflow = terminal_work(service)
    review = acceptance_review(service, task, workflow, consumed=False)
    with pytest.raises(TaskLedgerError, match="consumed"):
        resolve(service, task, [workflow, review])


def test_failed_workflow_does_not_excuse_missing_failure_condition(service):
    from scripts.agent_harness.task_ledger import TaskLedgerError
    task, workflow = terminal_work(service, "failed")
    def mutate(_assignment, report):
        for entry in report["acceptance"]:
            entry["outcome"] = "met"
    review = acceptance_review(service, task, workflow, status="failed", mutate=mutate)
    with pytest.raises(TaskLedgerError, match="acceptance conditions"):
        resolve(service, task, [workflow, review], "failed")
