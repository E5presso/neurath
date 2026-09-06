"""Persisted delegation topology가 independent evidence authority를 소유하는지 검증합니다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.delegation_evidence import (
    ConsumedDelegationEvidenceReader,
    DelegationEvidenceInvalid,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    InvalidSessionState,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    SessionStateCodec,
    TransitionRejected,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle


class DelegationTopologyPolicyTest(TestCase):
    """Assignment admission, persistence, migration과 evidence consumption을 검증합니다."""

    def setUp(self) -> None:
        """Root, child owner, sibling, direct child와 grandchild topology를 만듭니다."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.locator = SessionLocator(Path(self.directory.name))
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("delegation-topology")
        self.root_id = ActorId("codex:delegation-topology")
        self.owner_id = ActorId("codex:owner")
        self.sibling_id = ActorId("codex:sibling")
        self.direct_child_id = ActorId("codex:direct-child")
        self.intermediate_id = ActorId("codex:intermediate")
        self.grandchild_id = ActorId("codex:grandchild")
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume:delegation-topology"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.root_id,
                idempotency_key="session:delegation-topology",
            )
        )
        for actor_id, parent_id in (
            (self.owner_id, self.root_id),
            (self.sibling_id, self.root_id),
            (self.direct_child_id, self.owner_id),
            (self.intermediate_id, self.owner_id),
            (self.grandchild_id, self.intermediate_id),
        ):
            self.kernel.apply(
                ActorStarted(
                    session_id=self.session_id,
                    actor_id=actor_id,
                    parent_actor_id=parent_id,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"actor:{actor_id}",
                    lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
                )
            )

    def test_direct_child_policy_admits_only_exact_child_without_root_fallback(self) -> None:
        """Sibling, grandchild와 parent 없는 root를 direct-child authority로 대체하지 않습니다."""
        assignment = '{"kind":"independent-evaluation","workflow_id":"workflow-1"}'
        accepted = self.kernel.apply(
            self._assignment(
                "direct",
                self.direct_child_id,
                DelegationTopologyPolicy.DIRECT_CHILD,
                assignment=assignment,
            )
        )

        record = accepted.delegations[DelegationId("direct")]
        self.assertEqual(
            DelegationTopologyPolicy.DIRECT_CHILD,
            record.topology_policy,
        )
        self.assertEqual(
            hashlib.sha256(assignment.encode()).digest(),
            hashlib.sha256(record.assignment.encode()).digest(),
        )
        for delegation_id, target in (
            ("sibling", self.sibling_id),
            ("grandchild", self.grandchild_id),
            ("root-fallback", self.root_id),
        ):
            with (
                self.subTest(target=target),
                self.assertRaisesRegex(
                    TransitionRejected,
                    "direct child",
                ),
            ):
                self.kernel.apply(
                    self._assignment(
                        delegation_id,
                        target,
                        DelegationTopologyPolicy.DIRECT_CHILD,
                    )
                )

    def test_same_session_policy_does_not_claim_direct_child_authority(self) -> None:
        """Sibling assignment은 same-session delivery로 가능해도 independent authority가 아닙니다."""
        state = self.kernel.apply(
            self._assignment(
                "same-session-sibling",
                self.sibling_id,
                DelegationTopologyPolicy.SAME_SESSION,
            )
        )

        self.assertEqual(
            DelegationTopologyPolicy.SAME_SESSION,
            state.delegations[DelegationId("same-session-sibling")].topology_policy,
        )

    def test_unattested_parent_lineage_cannot_admit_direct_child_authority(self) -> None:
        """Persisted parent pointer만으로 independent evaluator authority를 얻지 못합니다."""
        target_id = ActorId("codex:unattested-child")
        self.kernel.apply(
            ActorStarted(
                session_id=self.session_id,
                actor_id=target_id,
                parent_actor_id=self.owner_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:unattested-child",
            )
        )

        with self.assertRaisesRegex(TransitionRejected, "host-attested"):
            self.kernel.apply(
                self._assignment(
                    "unattested-direct-child",
                    target_id,
                    DelegationTopologyPolicy.DIRECT_CHILD,
                )
            )

        same_session = self.kernel.apply(
            self._assignment(
                "unattested-same-session",
                target_id,
                DelegationTopologyPolicy.SAME_SESSION,
            )
        )
        self.assertEqual(
            DelegationTopologyPolicy.SAME_SESSION,
            same_session.delegations[DelegationId("unattested-same-session")].topology_policy,
        )

    def test_codec_rejects_direct_child_record_when_actor_attestation_is_removed(self) -> None:
        """Persisted payload도 parent pointer만 남은 DIRECT_CHILD record를 복원하지 않습니다."""
        accepted = self.kernel.apply(
            self._assignment(
                "tampered-assurance",
                self.direct_child_id,
                DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        payload = json.loads(SessionStateCodec().encode(accepted))
        del payload["actors"][str(self.direct_child_id)]["lineage_assurance"]

        with self.assertRaisesRegex(InvalidSessionState, "assurance"):
            SessionStateCodec().decode(payload, self.session_id)

    def test_legacy_missing_policy_round_trips_without_changing_content_digest(self) -> None:
        """Policy 없는 legacy record는 UNSPECIFIED이며 canonical payload digest를 보존합니다."""
        legacy = self.kernel.apply(
            self._assignment(
                "legacy",
                self.direct_child_id,
                DelegationTopologyPolicy.UNSPECIFIED,
            )
        )
        encoded = SessionStateCodec().encode(legacy)
        decoded = SessionStateCodec().decode(json.loads(encoded), self.session_id)
        reencoded = SessionStateCodec().encode(decoded)
        delegation_payload = decoded.delegations[DelegationId("legacy")].to_payload()

        self.assertEqual(
            DelegationTopologyPolicy.UNSPECIFIED,
            decoded.delegations[DelegationId("legacy")].topology_policy,
        )
        self.assertNotIn("topology_policy", delegation_payload)
        self.assertEqual(encoded, reencoded)
        self.assertEqual(hashlib.sha256(encoded).digest(), hashlib.sha256(reencoded).digest())

    def test_evidence_reader_uses_persisted_policy_and_rejects_legacy_record(self) -> None:
        """Caller flag 없이 DIRECT_CHILD만 소비하고 actual child인 legacy record도 거부합니다."""
        workflow_id = WorkflowId("independent-evaluation")
        owner = self._handle(self.owner_id)
        owner.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=workflow_id,
                owner_actor_id=self.owner_id,
                kind="evaluate-harness",
                goal="independent evidence topology를 검증한다",
                payload={"skill_state": {}},
                idempotency_key="workflow:independent-evaluation",
            )
        )
        direct_id = self._consumed_evidence(
            owner,
            workflow_id,
            "direct-evidence",
            DelegationTopologyPolicy.DIRECT_CHILD,
        )
        reader = ConsumedDelegationEvidenceReader(owner, workflow_id)

        direct = reader.read(kind="direct-evidence")

        self.assertEqual(direct_id, direct.delegation_id)
        self._consumed_evidence(
            owner,
            workflow_id,
            "legacy-evidence",
            DelegationTopologyPolicy.UNSPECIFIED,
        )
        with self.assertRaisesRegex(DelegationEvidenceInvalid, "DIRECT_CHILD"):
            reader.read(kind="legacy-evidence")

    def _assignment(
        self,
        delegation_id: str,
        target_actor_id: ActorId,
        topology_policy: DelegationTopologyPolicy,
        *,
        assignment: str = "bounded delegated task",
    ) -> DelegationAssigned:
        """Topology scenario 하나에 사용할 typed assignment event를 만듭니다."""
        return DelegationAssigned(
            session_id=self.session_id,
            delegation_id=DelegationId(delegation_id),
            owner_actor_id=self.owner_id,
            target_actor_id=target_actor_id,
            assignment=assignment,
            idempotency_key=f"delegation:{delegation_id}",
            topology_policy=topology_policy,
        )

    def _consumed_evidence(
        self,
        owner: StateHandle,
        workflow_id: WorkflowId,
        kind: str,
        topology_policy: DelegationTopologyPolicy,
    ) -> DelegationId:
        """Direct target가 report한 digest artifact를 owner가 consume하게 합니다."""
        delegation_id = DelegationId(kind)
        assignment = json.dumps(
            {
                "kind": kind,
                "scope": "frozen matrix",
                "started_at": "2026-08-17T00:00:00+00:00",
                "target": "independent evaluator",
                "workflow_id": str(workflow_id),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        owner.apply(
            self._assignment(
                str(delegation_id),
                self.direct_child_id,
                topology_policy,
                assignment=assignment,
            )
        )
        report = {
            "blocking_findings": [],
            "summary": "independent evaluation completed",
            "verdict": "pass",
        }
        artifact = SessionArtifactStore(owner).put_json({
            "delegation_id": str(delegation_id),
            "report": report,
            "schema": "neurath.delegation-result.v1",
            "target_agent_id": str(self.direct_child_id),
        })
        child = self._handle(self.direct_child_id)
        child.apply(
            DelegationReported(
                session_id=self.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=self.direct_child_id,
                result=DelegationResult(
                    verdict="pass",
                    summary="independent evaluation completed",
                    outcome_ref=artifact.reference,
                    blocking_findings=(),
                ),
                idempotency_key=f"delegation:{delegation_id}:reported",
            )
        )
        owner.apply(
            DelegationConsumed(
                session_id=self.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=self.owner_id,
                idempotency_key=f"delegation:{delegation_id}:consumed",
            )
        )
        return delegation_id

    def _handle(self, actor_id: ActorId) -> StateHandle:
        """Current test topology actor에 exact-session handle을 결속합니다."""
        return StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=self.session_id,
                actor_id=actor_id,
                root_actor_id=self.root_id,
            ),
        )
