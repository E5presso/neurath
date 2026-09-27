"""Immutable adaptive aggregate, domain invariants and derived decision receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import (
    Mapping,
)
from dataclasses import (
    dataclass,
)
from typing import (
    ClassVar,
)

from scripts.agent_harness.adaptive_control import (
    AmbiguityAssessment,
    ControlAction,
    ControlDecision,
    CriterionEvidence,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapAuthority,
    GapInventory,
    GapResolution,
    GoalAttainment,
    GoalContract,
    GoalCoverage,
    IterationObservation,
    ReflectionPolicy,
    UserDecision,
    UserDecisionDisposition,
    UserDecisionTarget,
    assess_ambiguity,
    assess_goal_attainment,
)
from scripts.agent_harness.efficiency_assessment import (
    EfficiencyAssessment,
)
from scripts.agent_harness.session_model import (
    WorkflowId,
)
from scripts.agent_harness.skill_state_contract import (
    SkillStateStoreError,
)


class AdaptiveControlStoreError(SkillStateStoreError):
    """Adaptive control persistence contract 위반의 base error입니다."""


class AdaptiveControlStateMissing(AdaptiveControlStoreError):
    """Exact workflow에 adaptive control snapshot이 없을 때 발생합니다."""


class InvalidAdaptiveControlState(AdaptiveControlStoreError):
    """Persisted adaptive control payload 또는 mutation 결과가 invalid할 때 발생합니다."""


class InvalidAdaptiveControlEvidence(AdaptiveControlStoreError):
    """Phase-runner receipt가 current snapshot과 일치하지 않을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class AdaptiveControlState:
    """한 goal fingerprint에 결속된 latest-only adaptive control state입니다."""

    contract: GoalContract
    """현재 intent, source와 completion criterion을 고정하는 goal 계약입니다."""

    inventory: GapInventory
    """Contract를 실행하기 전에 평가한 current clarification gap inventory입니다."""

    evidence: tuple[CriterionEvidence, ...]
    """각 criterion/evidence surface의 append-only evaluation history입니다."""

    coverage: GoalCoverage | None
    """Independent evaluator가 판정한 current goal 전체의 semantic coverage입니다."""

    execution_status: ExecutionStatus
    """Goal 실행의 incomplete, completed 또는 failed lifecycle 상태입니다."""

    observations: tuple[IterationObservation, ...]
    """Reflection이 정체와 회복을 판단하는 generation 순서의 관측 이력입니다."""

    user_decisions: tuple[UserDecision, ...] = ()
    """Raw 응답 없이 exact state effect에 소비되는 typed USER decision 이력입니다."""

    def __post_init__(self) -> None:
        """Cross-record identity와 observation 순서를 fail closed로 검증합니다.

        Raises:
            ValueError: Goal, gap, evidence, USER decision 또는 observation identity와 순서가
                서로 일치하지 않으면 발생합니다.
        """
        assess_ambiguity(self.inventory)
        if self.inventory.intent_revision != self.contract.intent_revision:
            raise ValueError("gap inventory and goal contract must share an intent revision")
        fingerprint = self.contract.fingerprint
        criteria = {item.criterion_id: item for item in self.contract.criteria}
        criterion_ids = frozenset(criteria)
        evidence_revisions: dict[tuple[str, EvidenceKind], int] = {}
        for receipt in self.evidence:
            if receipt.goal_fingerprint != fingerprint:
                raise ValueError("criterion evidence belongs to a different goal fingerprint")
            if receipt.criterion_id not in criterion_ids:
                raise ValueError("criterion evidence references an unknown criterion")
            if receipt.kind not in criteria[receipt.criterion_id].required_evidence:
                raise ValueError("criterion evidence uses an undeclared evidence kind")
            surface = (receipt.criterion_id, receipt.kind)
            previous_revision = evidence_revisions.get(surface)
            if previous_revision is None and receipt.evaluation_revision != 1:
                raise ValueError("evidence history must begin at evaluation revision one")
            if previous_revision is not None and receipt.evaluation_revision not in {
                previous_revision,
                previous_revision + 1,
            }:
                raise ValueError("evidence evaluation revisions must be monotonic and contiguous")
            evidence_revisions[surface] = receipt.evaluation_revision
        if self.coverage is not None:
            if self.coverage.goal_fingerprint != fingerprint:
                raise ValueError("goal coverage belongs to a different goal fingerprint")
            if not self.coverage.criterion_ids.issubset(criterion_ids):
                raise ValueError("goal coverage references an unknown criterion")
        _validate_user_decision_consumption(self)
        generations = tuple(item.generation for item in self.observations)
        if generations != tuple(range(1, len(generations) + 1)):
            raise ValueError("observation generations must be contiguous from one")
        for observation in self.observations:
            if observation.goal_fingerprint != fingerprint:
                raise ValueError("iteration observation belongs to a different goal fingerprint")
            if not set(observation.active_criteria).issubset(criterion_ids):
                raise ValueError("iteration observation references an unknown criterion")
        if self.observations:
            if self.observations[0].recovery_epoch != 0:
                raise ValueError("observation recovery epoch must begin at zero")
            if not self.observations[0].material_change:
                raise ValueError("first observation must record the initial material state")
        for previous, current in zip(self.observations, self.observations[1:], strict=False):
            if current.recovery_epoch not in {
                previous.recovery_epoch,
                previous.recovery_epoch + 1,
            }:
                raise ValueError("observation recovery epoch must stay or advance by one")
            changed = current.output_fingerprint != previous.output_fingerprint
            if current.material_change is not changed:
                raise ValueError("observation material_change must match its fingerprint delta")
            if current.recovery_epoch > previous.recovery_epoch and not changed:
                raise ValueError("new recovery epoch requires a material state change")

    @classmethod
    def empty(
        cls,
        contract: GoalContract,
        inventory: GapInventory,
    ) -> AdaptiveControlState:
        """새 goal용 authority가 비어 있는 incomplete snapshot을 반환합니다.

        Args:
            contract: 새 snapshot이 유일하게 증명할 current goal 계약입니다.
            inventory: 같은 intent/source revision에서 완전하게 평가한 gap inventory입니다.

        Returns:
            Evidence, coverage, observations, USER decision이 없는 initial state입니다.
        """
        return cls(
            contract=contract,
            inventory=inventory,
            evidence=(),
            coverage=None,
            execution_status=ExecutionStatus.INCOMPLETE,
            observations=(),
            user_decisions=(),
        )

    def to_payload(self) -> Mapping[str, object]:
        """State CLI가 사용할 canonical JSON-compatible payload를 반환합니다.

        Returns:
            Schema version을 포함한 deterministic adaptive state object입니다.
        """
        from scripts.agent_harness.adaptive_state_codec import _AdaptiveControlCodec

        return _AdaptiveControlCodec().encode(self)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> AdaptiveControlState:
        """Canonical payload를 invariant가 검증된 state로 복원합니다.

        Args:
            payload: Public schema version을 포함한 string-keyed state object입니다.

        Returns:
            모든 cross-record invariant를 통과한 immutable state입니다.

        Raises:
            InvalidAdaptiveControlState: Schema 또는 domain invariant가 invalid하면 발생합니다.
        """
        from scripts.agent_harness.adaptive_state_codec import _AdaptiveControlCodec

        return _AdaptiveControlCodec().decode(payload)


