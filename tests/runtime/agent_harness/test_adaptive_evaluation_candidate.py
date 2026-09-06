"""독립 evaluator 입력이 exact session/workflow snapshot에 고정되는지 검증합니다."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    GapInventory,
    GoalContract,
    OracleOwner,
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionTarget,
    approved_requirement_fingerprint,
    user_decision_value_summary_digest,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    AdaptiveControlStore,
)
from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateAuthorityError,
    AdaptiveEvaluationCandidateConflict,
    AdaptiveEvaluationCandidateInvalid,
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.material_action import (
    MaterialActionKind,
    MaterialActionResolution,
    ObservableDeltaKind,
    ObservableExpectation,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    ActorStatus,
    ActorStopped,
    DelegationAssigned,
    DelegationId,
    DelegationTopologyPolicy,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    MaterialActionPrepared,
    MaterialActionResolved,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle


class AdaptiveEvaluationCandidateStoreTest(TestCase):
    """Owner가 고정한 candidate만 같은 session의 active child가 읽는지 검증합니다."""

    def setUp(self) -> None:
        """Root owner, direct child와 active workflow를 가진 exact session을 만듭니다."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.control_root = Path(directory.name)
        self.locator = SessionLocator(self.control_root)
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("adaptive-candidate-session")
        self.root_actor_id = ActorId("codex:adaptive-candidate-session")
        self.child_actor_id = ActorId("codex:adaptive-evaluator")
        self.workflow_id = WorkflowId("adaptive-workflow")
        self._start_topology(
            self.session_id,
            self.root_actor_id,
            self.child_actor_id,
            self.workflow_id,
        )
        self.owner = self._handle(
            self.session_id,
            self.root_actor_id,
            self.root_actor_id,
        )
        self.child = self._handle(
            self.session_id,
            self.child_actor_id,
            self.root_actor_id,
        )
        self.state = self._state()
        self.delegation_sequence = 0

    def test_owner_prepares_content_addressed_candidate_and_child_reads_typed_state(self) -> None:
        """Assignment와 artifact가 exact workflow와 full adaptive payload를 함께 고정합니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        repeated = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        assignment = json.loads(prepared.assignment_json)
        source_payload = dict(self.owner.inspect().workflows[self.workflow_id].payload)
        target_payload = self._target_workflow_payload(source_payload)
        trajectory: dict[str, object] = {
            "schema": "neurath.adaptive-evaluation-trajectory.v1",
            "material_action": None,
        }

        self.assertEqual(
            {
                "candidate_ref": prepared.candidate_ref,
                "goal_fingerprint": self.state.contract.fingerprint,
                "intent_revision": self.state.contract.intent_revision,
                "kind": "adaptive-goal-evaluation",
                "source_revision": self.state.contract.source_revision,
                "trajectory_digest": self._payload_digest(trajectory),
                "target_workflow_revision": 1,
                "target_workflow_payload_digest": self._payload_digest(target_payload),
                "workflow_id": str(self.workflow_id),
                "workflow_revision": 0,
                "workflow_payload_digest": self._payload_digest(source_payload),
            },
            assignment,
        )
        self.assertEqual(
            prepared.assignment_json,
            json.dumps(
                assignment,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        artifact = SessionArtifactStore(self.owner).read_json(prepared.candidate_ref)
        self.assertEqual(str(self.session_id), artifact["session_id"])
        self.assertEqual(str(self.workflow_id), artifact["workflow_id"])
        self.assertEqual(0, artifact["workflow_revision"])
        self.assertEqual(1, artifact["target_workflow_revision"])
        self.assertEqual(
            self._payload_digest(source_payload),
            artifact["workflow_payload_digest"],
        )
        self.assertEqual(
            self._payload_digest(target_payload),
            artifact["target_workflow_payload_digest"],
        )
        self.assertEqual(self.state.to_payload(), artifact["state"])
        self.assertEqual(trajectory, artifact["trajectory"])
        self.assertEqual(self._payload_digest(trajectory), artifact["trajectory_digest"])
        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)
        restored = AdaptiveEvaluationCandidateStore(
            self.child,
            self.workflow_id,
        ).read_candidate(prepared.assignment_json)

        self.assertEqual(self.state, restored.state)
        self.assertEqual(trajectory, restored.trajectory)
        self.assertEqual(prepared.candidate_ref, repeated.candidate_ref)
        self.assertEqual(prepared.assignment_json, repeated.assignment_json)

    def test_material_trajectory_is_content_bound_and_stale_before_evaluation(self) -> None:
        """Evaluator는 latest raw-free material path를 읽고 이후 trajectory change를 거부합니다."""
        target = self.control_root / "trajectory.py"
        target.write_text("value = 1\n", encoding="utf-8")
        self.owner.apply(
            ForegroundTurnPrompted(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                vendor_turn_id="trajectory-turn",
                idempotency_key="trajectory:turn",
            )
        )
        turn = self.owner.inspect().foreground_turns[self.root_actor_id]
        self.owner.apply(
            MaterialActionPrepared(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                batch_id="trajectory-batch",
                sequence=1,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=(str(target),),
                expectations=(
                    ObservableExpectation(
                        observable_id=str(target),
                        baseline_digest=hashlib.sha256(target.read_bytes()).hexdigest(),
                        expected_delta=ObservableDeltaKind.CHANGED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=None,
                idempotency_key="trajectory:prepare",
            )
        )
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)

        readback = AdaptiveEvaluationCandidateStore(
            self.child,
            self.workflow_id,
        ).read_candidate(prepared.assignment_json)

        self.assertEqual(
            self.owner.inspect().material_actions[self.root_actor_id].to_payload(),
            readback.trajectory["material_action"],
        )
        self.owner.apply(
            MaterialActionResolved(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                batch_id="trajectory-batch",
                expected_batch_revision=0,
                resolution=MaterialActionResolution.ABORTED,
                idempotency_key="trajectory:abort",
            )
        )
        with self.assertRaises(AdaptiveEvaluationCandidateConflict):
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).read_candidate(prepared.assignment_json)

    def test_prepare_requires_current_active_workflow_owner(self) -> None:
        """Child, unrelated actor와 terminal owner는 evaluator input을 발행할 수 없습니다."""
        with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).prepare(self.state)

        terminal_workflow = WorkflowId("terminal-owner-workflow")
        self.child.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=terminal_workflow,
                owner_actor_id=self.child_actor_id,
                kind="evaluate-harness",
                goal=self.state.contract.goal,
                payload={"skill_state": {}},
                idempotency_key="start-terminal-owner-workflow",
            )
        )
        self.child.apply(
            ActorStopped(
                session_id=self.session_id,
                actor_id=self.child_actor_id,
                terminal_status=ActorStatus.STOPPED,
                idempotency_key="stop-candidate-owner",
            )
        )
        with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
            AdaptiveEvaluationCandidateStore(
                self.child,
                terminal_workflow,
            ).prepare(self.state)

    def test_candidate_goal_must_match_the_owned_workflow_goal(self) -> None:
        """Owner 권한도 workflow와 다른 goal의 evaluator candidate를 발행하지 못합니다."""
        with self.assertRaisesRegex(
            AdaptiveEvaluationCandidateInvalid,
            "goal does not match",
        ):
            AdaptiveEvaluationCandidateStore(
                self.owner,
                self.workflow_id,
            ).prepare(self._state(goal="다른 adaptive goal을 평가한다"))

    def test_candidate_accepts_exact_typed_goal_amendment(self) -> None:
        """Initial anchor는 보존하되 typed USER amendment가 current goal이 됩니다."""
        adaptive = AdaptiveControlStore(SkillStateStore(self.owner, self.workflow_id))
        initial = adaptive.compare_and_replace_payload(0, self.state.to_payload())
        replacement = self._state(
            goal="사용자가 수정한 adaptive goal을 평가한다",
            intent_revision=2,
        )
        decision = self._goal_override_decision(
            initial.state.contract,
            replacement.contract,
        )
        candidate = replace(replacement, user_decisions=(decision,))
        store = AdaptiveEvaluationCandidateStore(self.owner, self.workflow_id)

        prepared = store.prepare(candidate)
        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)

        self.assertEqual(
            candidate,
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).read(prepared.assignment_json),
        )
        self.assertEqual(
            prepared.candidate_ref,
            store.verify_prepared(prepared.assignment_json, candidate),
        )

    def test_read_requires_same_session_active_direct_child(self) -> None:
        """Owner 자신, stopped child와 다른 session은 candidate를 읽을 수 없습니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)

        with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
            AdaptiveEvaluationCandidateStore(
                self.owner,
                self.workflow_id,
            ).read(prepared.assignment_json)

        other_session = SessionId("foreign-candidate-session")
        other_root = ActorId("codex:foreign-candidate-session")
        other_child = ActorId("codex:foreign-evaluator")
        self._start_topology(
            other_session,
            other_root,
            other_child,
            self.workflow_id,
        )
        foreign_owner = self._handle(other_session, other_root, other_root)
        foreign = self._handle(other_session, other_child, other_root)
        self._assign(foreign_owner, other_child, prepared.assignment_json)
        with self.assertRaises(AdaptiveEvaluationCandidateInvalid):
            AdaptiveEvaluationCandidateStore(foreign, self.workflow_id).read(
                prepared.assignment_json
            )

        self.child.apply(
            ActorStopped(
                session_id=self.session_id,
                actor_id=self.child_actor_id,
                terminal_status=ActorStatus.STOPPED,
                idempotency_key="stop-candidate-child",
            )
        )
        with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).read(prepared.assignment_json)

    def test_malformed_or_noncanonical_assignment_is_rejected(self) -> None:
        """Shape가 비슷한 JSON, duplicate key와 noncanonical serialization은 신뢰하지 않습니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        assignment = json.loads(prepared.assignment_json)
        cases = (
            "not-json",
            "[]",
            prepared.assignment_json.replace(
                '"kind":"adaptive-goal-evaluation"',
                '"kind":"other"',
            ),
            json.dumps({**assignment, "extra": True}, sort_keys=True),
            json.dumps(assignment, indent=2, sort_keys=True),
            prepared.assignment_json[:-1] + ',"workflow_id":"duplicate-workflow"}',
        )

        for assignment_json in cases:
            with (
                self.subTest(assignment_json=assignment_json),
                self.assertRaises(AdaptiveEvaluationCandidateInvalid),
            ):
                AdaptiveEvaluationCandidateStore(
                    self.child,
                    self.workflow_id,
                ).read(assignment_json)

    def test_candidate_requires_owner_registered_pending_assignment(self) -> None:
        """Artifact ref를 아는 child도 owner-issued delegation 없이 provenance를 만들지 못합니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)

        with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).read(prepared.assignment_json)

    def test_owner_verifies_registered_candidate_against_exact_expected_state(self) -> None:
        """Completion verifier는 assignment artifact와 proposed final state의 동일성을 재검증합니다."""
        store = AdaptiveEvaluationCandidateStore(self.owner, self.workflow_id)
        prepared = store.prepare(self.state)

        with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
            store.verify_prepared(prepared.assignment_json, self.state)

        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)
        self.assertEqual(
            prepared.candidate_ref,
            store.verify_prepared(prepared.assignment_json, self.state),
        )
        persisted = AdaptiveControlStore(
            SkillStateStore(self.owner, self.workflow_id)
        ).compare_and_replace_payload(0, self.state.to_payload())
        self.assertEqual(1, persisted.workflow_revision)
        self.assertEqual(
            prepared.candidate_ref,
            store.verify_prepared(prepared.assignment_json, self.state),
        )

        foreign_inventory_state = AdaptiveControlState.empty(
            self.state.contract,
            GapInventory(
                intent_revision=self.state.contract.intent_revision,
                source_revision="repo:other-head",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )
        with self.assertRaises(AdaptiveEvaluationCandidateInvalid):
            store.verify_prepared(prepared.assignment_json, foreign_inventory_state)

    def test_sibling_workflow_mutation_invalidates_prepared_candidate_revision(self) -> None:
        """Rev N candidate는 unrelated sibling payload가 N+1을 소유하면 read/admission되지 않습니다."""
        store = AdaptiveEvaluationCandidateStore(self.owner, self.workflow_id)
        prepared = store.prepare(self.state)
        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)
        SkillStateStore(self.owner, self.workflow_id).update({"sibling": True})

        with self.assertRaises(AdaptiveEvaluationCandidateConflict):
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).read(prepared.assignment_json)
        with self.assertRaises(AdaptiveEvaluationCandidateConflict):
            store.verify_prepared(prepared.assignment_json, self.state)

    def test_wrong_artifact_schema_or_adaptive_payload_schema_is_rejected(self) -> None:
        """Artifact wrapper와 embedded AdaptiveControlState codec를 각각 fail closed로 읽습니다."""
        candidate_store = AdaptiveEvaluationCandidateStore(self.child, self.workflow_id)
        bad_wrapper = SessionArtifactStore(self.owner).put_json({
            "schema": "neurath.adaptive-evaluation-candidate.v0",
            "session_id": str(self.session_id),
            "workflow_id": str(self.workflow_id),
            "owner_actor_id": str(self.root_actor_id),
            "state": self.state.to_payload(),
        })
        bad_state_payload = dict(self.state.to_payload())
        bad_state_payload["schema_version"] = 2
        bad_state = SessionArtifactStore(self.owner).put_json({
            "schema": "neurath.adaptive-evaluation-candidate.v1",
            "session_id": str(self.session_id),
            "workflow_id": str(self.workflow_id),
            "owner_actor_id": str(self.root_actor_id),
            "state": bad_state_payload,
        })

        for reference in (bad_wrapper.reference, bad_state.reference):
            assignment = self._assignment(reference)
            self._assign(self.owner, self.child_actor_id, assignment)
            with (
                self.subTest(reference=reference),
                self.assertRaises(AdaptiveEvaluationCandidateInvalid),
            ):
                candidate_store.read(assignment)

    def test_artifact_byte_tamper_is_rejected_by_digest_readback(self) -> None:
        """Reference filename을 유지한 byte mutation도 typed decode 전에 거부됩니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        self._assign(self.owner, self.child_actor_id, prepared.assignment_json)
        digest = prepared.candidate_ref.removeprefix("sha256:")
        artifact_path = self.locator.locate(self.session_id).artifacts / "sha256" / f"{digest}.json"
        artifact_path.write_text('{"tampered":true}', encoding="utf-8")

        with self.assertRaises(AdaptiveEvaluationCandidateInvalid):
            AdaptiveEvaluationCandidateStore(
                self.child,
                self.workflow_id,
            ).read(prepared.assignment_json)

    def test_assignment_goal_identity_must_match_typed_candidate(self) -> None:
        """Valid artifact reference도 assignment의 goal/intent/source mismatch를 보상하지 못합니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        assignment = json.loads(prepared.assignment_json)
        cases = (
            {**assignment, "goal_fingerprint": "0" * 64},
            {**assignment, "intent_revision": 2},
            {**assignment, "source_revision": "other-source"},
            {**assignment, "workflow_id": "other-workflow"},
        )

        for candidate in cases:
            assignment_json = json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            self._assign(self.owner, self.child_actor_id, assignment_json)
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(AdaptiveEvaluationCandidateInvalid),
            ):
                AdaptiveEvaluationCandidateStore(
                    self.child,
                    self.workflow_id,
                ).read(assignment_json)

    def _assignment(self, reference: str) -> str:
        """Current state identity에 candidate reference만 교체한 canonical assignment입니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(self.state)
        assignment = json.loads(prepared.assignment_json)
        return json.dumps(
            {**assignment, "candidate_ref": reference},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _target_workflow_payload(
        self,
        source_payload: dict[str, object],
    ) -> dict[str, object]:
        """Typed adaptive replacement가 만들 exact target workflow payload를 재현합니다."""
        skill_state = source_payload["skill_state"]
        self.assertIsInstance(skill_state, dict)
        return {
            **source_payload,
            "skill_state": {
                **skill_state,
                "adaptive_control": self.state.to_payload(),
            },
        }

    def _payload_digest(self, payload: dict[str, object]) -> str:
        """Candidate assignment이 결속할 canonical workflow payload digest를 계산합니다."""
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _assign(
        self,
        owner: StateHandle,
        target_actor_id: ActorId,
        assignment: str,
    ) -> None:
        """Owner-issued pending delegation에 exact assignment를 등록합니다."""
        self.delegation_sequence += 1
        owner.apply(
            DelegationAssigned(
                session_id=owner.session_id,
                delegation_id=DelegationId(f"candidate-{self.delegation_sequence}"),
                owner_actor_id=owner.actor_id,
                target_actor_id=target_actor_id,
                assignment=assignment,
                idempotency_key=f"assign-candidate-{self.delegation_sequence}",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )

    def _state(
        self,
        *,
        goal: str = "adaptive evaluator가 exact goal attainment를 판정한다",
        intent_revision: int = 1,
    ) -> AdaptiveControlState:
        """Full codec payload를 갖되 아직 authority claim이 없는 evaluator candidate입니다."""
        constraints = ("현재 snapshot만 평가한다",)
        non_goals = ("live mutable state를 다시 읽지 않는다",)
        requirement_ids = frozenset({"REQ-evaluator-input"})
        source_revision = f"approved-plan:{intent_revision}"
        requirement = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            intent_revision,
            source_revision,
        )
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=requirement_ids,
            criteria=(
                CriterionSpec(
                    criterion_id="AC-evaluator-input",
                    description="독립 evaluator가 고정된 snapshot을 읽는다",
                    source_requirement_id="REQ-evaluator-input",
                    approved_requirement_fingerprint=requirement,
                    observer="independent evaluator",
                    precondition="owner가 candidate artifact를 준비했다",
                    stimulus="child가 canonical assignment를 읽는다",
                    expected_outcome="typed adaptive state가 exact identity로 복원된다",
                    oracle_owner=OracleOwner.PRIMARY_SOURCE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.SOURCE_READBACK}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )
        return AdaptiveControlState.empty(
            contract,
            GapInventory(
                intent_revision=intent_revision,
                source_revision=f"repo:head-{intent_revision}",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )

    def _goal_override_decision(
        self,
        previous: GoalContract,
        result: GoalContract,
    ) -> UserDecision:
        """Exact old/new contract와 criterion을 결속한 USER amendment를 만듭니다."""
        target_id = previous.criteria[0].criterion_id
        disposition = UserDecisionDisposition.ACCEPTED
        claim = UserDecisionClaim(
            workflow_id=str(self.workflow_id),
            question_workflow_revision=1,
            source_goal_fingerprint=previous.fingerprint,
            source_intent_revision=previous.intent_revision,
            source_revision=previous.source_revision,
            question_digest=hashlib.sha256(b"goal amendment question").hexdigest(),
            question_generation=1,
            question_turn_revision=2,
            prompt_digest=hashlib.sha256(b"goal amendment response").hexdigest(),
            prompt_reference="user-prompt:goal-amendment",
            prompt_generation=2,
            prompt_turn_revision=3,
            target_kind=UserDecisionTarget.CRITERION,
            target_id=target_id,
            disposition=disposition,
            value_summary_digest=user_decision_value_summary_digest(
                UserDecisionTarget.CRITERION,
                target_id,
                disposition,
                result.fingerprint,
                result.intent_revision,
                result.source_revision,
            ),
            result_goal_fingerprint=result.fingerprint,
            result_intent_revision=result.intent_revision,
            result_source_revision=result.source_revision,
        )
        return UserDecision(
            claim=claim,
            interpretation_lineage=AuthorityReceipt(
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                issuer_id=str(self.child_actor_id),
                subject_id=str(self.root_actor_id),
                intent_revision=result.intent_revision,
                source_revision=result.source_revision,
                receipt_digest="d" * 64,
                delegation_id="goal-amendment-evaluation",
            ),
        )

    def _start_topology(
        self,
        session_id: SessionId,
        root_actor_id: ActorId,
        child_actor_id: ActorId,
        workflow_id: WorkflowId,
    ) -> None:
        """한 session에 active root, direct child와 owner workflow를 생성합니다."""
        self.kernel.apply(
            SessionStarted(
                session_id=session_id,
                resume_id=ResumeId(f"resume-{session_id}"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=root_actor_id,
                idempotency_key=f"start-{session_id}",
            )
        )
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=session_id,
                actor_id=root_actor_id,
                idempotency_key=f"provision-{session_id}-{root_actor_id}",
            )
        )
        self.kernel.apply(
            ActorStarted(
                session_id=session_id,
                actor_id=child_actor_id,
                parent_actor_id=root_actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"start-{child_actor_id}",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        self.kernel.apply(
            WorkflowStarted(
                session_id=session_id,
                workflow_id=workflow_id,
                owner_actor_id=root_actor_id,
                kind="evaluate-harness",
                goal="adaptive evaluator가 exact goal attainment를 판정한다",
                payload={"skill_state": {}},
                idempotency_key=f"workflow-{session_id}-{workflow_id}",
            )
        )

    def _handle(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        root_actor_id: ActorId,
    ) -> StateHandle:
        """Existing exact session actor에 runtime-bound handle을 attach합니다."""
        return StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=session_id,
                actor_id=actor_id,
                root_actor_id=root_actor_id,
            ),
        )
