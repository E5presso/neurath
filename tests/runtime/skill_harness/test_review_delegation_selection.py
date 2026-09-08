"""Explicit review delegation selection preserves all underlying evidence gates."""

import json

import pytest

from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.delegation_evidence import (
    ConsumedDelegationEvidenceReader,
    DelegationEvidenceConflict,
    DelegationEvidenceError,
)
from scripts.agent_harness.session_kernel import (
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    WorkflowId,
)
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle
from scripts.skill_harness.tests.test_phase_runner import PhaseRunnerFixture


def add_delegation(fixture, identifier, *, assignment=None, verdict="pass", consumed=True):
    owner = fixture._state_handle
    original = owner.inspect().delegations[DelegationId("review-1")]
    owner.apply(DelegationAssigned(session_id=owner.session_id,
        delegation_id=DelegationId(identifier), owner_actor_id=owner.actor_id,
        target_actor_id=original.target_actor_id, assignment=assignment or original.assignment,
        idempotency_key=identifier + ":assign", topology_policy=DelegationTopologyPolicy.DIRECT_CHILD))
    reviewer = StateHandle.attach(fixture.locator, RuntimeIdentityBinding(runtime=owner.runtime,
        session_id=owner.session_id, actor_id=original.target_actor_id, root_actor_id=owner.actor_id))
    artifact = SessionArtifactStore(reviewer).read_json(original.result.outcome_ref)
    artifact["delegation_id"] = identifier
    artifact["report"]["verdict"] = verdict
    artifact["report"]["blocking_findings"] = ["F-block"] if verdict == "block" else []
    ref = SessionArtifactStore(reviewer).put_json(artifact).reference
    reviewer.apply(DelegationReported(session_id=owner.session_id, delegation_id=DelegationId(identifier),
        reporter_actor_id=reviewer.actor_id, result=DelegationResult(verdict=verdict,
        summary=artifact["report"]["summary"], outcome_ref=ref,
        blocking_findings=tuple(artifact["report"]["blocking_findings"])), idempotency_key=identifier + ":report"))
    if consumed:
        owner.apply(DelegationConsumed(session_id=owner.session_id, delegation_id=DelegationId(identifier),
            consumer_actor_id=owner.actor_id, idempotency_key=identifier + ":consume"))
    return ref


def initialize(fixture):
    fixture.write_review_code_contract()
    fixture.run("init", "--skill", "review-code", "--run-id", "review-001")
    return fixture.write_review_completion("a" * 40)


def test_plain_unrelated_assignment_does_not_block_review_phase_completion():
    with PhaseRunnerFixture() as fixture:
        outcome = initialize(fixture)
        add_delegation(fixture, "generic-work", assignment="Read a bounded module without editing")
        result = fixture.complete_review_code("a" * 40, outcome_ref=outcome)
        assert result.exit_code == 0, result.output


def test_explicit_pass_is_selected_even_with_another_block_at_same_workflow_head():
    with PhaseRunnerFixture() as fixture:
        outcome = initialize(fixture)
        add_delegation(fixture, "other-block", verdict="block")
        reader = ConsumedDelegationEvidenceReader(fixture._state_handle, WorkflowId(fixture.workflow_id))
        with pytest.raises(DelegationEvidenceConflict):
            reader.read(kind="review-code", reviewed_head_sha="a" * 40)
        selected = reader.read(kind="review-code", reviewed_head_sha="a" * 40, delegation_id="review-1")
        assert str(selected.delegation_id) == "review-1"
        result = fixture.complete_review_code("a" * 40, outcome_ref=outcome)
        assert result.exit_code == 0, result.output


def test_legacy_lookup_ignores_unrelated_plain_or_incomplete_selector():
    with PhaseRunnerFixture() as fixture:
        initialize(fixture)
        add_delegation(fixture, "plain", assignment="Ordinary task text")
        add_delegation(fixture, "other-workflow", assignment=json.dumps({"workflow_id": "other", "kind": "review-code"}))
        reader = ConsumedDelegationEvidenceReader(fixture._state_handle, WorkflowId(fixture.workflow_id))
        assert str(reader.read(kind="review-code", reviewed_head_sha="a" * 40).delegation_id) == "review-1"


@pytest.mark.parametrize("selected", ["missing", "plain", "unconsumed", "wrong-workflow", "wrong-kind", "wrong-head"])
def test_exact_selector_does_not_weaken_identity_or_consumption(selected):
    with PhaseRunnerFixture() as fixture:
        initialize(fixture)
        original = json.loads(fixture._state_handle.inspect().delegations[DelegationId("review-1")].assignment)
        add_delegation(fixture, "plain", assignment="Ordinary task text")
        add_delegation(fixture, "unconsumed", consumed=False)
        for identifier, key, value in (("wrong-workflow", "workflow_id", "other"),
                ("wrong-kind", "kind", "other"), ("wrong-head", "reviewed_head_sha", "b" * 40)):
            add_delegation(fixture, identifier, assignment=json.dumps({**original, key: value}))
        reader = ConsumedDelegationEvidenceReader(fixture._state_handle, WorkflowId(fixture.workflow_id))
        with pytest.raises(DelegationEvidenceError):
            reader.read(kind="review-code", reviewed_head_sha="a" * 40, delegation_id=selected)


def test_selected_foreign_owner_is_rejected_before_assignment_read():
    with PhaseRunnerFixture() as fixture:
        initialize(fixture)
        owner = fixture._state_handle
        original = owner.inspect().delegations[DelegationId("review-1")]
        foreign = StateHandle.attach(fixture.locator, RuntimeIdentityBinding(runtime=owner.runtime,
            session_id=owner.session_id, actor_id=original.target_actor_id, root_actor_id=owner.actor_id))
        foreign.apply(DelegationAssigned(session_id=owner.session_id, delegation_id=DelegationId("foreign"),
            owner_actor_id=foreign.actor_id, target_actor_id=owner.actor_id, assignment="Unrelated plain assignment",
            idempotency_key="foreign:assign", topology_policy=DelegationTopologyPolicy.SAME_SESSION))
        reader = ConsumedDelegationEvidenceReader(owner, WorkflowId(fixture.workflow_id))
        with pytest.raises(DelegationEvidenceError, match="owner"):
            reader.read(kind="review-code", reviewed_head_sha="a" * 40, delegation_id="foreign")
        assert str(reader.read(kind="review-code", reviewed_head_sha="a" * 40).delegation_id) == "review-1"


def test_matching_legacy_selector_still_requires_complete_assignment_identity():
    with PhaseRunnerFixture() as fixture:
        initialize(fixture)
        add_delegation(fixture, "incomplete-review", assignment=json.dumps({"workflow_id": fixture.workflow_id,
            "kind": "review-code", "reviewed_head_sha": "a" * 40}))
        reader = ConsumedDelegationEvidenceReader(fixture._state_handle, WorkflowId(fixture.workflow_id))
        with pytest.raises(DelegationEvidenceError, match="identity"):
            reader.read(kind="review-code", reviewed_head_sha="a" * 40)


def test_phase_requires_explicit_transition_id_without_legacy_fallback():
    with PhaseRunnerFixture() as fixture:
        outcome = initialize(fixture)
        evidence = tuple(item.replace("delegation_id=review-1", "")
            if item.startswith("delegate_transition_receipt:") else item
            for item in fixture.review_evidence("a" * 40, outcome))
        result = fixture.run("complete", "--phase-id", "1", "--status", "completed",
            "--summary", "review complete", *evidence)
        assert result.exit_code == 1
        assert "delegate_transition_receipt.identity" in str(result.payload["message"])
