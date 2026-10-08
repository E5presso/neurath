"""Invariant tests for the new domain, independent of database and host."""
import pytest
from neurath.domain import Criterion, Delegation, DomainError, Evidence, Lease, Phase, Task
from neurath.domain.codec import entity_from_dict
from neurath.domain.errors import AuthorizationError, ConflictError


def task():
    return Task(id="task", owner_id="owner", source_id="source", goal="Ship result", criteria=[Criterion("correct", "Result verified")], phases=[Phase("build", "Build"), Phase("verify", "Verify")])


def test_phase_order_and_completion_require_explicit_success():
    item = task()
    item.activate()
    with pytest.raises(DomainError):
        item.start_phase("verify")
    item.start_phase("build")
    item.complete_phase("build", ["build-evidence"])
    item.start_phase("verify")
    item.complete_phase("verify", ["verify-evidence"])
    with pytest.raises(DomainError):
        item.complete([])
    item.satisfy("correct", ["verified"])
    item.complete([])
    assert item.status == "completed"


def test_failure_evidence_and_report_cannot_establish_success():
    item = task()
    for evidence_type, success in [("tool", False), ("tool", None), ("report", None)]:
        evidence = Evidence(id="e", task_id=item.id, actor_id="owner", evidence_type=evidence_type, content="Result", scope_version=1, success=success, criterion_id="correct")
        with pytest.raises(DomainError):
            evidence.supports(item, criterion_id="correct")
    assert item.status == "pending"


def test_evidence_is_bound_to_scope_and_criterion():
    item = task()
    evidence = Evidence(id="e", task_id=item.id, actor_id="owner", evidence_type="tool", content="pass", scope_version=1, success=True, criterion_id="correct")
    evidence.supports(item, criterion_id="correct")
    with pytest.raises(DomainError):
        evidence.supports(item, criterion_id="other")
    item.scope_version += 1
    with pytest.raises(DomainError):
        evidence.supports(item, criterion_id="correct")


def test_delegation_report_and_parent_completion_are_independent():
    item = task()
    delegation = Delegation(id="d", task_id=item.id, owner_id="owner", recipient_id="child", instruction="Review")
    delegation.transition("start", "child")
    delegation.transition("report", "child", report="Review done")
    assert item.status == "pending"
    with pytest.raises(AuthorizationError):
        delegation.transition("accept", "child")
    delegation.transition("reject", "owner", reason="Need evidence")
    delegation.transition("start", "child")
    delegation.transition("report", "child", report="Fixed")
    delegation.transition("accept", "owner")
    assert item.status == "pending"


def test_stale_writer_is_fenced_and_codec_is_lossless():
    lease = Lease(id="l", resource="checkout", owner_id="new", generation=4)
    with pytest.raises(ConflictError):
        lease.check("old", 3)
    with pytest.raises(ConflictError):
        lease.check("new", 3)
    lease.check("new", 4)
    item = task()
    assert entity_from_dict("task", item.to_dict()) == item


def test_unknown_imported_evidence_cannot_gain_authority():
    item = task()
    evidence = Evidence(id="legacy", task_id=item.id, actor_id="owner", evidence_type="legacy-unclassified", content="Archived claim", scope_version=1, criterion_id="correct")
    with pytest.raises(DomainError):
        evidence.supports(item, criterion_id="correct")
