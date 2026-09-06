"""Adaptive completion의 external authority read-back 계약을 검증합니다."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    ClarificationGap,
    ControlAction,
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
    GoalCoverage,
    OracleOwner,
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionTarget,
    UserDeferral,
    approved_requirement_fingerprint,
    render_socratic_question,
    user_decision_value_summary_digest,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityConflict,
    AdaptiveControlAuthorityInvalid,
    AdaptiveControlAuthorityNotFound,
    AdaptiveControlAuthorityStatus,
    AdaptiveControlAuthorityVerifier,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    AdaptiveControlStateMissing,
    AdaptiveControlStore,
)
from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.adaptive_execution_receipt import (
    AdaptiveExecutionReceiptStore,
)
from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.repository_readback import RepositoryWorktreeReadback
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    DelegationAssigned,
    DelegationCancelled,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    ForegroundPromptAuthorityContext,
    ForegroundTurnClosed,
    ForegroundTurnOutcome,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnReceipt,
    ForegroundTurnYielded,
    ReservedSkillStateAdvanced,
    SessionLocator,
    SessionStateStore,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityBinding,
    StateHandle,
)


class AdaptiveControlAuthorityVerifierTest(TestCase):
    """외부 evaluator label이 실제 consumed authority 없이 완료를 만들지 못하게 합니다."""

    def _persist_verified_completion(
        self,
        fixture: AdaptiveAuthorityFixture,
        suffix: str,
    ) -> AdaptiveControlSnapshot:
        """Consumed direct-child report와 COMPLETE snapshot을 같은 authority에 결속합니다."""
        evidence_claim, coverage_claim = fixture.independent_claims()
        delegation_id = f"completion-readback-{suffix}"
        artifact = fixture.write_artifact(
            delegation_id,
            (evidence_claim, coverage_claim),
        )
        lineage = fixture.independent_lineage(delegation_id, artifact)
        persisted = fixture.persist_snapshot(
            fixture.independent_snapshot(
                evidence_lineage=lineage,
                coverage_lineage=lineage,
            )
        )
        fixture.transition_delegation(
            delegation_id,
            artifact,
            lifecycle="consumed",
            candidate_state=persisted.state,
        )
        return persisted

    def test_completion_readback_accepts_one_exact_current_snapshot_and_authority(self) -> None:
        """COMPLETE 의미와 external authority가 같은 revision이면 typed readback을 반환합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            persisted = self._persist_verified_completion(fixture, "current")

            readback = fixture.verifier.verify_completion(persisted.workflow_revision)

        self.assertEqual(persisted.workflow_id, readback.workflow_id)
        self.assertEqual(persisted.workflow_revision, readback.workflow_revision)
        self.assertEqual(persisted.state.contract.fingerprint, readback.goal_fingerprint)
        self.assertIs(ControlAction.COMPLETE, readback.receipt.decision.action)
        self.assertTrue(readback.receipt.ambiguity.ready)
        self.assertTrue(readback.receipt.decision.achieved)
        self.assertTrue(readback.receipt.attainment.achieved)
        self.assertTrue(readback.external_authority.complete)

    def test_completion_readback_rejects_stale_expected_revision(self) -> None:
        """Caller CAS revision은 current adaptive snapshot revision과 정확히 같아야 합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            persisted = self._persist_verified_completion(fixture, "stale-revision")

            with self.assertRaises(AdaptiveControlAuthorityConflict):
                fixture.verifier.verify_completion(persisted.workflow_revision - 1)

    def test_completion_readback_rejects_external_authority_for_another_fingerprint(self) -> None:
        """External verifier 결과가 같은 revision이어도 다른 goal이면 완료 권위가 아닙니다."""
        with AdaptiveAuthorityFixture() as fixture:
            persisted = self._persist_verified_completion(fixture, "stale-fingerprint")
            current_authority = fixture.verifier.verify()
            with (
                patch.object(
                    fixture.verifier,
                    "_verify_state",
                    return_value=replace(
                        current_authority,
                        goal_fingerprint="f" * 64,
                    ),
                ),
                self.assertRaises(AdaptiveControlAuthorityConflict),
            ):
                fixture.verifier.verify_completion(persisted.workflow_revision)

    def test_completion_readback_rejects_ambiguity_and_unachieved_goal(self) -> None:
        """Open ambiguity 또는 미달 attainment는 external label 검사 전에 완료를 거부합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.INDEPENDENT_SEMANTIC,
                OracleOwner.INDEPENDENT_EVALUATOR,
            )
            open_gap = ClarificationGap(
                gap_id="completion-open-scope",
                section=RequirementSection.SCOPE,
                authority=GapAuthority.USER,
                dependency_rank=0,
                weight=1.0,
                blocking=True,
                reversible=False,
                scope_local=False,
                context="완료 범위가 아직 열려 있다",
                question="어떤 범위를 완료해야 하나요?",
                consequence="모호한 범위에서 조기 완료할 수 있다",
                recommendation="사용자 범위를 먼저 확정한다",
                recommendation_rationale="Scope authority는 사용자가 소유한다",
                intent_revision=contract.intent_revision,
            )
            ambiguous = fixture.persist_snapshot(
                fixture._snapshot(
                    AdaptiveControlState.empty(
                        contract,
                        replace(fixture._inventory(contract), gaps=(open_gap,)),
                    )
                )
            )

            with self.assertRaises(AdaptiveControlAuthorityInvalid):
                fixture.verifier.verify_completion(ambiguous.workflow_revision)

        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.INDEPENDENT_SEMANTIC,
                OracleOwner.INDEPENDENT_EVALUATOR,
            )
            unachieved = fixture.persist_snapshot(
                fixture._snapshot(
                    AdaptiveControlState.empty(contract, fixture._inventory(contract))
                )
            )

            with self.assertRaises(AdaptiveControlAuthorityInvalid):
                fixture.verifier.verify_completion(unachieved.workflow_revision)

    def _persist_independent_snapshot_with_gaps(
        self,
        fixture: AdaptiveAuthorityFixture,
        gaps: tuple[ClarificationGap, ...],
        suffix: str,
        *,
        inventory_source_revision: str | None = None,
        register_evaluation: bool = True,
    ) -> AdaptiveControlSnapshot:
        """Valid independent completion에 adversarial gap resolution만 추가해 저장합니다."""
        evidence_claim, coverage_claim = fixture.independent_claims()
        delegation_id = f"gap-authority-{suffix}"
        artifact = fixture.write_artifact(
            delegation_id,
            (evidence_claim, coverage_claim),
        )
        lineage = fixture.independent_lineage(delegation_id, artifact)
        candidate = fixture.independent_snapshot(
            evidence_lineage=lineage,
            coverage_lineage=lineage,
        )
        candidate = AdaptiveControlSnapshot(
            workflow_id=candidate.workflow_id,
            workflow_revision=candidate.workflow_revision,
            state=replace(
                candidate.state,
                inventory=replace(
                    candidate.state.inventory,
                    source_revision=(
                        inventory_source_revision or candidate.state.inventory.source_revision
                    ),
                    gaps=gaps,
                ),
            ),
        )
        persisted = fixture.persist_snapshot(candidate)
        if register_evaluation:
            fixture.transition_delegation(
                delegation_id,
                artifact,
                lifecycle="consumed",
            )
        return persisted

    def _gap_lineage(
        self,
        fixture: AdaptiveAuthorityFixture,
        authority: EvidenceAuthority,
        *,
        source_revision: str,
        suffix: str,
        receipt_digest: str | None = None,
    ) -> AuthorityReceipt:
        """Fabricated enum과 digest만 가진 gap lineage를 만듭니다."""
        issuer = {
            EvidenceAuthority.USER: "user",
            EvidenceAuthority.PRIMARY_SOURCE: "repository",
            EvidenceAuthority.SAME_CONTEXT: str(fixture.owner.actor_id),
        }[authority]
        return AuthorityReceipt(
            authority=authority,
            issuer_id=issuer,
            subject_id=str(fixture.owner.actor_id),
            intent_revision=1,
            source_revision=source_revision,
            receipt_digest=(
                receipt_digest or hashlib.sha256(f"fabricated:{suffix}".encode()).hexdigest()
            ),
        )

    def _resolved_gap(
        self,
        fixture: AdaptiveAuthorityFixture,
        *,
        gap_id: str,
        authority: GapAuthority,
        resolution: GapResolution,
        lineage: AuthorityReceipt,
        blocking: bool,
        reversible: bool,
        scope_local: bool,
        evidence_reference: str | None = None,
    ) -> ClarificationGap:
        """External verifier가 반드시 provenance를 재검증해야 하는 resolved gap을 만듭니다."""
        del fixture
        return ClarificationGap(
            gap_id=gap_id,
            section=RequirementSection.SCOPE,
            authority=authority,
            dependency_rank=0,
            weight=1.0,
            blocking=blocking,
            reversible=reversible,
            scope_local=scope_local,
            context="해당 gap의 실제 authority를 확인해야 한다",
            question="이 resolution은 실제 authority source에서 왔는가?",
            consequence="Self assertion이 completion으로 승격될 수 있다",
            recommendation="External provenance를 read back한다",
            recommendation_rationale="직접 readback만 self-attestation을 차단한다",
            intent_revision=1,
            resolution=resolution,
            evidence_reference=evidence_reference or f"self-asserted:{gap_id}",
            resolution_lineage=lineage,
        )

    def _record_user_response(
        self,
        fixture: AdaptiveAuthorityFixture,
        contract: GoalContract,
        *,
        action: str,
        claim_ids: tuple[str, ...],
        question: str,
        prompt: str,
        context_workflow_id: WorkflowId | None = None,
    ) -> AuthorityReceipt:
        """직전 adaptive question과 subsequent runtime prompt를 exact turn receipt로 만듭니다."""
        owner = fixture.owner
        owner.apply(
            ForegroundTurnPrompted(
                session_id=owner.session_id,
                actor_id=owner.actor_id,
                vendor_turn_id="vendor-question-turn",
                idempotency_key="authority-fixture:question-turn",
            )
        )
        question_turn = owner.inspect().foreground_turns[owner.actor_id]
        owner.apply(
            ForegroundTurnYielded(
                session_id=owner.session_id,
                actor_id=owner.actor_id,
                expected_turn_revision=question_turn.revision,
                receipt=ForegroundTurnReceipt(
                    ForegroundTurnOutcome.AWAITING_INPUT,
                    question=question,
                ),
                idempotency_key="authority-fixture:question-yield",
            )
        )
        ready = owner.inspect().foreground_turns[owner.actor_id]
        owner.apply(
            ForegroundTurnClosed(
                session_id=owner.session_id,
                actor_id=owner.actor_id,
                expected_turn_revision=ready.revision,
                idempotency_key="authority-fixture:question-close",
            )
        )
        preceding = owner.inspect().foreground_turns[owner.actor_id]
        selected_workflow_id = context_workflow_id or fixture.workflow_id
        workflow = owner.inspect().workflows[selected_workflow_id]
        context = ForegroundPromptAuthorityContext(
            workflow_id=selected_workflow_id,
            workflow_revision=workflow.revision,
            goal_fingerprint=contract.fingerprint,
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            criterion_ids=tuple(item.criterion_id for item in contract.criteria),
            claim_ids=claim_ids,
            control_action=action,
            question_digest=hashlib.sha256(question.strip().encode("utf-8")).hexdigest(),
            question_generation=preceding.generation,
            question_turn_revision=preceding.revision,
        )
        prompt_digest = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
        owner.apply(
            ForegroundTurnPrompted(
                session_id=owner.session_id,
                actor_id=owner.actor_id,
                vendor_turn_id="vendor-user-response",
                idempotency_key="authority-fixture:user-response",
                prompt_digest=prompt_digest,
                authority_context=context,
            )
        )
        user_receipt = owner.inspect().foreground_turns[owner.actor_id].user_prompt_receipt
        self.assertIsNotNone(user_receipt)
        assert user_receipt is not None
        return AuthorityReceipt(
            authority=EvidenceAuthority.USER,
            issuer_id="user",
            subject_id=str(owner.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=user_receipt.prompt_digest,
            delegation_id=user_receipt.authority_reference,
        )

    def _pending_user_acceptance(
        self,
        fixture: AdaptiveAuthorityFixture,
        contract: GoalContract,
    ) -> AdaptiveControlSnapshot:
        """USER_ACCEPTANCE 질문 전 current goal을 evidence 없는 AWAIT_USER 상태로 저장합니다."""
        return fixture.persist_snapshot(
            fixture._snapshot(
                AdaptiveControlState(
                    contract=contract,
                    inventory=fixture._inventory(contract),
                    evidence=(),
                    coverage=None,
                    execution_status=ExecutionStatus.COMPLETED,
                    observations=(),
                )
            )
        )

    def _user_decision_claim(
        self,
        fixture: AdaptiveAuthorityFixture,
        contract: GoalContract,
        *,
        target_kind: UserDecisionTarget,
        target_id: str,
        disposition: UserDecisionDisposition,
    ) -> UserDecisionClaim:
        """Current transient prompt를 raw-free normalized decision claim으로 고정합니다."""
        receipt = (
            fixture.owner.inspect().foreground_turns[fixture.owner.actor_id].user_prompt_receipt
        )
        self.assertIsNotNone(receipt)
        assert receipt is not None
        context = receipt.authority_context
        self.assertIsNotNone(context)
        assert context is not None
        return UserDecisionClaim(
            workflow_id=str(context.workflow_id),
            question_workflow_revision=context.workflow_revision,
            source_goal_fingerprint=context.goal_fingerprint,
            source_intent_revision=context.intent_revision,
            source_revision=context.source_revision,
            question_digest=context.question_digest,
            question_generation=context.question_generation,
            question_turn_revision=context.question_turn_revision,
            prompt_digest=receipt.prompt_digest,
            prompt_reference=receipt.authority_reference,
            prompt_generation=receipt.generation,
            prompt_turn_revision=receipt.turn_revision,
            target_kind=target_kind,
            target_id=target_id,
            disposition=disposition,
            value_summary_digest=user_decision_value_summary_digest(
                target_kind,
                target_id,
                disposition,
                contract.fingerprint,
                contract.intent_revision,
                contract.source_revision,
            ),
            result_goal_fingerprint=contract.fingerprint,
            result_intent_revision=contract.intent_revision,
            result_source_revision=contract.source_revision,
        )

    def _user_decision_report_claim(
        self,
        claim: UserDecisionClaim,
    ) -> dict[str, object]:
        """Independent report가 소유할 lineage-free semantic oracle payload를 만듭니다."""
        return {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "user-decision",
            "decision_digest": claim.decision_digest,
            **claim.to_payload(),
        }

    def _user_acceptance_candidate(
        self,
        fixture: AdaptiveAuthorityFixture,
        contract: GoalContract,
        user_lineage: AuthorityReceipt,
        coverage_lineage: AuthorityReceipt,
        decision: UserDecision | None = None,
    ) -> AdaptiveControlSnapshot:
        """Direct user receipt와 independent interpretation을 결합한 completion candidate입니다."""
        return fixture._snapshot(
            AdaptiveControlState(
                contract=contract,
                inventory=fixture._inventory(contract),
                evidence=(
                    CriterionEvidence(
                        goal_fingerprint=contract.fingerprint,
                        criterion_id="phase-complete",
                        kind=EvidenceKind.USER_ACCEPTANCE,
                        authority=EvidenceAuthority.USER,
                        status=EvidenceStatus.PASS,
                        reference=(
                            decision.reference
                            if decision is not None
                            else user_lineage.delegation_id or "missing-user-reference"
                        ),
                        lineage=user_lineage,
                    ),
                ),
                coverage=GoalCoverage(
                    goal_fingerprint=contract.fingerprint,
                    criterion_ids=frozenset({"phase-complete"}),
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    status=EvidenceStatus.PASS,
                    reference="independent:user-coverage",
                    goal_alignment=1.0,
                    semantic_drift=0.0,
                    uncertainty=0.0,
                    reward_hacking_risk=0.0,
                    lineage=coverage_lineage,
                ),
                execution_status=ExecutionStatus.COMPLETED,
                observations=(),
                user_decisions=(() if decision is None else (decision,)),
            )
        )

    def _user_acceptance_claims(
        self,
        contract: GoalContract,
        user_reference: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Independent evaluator가 해석해야 하는 exact USER claim과 whole-goal coverage입니다."""
        return (
            {
                "authority": EvidenceAuthority.USER.value,
                "claim_type": "criterion-evidence",
                "criterion_id": "phase-complete",
                "evaluation_revision": 1,
                "goal_fingerprint": contract.fingerprint,
                "kind": EvidenceKind.USER_ACCEPTANCE.value,
                "reference": user_reference,
                "status": EvidenceStatus.PASS.value,
            },
            {
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "goal-coverage",
                "criterion_ids": ["phase-complete"],
                "evaluation_revision": 1,
                "goal_alignment": 1.0,
                "goal_fingerprint": contract.fingerprint,
                "reference": "independent:user-coverage",
                "reward_hacking_risk": 0.0,
                "semantic_drift": 0.0,
                "status": EvidenceStatus.PASS.value,
                "uncertainty": 0.0,
            },
        )

    def test_user_fact_and_deferral_are_pending_without_runtime_user_receipt(self) -> None:
        """USER enum/digest의 resolved fact와 deferral은 independent 완료를 승격하지 못합니다."""
        rows = ("user-fact", "user-deferral")
        for row in rows:
            with self.subTest(row=row), AdaptiveAuthorityFixture() as fixture:
                lineage = self._gap_lineage(
                    fixture,
                    EvidenceAuthority.USER,
                    source_revision="approved-plan:1",
                    suffix=row,
                )
                if row == "user-fact":
                    gap = self._resolved_gap(
                        fixture,
                        gap_id=row,
                        authority=GapAuthority.USER,
                        resolution=GapResolution.USER_FACT,
                        lineage=lineage,
                        blocking=True,
                        reversible=False,
                        scope_local=False,
                    )
                else:
                    deferral = UserDeferral(
                        gap_id=row,
                        intent_revision=1,
                        reason="self-declared deferral",
                        lineage=lineage,
                    )
                    gap = ClarificationGap(
                        gap_id=row,
                        section=RequirementSection.SCOPE,
                        authority=GapAuthority.USER,
                        dependency_rank=0,
                        weight=1.0,
                        blocking=False,
                        reversible=False,
                        scope_local=False,
                        context="사용자 선택을 유예한다",
                        question="현재 선택을 유예할까요?",
                        consequence="위조된 유예가 ambiguity를 숨긴다",
                        recommendation="Runtime user receipt를 요구한다",
                        recommendation_rationale="Runtime prompt만 user provenance를 소유한다",
                        intent_revision=1,
                        deferral=deferral,
                    )
                self._persist_independent_snapshot_with_gaps(fixture, (gap,), row)

                verification = fixture.verifier.verify()

                self.assertIs(
                    AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
                    verification.status,
                )
                self.assertFalse(verification.complete)
                self.assertIn(f"user-decision:gap:{row}", verification.pending_claims)

    def test_terminal_blocker_reuses_user_and_repository_runtime_authority(self) -> None:
        """BLOCKER enum도 USER prompt 또는 current repository bytes 없이 terminal이 아닙니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.INDEPENDENT_SEMANTIC,
                OracleOwner.INDEPENDENT_EVALUATOR,
            )
            user_lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.USER,
                source_revision=contract.source_revision,
                suffix="user-blocker",
            )
            user_gap = ClarificationGap(
                gap_id="user-blocker",
                section=RequirementSection.SCOPE,
                authority=GapAuthority.USER,
                dependency_rank=0,
                weight=1.0,
                blocking=True,
                reversible=False,
                scope_local=False,
                context="사용자만 terminal blocker를 판정한다",
                question="이 goal은 진행 불가능한가요?",
                consequence="Self-label이 loop를 조기 종료한다",
                recommendation="Runtime prompt receipt를 확인한다",
                recommendation_rationale="User authority를 직접 입증해야 한다",
                intent_revision=contract.intent_revision,
            ).mark_blocked("self-authored:user-blocker", user_lineage)
            user_candidate = AdaptiveControlState.empty(
                contract,
                replace(fixture._inventory(contract), gaps=(user_gap,)),
            )

            pending = fixture.verifier.validate_candidate(user_candidate, 0)

            self.assertIs(
                AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
                pending.status,
            )
            self.assertEqual(("user-decision:gap:user-blocker",), pending.pending_claims)

            source = RepositoryWorktreeReadback(fixture.repository).read_tracked_file(
                "docs/repository-fact.txt"
            )
            repository_lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source.worktree_fingerprint,
                suffix="repository-blocker",
                receipt_digest="f" * 64,
            )
            repository_gap = replace(
                user_gap,
                gap_id="repository-blocker",
                authority=GapAuthority.REPOSITORY,
                evidence_reference="docs/repository-fact.txt",
                resolution_lineage=repository_lineage,
            )
            repository_candidate = AdaptiveControlState.empty(
                contract,
                replace(
                    fixture._inventory(contract),
                    gaps=(repository_gap,),
                    source_revision=source.worktree_fingerprint,
                ),
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "content digest mismatch",
            ):
                fixture.verifier.validate_candidate(repository_candidate, 0)

    def test_current_user_prompt_verifies_user_gap_fact_and_deferral(self) -> None:
        """Exact ASK_USER response는 같은 gap의 USER_FACT와 explicit deferral을 검증합니다."""
        for row in ("user-fact", "user-deferral"):
            with self.subTest(row=row), AdaptiveAuthorityFixture() as fixture:
                contract = fixture._contract(
                    EvidenceKind.INDEPENDENT_SEMANTIC,
                    OracleOwner.INDEPENDENT_EVALUATOR,
                )
                open_gap = ClarificationGap(
                    gap_id=row,
                    section=RequirementSection.SCOPE,
                    authority=GapAuthority.USER,
                    dependency_rank=0,
                    weight=1.0,
                    blocking=True,
                    reversible=False,
                    scope_local=False,
                    context="사용자만 scope 결정을 소유한다",
                    question="현재 선택을 적용할까요?",
                    consequence="응답 없이는 scope가 확정되지 않는다",
                    recommendation="현재 선택을 명시한다",
                    recommendation_rationale="Agent 추측을 피한다",
                    intent_revision=contract.intent_revision,
                )
                persisted = self._persist_independent_snapshot_with_gaps(
                    fixture,
                    (open_gap,),
                    f"positive-{row}",
                    register_evaluation=False,
                )
                user_lineage = self._record_user_response(
                    fixture,
                    contract,
                    action=ControlAction.ASK_USER.value,
                    claim_ids=(f"gap:{row}",),
                    question=render_socratic_question(open_gap),
                    prompt="네, 적용합니다.",
                )
                disposition = (
                    UserDecisionDisposition.FACT
                    if row == "user-fact"
                    else UserDecisionDisposition.DEFERRED
                )
                decision_claim = self._user_decision_claim(
                    fixture,
                    contract,
                    target_kind=UserDecisionTarget.GAP,
                    target_id=row,
                    disposition=disposition,
                )
                decision_delegation_id = f"positive-{row}-decision"
                evidence_claim, coverage_claim = fixture.independent_claims()
                evidence_claim["evaluation_revision"] = 2
                coverage_claim["evaluation_revision"] = 2
                decision_artifact = fixture.write_artifact(
                    decision_delegation_id,
                    (
                        evidence_claim,
                        coverage_claim,
                        self._user_decision_report_claim(decision_claim),
                    ),
                    contract=contract,
                )
                decision_lineage = fixture.independent_lineage(
                    decision_delegation_id,
                    decision_artifact,
                )
                decision = UserDecision(
                    claim=decision_claim,
                    interpretation_lineage=decision_lineage,
                )
                if row == "user-fact":
                    resolved = replace(
                        open_gap,
                        resolution=GapResolution.USER_FACT,
                        evidence_reference=decision.reference,
                        resolution_lineage=user_lineage,
                    )
                else:
                    resolved = replace(
                        open_gap,
                        blocking=False,
                        deferral=UserDeferral(
                            gap_id=row,
                            intent_revision=contract.intent_revision,
                            reason="사용자가 현재 loop에서 명시적으로 유예했다",
                            lineage=user_lineage,
                            decision_reference=decision.reference,
                        ),
                    )
                persisted_coverage = persisted.state.coverage
                self.assertIsNotNone(persisted_coverage)
                assert persisted_coverage is not None
                candidate = replace(
                    persisted.state,
                    inventory=replace(persisted.state.inventory, gaps=(resolved,)),
                    evidence=(
                        *persisted.state.evidence,
                        replace(
                            persisted.state.evidence[-1],
                            lineage=decision_lineage,
                            evaluation_revision=2,
                        ),
                    ),
                    coverage=replace(
                        persisted_coverage,
                        lineage=decision_lineage,
                        evaluation_revision=2,
                    ),
                    user_decisions=(decision,),
                )
                coverage = candidate.coverage
                self.assertIsNotNone(coverage)
                assert coverage is not None
                fixture.transition_delegation(
                    decision_delegation_id,
                    decision_artifact,
                    lifecycle="consumed",
                    candidate_state=candidate,
                )

                verification = fixture.verifier.validate_candidate(
                    candidate,
                    fixture.owner.inspect().workflows[fixture.workflow_id].revision,
                )

                self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verification.status)
                self.assertNotIn(f"user-decision:gap:{row}", verification.pending_claims)

    def test_current_user_prompt_and_independent_decision_verify_user_blocker(self) -> None:
        """USER blocker도 다른 USER effect와 같은 typed semantic-oracle 경로를 사용합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.INDEPENDENT_SEMANTIC,
                OracleOwner.INDEPENDENT_EVALUATOR,
            )
            open_gap = ClarificationGap(
                gap_id="user-blocker",
                section=RequirementSection.SCOPE,
                authority=GapAuthority.USER,
                dependency_rank=0,
                weight=1.0,
                blocking=True,
                reversible=False,
                scope_local=False,
                context="사용자만 terminal blocker를 판정한다",
                question="이 goal은 현재 진행 불가능한가요?",
                consequence="Self-label이 loop를 조기 종료할 수 있다",
                recommendation="User decision을 독립적으로 판정한다",
                recommendation_rationale="Blocker도 동일한 authority가 필요하다",
                intent_revision=contract.intent_revision,
            )
            persisted = fixture.persist_snapshot(
                fixture._snapshot(
                    AdaptiveControlState.empty(
                        contract,
                        replace(fixture._inventory(contract), gaps=(open_gap,)),
                    )
                )
            )
            user_lineage = self._record_user_response(
                fixture,
                contract,
                action=ControlAction.ASK_USER.value,
                claim_ids=("gap:user-blocker",),
                question=render_socratic_question(open_gap),
                prompt="현재는 진행할 수 없습니다.",
            )
            decision_claim = self._user_decision_claim(
                fixture,
                contract,
                target_kind=UserDecisionTarget.GAP,
                target_id="user-blocker",
                disposition=UserDecisionDisposition.BLOCKED,
            )
            artifact = fixture.write_artifact(
                "user-blocker-decision",
                (self._user_decision_report_claim(decision_claim),),
                contract=contract,
                include_execution_completion=False,
            )
            decision = UserDecision(
                claim=decision_claim,
                interpretation_lineage=fixture.independent_lineage(
                    "user-blocker-decision",
                    artifact,
                ),
            )
            blocked = open_gap.mark_blocked(decision.reference, user_lineage)
            candidate = replace(
                persisted.state,
                inventory=replace(persisted.state.inventory, gaps=(blocked,)),
                user_decisions=(decision,),
            )
            fixture.transition_delegation(
                "user-blocker-decision",
                artifact,
                lifecycle="consumed",
                candidate_state=candidate,
            )

            verification = fixture.verifier.validate_candidate(
                candidate,
                persisted.workflow_revision,
            )

        self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verification.status)
        self.assertEqual((), verification.pending_claims)

    def test_repository_fact_requires_primary_source_readback(self) -> None:
        """PRIMARY_SOURCE enum과 digest만으로 repository resolution을 verified로 만들지 못합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            source = RepositoryWorktreeReadback(fixture.repository).read_tracked_file(
                "docs/repository-fact.txt"
            )
            lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source.worktree_fingerprint,
                suffix="repository-fact",
            )
            gap = self._resolved_gap(
                fixture,
                gap_id="repository-fact",
                authority=GapAuthority.REPOSITORY,
                resolution=GapResolution.REPOSITORY_FACT,
                lineage=lineage,
                blocking=True,
                reversible=False,
                scope_local=False,
                evidence_reference="docs/repository-fact.txt",
            )
            self._persist_independent_snapshot_with_gaps(
                fixture,
                (gap,),
                "repository-fact",
                inventory_source_revision=source.worktree_fingerprint,
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "content digest mismatch",
            ):
                fixture.verifier.verify()

    def test_repository_fact_accepts_only_current_tracked_primary_source(self) -> None:
        """Current tracked bytes와 inventory fingerprint가 모두 일치해야 repository fact입니다."""
        with AdaptiveAuthorityFixture() as fixture:
            source = RepositoryWorktreeReadback(fixture.repository).read_tracked_file(
                "docs/repository-fact.txt"
            )
            lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source.worktree_fingerprint,
                suffix="valid-repository-fact",
                receipt_digest=source.content_digest,
            )
            gap = self._resolved_gap(
                fixture,
                gap_id="valid-repository-fact",
                authority=GapAuthority.REPOSITORY,
                resolution=GapResolution.REPOSITORY_FACT,
                lineage=lineage,
                blocking=True,
                reversible=False,
                scope_local=False,
                evidence_reference=source.relative_path,
            )
            self._persist_independent_snapshot_with_gaps(
                fixture,
                (gap,),
                "valid-repository-fact",
                inventory_source_revision=source.worktree_fingerprint,
            )

            verification = fixture.verifier.verify()

        self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verification.status)
        self.assertTrue(verification.complete)

    def test_repository_fact_rejects_source_changed_after_authority_receipt(self) -> None:
        """Receipt 이후 current tracked bytes가 바뀌면 repository fact lineage는 즉시 stale입니다."""
        with AdaptiveAuthorityFixture() as fixture:
            source = RepositoryWorktreeReadback(fixture.repository).read_tracked_file(
                "docs/repository-fact.txt"
            )
            lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source.worktree_fingerprint,
                suffix="stale-repository-fact",
                receipt_digest=source.content_digest,
            )
            gap = self._resolved_gap(
                fixture,
                gap_id="stale-repository-fact",
                authority=GapAuthority.REPOSITORY,
                resolution=GapResolution.REPOSITORY_FACT,
                lineage=lineage,
                blocking=True,
                reversible=False,
                scope_local=False,
                evidence_reference=source.relative_path,
            )
            self._persist_independent_snapshot_with_gaps(
                fixture,
                (gap,),
                "stale-repository-fact",
                inventory_source_revision=source.worktree_fingerprint,
            )
            (fixture.repository / source.relative_path).write_text(
                "changed repository fact\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "worktree is stale",
            ):
                fixture.verifier.verify()

    def test_safe_assumption_requires_structure_and_current_same_context(self) -> None:
        """Safe assumption은 bounded 구조와 current owner lineage를 모두 요구합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.SAME_CONTEXT,
                source_revision="approved-plan:1",
                suffix="unsafe-shape",
            )
            unsafe = self._resolved_gap(
                fixture,
                gap_id="unsafe-shape",
                authority=GapAuthority.SAFE_ASSUMPTION,
                resolution=GapResolution.SAFE_ASSUMPTION,
                lineage=lineage,
                blocking=True,
                reversible=False,
                scope_local=False,
            )
            self._persist_independent_snapshot_with_gaps(
                fixture,
                (unsafe,),
                "unsafe-shape",
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "reversible, scope-local, and non-blocking",
            ):
                fixture.verifier.verify()

        with AdaptiveAuthorityFixture() as fixture:
            lineage = self._gap_lineage(
                fixture,
                EvidenceAuthority.SAME_CONTEXT,
                source_revision="approved-plan:1",
                suffix="safe-self-claim",
            )
            safe = self._resolved_gap(
                fixture,
                gap_id="safe-self-claim",
                authority=GapAuthority.SAFE_ASSUMPTION,
                resolution=GapResolution.SAFE_ASSUMPTION,
                lineage=lineage,
                blocking=False,
                reversible=True,
                scope_local=True,
            )
            self._persist_independent_snapshot_with_gaps(
                fixture,
                (safe,),
                "safe-self-claim",
            )

            verification = fixture.verifier.verify()

        self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verification.status)
        self.assertTrue(verification.complete)
        self.assertEqual((), verification.pending_claims)

    def test_one_consumed_evaluator_report_signs_the_exact_complete_claim_set(self) -> None:
        """Evaluator가 읽은 full candidate와 exact claim report가 함께 결속됩니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "evaluation-complete",
                (evidence_claim, coverage_claim),
            )
            lineage = fixture.independent_lineage("evaluation-complete", receipt)
            fixture.persist_snapshot(
                fixture.independent_snapshot(
                    evidence_lineage=lineage,
                    coverage_lineage=lineage,
                )
            )
            fixture.transition_delegation(
                "evaluation-complete",
                receipt,
                lifecycle="consumed",
            )

            verification = fixture.verifier.verify()

        self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verification.status)
        self.assertTrue(verification.complete)
        self.assertEqual(("evaluation-complete",), verification.verified_delegation_ids)
        self.assertEqual((), verification.pending_claims)

    def test_independent_report_must_assess_the_exact_bounded_trajectory(self) -> None:
        """Goal claim만 재서명한 report는 exact trajectory를 판정한 증거가 아닙니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "trajectory-omitted",
                (evidence_claim, coverage_claim),
                include_trajectory_assessment=False,
            )
            lineage = fixture.independent_lineage("trajectory-omitted", receipt)
            fixture.persist_snapshot(
                fixture.independent_snapshot(
                    evidence_lineage=lineage,
                    coverage_lineage=lineage,
                )
            )
            fixture.transition_delegation(
                "trajectory-omitted",
                receipt,
                lifecycle="consumed",
            )

            with self.assertRaises(AdaptiveControlAuthorityInvalid):
                fixture.verifier.verify()

    def test_candidate_admission_rejects_unbacked_independent_claim_before_persistence(
        self,
    ) -> None:
        """Independent enum과 digest만 든 candidate는 store에 들어가기 전에 거부됩니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "candidate-unbacked",
                (evidence_claim, coverage_claim),
            )
            lineage = fixture.independent_lineage("candidate-unbacked", receipt)
            candidate = fixture.independent_snapshot(
                evidence_lineage=lineage,
                coverage_lineage=lineage,
            )

            with self.assertRaises(AdaptiveControlAuthorityNotFound):
                fixture.verifier.validate_candidate(
                    candidate.state,
                    candidate.workflow_revision,
                )
            with self.assertRaises(AdaptiveControlStateMissing):
                AdaptiveControlStore(SkillStateStore(fixture.owner, fixture.workflow_id)).read()

    def test_candidate_admission_accepts_consumed_or_explicitly_pending_authority(self) -> None:
        """Consumed independent claim은 verified, USER claim은 저장 가능한 pending으로 분리합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "candidate-consumed",
                (evidence_claim, coverage_claim),
            )
            lineage = fixture.independent_lineage("candidate-consumed", receipt)
            candidate = fixture.independent_snapshot(
                evidence_lineage=lineage,
                coverage_lineage=lineage,
            )
            fixture.transition_delegation(
                "candidate-consumed",
                receipt,
                lifecycle="consumed",
                candidate_state=candidate.state,
            )

            verified = fixture.verifier.validate_candidate(
                candidate.state,
                candidate.workflow_revision,
            )

        self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verified.status)
        self.assertTrue(verified.complete)

        with AdaptiveAuthorityFixture() as fixture:
            candidate = fixture.user_snapshot()

            pending = fixture.verifier.validate_candidate(
                candidate.state,
                candidate.workflow_revision,
            )

        self.assertIs(AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE, pending.status)
        self.assertFalse(pending.complete)

    def test_candidate_artifact_must_equal_the_state_being_admitted(self) -> None:
        """다른 final state로 준비한 assignment는 report가 유효해도 admission을 통과하지 못합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "candidate-state-mismatch",
                (evidence_claim, coverage_claim),
            )
            lineage = fixture.independent_lineage("candidate-state-mismatch", receipt)
            candidate = fixture.independent_snapshot(
                evidence_lineage=lineage,
                coverage_lineage=lineage,
            )
            prepared_state = replace(candidate.state, execution_status=ExecutionStatus.FAILED)
            fixture.transition_delegation(
                "candidate-state-mismatch",
                receipt,
                lifecycle="consumed",
                candidate_state=prepared_state,
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "expected final state",
            ):
                fixture.verifier.validate_candidate(
                    candidate.state,
                    candidate.workflow_revision,
                )

    def test_typed_result_summary_must_bind_the_exact_candidate_reference(self) -> None:
        """Report artifact가 같아도 result summary의 다른 candidate_ref는 delegation을 무효화합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "candidate-summary-mismatch",
                (evidence_claim, coverage_claim),
            )
            lineage = fixture.independent_lineage("candidate-summary-mismatch", receipt)
            candidate = fixture.independent_snapshot(
                evidence_lineage=lineage,
                coverage_lineage=lineage,
            )
            fixture.persist_snapshot(candidate)
            fixture.transition_delegation(
                "candidate-summary-mismatch",
                receipt,
                lifecycle="consumed",
                typed_summary_candidate_ref="sha256:" + "f" * 64,
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "typed result is not blocker-free",
            ):
                fixture.verifier.verify()

    def test_missing_or_tampered_candidate_reference_is_denied(self) -> None:
        """Legacy assignment과 digest가 깨진 candidate artifact는 report authority를 만들지 못합니다."""
        rows = ("missing-reference", "tampered-artifact")
        for row in rows:
            with self.subTest(row=row), AdaptiveAuthorityFixture() as fixture:
                evidence_claim, coverage_claim = fixture.independent_claims()
                delegation_id = f"candidate-{row}"
                receipt = fixture.write_artifact(
                    delegation_id,
                    (evidence_claim, coverage_claim),
                )
                lineage = fixture.independent_lineage(delegation_id, receipt)
                candidate = fixture.independent_snapshot(
                    evidence_lineage=lineage,
                    coverage_lineage=lineage,
                )
                fixture.persist_snapshot(candidate)
                assignment_json, candidate_ref = fixture.prepare_candidate(candidate.state)
                fixture.transition_delegation(
                    delegation_id,
                    receipt,
                    lifecycle="consumed",
                    assignment_removed_fields=(
                        frozenset({"candidate_ref"}) if row == "missing-reference" else frozenset()
                    ),
                    prepared_assignment=assignment_json,
                    prepared_candidate_ref=candidate_ref,
                )
                if row == "tampered-artifact":
                    fixture.corrupt_artifact(candidate_ref)

                with self.assertRaises(AdaptiveControlAuthorityInvalid):
                    fixture.verifier.verify()

    def test_one_candidate_assignment_cannot_be_reused_by_two_delegations(self) -> None:
        """Content identity가 같아도 assignment 하나를 두 evaluator lifecycle에 재사용하지 못합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "candidate-reuse-primary",
                (evidence_claim, coverage_claim),
            )
            lineage = fixture.independent_lineage("candidate-reuse-primary", receipt)
            candidate = fixture.independent_snapshot(
                evidence_lineage=lineage,
                coverage_lineage=lineage,
            )
            fixture.persist_snapshot(candidate)
            assignment_json, candidate_ref = fixture.prepare_candidate(candidate.state)
            fixture.transition_delegation(
                "candidate-reuse-primary",
                receipt,
                lifecycle="consumed",
                prepared_assignment=assignment_json,
                prepared_candidate_ref=candidate_ref,
            )
            fixture.transition_delegation(
                "candidate-reuse-secondary",
                receipt,
                lifecycle="pending",
                target_actor_id=fixture.alternate_evaluator_id,
                prepared_assignment=assignment_json,
                prepared_candidate_ref=candidate_ref,
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityConflict,
                "exactly one delegation",
            ):
                fixture.verifier.verify()

    def test_candidate_admission_rejects_a_stale_workflow_revision(self) -> None:
        """Admission basis가 current workflow revision과 다르면 CAS 전에 conflict입니다."""
        with AdaptiveAuthorityFixture() as fixture:
            candidate = fixture.user_snapshot()
            SkillStateStore(fixture.owner, fixture.workflow_id).update({"sibling": True})

            with self.assertRaises(AdaptiveControlAuthorityConflict):
                fixture.verifier.validate_candidate(
                    candidate.state,
                    candidate.workflow_revision,
                )

    def test_missing_pending_reported_and_cancelled_delegations_are_denied(self) -> None:
        """CONSUMED 전 lifecycle 또는 delegation 부재는 모두 completion authority가 아닙니다."""
        rows = (
            ("missing", AdaptiveControlAuthorityNotFound),
            ("pending", AdaptiveControlAuthorityConflict),
            ("reported", AdaptiveControlAuthorityConflict),
            ("cancelled", AdaptiveControlAuthorityConflict),
        )
        for lifecycle, expected_error in rows:
            with self.subTest(lifecycle=lifecycle), AdaptiveAuthorityFixture() as fixture:
                evidence_claim, coverage_claim = fixture.independent_claims()
                receipt = fixture.write_artifact(
                    f"evaluation-{lifecycle}",
                    (evidence_claim, coverage_claim),
                )
                lineage = fixture.independent_lineage(
                    f"evaluation-{lifecycle}",
                    receipt,
                )
                fixture.persist_snapshot(
                    fixture.independent_snapshot(
                        evidence_lineage=lineage,
                        coverage_lineage=lineage,
                    )
                )
                if lifecycle != "missing":
                    fixture.transition_delegation(
                        f"evaluation-{lifecycle}",
                        receipt,
                        lifecycle=lifecycle,
                    )

                with self.assertRaises(expected_error):
                    fixture.verifier.verify()

    def test_evaluator_report_with_missing_or_extra_claim_is_denied(self) -> None:
        """Persisted claim set과 report claim set 사이의 부분집합·초집합을 모두 거부합니다."""
        rows = ("missing", "extra")
        for row in rows:
            with self.subTest(row=row), AdaptiveAuthorityFixture() as fixture:
                evidence_claim, coverage_claim = fixture.independent_claims()
                artifact_claims = (coverage_claim,)
                if row == "extra":
                    artifact_claims = (
                        evidence_claim,
                        coverage_claim,
                        {
                            **evidence_claim,
                            "criterion_id": "invented-criterion",
                        },
                    )
                receipt = fixture.write_artifact(
                    f"evaluation-{row}-claim",
                    artifact_claims,
                )
                lineage = fixture.independent_lineage(
                    f"evaluation-{row}-claim",
                    receipt,
                )
                fixture.persist_snapshot(
                    fixture.independent_snapshot(
                        evidence_lineage=lineage,
                        coverage_lineage=lineage,
                    )
                )
                fixture.transition_delegation(
                    f"evaluation-{row}-claim",
                    receipt,
                    lifecycle="consumed",
                )

                with self.assertRaisesRegex(
                    AdaptiveControlAuthorityInvalid,
                    "artifact mismatch",
                ):
                    fixture.verifier.verify()

    def test_mismatched_foreign_and_forged_authority_rows_are_denied(self) -> None:
        """Topology, assignment, artifact, typed result의 어느 한 축도 위조할 수 없습니다."""
        rows = (
            "assignment-goal",
            "assignment-intent-type",
            "foreign-owner",
            "wrong-target",
            "typed-result",
            "typed-blocker",
            "artifact-claim",
            "forged-artifact",
        )
        for row in rows:
            with self.subTest(row=row), AdaptiveAuthorityFixture() as fixture:
                evidence_claim, coverage_claim = fixture.independent_claims()
                delegation_id = f"evaluation-{row}"
                artifact_claims = (evidence_claim, coverage_claim)
                if row == "artifact-claim":
                    forged_coverage = dict(coverage_claim)
                    forged_coverage["goal_alignment"] = 0.5
                    artifact_claims = (evidence_claim, forged_coverage)
                receipt = fixture.write_artifact(
                    delegation_id,
                    artifact_claims,
                )
                lineage = fixture.independent_lineage(delegation_id, receipt)
                fixture.persist_snapshot(
                    fixture.independent_snapshot(
                        evidence_lineage=lineage,
                        coverage_lineage=lineage,
                    )
                )
                fixture.transition_delegation(
                    delegation_id,
                    receipt,
                    lifecycle="consumed",
                    assignment_overrides=(
                        {"goal_fingerprint": "f" * 64}
                        if row == "assignment-goal"
                        else {"intent_revision": True}
                        if row == "assignment-intent-type"
                        else None
                    ),
                    owner_actor_id=(fixture.foreign_owner_id if row == "foreign-owner" else None),
                    target_actor_id=(
                        fixture.alternate_evaluator_id if row == "wrong-target" else None
                    ),
                    topology_policy=(
                        DelegationTopologyPolicy.UNSPECIFIED
                        if row in {"foreign-owner", "wrong-target"}
                        else DelegationTopologyPolicy.DIRECT_CHILD
                    ),
                    typed_verdict="fail" if row == "typed-result" else "pass",
                    typed_blocking_findings=(
                        ("unresolved blocker",) if row == "typed-blocker" else ()
                    ),
                )
                if row == "forged-artifact":
                    fixture.corrupt_artifact(receipt)

                with self.assertRaises(AdaptiveControlAuthorityInvalid):
                    fixture.verifier.verify()

    def test_executable_claim_requires_and_accepts_exact_independent_report_signature(
        self,
    ) -> None:
        """Executable PASS는 actual runtime replay와 exact evaluator report를 모두 요구합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.PROPERTY_TEST,
                OracleOwner.EXECUTABLE,
            )
            executable = fixture.execute_evidence()
            executable_claim, coverage_claim = fixture.mixed_claims(executable)
            receipt = fixture.write_artifact(
                "mixed-coverage",
                (executable_claim, coverage_claim),
                report_overrides={
                    "goal_fingerprint": coverage_claim["goal_fingerprint"],
                },
                contract=contract,
            )
            lineage = fixture.independent_lineage("mixed-coverage", receipt)
            candidate = fixture.mixed_snapshot(lineage, executable)
            assignment, candidate_ref = fixture.prepare_candidate(candidate.state)
            fixture.transition_delegation(
                "mixed-coverage",
                receipt,
                lifecycle="consumed",
                assignment_overrides={
                    "goal_fingerprint": coverage_claim["goal_fingerprint"],
                },
                candidate_state=candidate.state,
                prepared_assignment=assignment,
                prepared_candidate_ref=candidate_ref,
            )
            fixture.persist_snapshot(candidate)

            verification = fixture.verifier.verify()

        self.assertTrue(verification.complete)
        self.assertEqual(("mixed-coverage",), verification.verified_delegation_ids)

    def test_arbitrary_executable_reference_without_exact_signed_report_is_denied(self) -> None:
        """Executable enum/reference와 coverage-only report는 criterion 실행을 증명하지 않습니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.PROPERTY_TEST,
                OracleOwner.EXECUTABLE,
            )
            _executable_claim, coverage_claim = fixture.mixed_claims()
            receipt = fixture.write_artifact(
                "unsigned-executable",
                (coverage_claim,),
                report_overrides={
                    "goal_fingerprint": coverage_claim["goal_fingerprint"],
                },
                contract=contract,
            )
            lineage = fixture.independent_lineage("unsigned-executable", receipt)
            fixture.persist_snapshot(fixture.mixed_snapshot(lineage))
            fixture.transition_delegation(
                "unsigned-executable",
                receipt,
                lifecycle="consumed",
                assignment_overrides={
                    "goal_fingerprint": coverage_claim["goal_fingerprint"],
                },
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "executable evidence lineage|artifact mismatch",
            ):
                fixture.verifier.verify()

    def test_fabricated_executable_receipt_is_denied_even_with_exact_independent_report(
        self,
    ) -> None:
        """Exact evaluator report도 missing runtime receipt를 executable execution으로 대체하지 못합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(
                EvidenceKind.PROPERTY_TEST,
                OracleOwner.EXECUTABLE,
            )
            executable_claim, coverage_claim = fixture.mixed_claims()
            receipt = fixture.write_artifact(
                "fabricated-executable",
                (executable_claim, coverage_claim),
                report_overrides={
                    "goal_fingerprint": coverage_claim["goal_fingerprint"],
                },
                contract=contract,
            )
            lineage = fixture.independent_lineage("fabricated-executable", receipt)
            candidate = fixture.mixed_snapshot(lineage)
            fixture.persist_snapshot(candidate)
            fixture.transition_delegation(
                "fabricated-executable",
                receipt,
                lifecycle="consumed",
                assignment_overrides={
                    "goal_fingerprint": coverage_claim["goal_fingerprint"],
                },
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "executable evidence lineage|artifact",
            ):
                fixture.verifier.verify()

    def test_completed_execution_requires_exact_independent_completion_claim(self) -> None:
        """COMPLETED self-label는 report claim set의 execution-completion 서명 없이 완료가 아닙니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "missing-execution-completion",
                (evidence_claim, coverage_claim),
                include_execution_completion=False,
            )
            lineage = fixture.independent_lineage(
                "missing-execution-completion",
                receipt,
            )
            fixture.persist_snapshot(
                fixture.independent_snapshot(
                    evidence_lineage=lineage,
                    coverage_lineage=lineage,
                )
            )
            fixture.transition_delegation(
                "missing-execution-completion",
                receipt,
                lifecycle="consumed",
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "artifact mismatch",
            ):
                fixture.verifier.verify()

    def test_primary_source_claim_requires_signed_report_and_direct_current_readback(self) -> None:
        """Primary-source completion은 evaluator signature와 repository bytes를 모두 요구합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            source = RepositoryWorktreeReadback(fixture.repository).read_tracked_file(
                "docs/repository-fact.txt"
            )
            contract = fixture.primary_contract(source.worktree_fingerprint)
            primary_claim, coverage_claim = fixture.primary_claims(
                contract,
                source.relative_path,
            )
            receipt = fixture.write_artifact(
                "primary-source-complete",
                (primary_claim, coverage_claim),
                contract=contract,
            )
            coverage_lineage = fixture.independent_lineage(
                "primary-source-complete",
                receipt,
                source_revision=source.worktree_fingerprint,
            )
            fixture.persist_snapshot(
                fixture.primary_snapshot(
                    contract,
                    reference=source.relative_path,
                    content_digest=source.content_digest,
                    coverage_lineage=coverage_lineage,
                )
            )
            fixture.transition_delegation(
                "primary-source-complete",
                receipt,
                lifecycle="consumed",
                contract=contract,
            )

            verification = fixture.verifier.verify()

        self.assertTrue(verification.complete)
        self.assertEqual(
            ("primary-source-complete",),
            verification.verified_delegation_ids,
        )

    def test_signed_but_forged_primary_source_digest_is_denied(self) -> None:
        """Evaluator가 exact payload를 서명해도 fabricated repository digest는 authority가 아닙니다."""
        with AdaptiveAuthorityFixture() as fixture:
            source = RepositoryWorktreeReadback(fixture.repository).read_tracked_file(
                "docs/repository-fact.txt"
            )
            contract = fixture.primary_contract(source.worktree_fingerprint)
            primary_claim, coverage_claim = fixture.primary_claims(
                contract,
                source.relative_path,
            )
            receipt = fixture.write_artifact(
                "forged-primary-source",
                (primary_claim, coverage_claim),
                contract=contract,
            )
            coverage_lineage = fixture.independent_lineage(
                "forged-primary-source",
                receipt,
                source_revision=source.worktree_fingerprint,
            )
            fixture.persist_snapshot(
                fixture.primary_snapshot(
                    contract,
                    reference=source.relative_path,
                    content_digest="f" * 64,
                    coverage_lineage=coverage_lineage,
                )
            )
            fixture.transition_delegation(
                "forged-primary-source",
                receipt,
                lifecycle="consumed",
                contract=contract,
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "content digest mismatch",
            ):
                fixture.verifier.verify()

    def test_distinct_lineages_cannot_reuse_one_delegation_identity(self) -> None:
        """하나의 delegation ID를 서로 다른 digest lineage 두 개가 공유하면 conflict입니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            receipt = fixture.write_artifact(
                "evaluation-reused",
                (evidence_claim, coverage_claim),
            )
            first = fixture.independent_lineage("evaluation-reused", receipt)
            second = replace(first, receipt_digest="a" * 64)
            fixture.persist_snapshot(
                fixture.independent_snapshot(
                    evidence_lineage=first,
                    coverage_lineage=second,
                )
            )

            with self.assertRaises(AdaptiveControlAuthorityConflict):
                fixture.verifier.verify()

    def test_user_authority_is_explicitly_pending_without_runtime_receipt_source(self) -> None:
        """Legacy v3 USER claim은 load되지만 typed decision 없이 verified가 되지 않습니다."""
        with AdaptiveAuthorityFixture() as fixture:
            legacy_payload = dict(fixture.user_snapshot().state.to_payload())
            legacy_payload["schema_version"] = 3
            legacy_payload.pop("user_decisions")
            legacy = AdaptiveControlState.from_payload(legacy_payload)
            fixture.persist_snapshot(fixture._snapshot(legacy))

            verification = fixture.verifier.verify()

        self.assertIs(
            AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
            verification.status,
        )
        self.assertFalse(verification.complete)
        self.assertEqual(
            (
                "execution-completion",
                "goal-coverage",
                "user-decision:criterion:phase-complete",
            ),
            verification.pending_claims,
        )
        self.assertIn("runtime-backed user authority", verification.reason)

    def test_current_user_prompt_and_independent_report_jointly_verify_acceptance(self) -> None:
        """USER_ACCEPTANCE는 exact prompt source와 independent semantic interpretation을 모두 요구합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(EvidenceKind.USER_ACCEPTANCE, OracleOwner.USER)
            self._pending_user_acceptance(fixture, contract)
            user_lineage = self._record_user_response(
                fixture,
                contract,
                action=ControlAction.AWAIT_USER.value,
                claim_ids=("criterion:phase-complete",),
                question="현재 결과를 승인하시나요?",
                prompt="승인합니다.",
            )
            decision_claim = self._user_decision_claim(
                fixture,
                contract,
                target_kind=UserDecisionTarget.CRITERION,
                target_id="phase-complete",
                disposition=UserDecisionDisposition.ACCEPTED,
            )
            claims = self._user_acceptance_claims(
                contract,
                f"user-decision:{decision_claim.decision_digest}",
            )
            artifact = fixture.write_artifact(
                "user-acceptance-evaluation",
                (*claims, self._user_decision_report_claim(decision_claim)),
                contract=contract,
            )
            coverage_lineage = fixture.independent_lineage(
                "user-acceptance-evaluation",
                artifact,
            )
            decision = UserDecision(
                claim=decision_claim,
                interpretation_lineage=coverage_lineage,
            )
            candidate = self._user_acceptance_candidate(
                fixture,
                contract,
                user_lineage,
                coverage_lineage,
                decision,
            )
            fixture.transition_delegation(
                "user-acceptance-evaluation",
                artifact,
                lifecycle="consumed",
                contract=contract,
                candidate_state=candidate.state,
            )

            verification = fixture.verifier.validate_candidate(
                candidate.state,
                candidate.workflow_revision,
            )

            store = AdaptiveControlStore(SkillStateStore(fixture.owner, fixture.workflow_id))
            persisted = store.compare_and_replace_payload(
                candidate.workflow_revision,
                candidate.state.to_payload(),
            )
            fixture.owner.apply(
                ForegroundTurnPrompted(
                    session_id=fixture.owner.session_id,
                    actor_id=fixture.owner.actor_id,
                    vendor_turn_id="vendor-user-response",
                    idempotency_key="accepted:steering",
                    prompt_digest=hashlib.sha256("진행 상황도 알려주세요.".encode()).hexdigest(),
                )
            )
            after_steering = store.read()
            self.assertEqual(persisted.state.user_decisions, after_steering.state.user_decisions)
            preserved = fixture.verifier.verify()
            self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, preserved.status)
            self.assertTrue(preserved.complete)

        self.assertIs(AdaptiveControlAuthorityStatus.VERIFIED, verification.status)
        self.assertTrue(verification.complete)
        self.assertEqual((), verification.pending_claims)
        self.assertIsNotNone(verification.user_prompt_receipt)

    def test_typed_user_decision_without_transient_prompt_capability_remains_pending(self) -> None:
        """Report가 있어도 raw prompt receipt capability가 없던 새 decision은 admission 대기입니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(EvidenceKind.USER_ACCEPTANCE, OracleOwner.USER)
            persisted = self._pending_user_acceptance(fixture, contract)
            prompt_digest = hashlib.sha256(b"unavailable transient response").hexdigest()
            target = UserDecisionTarget.CRITERION
            disposition = UserDecisionDisposition.ACCEPTED
            decision_claim = UserDecisionClaim(
                workflow_id=str(fixture.workflow_id),
                question_workflow_revision=persisted.workflow_revision,
                source_goal_fingerprint=contract.fingerprint,
                source_intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                question_digest=hashlib.sha256(b"question").hexdigest(),
                question_generation=1,
                question_turn_revision=1,
                prompt_digest=prompt_digest,
                prompt_reference="user-prompt:unavailable",
                prompt_generation=2,
                prompt_turn_revision=2,
                target_kind=target,
                target_id="phase-complete",
                disposition=disposition,
                value_summary_digest=user_decision_value_summary_digest(
                    target,
                    "phase-complete",
                    disposition,
                    contract.fingerprint,
                    contract.intent_revision,
                    contract.source_revision,
                ),
                result_goal_fingerprint=contract.fingerprint,
                result_intent_revision=contract.intent_revision,
                result_source_revision=contract.source_revision,
            )
            claims = self._user_acceptance_claims(
                contract,
                f"user-decision:{decision_claim.decision_digest}",
            )
            artifact = fixture.write_artifact(
                "unavailable-user-prompt",
                (*claims, self._user_decision_report_claim(decision_claim)),
                contract=contract,
            )
            evaluator = fixture.independent_lineage("unavailable-user-prompt", artifact)
            decision = UserDecision(decision_claim, evaluator)
            user_lineage = AuthorityReceipt(
                authority=EvidenceAuthority.USER,
                issuer_id="user",
                subject_id=str(fixture.owner.actor_id),
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                receipt_digest=prompt_digest,
                delegation_id="user-prompt:unavailable",
            )
            candidate = self._user_acceptance_candidate(
                fixture,
                contract,
                user_lineage,
                evaluator,
                decision,
            )
            fixture.transition_delegation(
                "unavailable-user-prompt",
                artifact,
                lifecycle="consumed",
                candidate_state=candidate.state,
            )

            verification = fixture.verifier.validate_candidate(
                candidate.state,
                persisted.workflow_revision,
            )

        self.assertIs(
            AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
            verification.status,
        )
        self.assertEqual((decision.reference,), verification.pending_claims)

    def test_direct_user_prompt_does_not_interpret_itself_as_acceptance(self) -> None:
        """Exact user bytes만으로는 '아니요' 같은 응답을 USER_ACCEPTANCE PASS로 해석하지 않습니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(EvidenceKind.USER_ACCEPTANCE, OracleOwner.USER)
            self._pending_user_acceptance(fixture, contract)
            user_lineage = self._record_user_response(
                fixture,
                contract,
                action=ControlAction.AWAIT_USER.value,
                claim_ids=("criterion:phase-complete",),
                question="현재 결과를 승인하시나요?",
                prompt="아니요, 수정이 필요합니다.",
            )
            candidate = AdaptiveControlState(
                contract=contract,
                inventory=fixture._inventory(contract),
                evidence=(
                    CriterionEvidence(
                        goal_fingerprint=contract.fingerprint,
                        criterion_id="phase-complete",
                        kind=EvidenceKind.USER_ACCEPTANCE,
                        authority=EvidenceAuthority.USER,
                        status=EvidenceStatus.PASS,
                        reference=user_lineage.delegation_id or "missing-user-reference",
                        lineage=user_lineage,
                    ),
                ),
                coverage=None,
                execution_status=ExecutionStatus.COMPLETED,
                observations=(),
            )

            verification = fixture.verifier.validate_candidate(
                candidate,
                fixture.owner.inspect().workflows[fixture.workflow_id].revision,
            )

        self.assertIs(
            AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
            verification.status,
        )
        self.assertEqual(
            (
                "execution-completion",
                "goal-coverage",
                "user-decision:criterion:phase-complete",
            ),
            verification.pending_claims,
        )

    def test_independent_report_cannot_omit_the_exact_user_acceptance_claim(self) -> None:
        """GoalCoverage evaluator는 direct USER claim을 빼고 whole-goal PASS만 서명할 수 없습니다."""
        with AdaptiveAuthorityFixture() as fixture:
            contract = fixture._contract(EvidenceKind.USER_ACCEPTANCE, OracleOwner.USER)
            self._pending_user_acceptance(fixture, contract)
            user_lineage = self._record_user_response(
                fixture,
                contract,
                action=ControlAction.AWAIT_USER.value,
                claim_ids=("criterion:phase-complete",),
                question="현재 결과를 승인하시나요?",
                prompt="승인합니다.",
            )
            decision_claim = self._user_decision_claim(
                fixture,
                contract,
                target_kind=UserDecisionTarget.CRITERION,
                target_id="phase-complete",
                disposition=UserDecisionDisposition.ACCEPTED,
            )
            claims = self._user_acceptance_claims(
                contract,
                f"user-decision:{decision_claim.decision_digest}",
            )
            artifact = fixture.write_artifact(
                "user-claim-omitted",
                (claims[1], self._user_decision_report_claim(decision_claim)),
                contract=contract,
            )
            coverage_lineage = fixture.independent_lineage(
                "user-claim-omitted",
                artifact,
            )
            decision = UserDecision(
                claim=decision_claim,
                interpretation_lineage=coverage_lineage,
            )
            candidate = self._user_acceptance_candidate(
                fixture,
                contract,
                user_lineage,
                coverage_lineage,
                decision,
            )
            fixture.transition_delegation(
                "user-claim-omitted",
                artifact,
                lifecycle="consumed",
                contract=contract,
                candidate_state=candidate.state,
            )

            with self.assertRaisesRegex(
                AdaptiveControlAuthorityInvalid,
                "artifact mismatch",
            ):
                fixture.verifier.validate_candidate(
                    candidate.state,
                    candidate.workflow_revision,
                )

    def test_user_acceptance_rejects_stale_or_foreign_prompt_receipt(self) -> None:
        """Digest, generation, claim, workflow 또는 source가 다른 prompt는 USER PASS가 아닙니다."""
        rows = (
            "digest",
            "reference",
            "claim",
            "workflow",
            "later-prompt",
            "active-steering",
            "subject",
            "source",
        )
        for row in rows:
            with self.subTest(row=row), AdaptiveAuthorityFixture() as fixture:
                contract = fixture._contract(EvidenceKind.USER_ACCEPTANCE, OracleOwner.USER)
                self._pending_user_acceptance(fixture, contract)
                context_workflow_id: WorkflowId | None = None
                if row == "workflow":
                    context_workflow_id = WorkflowId("foreign-user-workflow")
                    fixture.owner.apply(
                        WorkflowStarted(
                            session_id=fixture.owner.session_id,
                            workflow_id=context_workflow_id,
                            owner_actor_id=fixture.owner.actor_id,
                            kind="evaluate-harness",
                            goal=None,
                            payload={},
                            idempotency_key="foreign-user-workflow:start",
                        )
                    )
                claim_ids = (
                    ("criterion:foreign",) if row == "claim" else ("criterion:phase-complete",)
                )
                lineage = self._record_user_response(
                    fixture,
                    contract,
                    action=ControlAction.AWAIT_USER.value,
                    claim_ids=claim_ids,
                    question="현재 결과를 승인하시나요?",
                    prompt="승인합니다.",
                    context_workflow_id=context_workflow_id,
                )
                decision_claim = self._user_decision_claim(
                    fixture,
                    contract,
                    target_kind=UserDecisionTarget.CRITERION,
                    target_id="phase-complete",
                    disposition=UserDecisionDisposition.ACCEPTED,
                )
                if row == "active-steering":
                    fixture.owner.apply(
                        ForegroundTurnPrompted(
                            session_id=fixture.owner.session_id,
                            actor_id=fixture.owner.actor_id,
                            vendor_turn_id="vendor-user-response",
                            idempotency_key="unconsumed:steering",
                            prompt_digest=hashlib.sha256("추가 요청입니다.".encode()).hexdigest(),
                        )
                    )
                if row == "later-prompt":
                    active = fixture.owner.inspect().foreground_turns[fixture.owner.actor_id]
                    fixture.owner.apply(
                        ForegroundTurnYielded(
                            session_id=fixture.owner.session_id,
                            actor_id=fixture.owner.actor_id,
                            expected_turn_revision=active.revision,
                            receipt=ForegroundTurnReceipt(
                                ForegroundTurnOutcome.COMPLETED,
                                summary="이전 user response 처리가 종료됐다",
                            ),
                            idempotency_key="later-user-prompt:yield",
                        )
                    )
                    ready = fixture.owner.inspect().foreground_turns[fixture.owner.actor_id]
                    fixture.owner.apply(
                        ForegroundTurnClosed(
                            session_id=fixture.owner.session_id,
                            actor_id=fixture.owner.actor_id,
                            expected_turn_revision=ready.revision,
                            idempotency_key="later-user-prompt:close",
                        )
                    )
                    fixture.owner.apply(
                        ForegroundTurnPrompted(
                            session_id=fixture.owner.session_id,
                            actor_id=fixture.owner.actor_id,
                            vendor_turn_id="unrelated-later-turn",
                            idempotency_key="later-user-prompt:prompt",
                            prompt_digest=hashlib.sha256("새 unrelated 요청".encode()).hexdigest(),
                            authority_context=None,
                        )
                    )
                if row == "digest":
                    lineage = replace(lineage, receipt_digest="f" * 64)
                elif row == "reference":
                    lineage = replace(lineage, delegation_id="user-prompt:stale")
                elif row == "subject":
                    lineage = replace(lineage, subject_id="codex:foreign-owner")
                elif row == "source":
                    lineage = replace(lineage, source_revision="approved-plan:stale")
                missing_coverage = AuthorityReceipt(
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    issuer_id=str(fixture.evaluator_id),
                    subject_id=str(fixture.owner.actor_id),
                    intent_revision=contract.intent_revision,
                    source_revision=contract.source_revision,
                    receipt_digest="a" * 64,
                    delegation_id="missing-user-evaluation",
                )
                decision = UserDecision(
                    claim=decision_claim,
                    interpretation_lineage=missing_coverage,
                )
                candidate = self._user_acceptance_candidate(
                    fixture,
                    contract,
                    lineage,
                    missing_coverage,
                    decision,
                )

                with self.assertRaises(AdaptiveControlAuthorityInvalid):
                    fixture.verifier.validate_candidate(
                        candidate.state,
                        candidate.workflow_revision,
                    )

    def test_same_context_label_is_never_independent_authority(self) -> None:
        """Same-context coverage는 independent evaluator가 아니므로 즉시 거부합니다."""
        with AdaptiveAuthorityFixture() as fixture:
            fixture.persist_snapshot(fixture.same_context_snapshot())

            with self.assertRaises(AdaptiveControlAuthorityInvalid):
                fixture.verifier.verify()

    def test_missing_or_foreign_workflow_adaptive_state_is_denied(self) -> None:
        """Verifier는 selector 밖으로 fallback하거나 missing adaptive state를 승인하지 않습니다."""
        with AdaptiveAuthorityFixture() as fixture:
            foreign = AdaptiveControlAuthorityVerifier(
                fixture.owner,
                WorkflowId("foreign-workflow"),
            )

            with self.assertRaises(AdaptiveControlAuthorityNotFound):
                fixture.verifier.verify()
            with self.assertRaises(AdaptiveControlAuthorityNotFound):
                foreign.verify()

    def test_same_revision_self_authored_snapshot_cannot_replace_persisted_state(self) -> None:
        """Persisted A와 같은 revision인 caller B도 external authority basis가 아닙니다."""
        with AdaptiveAuthorityFixture() as fixture:
            evidence_claim, coverage_claim = fixture.independent_claims()
            persisted_receipt = fixture.write_artifact(
                "persisted-missing",
                (evidence_claim, coverage_claim),
            )
            persisted_lineage = fixture.independent_lineage(
                "persisted-missing",
                persisted_receipt,
            )
            persisted = fixture.persist_snapshot(
                fixture.independent_snapshot(
                    evidence_lineage=persisted_lineage,
                    coverage_lineage=persisted_lineage,
                )
            )

            supplied_receipt = fixture.write_artifact(
                "supplied-consumed",
                (evidence_claim, coverage_claim),
            )
            supplied_lineage = fixture.independent_lineage(
                "supplied-consumed",
                supplied_receipt,
            )
            supplied = fixture.independent_snapshot(
                evidence_lineage=supplied_lineage,
                coverage_lineage=supplied_lineage,
            )
            supplied = AdaptiveControlSnapshot(
                workflow_id=supplied.workflow_id,
                workflow_revision=persisted.workflow_revision,
                state=supplied.state,
            )
            fixture.transition_delegation(
                "supplied-consumed",
                supplied_receipt,
                lifecycle="consumed",
                candidate_state=persisted.state,
            )

            self.assertEqual(persisted.workflow_revision, supplied.workflow_revision)
            with self.assertRaises(AdaptiveControlAuthorityNotFound):
                fixture.verifier.verify()


class AdaptiveAuthorityFixture:
    """Exact session/workflow와 adversarial delegation lifecycle을 조립합니다."""

    _GOAL = "adaptive completion authority를 검증한다"
    _REPORT_SUMMARY = "adaptive goal evaluation passed"

    def __enter__(self) -> Self:
        """격리된 session과 workflow, evaluator actor를 준비합니다."""
        self._temporary = TemporaryDirectory()
        self.repository = Path(self._temporary.name)
        subprocess.run(("git", "init", "-q"), cwd=self.repository, check=True)
        subprocess.run(
            ("git", "config", "user.email", "fixture@example.invalid"),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "config", "user.name", "Fixture"),
            cwd=self.repository,
            check=True,
        )
        (self.repository / ".gitignore").write_text(
            ".agents/runs/\nignored/\n.pytest_cache/\n__pycache__/\n",
            encoding="utf-8",
        )
        source = self.repository / "docs/repository-fact.txt"
        source.parent.mkdir(parents=True)
        source.write_text("authoritative repository fact\n", encoding="utf-8")
        runtime_test = self.repository / "tests/test_runtime_evidence.py"
        runtime_test.parent.mkdir(parents=True)
        runtime_test.write_text(
            "def test_passes():\n    assert True\n",
            encoding="utf-8",
        )
        subprocess.run(
            (
                "git",
                "add",
                ".gitignore",
                "docs/repository-fact.txt",
                "tests/test_runtime_evidence.py",
            ),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "commit", "-qm", "fixture"),
            cwd=self.repository,
            check=True,
        )
        self.locator = SessionLocator(self.repository)
        binding = RuntimeEnvironmentResolver().resolve({
            "CODEX_THREAD_ID": "adaptive-authority-session"
        })
        self.owner = StateHandle.initialize(self.locator, binding)
        self.owner.apply(
            ForegroundTurnProvisioned(
                session_id=self.owner.session_id,
                actor_id=self.owner.actor_id,
                idempotency_key="authority-fixture:turn:provision",
            )
        )
        self.workflow_id = WorkflowId("adaptive-workflow")
        self.owner.apply(
            WorkflowStarted(
                session_id=self.owner.session_id,
                workflow_id=self.workflow_id,
                owner_actor_id=self.owner.actor_id,
                kind="plan-issues",
                goal=self._GOAL,
                payload={"skill_state": {}},
                idempotency_key="authority-fixture:workflow",
            )
        )
        self.evaluator_id = ActorId("codex:adaptive-evaluator")
        self.alternate_evaluator_id = ActorId("codex:alternate-evaluator")
        self.foreign_owner_id = ActorId("codex:foreign-owner")
        for actor_id in (
            self.evaluator_id,
            self.alternate_evaluator_id,
            self.foreign_owner_id,
        ):
            self.owner.apply(
                ActorStarted(
                    session_id=self.owner.session_id,
                    actor_id=actor_id,
                    parent_actor_id=self.owner.actor_id,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"authority-fixture:actor:{actor_id}",
                    lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
                )
            )
        self.verifier = AdaptiveControlAuthorityVerifier(self.owner, self.workflow_id)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Temporary control plane을 제거합니다."""
        self._temporary.cleanup()

    def independent_lineage(
        self,
        delegation_id: str,
        outcome_ref: str,
        *,
        source_revision: str = "approved-plan:1",
    ) -> AuthorityReceipt:
        """Artifact digest에 결속된 independent evaluator lineage를 반환합니다."""
        return AuthorityReceipt(
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            issuer_id=str(self.evaluator_id),
            subject_id=str(self.owner.actor_id),
            intent_revision=1,
            source_revision=source_revision,
            receipt_digest=outcome_ref.removeprefix("sha256:"),
            delegation_id=delegation_id,
        )

    def independent_claims(self) -> tuple[dict[str, object], dict[str, object]]:
        """Lineage digest와 무관한 canonical criterion/coverage claim을 반환합니다."""
        contract = self._contract(
            EvidenceKind.INDEPENDENT_SEMANTIC,
            OracleOwner.INDEPENDENT_EVALUATOR,
        )
        return (
            {
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "criterion-evidence",
                "evaluation_revision": 1,
                "criterion_id": "phase-complete",
                "goal_fingerprint": contract.fingerprint,
                "kind": EvidenceKind.INDEPENDENT_SEMANTIC.value,
                "reference": "independent:criterion",
                "status": EvidenceStatus.PASS.value,
            },
            {
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "goal-coverage",
                "evaluation_revision": 1,
                "criterion_ids": ["phase-complete"],
                "goal_alignment": 1.0,
                "goal_fingerprint": contract.fingerprint,
                "reference": "independent:coverage",
                "reward_hacking_risk": 0.0,
                "semantic_drift": 0.0,
                "status": EvidenceStatus.PASS.value,
                "uncertainty": 0.0,
            },
        )

    def independent_snapshot(
        self,
        *,
        evidence_lineage: AuthorityReceipt,
        coverage_lineage: AuthorityReceipt,
    ) -> AdaptiveControlSnapshot:
        """Independent criterion과 coverage가 포함된 current workflow snapshot을 만듭니다."""
        contract = self._contract(
            EvidenceKind.INDEPENDENT_SEMANTIC,
            OracleOwner.INDEPENDENT_EVALUATOR,
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=self._inventory(contract),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id="phase-complete",
                    kind=EvidenceKind.INDEPENDENT_SEMANTIC,
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    status=EvidenceStatus.PASS,
                    reference="independent:criterion",
                    lineage=evidence_lineage,
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({"phase-complete"}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="independent:coverage",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=coverage_lineage,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        return self._snapshot(state)

    def user_snapshot(self) -> AdaptiveControlSnapshot:
        """Self-declared USER receipts가 포함된 snapshot을 만듭니다."""
        contract = self._contract(EvidenceKind.USER_ACCEPTANCE, OracleOwner.USER)
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.USER,
            issuer_id="user",
            subject_id=str(self.owner.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest="b" * 64,
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=self._inventory(contract),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id="phase-complete",
                    kind=EvidenceKind.USER_ACCEPTANCE,
                    authority=EvidenceAuthority.USER,
                    status=EvidenceStatus.PASS,
                    reference="self-declared:user-acceptance",
                    lineage=lineage,
                ),
            ),
            coverage=None,
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        return self._snapshot(state)

    def execute_evidence(self) -> CriterionEvidence:
        """Current workflow revision에서 harness-owned executable evidence를 발행합니다."""
        contract = self._contract(EvidenceKind.PROPERTY_TEST, OracleOwner.EXECUTABLE)
        return (
            AdaptiveExecutionReceiptStore(
                self.owner,
                self.workflow_id,
            )
            .execute_pytest(
                contract,
                criterion_id="phase-complete",
                evidence_kind=EvidenceKind.PROPERTY_TEST,
                pytest_node="tests/test_runtime_evidence.py::test_passes",
            )
            .evidence
        )

    def mixed_claims(
        self,
        executable: CriterionEvidence | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Executable criterion과 independent coverage의 canonical claim을 반환합니다."""
        contract = self._contract(EvidenceKind.PROPERTY_TEST, OracleOwner.EXECUTABLE)
        reference = (
            "pytest:/definitely/not/run.py::test_never_ran"
            if executable is None
            else executable.reference
        )
        return (
            {
                "authority": EvidenceAuthority.EXECUTABLE.value,
                "claim_type": "criterion-evidence",
                "evaluation_revision": 1,
                "criterion_id": "phase-complete",
                "goal_fingerprint": contract.fingerprint,
                "kind": EvidenceKind.PROPERTY_TEST.value,
                "reference": reference,
                "status": EvidenceStatus.PASS.value,
            },
            {
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "goal-coverage",
                "evaluation_revision": 1,
                "criterion_ids": ["phase-complete"],
                "goal_alignment": 1.0,
                "goal_fingerprint": contract.fingerprint,
                "reference": "independent:mixed-coverage",
                "reward_hacking_risk": 0.0,
                "semantic_drift": 0.0,
                "status": EvidenceStatus.PASS.value,
                "uncertainty": 0.0,
            },
        )

    def mixed_snapshot(
        self,
        coverage_lineage: AuthorityReceipt,
        executable_evidence: CriterionEvidence | None = None,
    ) -> AdaptiveControlSnapshot:
        """Non-owner executable evidence와 independent coverage를 함께 보존합니다."""
        contract = self._contract(EvidenceKind.PROPERTY_TEST, OracleOwner.EXECUTABLE)
        evidence = executable_evidence
        if evidence is None:
            executable = AuthorityReceipt(
                authority=EvidenceAuthority.EXECUTABLE,
                issuer_id="fabricated-runner",
                subject_id=str(self.owner.actor_id),
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                receipt_digest="e" * 64,
            )
            evidence = CriterionEvidence(
                goal_fingerprint=contract.fingerprint,
                criterion_id="phase-complete",
                kind=EvidenceKind.PROPERTY_TEST,
                authority=EvidenceAuthority.EXECUTABLE,
                status=EvidenceStatus.PASS,
                reference="pytest:/definitely/not/run.py::test_never_ran",
                lineage=executable,
            )
        state = AdaptiveControlState(
            contract=contract,
            inventory=self._inventory(contract),
            evidence=(evidence,),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({"phase-complete"}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="independent:mixed-coverage",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=coverage_lineage,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        return self._snapshot(state)

    def primary_contract(self, source_revision: str) -> GoalContract:
        """Current repository fingerprint에 결속된 source-readback contract를 반환합니다."""
        return self._contract(
            EvidenceKind.SOURCE_READBACK,
            OracleOwner.PRIMARY_SOURCE,
            source_revision=source_revision,
        )

    def primary_claims(
        self,
        contract: GoalContract,
        reference: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Primary-source criterion과 independent coverage의 canonical claim을 반환합니다."""
        return (
            {
                "authority": EvidenceAuthority.PRIMARY_SOURCE.value,
                "claim_type": "criterion-evidence",
                "evaluation_revision": 1,
                "criterion_id": "phase-complete",
                "goal_fingerprint": contract.fingerprint,
                "kind": EvidenceKind.SOURCE_READBACK.value,
                "reference": reference,
                "status": EvidenceStatus.PASS.value,
            },
            {
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "goal-coverage",
                "evaluation_revision": 1,
                "criterion_ids": ["phase-complete"],
                "goal_alignment": 1.0,
                "goal_fingerprint": contract.fingerprint,
                "reference": "independent:primary-coverage",
                "reward_hacking_risk": 0.0,
                "semantic_drift": 0.0,
                "status": EvidenceStatus.PASS.value,
                "uncertainty": 0.0,
            },
        )

    def primary_snapshot(
        self,
        contract: GoalContract,
        *,
        reference: str,
        content_digest: str,
        coverage_lineage: AuthorityReceipt,
    ) -> AdaptiveControlSnapshot:
        """Repository bytes와 independent semantic coverage를 함께 보존합니다."""
        source_lineage = AuthorityReceipt(
            authority=EvidenceAuthority.PRIMARY_SOURCE,
            issuer_id="repository",
            subject_id=str(self.owner.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=content_digest,
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=self._inventory(contract),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id="phase-complete",
                    kind=EvidenceKind.SOURCE_READBACK,
                    authority=EvidenceAuthority.PRIMARY_SOURCE,
                    status=EvidenceStatus.PASS,
                    reference=reference,
                    lineage=source_lineage,
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({"phase-complete"}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="independent:primary-coverage",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=coverage_lineage,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        return self._snapshot(state)

    def same_context_snapshot(self) -> AdaptiveControlSnapshot:
        """Executable criterion에 same-context coverage label을 붙인 snapshot을 만듭니다."""
        contract = self._contract(EvidenceKind.PROPERTY_TEST, OracleOwner.EXECUTABLE)
        executable = self._lineage(EvidenceAuthority.EXECUTABLE, "test-runner", "c" * 64)
        same_context = self._lineage(
            EvidenceAuthority.SAME_CONTEXT,
            str(self.owner.actor_id),
            "d" * 64,
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=self._inventory(contract),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id="phase-complete",
                    kind=EvidenceKind.PROPERTY_TEST,
                    authority=EvidenceAuthority.EXECUTABLE,
                    status=EvidenceStatus.PASS,
                    reference="unittest:property",
                    lineage=executable,
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({"phase-complete"}),
                authority=EvidenceAuthority.SAME_CONTEXT,
                status=EvidenceStatus.PASS,
                reference="same-context:self-score",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=same_context,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        return self._snapshot(state)

    def write_artifact(
        self,
        delegation_id: str,
        claims: tuple[dict[str, object], ...],
        *,
        target_actor_id: ActorId | None = None,
        report_overrides: Mapping[str, object] | None = None,
        contract: GoalContract | None = None,
        include_execution_completion: bool = True,
        include_trajectory_assessment: bool = True,
    ) -> str:
        """Canonical adaptive evaluation report를 target actor artifact로 씁니다."""
        selected_target = target_actor_id or self.evaluator_id
        report = self._report(
            claims,
            contract=contract,
            include_execution_completion=include_execution_completion,
            include_trajectory_assessment=include_trajectory_assessment,
        )
        if report_overrides is not None:
            report.update(report_overrides)
        artifact = SessionArtifactStore(self._handle(selected_target)).put_json({
            "delegation_id": delegation_id,
            "report": report,
            "schema": "neurath.delegation-result.v1",
            "target_agent_id": str(selected_target),
        })
        return artifact.reference

    def transition_delegation(
        self,
        delegation_id: str,
        outcome_ref: str,
        *,
        lifecycle: str,
        assignment_overrides: Mapping[str, object] | None = None,
        assignment_removed_fields: frozenset[str] = frozenset(),
        owner_actor_id: ActorId | None = None,
        target_actor_id: ActorId | None = None,
        typed_verdict: str = "pass",
        typed_blocking_findings: tuple[str, ...] = (),
        typed_summary_candidate_ref: str | None = None,
        contract: GoalContract | None = None,
        candidate_state: AdaptiveControlState | None = None,
        prepared_assignment: str | None = None,
        prepared_candidate_ref: str | None = None,
        topology_policy: DelegationTopologyPolicy = DelegationTopologyPolicy.DIRECT_CHILD,
    ) -> None:
        """지정한 lifecycle까지 typed delegation을 전이합니다."""
        selected_owner = owner_actor_id or self.owner.actor_id
        selected_target = target_actor_id or self.evaluator_id
        owner_handle = self._handle(selected_owner)
        if (prepared_assignment is None) != (prepared_candidate_ref is None):
            raise AssertionError(
                "prepared assignment and candidate reference must be supplied together"
            )
        if prepared_assignment is None or prepared_candidate_ref is None:
            selected_state = candidate_state
            if selected_state is None:
                selected_state = (
                    AdaptiveControlStore(SkillStateStore(self.owner, self.workflow_id)).read().state
                )
            prepared_assignment, prepared_candidate_ref = self.prepare_candidate(selected_state)
        assignment: object = json.loads(prepared_assignment)
        assert isinstance(assignment, dict)
        if assignment_overrides is not None:
            assignment.update(assignment_overrides)
        for field in assignment_removed_fields:
            assignment.pop(field, None)
        trajectory_digest = assignment.get("trajectory_digest")
        if not isinstance(trajectory_digest, str):
            trajectory_digest = "0" * 64
        owner_handle.apply(
            DelegationAssigned(
                session_id=owner_handle.session_id,
                delegation_id=DelegationId(delegation_id),
                owner_actor_id=selected_owner,
                target_actor_id=selected_target,
                assignment=json.dumps(
                    assignment,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                idempotency_key=f"authority-fixture:assign:{delegation_id}",
                topology_policy=topology_policy,
            )
        )
        if lifecycle == "pending":
            return
        if lifecycle == "cancelled":
            owner_handle.apply(
                DelegationCancelled(
                    session_id=owner_handle.session_id,
                    delegation_id=DelegationId(delegation_id),
                    owner_actor_id=selected_owner,
                    reason="evaluation cancelled",
                    idempotency_key=f"authority-fixture:cancel:{delegation_id}",
                )
            )
            return
        report = SessionArtifactStore(self.owner).read_json(outcome_ref)["report"]
        assert isinstance(report, dict)
        target_handle = self._handle(selected_target)
        target_handle.apply(
            DelegationReported(
                session_id=target_handle.session_id,
                delegation_id=DelegationId(delegation_id),
                reporter_actor_id=selected_target,
                result=DelegationResult(
                    verdict=typed_verdict,
                    summary=self._result_summary(
                        typed_summary_candidate_ref or prepared_candidate_ref,
                        trajectory_digest,
                    ),
                    outcome_ref=outcome_ref,
                    blocking_findings=typed_blocking_findings,
                ),
                idempotency_key=f"authority-fixture:report:{delegation_id}",
            )
        )
        if lifecycle == "reported":
            return
        owner_handle.apply(
            DelegationConsumed(
                session_id=owner_handle.session_id,
                delegation_id=DelegationId(delegation_id),
                consumer_actor_id=selected_owner,
                idempotency_key=f"authority-fixture:consume:{delegation_id}",
            )
        )

    def prepare_candidate(self, state: AdaptiveControlState) -> tuple[str, str]:
        """Owner authority로 exact full state candidate와 canonical assignment를 만듭니다."""
        prepared = AdaptiveEvaluationCandidateStore(
            self.owner,
            self.workflow_id,
        ).prepare(state)
        return prepared.assignment_json, prepared.candidate_ref

    def corrupt_artifact(self, reference: str) -> None:
        """Content-addressed artifact bytes를 바꿔 digest read-back failure를 만듭니다."""
        digest = reference.removeprefix("sha256:")
        path = self.locator.locate(self.owner.session_id).artifacts / "sha256" / f"{digest}.json"
        path.write_text('{"forged":true}', encoding="utf-8")

    def persist_snapshot(
        self,
        snapshot: AdaptiveControlSnapshot,
    ) -> AdaptiveControlSnapshot:
        """Verifier negative test용 domain-valid snapshot을 reducer primitive로 seed합니다."""
        workflow = self.owner.inspect().workflows[self.workflow_id]
        payload = dict(workflow.payload)
        skill_state = payload.get("skill_state")
        if not isinstance(skill_state, Mapping):
            raise TypeError("authority fixture requires object skill_state")
        payload["skill_state"] = {
            **skill_state,
            "adaptive_control": snapshot.state.to_payload(),
        }
        payload_digest = hashlib.sha256(
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        SessionStateStore(self.locator.locate(self.owner.session_id).process_state).transact(
            ReservedSkillStateAdvanced(
                session_id=self.owner.session_id,
                workflow_id=self.workflow_id,
                actor_id=self.owner.actor_id,
                expected_workflow_revision=workflow.revision,
                payload=payload,
                idempotency_key=(
                    f"skill-state:{self.workflow_id}:{'0' * 32}:"
                    f"{workflow.revision}:{payload_digest}"
                ),
                reserved_namespaces=frozenset({"adaptive_control"}),
            )
        )
        return AdaptiveControlStore(SkillStateStore(self.owner, self.workflow_id)).read()

    def _snapshot(self, state: AdaptiveControlState) -> AdaptiveControlSnapshot:
        workflow = self.owner.inspect().workflows[self.workflow_id]
        return AdaptiveControlSnapshot(
            workflow_id=self.workflow_id,
            workflow_revision=workflow.revision,
            state=state,
        )

    def _contract(
        self,
        kind: EvidenceKind,
        owner: OracleOwner,
        *,
        source_revision: str = "approved-plan:1",
    ) -> GoalContract:
        goal = self._GOAL
        constraints = ("exact workflow delegation만 신뢰한다",)
        non_goals = ("same-context self-score를 independent로 취급하지 않는다",)
        requirement = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            1,
            source_revision,
        )
        return GoalContract(
            goal=goal,
            constraints=constraints,
            criteria=(
                CriterionSpec(
                    criterion_id="phase-complete",
                    description="외부 authority가 completion을 판정한다",
                    source_requirement_id="REQ-adaptive-authority",
                    approved_requirement_fingerprint=requirement,
                    observer="external authority verifier",
                    precondition="current workflow와 goal revision이 고정되어 있다",
                    stimulus="completion evidence를 검증한다",
                    expected_outcome="runtime-backed authority만 완료를 승인한다",
                    oracle_owner=owner,
                    hard=True,
                    required_evidence=frozenset({kind}),
                ),
            ),
            requirement_ids=frozenset({"REQ-adaptive-authority"}),
            non_goals=non_goals,
            intent_revision=1,
            source_revision=source_revision,
        )

    def _inventory(self, contract: GoalContract) -> GapInventory:
        return GapInventory(
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            assessed_sections=frozenset(RequirementSection),
            gaps=(),
        )

    def _lineage(
        self,
        authority: EvidenceAuthority,
        issuer_id: str,
        digest: str,
    ) -> AuthorityReceipt:
        return AuthorityReceipt(
            authority=authority,
            issuer_id=issuer_id,
            subject_id=str(self.owner.actor_id),
            intent_revision=1,
            source_revision="approved-plan:1",
            receipt_digest=digest,
        )

    def _assignment(self, *, contract: GoalContract | None = None) -> dict[str, object]:
        selected_contract = contract or self._contract(
            EvidenceKind.INDEPENDENT_SEMANTIC,
            OracleOwner.INDEPENDENT_EVALUATOR,
        )
        return {
            "goal_fingerprint": selected_contract.fingerprint,
            "intent_revision": selected_contract.intent_revision,
            "kind": "adaptive-goal-evaluation",
            "source_revision": selected_contract.source_revision,
            "workflow_id": str(self.workflow_id),
        }

    def _result_summary(self, candidate_ref: str, trajectory_digest: str) -> str:
        """Typed delegation result를 exact evaluated candidate에 결속합니다."""
        return json.dumps(
            {
                "candidate_ref": candidate_ref,
                "summary": self._REPORT_SUMMARY,
                "trajectory_digest": trajectory_digest,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _report(
        self,
        claims: tuple[dict[str, object], ...],
        *,
        contract: GoalContract | None = None,
        include_execution_completion: bool = True,
        include_trajectory_assessment: bool = True,
    ) -> dict[str, object]:
        selected_contract = contract or self._contract(
            EvidenceKind.INDEPENDENT_SEMANTIC,
            OracleOwner.INDEPENDENT_EVALUATOR,
        )
        report_claims = claims
        if include_execution_completion:
            report_claims += (
                {
                    "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                    "claim_type": "execution-completion",
                    "goal_fingerprint": selected_contract.fingerprint,
                    "status": ExecutionStatus.COMPLETED.value,
                },
            )
        report: dict[str, object] = {
            "blocking_findings": [],
            "claims": sorted(
                report_claims,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
            "goal_fingerprint": selected_contract.fingerprint,
            "intent_revision": selected_contract.intent_revision,
            "kind": "adaptive-goal-evaluation",
            "source_revision": selected_contract.source_revision,
            "summary": self._REPORT_SUMMARY,
            "verdict": "pass",
            "workflow_id": str(self.workflow_id),
        }
        if include_trajectory_assessment:
            trajectory_digest = AdaptiveEvaluationCandidateStore(
                self.owner,
                self.workflow_id,
            ).current_trajectory_digest()
            report["trajectory_assessment"] = {
                "blocking_findings": [],
                "trajectory_digest": trajectory_digest,
                "verdict": "pass",
            }
        return report

    def _handle(self, actor_id: ActorId) -> StateHandle:
        return StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=self.owner.runtime,
                session_id=self.owner.session_id,
                actor_id=actor_id,
                root_actor_id=self.owner.actor_id,
            ),
        )
