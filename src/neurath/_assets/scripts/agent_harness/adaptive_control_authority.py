"""Adaptive completion의 external authority를 exact runtime state에서 검증합니다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    ClarificationGap,
    ControlAction,
    CriterionEvidence,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapAuthority,
    GapResolution,
    GoalContract,
    GoalCoverage,
    UserDecision,
    UserDecisionDisposition,
    UserDecisionProvenance,
    UserDecisionTarget,
    effective_criterion_evidence,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlReceipt,
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    AdaptiveControlStateMissing,
    AdaptiveControlStore,
)
from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateConflict,
    AdaptiveEvaluationCandidateError,
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.adaptive_execution_receipt import (
    AdaptiveExecutionReceiptError,
    AdaptiveExecutionReceiptStore,
)
from scripts.agent_harness.artifact_store import ArtifactStoreError, SessionArtifactStore
from scripts.agent_harness.repository_readback import (
    RepositoryReadbackError,
    RepositoryWorktreeReadback,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    DelegationId,
    DelegationRecord,
    DelegationStatus,
    DelegationTopologyPolicy,
    ForegroundTurnRecord,
    ForegroundUserPromptReceipt,
    ProcessState,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateStore,
    SkillStateStoreError,
    SkillStateWorkflowNotFound,
)
from scripts.agent_harness.state_handle import StateHandle


class AdaptiveControlAuthorityError(RuntimeError):
    """Adaptive external authority를 안전하게 증명할 수 없음을 나타냅니다."""


class AdaptiveControlAuthorityNotFound(AdaptiveControlAuthorityError):
    """Lineage가 지목한 exact delegation이 없을 때 발생합니다."""


class AdaptiveControlAuthorityConflict(AdaptiveControlAuthorityError):
    """Delegation lifecycle, uniqueness 또는 concurrent snapshot이 충돌할 때 발생합니다."""


class AdaptiveControlAuthorityInvalid(AdaptiveControlAuthorityError):
    """Identity, assignment, artifact 또는 typed result가 contract와 다를 때 발생합니다."""


class AdaptiveControlAuthorityStatus(StrEnum):
    """External authority verifier가 반환할 수 있는 bounded 상태입니다."""

    VERIFIED = "verified"
    """모든 external claim이 current runtime authority로 검증됐습니다."""

    PENDING_UNVERIFIABLE = "pending-unverifiable"
    """저장 가능하지만 아직 runtime source가 없어 completion에는 사용할 수 없습니다."""


@dataclass(frozen=True, slots=True)
class AdaptiveControlAuthorityVerification:
    """Exact workflow에서 검증된 delegation과 아직 증명 불가능한 user claim입니다."""

    status: AdaptiveControlAuthorityStatus
    """Current claim 집합의 external authority 검증 상태입니다."""

    workflow_id: WorkflowId
    """검증 대상 exact workflow identity입니다."""

    workflow_revision: int
    """검증 시점의 workflow-local optimistic revision입니다."""

    goal_fingerprint: str
    """검증된 current goal contract의 canonical fingerprint입니다."""

    verified_delegation_ids: tuple[str, ...]
    """Exact assignment, candidate, report를 통과한 consumed delegation identity입니다."""

    pending_claims: tuple[str, ...]
    """Current runtime source가 없어 아직 검증할 수 없는 claim identity입니다."""

    reason: str
    """Caller가 분기할 수 있는 검증 결과 설명입니다."""

    user_prompt_receipt: ForegroundUserPromptReceipt | None
    """Raw prompt 없이 보존된 current user authority provenance입니다."""

    @property
    def complete(self) -> bool:
        """모든 external authority가 runtime read-back을 통과했는지 반환합니다.

        Returns:
            Pending claim 없이 external authority가 검증됐으면 `True`입니다.
        """
        return self.status is AdaptiveControlAuthorityStatus.VERIFIED


@dataclass(frozen=True, slots=True)
class AdaptiveCompletionAuthorityReadback:
    """한 current snapshot에서 함께 검증된 completion 의미와 external authority입니다."""

    receipt: AdaptiveControlReceipt
    """Current adaptive snapshot에서 파생된 COMPLETE decision입니다."""

    external_authority: AdaptiveControlAuthorityVerification
    """같은 snapshot의 external claims를 runtime source에 재대조한 결과입니다."""

    @property
    def workflow_id(self) -> WorkflowId:
        """검증된 exact workflow identity를 반환합니다.

        Returns:
            Completion read-back이 결속된 workflow identity입니다.
        """
        return self.receipt.workflow_id

    @property
    def workflow_revision(self) -> int:
        """검증된 workflow-local CAS revision을 반환합니다.

        Returns:
            Completion read-back이 결속된 workflow revision입니다.
        """
        return self.receipt.workflow_revision

    @property
    def goal_fingerprint(self) -> str:
        """검증된 current goal contract fingerprint를 반환합니다.

        Returns:
            Completion read-back이 결속된 goal fingerprint입니다.
        """
        return self.receipt.goal_fingerprint


@dataclass(frozen=True, slots=True)
class _AuthorityClaim:
    """Coverage 또는 criterion evidence의 lineage-free canonical claim입니다."""

    claim_id: str
    authority: EvidenceAuthority
    lineage: AuthorityReceipt
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _IndependentCompletionReport:
    """Coverage evaluator 하나가 함께 서명해야 하는 exact completion claim 집합입니다."""

    lineage: AuthorityReceipt
    claims: tuple[_AuthorityClaim, ...]


class AdaptiveControlAuthorityVerifier:
    """Self-attested authority label을 consumed delegation artifact와 대조합니다."""

    _ASSIGNMENT_KIND = "adaptive-goal-evaluation"
    _ARTIFACT_SCHEMA = "neurath.delegation-result.v1"
    _REPORT_SUMMARY = "adaptive goal evaluation passed"

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Runtime-bound handle과 exact workflow selector를 고정합니다.

        Args:
            handle: Current workflow owner actor에 결속된 state facade입니다.
            workflow_id: Adaptive snapshot과 delegation assignment가 공유할 identity입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._artifacts = SessionArtifactStore(handle)
        self._adaptive = AdaptiveControlStore(SkillStateStore(handle, workflow_id))
        self._candidates = AdaptiveEvaluationCandidateStore(handle, workflow_id)

    def verify(self) -> AdaptiveControlAuthorityVerification:
        """Current adaptive snapshot의 external authority를 fail closed로 검증합니다.

        Returns:
            Independent delegation read-back 또는 explicit user-pending 결과입니다.

        Raises:
            AdaptiveControlAuthorityNotFound: Independent lineage의 delegation이 없습니다.
            AdaptiveControlAuthorityConflict: Lifecycle, uniqueness 또는 revision이 충돌합니다.
            AdaptiveControlAuthorityInvalid: Identity, assignment, artifact가 위조됐습니다.
        """
        process_state, workflow, snapshot = self._read_current_snapshot()
        return self._verify_state(
            process_state.revision,
            process_state.delegations,
            process_state.foreground_turns,
            workflow,
            snapshot.state,
            prompt_required_decisions=frozenset(),
        )

    def verify_completion(
        self,
        expected_workflow_revision: int,
    ) -> AdaptiveCompletionAuthorityReadback:
        """한 current snapshot에서 semantic completion과 external authority를 검증합니다.

        Args:
            expected_workflow_revision: Caller가 읽은 exact workflow-local CAS revision입니다.

        Returns:
            같은 workflow, revision, goal fingerprint에 결속된 COMPLETE receipt와 external
            authority입니다.

        Raises:
            AdaptiveControlAuthorityConflict: Caller revision 또는 external authority identity가
                current snapshot과 다릅니다.
            AdaptiveControlAuthorityInvalid: Current receipt가 ready/COMPLETE/achieved가 아니거나
                external authority가 아직 완료되지 않았습니다.
            AdaptiveControlAuthorityNotFound: Exact adaptive snapshot 또는 workflow가 없습니다.
        """
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise AdaptiveControlAuthorityInvalid(
                "expected adaptive workflow revision must be a non-negative integer"
            )
        process_state, workflow, snapshot = self._read_current_snapshot()
        if workflow.revision != expected_workflow_revision:
            raise AdaptiveControlAuthorityConflict(
                f"expected workflow revision {expected_workflow_revision}, got {workflow.revision}"
            )
        try:
            receipt = snapshot.receipt()
        except (TypeError, ValueError) as error:
            raise AdaptiveControlAuthorityInvalid(
                "current adaptive completion receipt is invalid"
            ) from error
        if (
            receipt.workflow_id != workflow.id
            or receipt.workflow_revision != workflow.revision
            or receipt.goal_fingerprint != snapshot.state.contract.fingerprint
        ):
            raise AdaptiveControlAuthorityConflict(
                "adaptive completion receipt is stale for the current workflow"
            )
        if (
            receipt.decision.action is not ControlAction.COMPLETE
            or not receipt.ambiguity.ready
            or not receipt.decision.achieved
            or not receipt.attainment.achieved
        ):
            raise AdaptiveControlAuthorityInvalid(
                "adaptive completion requires current ready intent and achieved COMPLETE authority"
            )
        external_authority = self._verify_state(
            process_state.revision,
            process_state.delegations,
            process_state.foreground_turns,
            workflow,
            snapshot.state,
            prompt_required_decisions=frozenset(),
        )
        if (
            external_authority.workflow_id != receipt.workflow_id
            or external_authority.workflow_revision != receipt.workflow_revision
            or external_authority.goal_fingerprint != receipt.goal_fingerprint
        ):
            raise AdaptiveControlAuthorityConflict(
                "adaptive external authority changed while verifying completion"
            )
        if not external_authority.complete:
            raise AdaptiveControlAuthorityInvalid(
                "adaptive completion requires verified external authority"
            )
        return AdaptiveCompletionAuthorityReadback(
            receipt=receipt,
            external_authority=external_authority,
        )

    def _read_current_snapshot(
        self,
    ) -> tuple[ProcessState, WorkflowRecord, AdaptiveControlSnapshot]:
        """Process revision과 exact adaptive snapshot을 한 read window에 고정합니다."""
        before_read = self._handle.inspect()
        try:
            snapshot = self._adaptive.read()
        except (AdaptiveControlStateMissing, SkillStateWorkflowNotFound) as error:
            raise AdaptiveControlAuthorityNotFound(str(error)) from error
        except SkillStateStoreError as error:
            raise AdaptiveControlAuthorityInvalid(str(error)) from error
        process_state = self._handle.inspect()
        if process_state.revision != before_read.revision:
            raise AdaptiveControlAuthorityConflict(
                "process state changed while reading current adaptive control state"
            )
        workflow = self._current_workflow(process_state.workflows, snapshot)
        return process_state, workflow, snapshot

    def validate_candidate(
        self,
        state: AdaptiveControlState,
        expected_workflow_revision: int,
    ) -> AdaptiveControlAuthorityVerification:
        """Mutation 전에 candidate의 external claims를 exact current authority로 검증합니다.

        USER claim은 current runtime prompt receipt와 exact preceding question을 검증하며
        source가 아직 없을 때만 명시적인 pending 결과로 허용합니다. Independent 또는
        same-context claim은 current consumed delegation과 content-addressed artifact를
        통과하지 못하면 persistence 전에 fail closed합니다.

        Args:
            state: Canonical codec가 복원하고 domain invariant가 검증한 candidate입니다.
            expected_workflow_revision: Caller가 읽은 exact workflow-local CAS revision입니다.

        Returns:
            Verified independent authority 또는 explicit user-pending 상태입니다.

        Raises:
            AdaptiveControlAuthorityConflict: Candidate revision이 current workflow와 다릅니다.
            AdaptiveControlAuthorityError: Candidate external authority를 증명할 수 없습니다.
        """
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise AdaptiveControlAuthorityInvalid(
                "expected adaptive workflow revision must be a non-negative integer"
            )
        process_state = self._handle.inspect()
        workflow = self._owned_active_workflow(process_state.workflows)
        if workflow.revision != expected_workflow_revision:
            raise AdaptiveControlAuthorityConflict(
                f"expected workflow revision {expected_workflow_revision}, got {workflow.revision}"
            )
        try:
            current_decisions = frozenset(
                item.reference for item in self._adaptive.read().state.user_decisions
            )
        except AdaptiveControlStateMissing:
            current_decisions = frozenset()
        candidate_decisions = frozenset(item.reference for item in state.user_decisions)
        return self._verify_state(
            process_state.revision,
            process_state.delegations,
            process_state.foreground_turns,
            workflow,
            state,
            prompt_required_decisions=candidate_decisions - current_decisions,
        )

    def _verify_state(
        self,
        process_revision: int,
        delegations: Mapping[DelegationId, DelegationRecord],
        foreground_turns: Mapping[ActorId, ForegroundTurnRecord],
        workflow: WorkflowRecord,
        state: AdaptiveControlState,
        *,
        prompt_required_decisions: frozenset[str],
    ) -> AdaptiveControlAuthorityVerification:
        turn = foreground_turns.get(workflow.owner_actor_id)
        user_prompt_receipt = None if turn is None else turn.user_prompt_receipt
        gap_pending = self._verify_gap_authority(
            state,
            workflow,
            user_prompt_receipt,
            prompt_required_decisions,
        )
        claims = self._claims(state, workflow)
        reports, pending = self._completion_reports(
            claims,
            state,
            workflow,
            user_prompt_receipt,
            prompt_required_decisions,
        )
        verified: list[str] = []
        for report in reports:
            delegation_id = report.lineage.delegation_id
            if delegation_id is None:
                raise AdaptiveControlAuthorityInvalid(
                    "independent report lineage has no delegation identity"
                )
            self._verify_independent_group(
                delegations,
                workflow,
                state,
                delegation_id,
                report,
            )
            verified.append(delegation_id)

        latest = self._handle.inspect()
        if latest.revision != process_revision:
            raise AdaptiveControlAuthorityConflict(
                "process state changed during adaptive authority verification"
            )

        pending_claims = tuple(sorted({*pending, *gap_pending}))
        if pending_claims:
            return AdaptiveControlAuthorityVerification(
                status=AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
                workflow_id=self._workflow_id,
                workflow_revision=workflow.revision,
                goal_fingerprint=state.contract.fingerprint,
                verified_delegation_ids=tuple(verified),
                pending_claims=pending_claims,
                reason="runtime-backed user authority or independent interpretation is unavailable",
                user_prompt_receipt=user_prompt_receipt,
            )
        return AdaptiveControlAuthorityVerification(
            status=AdaptiveControlAuthorityStatus.VERIFIED,
            workflow_id=self._workflow_id,
            workflow_revision=workflow.revision,
            goal_fingerprint=state.contract.fingerprint,
            verified_delegation_ids=tuple(verified),
            pending_claims=(),
            reason="all external authority claims are runtime verified",
            user_prompt_receipt=user_prompt_receipt,
        )

    def _verify_gap_authority(
        self,
        state: AdaptiveControlState,
        workflow: WorkflowRecord,
        user_prompt_receipt: ForegroundUserPromptReceipt | None,
        prompt_required_decisions: frozenset[str],
    ) -> tuple[str, ...]:
        """Resolved clarification gap을 actual authority source에 다시 결속합니다.

        USER fact와 deferral은 current runtime prompt와 preceding ASK_USER question에
        결속되며 source가 없을 때만 pending입니다. REPOSITORY fact는 current tracked file
        bytes와 worktree fingerprint를 직접 읽고, SAFE_ASSUMPTION은 external fact로
        가장하지 않은 채 bounded same-context invariants만 통과시킵니다.

        Args:
            state: Candidate 또는 persisted adaptive control state입니다.
            workflow: Current owner와 workflow revision을 제공하는 exact aggregate입니다.
            user_prompt_receipt: Exact owner turn에서 읽은 current runtime user provenance입니다.

        Returns:
            Runtime user authority가 없어 pending인 gap claim identity입니다.

        Raises:
            AdaptiveControlAuthorityInvalid: Gap resolution, lineage 또는 source readback이
                current authority와 다르면 발생합니다.
        """
        pending: list[str] = []
        for gap in state.inventory.gaps:
            if gap.deferral is not None:
                self._validate_user_gap_lineage(
                    gap,
                    gap.deferral.lineage,
                    state.contract,
                    workflow,
                )
                decision = self._user_decision(
                    state,
                    gap.deferral.decision_reference,
                    UserDecisionTarget.GAP,
                    gap.gap_id,
                    UserDecisionDisposition.DEFERRED,
                )
                if decision is None:
                    pending.append(f"user-decision:gap:{gap.gap_id}")
                    continue
                if (
                    decision.reference in prompt_required_decisions
                    and not self._verify_user_decision_prompt(
                        gap.deferral.lineage,
                        decision,
                        f"gap:{gap.gap_id}",
                        ControlAction.ASK_USER,
                        workflow,
                        user_prompt_receipt,
                    )
                ):
                    pending.append(f"user-decision:gap:{gap.gap_id}")
                continue
            if gap.resolution is GapResolution.OPEN:
                continue
            lineage = gap.resolution_lineage
            if lineage is None:
                raise AdaptiveControlAuthorityInvalid(
                    f"gap {gap.gap_id} resolution has no authority lineage"
                )
            if gap.authority is GapAuthority.USER:
                if gap.resolution not in {
                    GapResolution.USER_FACT,
                    GapResolution.BLOCKER,
                }:
                    raise AdaptiveControlAuthorityInvalid(
                        f"gap {gap.gap_id} user authority has an invalid resolution"
                    )
                self._validate_user_gap_lineage(
                    gap,
                    lineage,
                    state.contract,
                    workflow,
                )
                expected_disposition = (
                    UserDecisionDisposition.FACT
                    if gap.resolution is GapResolution.USER_FACT
                    else UserDecisionDisposition.BLOCKED
                )
                decision = self._user_decision(
                    state,
                    gap.evidence_reference,
                    UserDecisionTarget.GAP,
                    gap.gap_id,
                    expected_disposition,
                )
                if decision is None:
                    pending.append(f"user-decision:gap:{gap.gap_id}")
                    continue
                if (
                    decision.reference in prompt_required_decisions
                    and not self._verify_user_decision_prompt(
                        lineage,
                        decision,
                        f"gap:{gap.gap_id}",
                        ControlAction.ASK_USER,
                        workflow,
                        user_prompt_receipt,
                    )
                ):
                    pending.append(f"user-decision:gap:{gap.gap_id}")
                continue
            if gap.authority is GapAuthority.REPOSITORY:
                self._verify_repository_gap(gap, lineage, state, workflow)
                continue
            self._verify_safe_assumption_gap(gap, lineage, state, workflow)
        return tuple(pending)

    def _user_decision(
        self,
        state: AdaptiveControlState,
        reference: object,
        target_kind: UserDecisionTarget,
        target_id: str,
        disposition: UserDecisionDisposition,
    ) -> UserDecision | None:
        """Exact reference가 지목하는 typed decision을 찾고 expected effect를 검증합니다."""
        if not isinstance(reference, str) or not reference.startswith("user-decision:"):
            return None
        decision = next(
            (item for item in state.user_decisions if item.reference == reference),
            None,
        )
        if decision is None:
            raise AdaptiveControlAuthorityInvalid(
                f"{target_kind.value}:{target_id} references an unknown USER decision"
            )
        claim = decision.claim
        if (
            claim.target_kind is not target_kind
            or claim.target_id != target_id
            or claim.disposition is not disposition
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{target_kind.value}:{target_id} USER decision effect does not match"
            )
        return decision

    def _validate_user_gap_lineage(
        self,
        gap: ClarificationGap,
        lineage: AuthorityReceipt,
        contract: GoalContract,
        workflow: WorkflowRecord,
    ) -> None:
        if lineage.authority is not EvidenceAuthority.USER:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} user claim requires USER lineage"
            )
        if not lineage.is_current(contract.intent_revision, contract.source_revision):
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} user lineage revision is stale"
            )
        if lineage.subject_id != str(workflow.owner_actor_id):
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} user lineage subject is not the workflow owner"
            )
        if lineage.issuer_id != "user":
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} user lineage issuer is not user"
            )

    def _verify_user_prompt_claim(
        self,
        lineage: AuthorityReceipt,
        claim_id: str,
        action: ControlAction,
        contract: GoalContract,
        workflow: WorkflowRecord,
        receipt: ForegroundUserPromptReceipt | None,
        *,
        reference: object,
    ) -> bool:
        """USER lineage를 current runtime prompt와 preceding adaptive question에 대조합니다.

        Args:
            lineage: Candidate claim이 제시한 USER authority receipt입니다.
            claim_id: Gap 또는 criterion의 exact canonical identity입니다.
            action: Prompt 직전 요구됐던 ASK_USER 또는 AWAIT_USER action입니다.
            contract: Current workflow가 소유한 immutable goal contract입니다.
            workflow: Claim subject와 workflow identity를 제공하는 aggregate입니다.
            receipt: Exact foreground actor의 latest runtime user prompt receipt입니다.
            reference: Evidence surface가 제시한 exact user-prompt reference입니다.

        Returns:
            아직 runtime prompt source가 없으면 False이며 exact source가 일치하면 True입니다.

        Raises:
            AdaptiveControlAuthorityInvalid: Runtime receipt가 존재하지만 identity, source,
                question, claim 또는 digest가 current contract와 다르면 발생합니다.
        """
        if lineage.authority is not EvidenceAuthority.USER:
            raise AdaptiveControlAuthorityInvalid(f"{claim_id} requires USER lineage")
        if (
            lineage.issuer_id != "user"
            or lineage.subject_id != str(workflow.owner_actor_id)
            or not lineage.is_current(contract.intent_revision, contract.source_revision)
        ):
            raise AdaptiveControlAuthorityInvalid(f"{claim_id} user lineage is stale or foreign")
        if receipt is None:
            return False
        context = receipt.authority_context
        if context is None:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} current prompt did not answer an adaptive question"
            )
        expected_criteria = tuple(sorted(item.criterion_id for item in contract.criteria))
        if (
            context.workflow_id != self._workflow_id
            or context.goal_fingerprint != contract.fingerprint
            or context.intent_revision != contract.intent_revision
            or context.source_revision != contract.source_revision
            or context.criterion_ids != expected_criteria
            or context.control_action != action.value
            or claim_id not in context.claim_ids
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} current prompt belongs to another adaptive question"
            )
        if (
            lineage.receipt_digest != receipt.prompt_digest
            or lineage.delegation_id != receipt.authority_reference
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} user prompt digest or generation is stale"
            )
        if reference is not None and reference != receipt.authority_reference:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} evidence reference does not identify the current user prompt"
            )
        return True

    def _verify_user_decision_prompt(
        self,
        lineage: AuthorityReceipt | None,
        decision: UserDecision,
        claim_id: str,
        action: ControlAction,
        workflow: WorkflowRecord,
        receipt: ForegroundUserPromptReceipt | None,
    ) -> bool:
        """Typed decision을 exact question/response provenance에 결속합니다.

        Natural-language disposition은 여기서 다시 해석하지 않습니다. Direct-child
        independent evaluator가 report에 서명한 `UserDecisionClaim`이 semantic oracle이며,
        이 함수는 raw-free digest/revision/identity만 검증합니다.
        """
        claim = decision.claim
        if claim.workflow_id != str(self._workflow_id):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} USER decision belongs to another workflow"
            )
        if decision.interpretation_lineage.subject_id != str(workflow.owner_actor_id):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} USER decision evaluator subject is not the workflow owner"
            )
        if lineage is not None and (
            lineage.authority is not EvidenceAuthority.USER
            or lineage.issuer_id != "user"
            or lineage.subject_id != str(workflow.owner_actor_id)
            or lineage.intent_revision != claim.result_intent_revision
            or lineage.source_revision != claim.result_source_revision
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} USER effect lineage is stale or foreign"
            )
        if claim.provenance is UserDecisionProvenance.NATIVE_PROMPT:
            self._verify_native_decision_prompt(claim, lineage, workflow, receipt)
            return True
        if receipt is None:
            return False
        context = receipt.authority_context
        if context is None:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} current prompt did not answer an adaptive question"
            )
        if (
            context.workflow_id != self._workflow_id
            or context.workflow_revision != claim.question_workflow_revision
            or context.goal_fingerprint != claim.source_goal_fingerprint
            or context.intent_revision != claim.source_intent_revision
            or context.source_revision != claim.source_revision
            or context.control_action != action.value
            or claim_id not in context.claim_ids
            or context.question_digest != claim.question_digest
            or context.question_generation != claim.question_generation
            or context.question_turn_revision != claim.question_turn_revision
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} USER decision question provenance does not match"
            )
        if (
            receipt.prompt_digest != claim.prompt_digest
            or receipt.authority_reference != claim.prompt_reference
            or receipt.generation != claim.prompt_generation
            or receipt.turn_revision != claim.prompt_turn_revision
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} USER decision prompt provenance does not match"
            )
        if lineage is not None and (
            lineage.receipt_digest != receipt.prompt_digest
            or lineage.delegation_id != receipt.authority_reference
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim_id} USER effect does not reference the decision prompt"
            )
        return True

    def _verify_native_decision_prompt(
        self,
        claim,
        lineage,
        workflow,
        current_receipt,
    ) -> None:
        """Verify prompt authenticity while leaving semantic effect to its evaluator."""
        if lineage is not None and (
            lineage.receipt_digest != claim.prompt_digest
            or lineage.delegation_id != claim.prompt_reference
        ):
            raise AdaptiveControlAuthorityInvalid(
                "native USER effect does not reference its decision prompt")

        native = None
        if (
            current_receipt is not None
            and current_receipt.authority_reference == claim.prompt_reference
        ):
            native = current_receipt.to_payload()
        else:
            from scripts.agent_harness.runtime_database import RuntimeDatabase
            with RuntimeDatabase(
                self._handle._repository_control_root()
            ).transaction() as tx:
                record = tx.get(
                    f"prompt:{self._handle.session_id}",
                    claim.prompt_reference,
                )
            if record is not None:
                try:
                    stored = json.loads(record.payload)
                except (json.JSONDecodeError, UnicodeError) as error:
                    raise AdaptiveControlAuthorityInvalid(
                        "historical native prompt receipt is corrupt") from error
                if stored.get("actor_id") != str(workflow.owner_actor_id):
                    raise AdaptiveControlAuthorityInvalid(
                        "historical native prompt belongs to another actor")
                native = stored

        if native is None:
            if claim.prompt_generation is not None or claim.prompt_turn_revision is not None:
                raise AdaptiveControlAuthorityInvalid(
                    "missing kernel prompt cannot carry kernel turn provenance")
            try:
                from neurath.runtime.user_choices import verify_registered_prompt
                verify_registered_prompt(
                    self._handle._repository_control_root(),
                    self._handle.session_id,
                    claim.prompt_reference,
                    claim.prompt_digest,
                )
            except (ValueError, OSError) as error:
                raise AdaptiveControlAuthorityInvalid(str(error)) from error
            return

        if native.get("authority_context") is not None:
            raise AdaptiveControlAuthorityInvalid(
                "question-bound prompt must use adaptive-question provenance")
        if (
            native.get("authority_reference") != claim.prompt_reference
            or native.get("prompt_digest") != claim.prompt_digest
            or native.get("generation") != claim.prompt_generation
            or native.get("turn_revision") != claim.prompt_turn_revision
        ):
            raise AdaptiveControlAuthorityInvalid(
                "native USER decision prompt provenance does not match")

    def _verify_repository_gap(
        self,
        gap: ClarificationGap,
        lineage: AuthorityReceipt,
        state: AdaptiveControlState,
        workflow: WorkflowRecord,
    ) -> None:
        if gap.resolution not in {
            GapResolution.REPOSITORY_FACT,
            GapResolution.BLOCKER,
        }:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} repository authority has an invalid resolution"
            )
        if lineage.authority is not EvidenceAuthority.PRIMARY_SOURCE:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} repository fact requires PRIMARY_SOURCE lineage"
            )
        if (
            lineage.intent_revision != state.inventory.intent_revision
            or lineage.source_revision != state.inventory.source_revision
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} repository lineage revision is stale"
            )
        if lineage.issuer_id != "repository" or lineage.subject_id != str(workflow.owner_actor_id):
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} repository lineage provenance is invalid"
            )
        reference = gap.evidence_reference
        if reference is None:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} repository fact has no source reference"
            )
        try:
            readback = RepositoryWorktreeReadback(
                self._handle._repository_control_root()
            ).read_tracked_file(reference)
        except RepositoryReadbackError as error:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} primary-source readback failed: {error}"
            ) from error
        if readback.worktree_fingerprint != state.inventory.source_revision:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} primary-source readback worktree is stale"
            )
        if readback.content_digest != lineage.receipt_digest:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} primary-source readback content digest mismatch"
            )

    def _verify_safe_assumption_gap(
        self,
        gap: ClarificationGap,
        lineage: AuthorityReceipt,
        state: AdaptiveControlState,
        workflow: WorkflowRecord,
    ) -> None:
        if (
            gap.authority is not GapAuthority.SAFE_ASSUMPTION
            or gap.resolution is not GapResolution.SAFE_ASSUMPTION
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} has an unsupported authority resolution"
            )
        if not gap.reversible or not gap.scope_local or gap.blocking:
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} safe assumption must be reversible, scope-local, and non-blocking"
            )
        owner = str(workflow.owner_actor_id)
        if (
            lineage.authority is not EvidenceAuthority.SAME_CONTEXT
            or lineage.issuer_id != owner
            or lineage.subject_id != owner
            or not lineage.is_current(
                state.inventory.intent_revision,
                state.inventory.source_revision,
            )
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"gap {gap.gap_id} safe assumption lineage is not current same-context authority"
            )

    def _current_workflow(
        self,
        workflows: Mapping[WorkflowId, WorkflowRecord],
        snapshot: AdaptiveControlSnapshot,
    ) -> WorkflowRecord:
        if snapshot.workflow_id != self._workflow_id:
            raise AdaptiveControlAuthorityInvalid("adaptive snapshot belongs to another workflow")
        workflow = self._owned_active_workflow(workflows)
        if snapshot.workflow_revision != workflow.revision:
            raise AdaptiveControlAuthorityInvalid(
                "adaptive snapshot workflow revision is not current"
            )
        return workflow

    def _owned_active_workflow(
        self,
        workflows: Mapping[WorkflowId, WorkflowRecord],
    ) -> WorkflowRecord:
        workflow = workflows.get(self._workflow_id)
        if workflow is None:
            raise AdaptiveControlAuthorityNotFound(
                f"adaptive workflow is missing: {self._workflow_id}"
            )
        if workflow.owner_actor_id != self._handle.actor_id:
            raise AdaptiveControlAuthorityInvalid(
                "adaptive workflow owner does not match current actor"
            )
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise AdaptiveControlAuthorityInvalid(
                f"adaptive workflow is terminal: {self._workflow_id}"
            )
        return workflow

    def _claims(
        self,
        state: AdaptiveControlState,
        workflow: WorkflowRecord,
    ) -> tuple[_AuthorityClaim, ...]:
        contract = state.contract
        all_criterion_claims = tuple(self._criterion_claim(item) for item in state.evidence)
        effective_claims = tuple(
            self._criterion_claim(item)
            for item in effective_criterion_evidence(
                state.evidence,
                goal_fingerprint=contract.fingerprint,
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
            )
        )
        coverage = state.coverage
        coverage_claims: tuple[_AuthorityClaim, ...] = ()
        if coverage is not None:
            coverage_claims = (self._coverage_claim(coverage),)
        decision_claims = tuple(self._user_decision_claim(item) for item in state.user_decisions)
        for claim in (*all_criterion_claims, *coverage_claims, *decision_claims):
            self._validate_claim_lineage(claim, contract, workflow)
        return (*effective_claims, *coverage_claims, *decision_claims)

    def _validate_claim_lineage(
        self,
        claim: _AuthorityClaim,
        contract: GoalContract,
        workflow: WorkflowRecord,
    ) -> None:
        if claim.lineage.authority is not claim.authority:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} authority does not match its lineage"
            )
        goal_field = (
            "result_goal_fingerprint"
            if claim.payload.get("claim_type") == "user-decision"
            else "goal_fingerprint"
        )
        if claim.payload.get(goal_field) != contract.fingerprint:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} belongs to another goal fingerprint"
            )
        if not claim.lineage.is_current(
            contract.intent_revision,
            contract.source_revision,
        ):
            raise AdaptiveControlAuthorityInvalid(f"{claim.claim_id} lineage revision is stale")
        if claim.authority in {
            EvidenceAuthority.USER,
        }:
            return
        if claim.authority is EvidenceAuthority.EXECUTABLE:
            if (
                claim.lineage.issuer_id != "harness:adaptive-execution"
                or claim.lineage.subject_id != str(workflow.owner_actor_id)
            ):
                raise AdaptiveControlAuthorityInvalid(
                    f"{claim.claim_id} executable evidence lineage is not harness-owned"
                )
            return
        if claim.lineage.subject_id != str(workflow.owner_actor_id):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} lineage subject is not the workflow owner"
            )
        if claim.authority is EvidenceAuthority.PRIMARY_SOURCE:
            self._verify_primary_source_claim(claim, contract)

    def _verify_primary_source_claim(
        self,
        claim: _AuthorityClaim,
        contract: GoalContract,
    ) -> None:
        if claim.lineage.issuer_id != "repository":
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} primary-source issuer is not repository"
            )
        reference = claim.payload.get("reference")
        if not isinstance(reference, str):
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} primary-source reference is invalid"
            )
        try:
            readback = RepositoryWorktreeReadback(
                self._handle._repository_control_root()
            ).read_tracked_file(reference)
        except RepositoryReadbackError as error:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} primary-source readback failed: {error}"
            ) from error
        if readback.worktree_fingerprint != contract.source_revision:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} primary-source readback worktree is stale"
            )
        if readback.content_digest != claim.lineage.receipt_digest:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} primary-source readback content digest mismatch"
            )

    def _completion_reports(
        self,
        claims: tuple[_AuthorityClaim, ...],
        state: AdaptiveControlState,
        workflow: WorkflowRecord,
        user_prompt_receipt: ForegroundUserPromptReceipt | None,
        prompt_required_decisions: frozenset[str],
    ) -> tuple[tuple[_IndependentCompletionReport, ...], tuple[str, ...]]:
        """Completion report와 independent USER semantic-oracle report를 구성합니다.

        Static harness는 response 문장을 해석하지 않습니다. 새 decision의 exact prompt
        provenance만 확인하고, normalized disposition은 direct-child evaluator가 서명한
        `user-decision` claim에서 가져옵니다. 과거 append-only decision은 기존 report
        lineage로 재검증하되 latest raw prompt를 다시 요구하지 않습니다.
        """
        contract = state.contract
        execution_status = state.execution_status
        coverage = next((claim for claim in claims if claim.claim_id == "goal-coverage"), None)
        decision_claims = tuple(
            claim for claim in claims if claim.payload.get("claim_type") == "user-decision"
        )
        ordinary_claims = tuple(claim for claim in claims if claim not in decision_claims)
        user_claims = tuple(
            claim for claim in ordinary_claims if claim.authority is EvidenceAuthority.USER
        )
        decisions = {item.reference: item for item in state.user_decisions}
        report_claims: dict[AuthorityReceipt, list[_AuthorityClaim]] = {}
        pending: list[str] = []

        def append_report_claim(lineage: AuthorityReceipt, claim: _AuthorityClaim) -> None:
            """같은 evaluator lineage가 증명할 claim을 중복 없이 묶습니다.

            Args:
                lineage: Claim 집합을 서명할 independent evaluator receipt입니다.
                claim: 해당 evaluator report에 포함할 exact authority claim입니다.
            """
            group = report_claims.setdefault(lineage, [])
            if claim not in group:
                group.append(claim)

        for claim in decision_claims:
            decision = decisions.get(claim.claim_id)
            if decision is None:  # pragma: no cover - domain construction invariant
                raise AdaptiveControlAuthorityInvalid(
                    f"{claim.claim_id} USER decision claim has no typed state"
                )
            decision_is_current_report = decision.reference in prompt_required_decisions or (
                coverage is not None and decision.interpretation_lineage == coverage.lineage
            )
            if not decision_is_current_report:
                continue
            append_report_claim(decision.interpretation_lineage, claim)
            target_claim_id = (
                f"gap:{decision.claim.target_id}"
                if decision.claim.target_kind is UserDecisionTarget.GAP
                else f"criterion:{decision.claim.target_id}"
            )
            action = (
                ControlAction.ASK_USER
                if decision.claim.target_kind is UserDecisionTarget.GAP
                else ControlAction.AWAIT_USER
            )
            if (
                decision.reference in prompt_required_decisions
                and not self._verify_user_decision_prompt(
                    None,
                    decision,
                    target_claim_id,
                    action,
                    workflow,
                    user_prompt_receipt,
                )
            ):
                pending.append(decision.reference)

        status_disposition = {
            EvidenceStatus.PASS: UserDecisionDisposition.ACCEPTED,
            EvidenceStatus.FAIL: UserDecisionDisposition.REJECTED,
            EvidenceStatus.NOT_EVALUATED: UserDecisionDisposition.DEFERRED,
        }
        legacy_user_claims: list[_AuthorityClaim] = []
        for claim in user_claims:
            if claim.claim_id == "goal-coverage":
                raise AdaptiveControlAuthorityInvalid(
                    "goal coverage requires independent evaluator authority"
                )
            if claim.payload.get("kind") != EvidenceKind.USER_ACCEPTANCE.value:
                raise AdaptiveControlAuthorityInvalid(
                    f"{claim.claim_id} USER authority is not a user-acceptance criterion"
                )
            criterion_id = claim.payload.get("criterion_id")
            status = claim.payload.get("status")
            reference = claim.payload.get("reference")
            if not isinstance(criterion_id, str) or not isinstance(status, str):
                raise AdaptiveControlAuthorityInvalid(
                    f"{claim.claim_id} USER acceptance payload is invalid"
                )
            try:
                expected_disposition = status_disposition[EvidenceStatus(status)]
            except (KeyError, ValueError) as error:
                raise AdaptiveControlAuthorityInvalid(
                    f"{claim.claim_id} USER acceptance status has no decision disposition"
                ) from error
            decision = self._user_decision(
                state,
                reference,
                UserDecisionTarget.CRITERION,
                criterion_id,
                expected_disposition,
            )
            if decision is None:
                pending.append(f"user-decision:criterion:{criterion_id}")
                legacy_user_claims.append(claim)
                continue
            if decision.reference in prompt_required_decisions or (
                coverage is not None and decision.interpretation_lineage == coverage.lineage
            ):
                append_report_claim(decision.interpretation_lineage, claim)
            elif coverage is not None:
                append_report_claim(coverage.lineage, claim)
            if (
                decision.reference in prompt_required_decisions
                and not self._verify_user_decision_prompt(
                    claim.lineage,
                    decision,
                    claim.claim_id,
                    ControlAction.AWAIT_USER,
                    workflow,
                    user_prompt_receipt,
                )
            ):
                pending.append(decision.reference)

        same_context = tuple(
            claim.claim_id
            for claim in ordinary_claims
            if claim.authority is EvidenceAuthority.SAME_CONTEXT
        )
        if same_context:
            raise AdaptiveControlAuthorityInvalid(
                f"{same_context[0]} same-context authority cannot complete a goal"
            )

        non_user_claims = tuple(
            claim for claim in ordinary_claims if claim.authority is not EvidenceAuthority.USER
        )
        if coverage is None:
            if non_user_claims:
                raise AdaptiveControlAuthorityInvalid(
                    "non-user criterion evidence requires independent goal coverage"
                )
            if user_claims:
                pending.append("goal-coverage")
            if execution_status is ExecutionStatus.COMPLETED:
                pending.append("execution-completion")
        else:
            if coverage.authority is not EvidenceAuthority.INDEPENDENT_EVALUATOR:
                raise AdaptiveControlAuthorityInvalid(
                    "goal coverage requires independent evaluator authority"
                )
            if coverage.lineage.delegation_id is None:
                raise AdaptiveControlAuthorityInvalid(
                    "goal-coverage independent lineage has no delegation identity"
                )
            for claim in non_user_claims:
                if (
                    claim.authority is EvidenceAuthority.INDEPENDENT_EVALUATOR
                    and claim.lineage != coverage.lineage
                ):
                    raise AdaptiveControlAuthorityConflict(
                        "independent criterion and coverage must share one exact report lineage"
                    )
                append_report_claim(coverage.lineage, claim)
            for claim in legacy_user_claims:
                append_report_claim(coverage.lineage, claim)
            if execution_status is ExecutionStatus.COMPLETED:
                append_report_claim(
                    coverage.lineage,
                    self._execution_completion_claim(contract, coverage.lineage),
                )

        reports = tuple(
            _IndependentCompletionReport(lineage=lineage, claims=tuple(group))
            for lineage, group in sorted(
                report_claims.items(),
                key=lambda item: item[0].receipt_digest,
            )
        )
        if len(reports) > 1:
            raise AdaptiveControlAuthorityConflict(
                "one adaptive candidate must use one exact independent report lineage"
            )
        return reports, tuple(pending)

    def _verify_independent_group(
        self,
        delegations: Mapping[DelegationId, DelegationRecord],
        workflow: WorkflowRecord,
        state: AdaptiveControlState,
        delegation_id: str,
        group: _IndependentCompletionReport,
    ) -> None:
        delegation = delegations.get(DelegationId(delegation_id))
        if delegation is None:
            raise AdaptiveControlAuthorityNotFound(
                f"independent delegation is missing: {delegation_id}"
            )
        if delegation.status is not DelegationStatus.CONSUMED:
            raise AdaptiveControlAuthorityConflict(
                f"independent delegation must be consumed: {delegation_id}"
            )
        if delegation.topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD:
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation requires persisted DIRECT_CHILD policy: {delegation_id}"
            )
        lineage = group.lineage
        if delegation.owner_actor_id != workflow.owner_actor_id:
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation owner mismatch: {delegation_id}"
            )
        if str(delegation.target_actor_id) != lineage.issuer_id:
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation target mismatch: {delegation_id}"
            )
        try:
            candidate_ref = self._candidates.verify_prepared(
                delegation.assignment,
                state,
            )
        except AdaptiveEvaluationCandidateConflict as error:
            raise AdaptiveControlAuthorityConflict(str(error)) from error
        except AdaptiveEvaluationCandidateError as error:
            raise AdaptiveControlAuthorityInvalid(str(error)) from error

        assignment = self._assignment(delegation)
        workflow_revision = assignment.get("workflow_revision")
        trajectory_digest = assignment.get("trajectory_digest")
        if (
            not isinstance(workflow_revision, int)
            or isinstance(workflow_revision, bool)
            or workflow_revision < 0
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation workflow revision is invalid: {delegation_id}"
            )
        if not isinstance(trajectory_digest, str):
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation trajectory digest is invalid: {delegation_id}"
            )
        for claim in group.claims:
            if (
                claim.payload.get("claim_type") == "user-decision"
                and claim.payload.get("provenance")
                == UserDecisionProvenance.NATIVE_PROMPT.value
                and claim.payload.get("source_workflow_revision") != workflow_revision
            ):
                raise AdaptiveControlAuthorityInvalid(
                    "native USER decision was interpreted from another workflow revision")
        execution_receipts: AdaptiveExecutionReceiptStore | None = None
        for claim in group.claims:
            if claim.authority is not EvidenceAuthority.EXECUTABLE:
                continue
            if execution_receipts is None:
                execution_receipts = AdaptiveExecutionReceiptStore(
                    self._handle,
                    self._workflow_id,
                )
            try:
                execution_receipts.verify(
                    self._criterion_evidence(claim),
                    state.contract,
                    expected_workflow_revision=workflow_revision,
                )
            except AdaptiveExecutionReceiptError as error:
                raise AdaptiveControlAuthorityInvalid(str(error)) from error

        result = delegation.result
        expected_ref = f"sha256:{lineage.receipt_digest}"
        if result.outcome_ref != expected_ref:
            raise AdaptiveControlAuthorityInvalid(
                f"independent lineage digest mismatch: {delegation_id}"
            )
        try:
            artifact = self._artifacts.read_json(result.outcome_ref)
        except ArtifactStoreError as error:
            raise AdaptiveControlAuthorityInvalid(str(error)) from error
        expected_report = self._expected_report(
            state.contract,
            group.claims,
            trajectory_digest,
        )
        expected_artifact: dict[str, object] = {
            "delegation_id": delegation_id,
            "report": expected_report,
            "schema": self._ARTIFACT_SCHEMA,
            "target_agent_id": lineage.issuer_id,
        }
        if self._canonical_json(
            artifact,
            "independent delegation artifact",
        ) != self._canonical_json(
            expected_artifact,
            "expected independent delegation artifact",
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation artifact mismatch: {delegation_id}"
            )
        if (
            result.verdict != "pass"
            or result.summary != self._result_summary(candidate_ref, trajectory_digest)
            or result.blocking_findings
        ):
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation typed result is not blocker-free: {delegation_id}"
            )

    def _result_summary(self, candidate_ref: str, trajectory_digest: str) -> str:
        """Typed result를 report digest와 독립적인 exact candidate identity에 결속합니다."""
        return self._canonical_json(
            {
                "candidate_ref": candidate_ref,
                "summary": self._REPORT_SUMMARY,
                "trajectory_digest": trajectory_digest,
            },
            "independent delegation result summary",
        )

    def _assignment(self, delegation: DelegationRecord) -> dict[str, object]:
        try:
            decoded: object = json.loads(
                delegation.assignment,
                object_pairs_hook=self._unique_object,
            )
        except json.JSONDecodeError as error:
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation assignment is not JSON: {delegation.id}"
            ) from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise AdaptiveControlAuthorityInvalid(
                f"independent delegation assignment is not an object: {delegation.id}"
            )
        self._canonical_json(decoded, "independent delegation assignment")
        return {str(key): value for key, value in decoded.items()}

    def _unique_object(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded:
                raise AdaptiveControlAuthorityInvalid(
                    f"independent delegation assignment has duplicate key: {key}"
                )
            decoded[key] = value
        return decoded

    def _expected_report(
        self,
        contract: GoalContract,
        claims: tuple[_AuthorityClaim, ...],
        trajectory_digest: str,
    ) -> dict[str, object]:
        payloads = [dict(claim.payload) for claim in claims]
        payloads.sort(key=self._canonical_sort_key)
        return {
            "blocking_findings": [],
            "claims": payloads,
            "goal_fingerprint": contract.fingerprint,
            "intent_revision": contract.intent_revision,
            "kind": self._ASSIGNMENT_KIND,
            "source_revision": contract.source_revision,
            "summary": self._REPORT_SUMMARY,
            "trajectory_assessment": {
                "blocking_findings": [],
                "trajectory_digest": trajectory_digest,
                "verdict": "pass",
            },
            "verdict": "pass",
            "workflow_id": str(self._workflow_id),
        }

    def _criterion_claim(self, evidence: CriterionEvidence) -> _AuthorityClaim:
        return _AuthorityClaim(
            claim_id=f"criterion:{evidence.criterion_id}",
            authority=evidence.authority,
            lineage=evidence.lineage,
            payload={
                "authority": evidence.authority.value,
                "claim_type": "criterion-evidence",
                "criterion_id": evidence.criterion_id,
                "evaluation_revision": evidence.evaluation_revision,
                "goal_fingerprint": evidence.goal_fingerprint,
                "kind": evidence.kind.value,
                "reference": evidence.reference,
                "status": evidence.status.value,
            },
        )

    def _coverage_claim(self, coverage: GoalCoverage) -> _AuthorityClaim:
        return _AuthorityClaim(
            claim_id="goal-coverage",
            authority=coverage.authority,
            lineage=coverage.lineage,
            payload={
                "authority": coverage.authority.value,
                "claim_type": "goal-coverage",
                "criterion_ids": sorted(coverage.criterion_ids),
                "evaluation_revision": coverage.evaluation_revision,
                "goal_alignment": coverage.goal_alignment,
                "goal_fingerprint": coverage.goal_fingerprint,
                "reference": coverage.reference,
                "reward_hacking_risk": coverage.reward_hacking_risk,
                "semantic_drift": coverage.semantic_drift,
                "status": coverage.status.value,
                "uncertainty": coverage.uncertainty,
            },
        )

    def _user_decision_claim(self, decision: UserDecision) -> _AuthorityClaim:
        """Lineage cycle 없이 evaluator report에 들어갈 semantic decision claim을 만듭니다."""
        return _AuthorityClaim(
            claim_id=decision.reference,
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            lineage=decision.interpretation_lineage,
            payload={
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "user-decision",
                "decision_digest": decision.claim.decision_digest,
                **decision.claim.to_payload(),
            },
        )

    def _execution_completion_claim(
        self,
        contract: GoalContract,
        lineage: AuthorityReceipt,
    ) -> _AuthorityClaim:
        return _AuthorityClaim(
            claim_id="execution-completion",
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            lineage=lineage,
            payload={
                "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
                "claim_type": "execution-completion",
                "goal_fingerprint": contract.fingerprint,
                "status": ExecutionStatus.COMPLETED.value,
            },
        )

    def _criterion_evidence(self, claim: _AuthorityClaim) -> CriterionEvidence:
        payload = claim.payload
        try:
            goal_fingerprint = payload["goal_fingerprint"]
            criterion_id = payload["criterion_id"]
            kind = payload["kind"]
            status = payload["status"]
            reference = payload["reference"]
            evaluation_revision = payload["evaluation_revision"]
            if (
                not isinstance(goal_fingerprint, str)
                or not isinstance(criterion_id, str)
                or not isinstance(kind, str)
                or not isinstance(status, str)
                or not isinstance(reference, str)
                or not isinstance(evaluation_revision, int)
                or isinstance(evaluation_revision, bool)
            ):
                raise TypeError("executable claim fields have invalid types")
            return CriterionEvidence(
                goal_fingerprint=goal_fingerprint,
                criterion_id=criterion_id,
                kind=EvidenceKind(kind),
                authority=claim.authority,
                status=EvidenceStatus(status),
                reference=reference,
                lineage=claim.lineage,
                evaluation_revision=evaluation_revision,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AdaptiveControlAuthorityInvalid(
                f"{claim.claim_id} executable claim payload is invalid"
            ) from error

    def _canonical_sort_key(self, value: Mapping[str, object]) -> str:
        return self._canonical_json(value, "adaptive authority claim")

    def _canonical_json(self, value: Mapping[str, object], label: str) -> str:
        try:
            return json.dumps(
                dict(value),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise AdaptiveControlAuthorityInvalid(f"{label} must be JSON-compatible") from error