def _validate_user_decision_consumption(state: AdaptiveControlState) -> None:
    """Typed USER decisions가 current effect에 exact-once identity로 소비됐는지 검증합니다.

    v3 snapshot의 opaque USER reference는 migration을 위해 domain load를 허용합니다.
    다만 `user-decision:` namespace를 사용하는 v4 effect는 반드시 typed decision과
    일치해야 하며, 같은 goal의 decision은 consumer 없이 durable state에 남을 수 없습니다.
    """
    decisions: dict[str, UserDecision] = {}
    for decision in state.user_decisions:
        reference = decision.reference
        if reference in decisions:
            raise ValueError("USER decision identities must be unique")
        claim = decision.claim
        if (
            claim.result_goal_fingerprint != state.contract.fingerprint
            or claim.result_intent_revision != state.contract.intent_revision
            or claim.result_source_revision != state.contract.source_revision
        ):
            raise ValueError("USER decision result must match the current goal contract")
        decisions[reference] = decision

    consumed: set[str] = set()
    for gap in state.inventory.gaps:
        if gap.authority is not GapAuthority.USER:
            continue
        reference: str | None = None
        expected: UserDecisionDisposition | None = None
        if gap.deferral is not None and gap.deferral.decision_reference is not None:
            reference = gap.deferral.decision_reference
            expected = UserDecisionDisposition.DEFERRED
        elif gap.evidence_reference is not None and gap.evidence_reference.startswith(
            "user-decision:"
        ):
            reference = gap.evidence_reference
            expected = {
                GapResolution.USER_FACT: UserDecisionDisposition.FACT,
                GapResolution.BLOCKER: UserDecisionDisposition.BLOCKED,
            }.get(gap.resolution)
        if reference is None:
            continue
        decision = decisions.get(reference)
        if decision is None:
            raise ValueError("USER gap effect references an unknown USER decision")
        claim = decision.claim
        if (
            expected is None
            or claim.target_kind is not UserDecisionTarget.GAP
            or claim.target_id != gap.gap_id
            or claim.disposition is not expected
        ):
            raise ValueError("USER gap effect does not match its USER decision")
        consumed.add(reference)

    expected_status = {
        UserDecisionDisposition.ACCEPTED: EvidenceStatus.PASS,
        UserDecisionDisposition.REJECTED: EvidenceStatus.FAIL,
        UserDecisionDisposition.DEFERRED: EvidenceStatus.NOT_EVALUATED,
    }
    for receipt in state.evidence:
        if receipt.kind is not EvidenceKind.USER_ACCEPTANCE or not receipt.reference.startswith(
            "user-decision:"
        ):
            continue
        decision = decisions.get(receipt.reference)
        if decision is None:
            raise ValueError("USER acceptance references an unknown USER decision")
        claim = decision.claim
        if (
            claim.target_kind is not UserDecisionTarget.CRITERION
            or claim.target_id != receipt.criterion_id
            or expected_status.get(claim.disposition) is not receipt.status
        ):
            raise ValueError("USER acceptance does not match its USER decision")
        consumed.add(receipt.reference)

    for reference, decision in decisions.items():
        if reference in consumed:
            continue
        claim = decision.claim
        if claim.source_goal_fingerprint == claim.result_goal_fingerprint:
            raise ValueError("same-goal USER decision must be consumed by an exact effect")


