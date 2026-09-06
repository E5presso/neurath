"""Raw-free USER decision domain과 state consumption 계약을 검증합니다."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from unittest import TestCase

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    ClarificationGap,
    CriterionEvidence,
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapAuthority,
    GapInventory,
    GapResolution,
    GoalContract,
    OracleOwner,
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionTarget,
    UserDeferral,
    approved_requirement_fingerprint,
    user_decision_value_summary_digest,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    InvalidAdaptiveControlState,
    validate_adaptive_control_transition,
)


class UserDecisionContractTest(TestCase):
    """USER 의미 판정이 prompt bytes 없이 typed effect에 결속되는지 검증합니다."""

    def test_decision_digest_contains_only_typed_provenance_and_effect(self) -> None:
        """Decision payload는 raw answer 대신 digest, revision, disposition만 보존합니다."""
        contract = self._contract()
        decision = self._decision(
            contract,
            target=UserDecisionTarget.CRITERION,
            target_id="phase-complete",
            disposition=UserDecisionDisposition.ACCEPTED,
        )

        payload = decision.to_payload()

        self.assertEqual(decision.reference, f"user-decision:{decision.claim.decision_digest}")
        self.assertNotIn("answer", payload)
        self.assertNotIn("prompt_text", payload)
        self.assertNotIn("value_summary", payload)
        claim_payload = payload["claim"]
        self.assertIsInstance(claim_payload, Mapping)
        assert isinstance(claim_payload, Mapping)
        self.assertEqual("accepted", claim_payload["disposition"])

    def test_schema_v5_is_raw_free_and_legacy_non_user_states_remain_decodable(self) -> None:
        """v5는 admission과 decision을 소유하고 v4/v3 non-USER state를 읽습니다."""
        state = AdaptiveControlState.empty(self._contract(), self._inventory(self._contract()))
        payload = dict(state.to_payload())

        self.assertEqual(5, payload["schema_version"])
        self.assertEqual([], payload["user_decisions"])
        legacy_v4 = dict(payload)
        legacy_v4["schema_version"] = 4
        self.assertEqual(state, AdaptiveControlState.from_payload(legacy_v4))
        legacy_v3 = dict(legacy_v4)
        legacy_v3["schema_version"] = 3
        legacy_v3.pop("user_decisions")

        self.assertEqual(state, AdaptiveControlState.from_payload(legacy_v3))

    def test_schema_v5_rejects_raw_user_response_fields(self) -> None:
        """Raw response bytes를 current state의 unknown field로 밀어 넣을 수도 없습니다."""
        contract = self._contract()
        payload = dict(AdaptiveControlState.empty(contract, self._inventory(contract)).to_payload())
        payload["raw_user_response"] = "승인합니다"

        with self.assertRaisesRegex(InvalidAdaptiveControlState, "fields"):
            AdaptiveControlState.from_payload(payload)

    def test_target_and_disposition_matrix_is_closed(self) -> None:
        """Gap과 criterion이 소유하지 않는 disposition 조합은 생성 단계에서 거부됩니다."""
        contract = self._contract()
        invalid = (
            (UserDecisionTarget.GAP, UserDecisionDisposition.ACCEPTED),
            (UserDecisionTarget.GAP, UserDecisionDisposition.REJECTED),
            (UserDecisionTarget.CRITERION, UserDecisionDisposition.FACT),
            (UserDecisionTarget.CRITERION, UserDecisionDisposition.BLOCKED),
        )

        for target, disposition in invalid:
            with (
                self.subTest(target=target, disposition=disposition),
                self.assertRaisesRegex(
                    ValueError,
                    "disposition",
                ),
            ):
                self._decision(
                    contract,
                    target=target,
                    target_id="scope-choice"
                    if target is UserDecisionTarget.GAP
                    else "phase-complete",
                    disposition=disposition,
                )

    def test_user_criterion_evidence_must_consume_exact_decision(self) -> None:
        """USER_ACCEPTANCE는 prompt reference가 아니라 exact typed decision을 참조합니다."""
        contract = self._contract()
        decision = self._decision(
            contract,
            target=UserDecisionTarget.CRITERION,
            target_id="phase-complete",
            disposition=UserDecisionDisposition.ACCEPTED,
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=self._inventory(contract),
            evidence=(self._user_evidence(contract, decision, EvidenceStatus.PASS),),
            coverage=None,
            execution_status=ExecutionStatus.INCOMPLETE,
            observations=(),
            user_decisions=(decision,),
        )

        self.assertEqual((decision,), state.user_decisions)

        with self.assertRaisesRegex(ValueError, "USER decision"):
            replace(
                state, evidence=(replace(state.evidence[0], reference="user-decision:missing"),)
            )

    def test_user_gap_fact_deferral_and_blocker_consume_exact_dispositions(self) -> None:
        """USER gap의 세 terminal/nonterminal effect는 동일한 decision reference를 소비합니다."""
        contract = self._contract()
        rows = (
            (UserDecisionDisposition.FACT, GapResolution.USER_FACT, True),
            (UserDecisionDisposition.DEFERRED, GapResolution.OPEN, False),
            (UserDecisionDisposition.BLOCKED, GapResolution.BLOCKER, True),
        )
        for disposition, resolution, blocking in rows:
            with self.subTest(disposition=disposition):
                decision = self._decision(
                    contract,
                    target=UserDecisionTarget.GAP,
                    target_id="scope-choice",
                    disposition=disposition,
                )
                if disposition is UserDecisionDisposition.DEFERRED:
                    resolved = self._gap(
                        contract,
                        blocking=blocking,
                        deferral=UserDeferral(
                            gap_id="scope-choice",
                            intent_revision=contract.intent_revision,
                            reason="deferred",
                            lineage=self._user_lineage(contract),
                            decision_reference=decision.reference,
                        ),
                    )
                else:
                    gap = self._gap(contract, blocking=blocking)
                    resolved = replace(
                        gap,
                        resolution=resolution,
                        evidence_reference=decision.reference,
                        resolution_lineage=self._user_lineage(contract),
                    )
                state = AdaptiveControlState(
                    contract=contract,
                    inventory=replace(self._inventory(contract), gaps=(resolved,)),
                    evidence=(),
                    coverage=None,
                    execution_status=ExecutionStatus.INCOMPLETE,
                    observations=(),
                    user_decisions=(decision,),
                )

                self.assertEqual((decision,), state.user_decisions)

    def test_same_goal_user_decisions_are_append_only_and_cannot_be_orphaned(self) -> None:
        """같은 goal에서 decision history 삭제와 consumer 없는 self-attestation을 거부합니다."""
        contract = self._contract()
        decision = self._decision(
            contract,
            target=UserDecisionTarget.CRITERION,
            target_id="phase-complete",
            disposition=UserDecisionDisposition.REJECTED,
        )
        previous = AdaptiveControlState.empty(contract, self._inventory(contract))
        candidate = replace(
            previous,
            evidence=(self._user_evidence(contract, decision, EvidenceStatus.FAIL),),
            user_decisions=(decision,),
        )
        validate_adaptive_control_transition(previous, candidate)

        with self.assertRaisesRegex(InvalidAdaptiveControlState, "append-only"):
            validate_adaptive_control_transition(candidate, previous)
        with self.assertRaisesRegex(ValueError, "consumed"):
            replace(previous, user_decisions=(decision,))

    def test_user_driven_goal_override_consumes_exact_old_to_new_decision(self) -> None:
        """Goal override decision은 이전 target과 old→new contract identity를 정확히 묶습니다."""
        previous_contract = self._contract()
        previous_gap = self._gap(previous_contract, blocking=True)
        previous = AdaptiveControlState.empty(
            previous_contract,
            replace(self._inventory(previous_contract), gaps=(previous_gap,)),
        )
        next_contract = self._contract(intent_revision=2, suffix="revised")
        decision = self._goal_override_decision(
            previous_contract,
            next_contract,
            target_id=previous_gap.gap_id,
        )
        candidate = replace(
            AdaptiveControlState.empty(next_contract, self._inventory(next_contract)),
            user_decisions=(decision,),
        )

        without_decision = AdaptiveControlState.empty(
            next_contract,
            self._inventory(next_contract),
        )
        with self.assertRaisesRegex(InvalidAdaptiveControlState, "USER decision"):
            validate_adaptive_control_transition(
                previous,
                without_decision,
                allow_goal_override=True,
            )
        validate_adaptive_control_transition(previous, candidate, allow_goal_override=True)

        foreign_claim = replace(decision.claim, source_goal_fingerprint="f" * 64)
        foreign = replace(
            candidate,
            user_decisions=(replace(decision, claim=foreign_claim),),
        )
        with self.assertRaisesRegex(InvalidAdaptiveControlState, "old and new"):
            validate_adaptive_control_transition(previous, foreign, allow_goal_override=True)

    def _contract(
        self,
        *,
        intent_revision: int = 1,
        suffix: str = "current",
    ) -> GoalContract:
        goal = f"USER decision semantics를 검증한다 ({suffix})"
        constraints = ("raw response를 저장하지 않는다",)
        non_goals = ("static parser로 자연어를 재해석하지 않는다",)
        source_revision = f"approved-plan:{intent_revision}"
        fingerprint = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            intent_revision,
            source_revision,
        )
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({"REQ-user-decision"}),
            criteria=(
                CriterionSpec(
                    criterion_id="phase-complete",
                    description="사용자가 결과를 판정한다",
                    source_requirement_id="REQ-user-decision",
                    approved_requirement_fingerprint=fingerprint,
                    observer="user",
                    precondition="질문 provenance가 고정됐다",
                    stimulus="사용자가 응답한다",
                    expected_outcome="독립 evaluator가 typed disposition을 판정한다",
                    oracle_owner=OracleOwner.USER,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.USER_ACCEPTANCE}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )

    def _inventory(self, contract: GoalContract) -> GapInventory:
        return GapInventory(
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            assessed_sections=frozenset(RequirementSection),
            gaps=(),
        )

    def _gap(
        self,
        contract: GoalContract,
        *,
        blocking: bool,
        deferral: UserDeferral | None = None,
    ) -> ClarificationGap:
        return ClarificationGap(
            gap_id="scope-choice",
            section=RequirementSection.SCOPE,
            authority=GapAuthority.USER,
            dependency_rank=0,
            weight=1.0,
            blocking=blocking,
            reversible=False,
            scope_local=False,
            context="사용자 scope 결정을 확인한다",
            question="어떤 scope를 적용할까요?",
            consequence="답을 추측하면 contract가 바뀐다",
            recommendation="현재 scope를 명시한다",
            recommendation_rationale="사용자만 제품 scope를 소유한다",
            intent_revision=contract.intent_revision,
            deferral=deferral,
        )

    def _decision(
        self,
        contract: GoalContract,
        *,
        target: UserDecisionTarget,
        target_id: str,
        disposition: UserDecisionDisposition,
    ) -> UserDecision:
        summary_digest = user_decision_value_summary_digest(
            target,
            target_id,
            disposition,
            contract.fingerprint,
            contract.intent_revision,
            contract.source_revision,
        )
        claim = UserDecisionClaim(
            workflow_id="adaptive-workflow",
            question_workflow_revision=1,
            source_goal_fingerprint=contract.fingerprint,
            source_intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            question_digest=hashlib.sha256(b"question").hexdigest(),
            question_generation=1,
            question_turn_revision=2,
            prompt_digest=hashlib.sha256(b"response").hexdigest(),
            prompt_reference="user-prompt:response",
            prompt_generation=2,
            prompt_turn_revision=3,
            target_kind=target,
            target_id=target_id,
            disposition=disposition,
            value_summary_digest=summary_digest,
            result_goal_fingerprint=contract.fingerprint,
            result_intent_revision=contract.intent_revision,
            result_source_revision=contract.source_revision,
        )
        return UserDecision(
            claim=claim,
            interpretation_lineage=AuthorityReceipt(
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                issuer_id="codex:evaluator",
                subject_id="codex:owner",
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                receipt_digest="a" * 64,
                delegation_id="user-decision-evaluation",
            ),
        )

    def _goal_override_decision(
        self,
        previous: GoalContract,
        result: GoalContract,
        *,
        target_id: str,
    ) -> UserDecision:
        disposition = UserDecisionDisposition.FACT
        claim = UserDecisionClaim(
            workflow_id="adaptive-workflow",
            question_workflow_revision=1,
            source_goal_fingerprint=previous.fingerprint,
            source_intent_revision=previous.intent_revision,
            source_revision=previous.source_revision,
            question_digest=hashlib.sha256(b"goal override question").hexdigest(),
            question_generation=1,
            question_turn_revision=2,
            prompt_digest=hashlib.sha256(b"goal override response").hexdigest(),
            prompt_reference="user-prompt:goal-override",
            prompt_generation=2,
            prompt_turn_revision=3,
            target_kind=UserDecisionTarget.GAP,
            target_id=target_id,
            disposition=disposition,
            value_summary_digest=user_decision_value_summary_digest(
                UserDecisionTarget.GAP,
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
                issuer_id="codex:evaluator",
                subject_id="codex:owner",
                intent_revision=result.intent_revision,
                source_revision=result.source_revision,
                receipt_digest="b" * 64,
                delegation_id="user-goal-override-evaluation",
            ),
        )

    def _user_lineage(self, contract: GoalContract) -> AuthorityReceipt:
        return AuthorityReceipt(
            authority=EvidenceAuthority.USER,
            issuer_id="user",
            subject_id="codex:owner",
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=hashlib.sha256(b"response").hexdigest(),
            delegation_id="user-prompt:response",
        )

    def _user_evidence(
        self,
        contract: GoalContract,
        decision: UserDecision,
        status: EvidenceStatus,
    ) -> CriterionEvidence:
        return CriterionEvidence(
            goal_fingerprint=contract.fingerprint,
            criterion_id="phase-complete",
            kind=EvidenceKind.USER_ACCEPTANCE,
            authority=EvidenceAuthority.USER,
            status=status,
            reference=decision.reference,
            lineage=self._user_lineage(contract),
        )
