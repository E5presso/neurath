"""Consumed delegation shared read model의 immutable review policy 계약입니다."""

import hashlib
import inspect
import json
from collections.abc import Mapping
from unittest import TestCase

from scripts.agent_harness.delegation_evidence import (
    ConsumedDelegationEvidenceReader,
    ConsumedDelegationEvidenceSnapshot,
    DelegationEvidenceInvalid,
    FinalReviewEvidencePolicy,
)
from scripts.agent_harness.session_kernel import ActorId, DelegationId, WorkflowId

REVIEW_ROWS = (
    ("C01", "architecture-boundary", "critical"),
    ("C02", "type-discipline", "warning"),
    ("C03", "yagni", "warning"),
    ("C04", "domain-boundary", "critical"),
    ("C05", "naming", "warning"),
    ("C06", "test-gate", "critical"),
    ("C07", "readability", "warning"),
    ("C08", "api-contract", "warning"),
    ("C09", "persistence", "warning"),
    ("C10", "transaction-integrity", "critical"),
    ("C11", "pattern-consistency", "warning"),
    ("C12", "defensive-helper", "warning"),
    ("C13", "operations-consistency", "warning"),
    ("C14", "spec-completeness", "critical"),
)


class DelegationEvidenceTest(TestCase):
    """Publisher와 phase runner가 공유할 read-only evidence projection을 검증합니다."""

    head = "1" * 40
    """Canonical matrix와 artifact report가 공유하는 exact head fixture입니다."""

    outcome_ref = "sha256:" + "2" * 64
    """Bounded verification이 보존해야 할 artifact reference fixture입니다."""

    def snapshot(self) -> ConsumedDelegationEvidenceSnapshot:
        """Canonical final-local-review assignment와 artifact report를 만듭니다."""
        rows = [
            {"category": category, "row_id": row_id, "severity": severity}
            for row_id, category, severity in REVIEW_ROWS
        ]
        matrix_identity = json.dumps(
            {"head_sha": self.head, "rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        matrix_id = hashlib.sha256(matrix_identity.encode()).hexdigest()
        row_ids = [row_id for row_id, _category, _severity in REVIEW_ROWS]
        return ConsumedDelegationEvidenceSnapshot(
            process_revision=8,
            workflow_id=WorkflowId("process-ticket-42"),
            workflow_revision=5,
            delegation_id=DelegationId("final-review-42"),
            owner_actor_id=ActorId("codex:session-42"),
            target_actor_id=ActorId("codex:reviewer-42"),
            kind="final-local-review",
            reviewed_head_sha=self.head,
            outcome_ref=self.outcome_ref,
            skill_state={"commit_done": {"sha": self.head}},
            assignment={
                "kind": "final-local-review",
                "review_acceptance_matrix": {
                    "frozen": True,
                    "head_sha": self.head,
                    "matrix_id": matrix_id,
                    "row_count": 14,
                    "rows": rows,
                },
                "reviewed_head_sha": self.head,
                "scope": "exact-head review",
                "started_at": "2026-08-04T00:00:00+00:00",
                "target": "reviewer",
                "workflow_id": "process-ticket-42",
            },
            report={
                "blocking_findings": [],
                "harness_audit": {
                    "checked": True,
                    "evidence": [
                        "git_diff:sha256:" + "3" * 64,
                        "process_state:sha256:" + "4" * 64,
                        "execution_trajectory:sha256:" + "5" * 64,
                    ],
                },
                "matrix_head_sha": self.head,
                "matrix_id": matrix_id,
                "review_findings": [],
                "summary": "pass",
                "verified_review_rows": row_ids,
                "verdict": "pass",
            },
        )

    def test_final_review_policy_returns_bounded_phase_and_publication_receipt(self) -> None:
        """Canonical matrix/artifact는 path-free bounded verification으로 투영됩니다."""
        verification = FinalReviewEvidencePolicy().verify(self.snapshot())

        self.assertEqual(self.head, verification.head_sha)
        self.assertEqual(self.outcome_ref, verification.outcome_ref)
        self.assertEqual(
            tuple(f"C{index:02d}" for index in range(1, 15)), verification.verified_rows
        )
        self.assertEqual(0, verification.blocking_finding_count)
        self.assertEqual(3, verification.harness_audit_evidence_count)
        self.assertEqual(14, verification.to_payload()["verified_row_count"])

    def test_policy_accepts_explicit_review_code_kind_without_weakening_default(self) -> None:
        """같은 matrix 정책은 명시한 review kind에만 재사용되고 default는 유지됩니다."""
        source = self.snapshot()
        assignment = source.assignment_payload()
        assignment["kind"] = "review-code"
        review_code = ConsumedDelegationEvidenceSnapshot(
            process_revision=source.process_revision,
            workflow_id=source.workflow_id,
            workflow_revision=source.workflow_revision,
            delegation_id=source.delegation_id,
            owner_actor_id=source.owner_actor_id,
            target_actor_id=source.target_actor_id,
            kind="review-code",
            reviewed_head_sha=source.reviewed_head_sha,
            outcome_ref=source.outcome_ref,
            skill_state=source.skill_state_payload(),
            assignment=assignment,
            report=source.report_payload(),
        )

        verification = FinalReviewEvidencePolicy().verify(
            review_code,
            expected_kind="review-code",
        )

        self.assertEqual(self.head, verification.head_sha)
        with self.assertRaisesRegex(DelegationEvidenceInvalid, "final-local-review"):
            FinalReviewEvidencePolicy().verify(review_code)

    def test_snapshot_is_deeply_immutable_but_exposes_detached_json_payloads(self) -> None:
        """Shared snapshot은 mutation을 거부하고 consumer용 payload는 detached copy입니다."""
        snapshot = self.snapshot()
        payload = snapshot.assignment_payload()
        payload["kind"] = "changed"
        matrix = payload["review_acceptance_matrix"]
        if not isinstance(matrix, dict):
            self.fail("detached review matrix must be an object")
        matrix["frozen"] = False

        self.assertEqual("final-local-review", snapshot.assignment["kind"])
        persisted_matrix = snapshot.assignment["review_acceptance_matrix"]
        if not isinstance(persisted_matrix, Mapping):
            self.fail("persisted review matrix must be an immutable mapping")
        self.assertEqual(True, persisted_matrix["frozen"])
        with self.assertRaises(AttributeError):
            snapshot.kind = "changed"

    def test_policy_rejects_self_consistent_but_noncanonical_matrix(self) -> None:
        """Assignment 안 matrix를 임의 row로 바꿔도 publication policy를 우회하지 못합니다."""
        snapshot = self.snapshot()
        assignment = snapshot.assignment_payload()
        matrix = assignment["review_acceptance_matrix"]
        if not isinstance(matrix, dict):
            self.fail("review matrix must be an object")
        matrix["row_count"] = 13
        corrupted = ConsumedDelegationEvidenceSnapshot(
            process_revision=snapshot.process_revision,
            workflow_id=snapshot.workflow_id,
            workflow_revision=snapshot.workflow_revision,
            delegation_id=snapshot.delegation_id,
            owner_actor_id=snapshot.owner_actor_id,
            target_actor_id=snapshot.target_actor_id,
            kind=snapshot.kind,
            reviewed_head_sha=snapshot.reviewed_head_sha,
            outcome_ref=snapshot.outcome_ref,
            skill_state=snapshot.skill_state_payload(),
            assignment=assignment,
            report=snapshot.report_payload(),
        )

        with self.assertRaisesRegex(DelegationEvidenceInvalid, "matrix"):
            FinalReviewEvidencePolicy().verify(corrupted)

    def test_reader_public_surface_has_no_path_or_state_selector(self) -> None:
        """Shared reader는 StateHandle과 WorkflowId 밖의 storage selector를 노출하지 않습니다."""
        constructor = inspect.signature(ConsumedDelegationEvidenceReader)
        read = inspect.signature(ConsumedDelegationEvidenceReader.read)

        self.assertEqual(("handle", "workflow_id"), tuple(constructor.parameters))
        for parameters in (constructor.parameters, read.parameters):
            self.assertNotIn("path", parameters)
            self.assertNotIn("state", parameters)
            self.assertNotIn("session_id", parameters)
        self.assertNotIn("require_direct_child", read.parameters)