@dataclass(frozen=True, slots=True)
class AdaptiveControlReceipt:
    """Current state에서 파생된 ambiguity, progress, reflection decision 증명입니다."""

    workflow_id: WorkflowId
    """Receipt가 재대조되어야 하는 exact workflow identity입니다."""

    workflow_revision: int
    """Receipt 계산에 사용한 workflow-local optimistic revision입니다."""

    goal_fingerprint: str
    """Attainment와 decision이 평가한 immutable goal contract identity입니다."""

    ambiguity: AmbiguityAssessment
    """Current gap inventory의 readiness와 다음 clarification action 판정입니다."""

    progress: float
    """Required criterion 중 current authority가 충족한 비율입니다."""

    attainment: GoalAttainment
    """모든 required criterion과 execution을 결합한 exact completion 판정입니다."""

    decision: ControlDecision
    """Ambiguity, attainment, observation history에서 파생된 다음 control action입니다."""

    _EVIDENCE_KIND: ClassVar[str] = "adaptive-control-decision"
    _EVIDENCE_SCHEMA_VERSION: ClassVar[int] = 1

    def __post_init__(self) -> None:
        """COMPLETE가 intent와 goal authority 없이 발행되지 않게 검증합니다.

        Raises:
            ValueError: Receipt identity와 attainment가 다르거나 COMPLETE/achieved 조합이
                current authority를 과장하면 발생합니다.
        """
        if self.goal_fingerprint != self.attainment.goal_fingerprint:
            raise ValueError("receipt goal fingerprint does not match attainment")
        if self.progress != self.attainment.progress:
            raise ValueError("receipt progress does not match attainment")
        if self.decision.action is ControlAction.COMPLETE and not (
            self.ambiguity.ready and self.attainment.achieved and self.decision.achieved
        ):
            raise ValueError("COMPLETE requires ready intent and achieved goal authority")
        if self.decision.achieved and self.decision.action is not ControlAction.COMPLETE:
            raise ValueError("achieved decision must use COMPLETE")

    @property
    def evidence_digest(self) -> str:
        """Exact decision body의 deterministic SHA-256 digest를 반환합니다.

        Returns:
            Phase evidence body를 content-address하는 lowercase hexadecimal digest입니다.
        """
        return self._digest_body(self._evidence_body())

    def to_evidence(self) -> Mapping[str, object]:
        """Phase runner가 current snapshot에 재대조할 canonical evidence object를 반환합니다.

        Returns:
            Workflow, goal, action과 canonical body content digest를 담은 JSON object입니다.
        """
        body = self._evidence_body()
        return {**body, "evidence_digest": self._digest_body(body)}

    def _evidence_body(self) -> dict[str, object]:
        return {
            "kind": self._EVIDENCE_KIND,
            "schema_version": self._EVIDENCE_SCHEMA_VERSION,
            "workflow_id": str(self.workflow_id),
            "workflow_revision": self.workflow_revision,
            "goal_fingerprint": self.goal_fingerprint,
            "action": self.decision.action.value,
            "achieved": self.decision.achieved,
            "ambiguity_ready": self.ambiguity.ready,
            "progress": self.progress,
            "reason": self.decision.reason,
        }

    @staticmethod
    def _digest_body(body: Mapping[str, object]) -> str:
        encoded = json.dumps(
            dict(body),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AdaptiveControlSnapshot:
    """Workflow CAS revision과 decoded adaptive state를 함께 고정합니다."""

    workflow_id: WorkflowId
    """Decoded state가 저장된 exact workflow aggregate identity입니다."""

    workflow_revision: int
    """Snapshot 이후 sibling mutation도 감지하는 workflow-local CAS 원본입니다."""

    state: AdaptiveControlState
    """Persisted payload의 schema와 cross-record invariant를 통과한 domain state입니다."""

    @property
    def latest_efficiency(self) -> EfficiencyAssessment | None:
        """Current generation의 store-admitted efficiency assessment를 반환합니다.

        Returns:
            Observation이 없거나 legacy generation이면 `None`, 아니면 연속 snapshot에서
            파생되어 persisted codec을 통과한 latest assessment입니다.
        """
        if not self.state.observations:
            return None
        return self.state.observations[-1].efficiency_assessment

    def receipt(self, policy: ReflectionPolicy | None = None) -> AdaptiveControlReceipt:
        """Snapshot 하나에서 side-effect 없이 현재 adaptive control receipt를 계산합니다.

        Args:
            policy: Observation history에 적용할 reflection 상한과 정체 기준입니다.

        Returns:
            같은 workflow revision에 결속된 ambiguity, attainment, decision receipt입니다.
        """
        ambiguity = assess_ambiguity(self.state.inventory)
        attainment = assess_goal_attainment(
            self.state.contract,
            self.state.evidence,
            self.state.coverage,
            self.state.execution_status,
        )
        decision = (policy or ReflectionPolicy()).decide(
            ambiguity,
            attainment,
            self.state.observations,
        )
        decision = _StoreAdmittedReflectionDecision().decide(
            attainment,
            self.state.observations,
            decision,
        )
        return AdaptiveControlReceipt(
            workflow_id=self.workflow_id,
            workflow_revision=self.workflow_revision,
            goal_fingerprint=self.state.contract.fingerprint,
            ambiguity=ambiguity,
            progress=attainment.progress,
            attainment=attainment,
            decision=decision,
        )


class _StoreAdmittedReflectionDecision:
    """Store-admitted current generation만 pure reflection decision에 반영합니다."""

    def decide(
        self,
        attainment: GoalAttainment,
        observations: tuple[IterationObservation, ...],
        fallback: ControlDecision,
    ) -> ControlDecision:
        """완료 전 current generation의 admitted goal delta를 reflection에 적용합니다.

        Args:
            attainment: Current adaptive snapshot에서 파생된 goal 판정입니다.
            observations: Store codec을 통과한 generation history입니다.
            fallback: Ambiguity, completion, root cause와 stagnation으로 계산한 기본 결정입니다.

        Returns:
            Current admission이 없거나 zero-progress면 같은 접근을 금지하고, 그 밖에는
            기존 deterministic decision을 보존합니다.
        """
        if attainment.achieved or not observations:
            return fallback
        if fallback.action is not ControlAction.CONTINUE:
            return fallback
        assessment = observations[-1].efficiency_assessment
        if assessment is None:
            return ControlDecision(
                ControlAction.CHANGE_APPROACH,
                False,
                "current generation lacks a store-admitted goal-resource readback",
            )
        if assessment.requires_approach_change:
            return ControlDecision(
                ControlAction.CHANGE_APPROACH,
                False,
                "latest generation made no verified goal-attainment progress",
            )
        return fallback
