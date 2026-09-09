"""Adaptive control의 latest snapshot을 exact workflow skill state에 보존합니다."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, TypeVar

from scripts.agent_harness.adaptive_control import (
    AmbiguityAssessment,
    AuthorityReceipt,
    ClarificationGap,
    ControlAction,
    ControlDecision,
    CriterionEvidence,
    CriterionSpec,
    EvidenceAuthority,
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
    OracleOwner,
    ReflectionPolicy,
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionProvenance,
    UserDecisionTarget,
    UserDeferral,
    adaptive_output_fingerprint,
    assess_ambiguity,
    assess_goal_attainment,
    effective_criterion_evidence,
)
from scripts.agent_harness.efficiency_assessment import (
    AuthoritativeResourceDelta,
    EfficiencyAssessment,
    EfficiencyAssessor,
    EfficiencyStatus,
    GoalAttainmentReadback,
    ResourceMetricDelta,
    ResourceTelemetryStatus,
    VerifiedGoalAttainmentDelta,
)
from scripts.agent_harness.material_action import MaterialActionBatch
from scripts.agent_harness.skill_state_contract import (
    SkillStateReservedMutation,
    SkillStateStoreError,
)

if TYPE_CHECKING:
    from scripts.agent_harness.session_kernel import WorkflowId
    from scripts.agent_harness.skill_state_store import SkillStateSnapshot, SkillStateStore

EnumValue = TypeVar("EnumValue", bound=StrEnum)


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


@dataclass(frozen=True, slots=True)
class _EfficiencyResourceContext:
    """Same-session material receipt를 adaptive generation authority에 결속합니다."""

    session_id: str
    actor_id: str
    workflow_id: str
    workflow_revision: int
    material_batch: MaterialActionBatch | None


class _EfficiencyAdmissionFactory:
    """연속 adaptive snapshot에서 goal delta를 만들고 missing telemetry를 보존합니다."""

    _AUTHORITY_SOURCE = "adaptive-control-store"
    _RESOURCE_BASIS = hashlib.sha256(
        b"adaptive-control-generation:material-phase-session-receipts:v1"
    ).hexdigest()

    def admit(
        self,
        previous: AdaptiveControlState | None,
        candidate: AdaptiveControlState,
        resource_context: _EfficiencyResourceContext,
    ) -> AdaptiveControlState:
        """새 observation 하나에만 store-derived efficiency assessment를 결속합니다.

        Args:
            previous: CAS가 읽은 exact pre-generation adaptive snapshot입니다.
            candidate: Caller가 제안한 post-generation adaptive snapshot입니다.
            resource_context: Same-session actor/workflow의 current material receipt readback입니다.

        Returns:
            첫 snapshot이면 admission을 만들지 않고, 기존 snapshot에 generation 하나가
            추가됐으면 caller 값을 거부한 뒤 derived assessment를 결속한 state입니다.

        Raises:
            InvalidAdaptiveControlState: Caller가 assessment를 주입하거나 observation 전이와
                admission generation이 맞지 않을 때 발생합니다.
        """
        if previous is None:
            if any(item.efficiency_assessment is not None for item in candidate.observations):
                raise InvalidAdaptiveControlState(
                    "fresh adaptive state cannot import an efficiency admission"
                )
            return candidate
        if len(candidate.observations) != len(previous.observations) + 1:
            return candidate
        latest = candidate.observations[-1]
        if latest.efficiency_assessment is not None:
            raise InvalidAdaptiveControlState(
                "caller-provided efficiency assessment is not store-admitted"
            )
        generation = latest.generation
        before = self._prior_readback(previous, generation)
        after = self._readback(candidate, generation)
        assessment = EfficiencyAssessor().assess(
            VerifiedGoalAttainmentDelta(before=before, after=after),
            self._resources(resource_context, candidate.contract.fingerprint, after),
        )
        admitted = replace(latest, efficiency_assessment=assessment)
        return replace(
            candidate,
            observations=(*candidate.observations[:-1], admitted),
        )

    def validate(self, state: AdaptiveControlState) -> None:
        """Persisted admission chain과 current adaptive readback의 exact 일치를 검증합니다.

        Args:
            state: Codec이 구조와 domain invariant를 복원한 candidate state입니다.

        Raises:
            InvalidAdaptiveControlState: Generation, assessment derivation, chain 또는 current
                readback이 persisted payload와 다를 때 발생합니다.
        """
        previous_after: GoalAttainmentReadback | None = None
        admission_started = False
        for observation in state.observations:
            assessment = observation.efficiency_assessment
            if assessment is None:
                if admission_started:
                    raise InvalidAdaptiveControlState(
                        "efficiency admission cannot disappear from a later generation"
                    )
                previous_after = None
                continue
            admission_started = True
            expected = EfficiencyAssessor().assess(
                assessment.goal_delta,
                assessment.resource_delta,
            )
            if assessment != expected:
                raise InvalidAdaptiveControlState(
                    "efficiency assessment must derive from its goal-resource delta"
                )
            if assessment.resource_delta.basis_fingerprint != self._RESOURCE_BASIS:
                raise InvalidAdaptiveControlState(
                    "efficiency resource telemetry uses an unknown basis"
                )
            mask = assessment.resource_delta.availability_mask
            if mask not in {
                (False, False, False, False, False),
                (False, True, False, False, True),
                (True, True, False, False, True),
            }:
                raise InvalidAdaptiveControlState(
                    "efficiency resource telemetry has an invalid admitted availability mask"
                )
            if assessment.goal_delta.after.evaluation_revision != observation.generation + 1:
                raise InvalidAdaptiveControlState(
                    "efficiency admission revision must match its generation"
                )
            if previous_after is not None and assessment.goal_delta.before != previous_after:
                raise InvalidAdaptiveControlState(
                    "efficiency admissions must form an exact consecutive readback chain"
                )
            previous_after = assessment.goal_delta.after
        if not state.observations:
            return
        latest = state.observations[-1]
        assessment = latest.efficiency_assessment
        if assessment is not None and assessment.goal_delta.after != self._readback(
            state,
            latest.generation,
        ):
            raise InvalidAdaptiveControlState(
                "latest efficiency admission must match the current adaptive snapshot"
            )

    def _prior_readback(
        self,
        previous: AdaptiveControlState,
        generation: int,
    ) -> GoalAttainmentReadback:
        if previous.observations:
            admission = previous.observations[-1].efficiency_assessment
            if admission is not None:
                return admission.goal_delta.after
        return self._readback(previous, generation - 1)

    def _readback(
        self,
        state: AdaptiveControlState,
        generation: int,
    ) -> GoalAttainmentReadback:
        coverage_units = self._coverage_units()
        execution_unit = "execution:completed"
        surfaces = tuple(
            sorted({
                execution_unit,
                *coverage_units,
                *(
                    f"{criterion.criterion_id}:{kind.value}"
                    for criterion in state.contract.criteria
                    for kind in criterion.required_evidence
                ),
            })
        )
        basis = self._digest({"goal": state.contract.fingerprint, "surfaces": surfaces})
        settled, failed, reopened = self._criterion_states(state)
        coverage_settled, coverage_failed, coverage_reopened = self._coverage_states(state)
        settled.update(coverage_settled)
        failed.update(coverage_failed)
        reopened.update(coverage_reopened)
        if state.execution_status is ExecutionStatus.COMPLETED:
            settled.add(execution_unit)
        elif state.execution_status is ExecutionStatus.FAILED:
            failed.add(execution_unit)
        blockers = frozenset(
            gap.gap_id
            for gap in state.inventory.gaps
            if gap.blocking and not gap.is_resolved_for(state.inventory)
        )
        revision = generation + 1
        identity: dict[str, object] = {
            "authority_source_id": self._AUTHORITY_SOURCE,
            "evaluation_revision": revision,
            "evidence_basis_fingerprint": basis,
            "failed_evidence_units": tuple(sorted(failed)),
            "goal_fingerprint": state.contract.fingerprint,
            "open_blocker_ids": tuple(sorted(blockers)),
            "reopened_evidence_units": tuple(sorted(reopened)),
            "settled_evidence_units": tuple(sorted(settled)),
        }
        identity_digest = self._digest(identity)
        reference = (
            f"adaptive-control:{state.contract.fingerprint[:16]}:"
            f"generation:{generation}:{identity_digest[:24]}"
        )
        receipt_digest = self._digest({**identity, "readback_reference": reference})
        return GoalAttainmentReadback(
            goal_fingerprint=state.contract.fingerprint,
            evidence_basis_fingerprint=basis,
            evaluation_revision=revision,
            settled_evidence_units=frozenset(settled),
            failed_evidence_units=frozenset(failed),
            reopened_evidence_units=frozenset(reopened),
            open_blocker_ids=blockers,
            authority_source_id=self._AUTHORITY_SOURCE,
            readback_reference=reference,
            receipt_digest=receipt_digest,
        )

    def _criterion_states(
        self,
        state: AdaptiveControlState,
    ) -> tuple[set[str], set[str], set[str]]:
        """Current latest-revision criterion receipts를 non-compensating states로 나눕니다.

        Args:
            state: Intent/source-current evidence를 선택할 adaptive snapshot입니다.

        Returns:
            Settled, failed, reopened exact surface identity set의 순서쌍입니다.
        """
        effective = effective_criterion_evidence(
            state.evidence,
            goal_fingerprint=state.contract.fingerprint,
            intent_revision=state.contract.intent_revision,
            source_revision=state.contract.source_revision,
        )
        settled: set[str] = set()
        failed: set[str] = set()
        reopened: set[str] = set()
        for criterion in state.contract.criteria:
            for kind in criterion.required_evidence:
                unit = f"{criterion.criterion_id}:{kind.value}"
                matching = tuple(
                    item
                    for item in effective
                    if item.kind is kind and item.criterion_id == criterion.criterion_id
                )
                if any(
                    item.status
                    in {
                        EvidenceStatus.FAIL,
                        EvidenceStatus.ERROR,
                        EvidenceStatus.STALE,
                    }
                    for item in matching
                ):
                    failed.add(unit)
                elif any(item.status is EvidenceStatus.NOT_EVALUATED for item in matching):
                    reopened.add(unit)
                elif any(item.status is EvidenceStatus.PASS for item in matching):
                    settled.add(unit)
        return settled, failed, reopened

    def _coverage_units(self) -> frozenset[str]:
        """Goal-level semantic coverage를 환산하지 않는 exact surface 집합으로 반환합니다.

        Returns:
            Authority와 네 threshold를 독립적으로 식별하는 stable unit 집합입니다.
        """
        return frozenset({
            "goal-coverage:authority",
            "goal-coverage:goal-alignment",
            "goal-coverage:reward-hacking-risk",
            "goal-coverage:semantic-drift",
            "goal-coverage:semantic-uncertainty",
        })

    def _coverage_states(
        self,
        state: AdaptiveControlState,
    ) -> tuple[set[str], set[str], set[str]]:
        """Current coverage authority와 threshold를 settled/failed/reopened로 나눕니다.

        Args:
            state: Goal contract와 optional coverage receipt를 가진 adaptive snapshot입니다.

        Returns:
            Coverage unit의 settled, failed, reopened exact set입니다.
        """
        coverage = state.coverage
        units = set(self._coverage_units())
        if coverage is None:
            return set(), set(), set()
        current = (
            coverage.goal_fingerprint == state.contract.fingerprint
            and coverage.criterion_ids
            == frozenset(item.criterion_id for item in state.contract.criteria)
            and coverage.authority is EvidenceAuthority.INDEPENDENT_EVALUATOR
            and coverage.lineage.is_current(
                state.contract.intent_revision,
                state.contract.source_revision,
            )
        )
        if not current or coverage.status in {
            EvidenceStatus.NOT_EVALUATED,
            EvidenceStatus.STALE,
        }:
            return set(), set(), units
        if coverage.status in {EvidenceStatus.FAIL, EvidenceStatus.ERROR}:
            return set(), units, set()
        settled = {"goal-coverage:authority"}
        failed: set[str] = set()
        thresholds = {
            "goal-coverage:goal-alignment": coverage.goal_alignment >= 0.70,
            "goal-coverage:semantic-drift": coverage.semantic_drift <= 0.30,
            "goal-coverage:semantic-uncertainty": coverage.uncertainty <= 0.30,
            "goal-coverage:reward-hacking-risk": coverage.reward_hacking_risk < 0.70,
        }
        for unit, passed in thresholds.items():
            (settled if passed else failed).add(unit)
        return settled, failed, set()

    def _unavailable_resources(self) -> AuthoritativeResourceDelta:
        unavailable = ResourceMetricDelta(
            status=ResourceTelemetryStatus.UNAVAILABLE,
            value=None,
            source_id=None,
            receipt_reference=None,
            receipt_digest=None,
        )
        return AuthoritativeResourceDelta(
            basis_fingerprint=self._RESOURCE_BASIS,
            wall_clock_milliseconds=unavailable,
            tool_invocations=unavailable,
            input_tokens=unavailable,
            output_tokens=unavailable,
            evaluator_generations=unavailable,
        )

    def _resources(
        self,
        context: _EfficiencyResourceContext,
        goal_fingerprint: str,
        after: GoalAttainmentReadback,
    ) -> AuthoritativeResourceDelta:
        """Current host가 total resource authority를 제공할 때까지 모두 unavailable로 둡니다.

        Material batch는 local mutation subset일 뿐 read/search/delegation을 포함한 전체 tool
        consumption이 아닙니다. Goal readback 한 번도 실제 evaluator generation 수의 receipt가
        아니므로 어느 쪽도 total resource metric으로 승격하지 않습니다.
        """
        del context, goal_fingerprint, after
        return self._unavailable_resources()

    def _digest(self, value: Mapping[str, object]) -> str:
        encoded = json.dumps(
            dict(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def validate_efficiency_resource_admission(
    previous: AdaptiveControlState | None,
    candidate: AdaptiveControlState,
    *,
    session_id: str,
    actor_id: str,
    workflow_id: str,
    workflow_revision: int,
    material_batch: MaterialActionBatch | None,
) -> None:
    """Final process aggregate에서 candidate resource projection을 exact하게 재대조합니다.

    SessionKernel은 이 검증 뒤 같은 process revision을 CAS하므로 material batch가 바뀌면
    conflict retry에서 다시 대조되어 stale candidate를 commit하지 못합니다.

    Args:
        previous: Candidate 직전 exact adaptive state입니다.
        candidate: Store-derived efficiency admission을 가진 post-generation state입니다.
        session_id: Final process aggregate의 exact session identity입니다.
        actor_id: Workflow와 material batch를 소유하는 exact actor identity입니다.
        workflow_id: Candidate를 저장할 exact workflow identity입니다.
        workflow_revision: Final CAS가 비교하는 pre-generation workflow revision입니다.
        material_batch: Final aggregate에서 다시 읽은 actor latest material batch입니다.

    Raises:
        InvalidAdaptiveControlState: Candidate resource vector가 final aggregate projection과
            다르거나 new generation에 store admission이 없을 때 발생합니다.
    """
    if previous is None or len(candidate.observations) != len(previous.observations) + 1:
        return
    assessment = candidate.observations[-1].efficiency_assessment
    if assessment is None:
        raise InvalidAdaptiveControlState(
            "new adaptive generation requires a store-admitted efficiency assessment"
        )
    context = _EfficiencyResourceContext(
        session_id=session_id,
        actor_id=actor_id,
        workflow_id=workflow_id,
        workflow_revision=workflow_revision,
        material_batch=material_batch,
    )
    expected = _EfficiencyAdmissionFactory()._resources(
        context,
        candidate.contract.fingerprint,
        assessment.goal_delta.after,
    )
    if assessment.resource_delta != expected:
        raise InvalidAdaptiveControlState(
            "efficiency resource admission does not match the current process aggregate"
        )


type AdaptiveControlMutation = Callable[[AdaptiveControlState | None], AdaptiveControlState]


class _AdaptiveControlCodec:
    """Adaptive domain value와 canonical JSON object 사이를 왕복합니다."""

    _SCHEMA_VERSION = 5
    _USER_DECISION_SCHEMA_VERSION = 4
    _LEGACY_SCHEMA_VERSION = 3

    def encode(self, state: AdaptiveControlState) -> Mapping[str, object]:
        """Immutable domain state를 JSON-compatible object로 변환합니다.

        Args:
            state: 모든 cross-record invariant를 만족한 adaptive domain state입니다.

        Returns:
            Raw USER 응답을 제외하고 schema version을 명시한 canonical payload입니다.
        """
        return {
            "schema_version": self._SCHEMA_VERSION,
            "contract": self._encode_contract(state.contract),
            "inventory": self._encode_inventory(state.inventory),
            "evidence": [self._encode_evidence(item) for item in state.evidence],
            "coverage": (None if state.coverage is None else self._encode_coverage(state.coverage)),
            "execution_status": state.execution_status.value,
            "observations": [self._encode_observation(item) for item in state.observations],
            "user_decisions": [self._encode_user_decision(item) for item in state.user_decisions],
        }

    def decode(self, payload: Mapping[str, object]) -> AdaptiveControlState:
        """Persisted JSON object를 검증된 immutable domain state로 복원합니다.

        Args:
            payload: Supported schema version과 exact field set을 가진 persisted object입니다.

        Returns:
            Schema와 모든 domain invariant를 통과한 immutable adaptive state입니다.

        Raises:
            InvalidAdaptiveControlState: Field, type, enum, schema 또는 cross-record invariant가
                invalid하면 발생합니다.
        """
        try:
            schema_version = self._integer(payload.get("schema_version"), "schema_version")
            if schema_version not in {
                self._LEGACY_SCHEMA_VERSION,
                self._USER_DECISION_SCHEMA_VERSION,
                self._SCHEMA_VERSION,
            }:
                raise InvalidAdaptiveControlState("unsupported adaptive control schema version")
            expected_fields = {
                "schema_version",
                "contract",
                "inventory",
                "evidence",
                "coverage",
                "execution_status",
                "observations",
            }
            if schema_version >= self._USER_DECISION_SCHEMA_VERSION:
                expected_fields.add("user_decisions")
            self._exact_fields(payload, expected_fields, "adaptive control")
            raw_coverage = payload.get("coverage")
            coverage = (
                None
                if raw_coverage is None
                else self._decode_coverage(self._mapping(raw_coverage, "coverage"))
            )
            state = AdaptiveControlState(
                contract=self._decode_contract(self._mapping(payload.get("contract"), "contract")),
                inventory=self._decode_inventory(
                    self._mapping(payload.get("inventory"), "inventory")
                ),
                evidence=tuple(
                    self._decode_evidence(self._mapping(item, "evidence"))
                    for item in self._list(payload.get("evidence"), "evidence")
                ),
                coverage=coverage,
                execution_status=self._enum(
                    ExecutionStatus,
                    payload.get("execution_status"),
                    "execution_status",
                ),
                observations=tuple(
                    self._decode_observation(self._mapping(item, "observation"))
                    for item in self._list(payload.get("observations"), "observations")
                ),
                user_decisions=(
                    ()
                    if schema_version == self._LEGACY_SCHEMA_VERSION
                    else tuple(
                        self._decode_user_decision(self._mapping(item, "user decision"))
                        for item in self._list(
                            payload.get("user_decisions"),
                            "user_decisions",
                        )
                    )
                ),
            )
            _EfficiencyAdmissionFactory().validate(state)
            return state
        except InvalidAdaptiveControlState:
            raise
        except (TypeError, ValueError) as error:
            raise InvalidAdaptiveControlState("invalid adaptive control payload") from error

    def _encode_contract(self, contract: GoalContract) -> Mapping[str, object]:
        return {
            "goal": contract.goal,
            "constraints": list(contract.constraints),
            "requirement_ids": sorted(contract.requirement_ids),
            "criteria": [
                {
                    "criterion_id": item.criterion_id,
                    "description": item.description,
                    "source_requirement_id": item.source_requirement_id,
                    "approved_requirement_fingerprint": (item.approved_requirement_fingerprint),
                    "observer": item.observer,
                    "precondition": item.precondition,
                    "stimulus": item.stimulus,
                    "expected_outcome": item.expected_outcome,
                    "oracle_owner": item.oracle_owner.value,
                    "hard": item.hard,
                    "required_evidence": sorted(kind.value for kind in item.required_evidence),
                }
                for item in contract.criteria
            ],
            "non_goals": list(contract.non_goals),
            "intent_revision": contract.intent_revision,
            "source_revision": contract.source_revision,
        }

    def _decode_contract(self, payload: Mapping[str, object]) -> GoalContract:
        criteria: list[CriterionSpec] = []
        for raw_item in self._list(payload.get("criteria"), "contract.criteria"):
            item = self._mapping(raw_item, "criterion")
            criteria.append(
                CriterionSpec(
                    criterion_id=self._text(item.get("criterion_id"), "criterion_id"),
                    description=self._text(item.get("description"), "criterion.description"),
                    source_requirement_id=self._text(
                        item.get("source_requirement_id"),
                        "criterion.source_requirement_id",
                    ),
                    approved_requirement_fingerprint=self._text(
                        item.get("approved_requirement_fingerprint"),
                        "criterion.approved_requirement_fingerprint",
                    ),
                    observer=self._text(item.get("observer"), "criterion.observer"),
                    precondition=self._text(
                        item.get("precondition"),
                        "criterion.precondition",
                    ),
                    stimulus=self._text(item.get("stimulus"), "criterion.stimulus"),
                    expected_outcome=self._text(
                        item.get("expected_outcome"),
                        "criterion.expected_outcome",
                    ),
                    oracle_owner=self._enum(
                        OracleOwner,
                        item.get("oracle_owner"),
                        "criterion.oracle_owner",
                    ),
                    hard=self._boolean(item.get("hard"), "criterion.hard"),
                    required_evidence=frozenset(
                        self._enum(EvidenceKind, value, "criterion.required_evidence")
                        for value in self._list(
                            item.get("required_evidence"),
                            "criterion.required_evidence",
                        )
                    ),
                )
            )
        return GoalContract(
            goal=self._text(payload.get("goal"), "contract.goal"),
            constraints=self._text_tuple(payload.get("constraints"), "contract.constraints"),
            requirement_ids=frozenset(
                self._text(item, "contract.requirement_id")
                for item in self._list(
                    payload.get("requirement_ids"),
                    "contract.requirement_ids",
                )
            ),
            criteria=tuple(criteria),
            non_goals=self._text_tuple(payload.get("non_goals"), "contract.non_goals"),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "contract.intent_revision",
            ),
            source_revision=self._text(
                payload.get("source_revision"),
                "contract.source_revision",
            ),
        )

    def _encode_inventory(self, inventory: GapInventory) -> Mapping[str, object]:
        return {
            "intent_revision": inventory.intent_revision,
            "source_revision": inventory.source_revision,
            "assessed_sections": sorted(item.value for item in inventory.assessed_sections),
            "gaps": [self._encode_gap(item) for item in inventory.gaps],
        }

    def _decode_inventory(self, payload: Mapping[str, object]) -> GapInventory:
        return GapInventory(
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "inventory.intent_revision",
            ),
            source_revision=self._text(
                payload.get("source_revision"),
                "inventory.source_revision",
            ),
            assessed_sections=frozenset(
                self._enum(RequirementSection, item, "inventory.assessed_section")
                for item in self._list(
                    payload.get("assessed_sections"),
                    "inventory.assessed_sections",
                )
            ),
            gaps=tuple(
                self._decode_gap(self._mapping(item, "gap"))
                for item in self._list(payload.get("gaps"), "inventory.gaps")
            ),
        )

    def _encode_gap(self, gap: ClarificationGap) -> Mapping[str, object]:
        return {
            "gap_id": gap.gap_id,
            "section": gap.section.value,
            "authority": gap.authority.value,
            "dependency_rank": gap.dependency_rank,
            "weight": gap.weight,
            "blocking": gap.blocking,
            "reversible": gap.reversible,
            "scope_local": gap.scope_local,
            "context": gap.context,
            "question": gap.question,
            "consequence": gap.consequence,
            "recommendation": gap.recommendation,
            "recommendation_rationale": gap.recommendation_rationale,
            "intent_revision": gap.intent_revision,
            "resolution": gap.resolution.value,
            "evidence_reference": gap.evidence_reference,
            "resolution_lineage": (
                None
                if gap.resolution_lineage is None
                else self._encode_authority_receipt(gap.resolution_lineage)
            ),
            "deferral": (
                None if gap.deferral is None else self._encode_user_deferral(gap.deferral)
            ),
        }

    def _decode_gap(self, payload: Mapping[str, object]) -> ClarificationGap:
        return ClarificationGap(
            gap_id=self._text(payload.get("gap_id"), "gap_id"),
            section=self._enum(RequirementSection, payload.get("section"), "gap.section"),
            authority=self._enum(GapAuthority, payload.get("authority"), "gap.authority"),
            dependency_rank=self._integer(
                payload.get("dependency_rank"),
                "gap.dependency_rank",
            ),
            weight=self._number(payload.get("weight"), "gap.weight"),
            blocking=self._boolean(payload.get("blocking"), "gap.blocking"),
            reversible=self._boolean(payload.get("reversible"), "gap.reversible"),
            scope_local=self._boolean(payload.get("scope_local"), "gap.scope_local"),
            context=self._text(payload.get("context"), "gap.context"),
            question=self._text(payload.get("question"), "gap.question"),
            consequence=self._text(payload.get("consequence"), "gap.consequence"),
            recommendation=self._text(
                payload.get("recommendation"),
                "gap.recommendation",
            ),
            recommendation_rationale=self._text(
                payload.get("recommendation_rationale"),
                "gap.recommendation_rationale",
            ),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "gap.intent_revision",
            ),
            resolution=self._enum(
                GapResolution,
                payload.get("resolution"),
                "gap.resolution",
            ),
            evidence_reference=self._optional_text(
                payload.get("evidence_reference"),
                "gap.evidence_reference",
            ),
            resolution_lineage=self._decode_optional_authority_receipt(
                payload.get("resolution_lineage"),
                "gap.resolution_lineage",
            ),
            deferral=self._decode_optional_user_deferral(
                payload.get("deferral"),
                "gap.deferral",
            ),
        )

    def _encode_authority_receipt(
        self,
        receipt: AuthorityReceipt,
    ) -> Mapping[str, object]:
        return {
            "authority": receipt.authority.value,
            "issuer_id": receipt.issuer_id,
            "subject_id": receipt.subject_id,
            "intent_revision": receipt.intent_revision,
            "source_revision": receipt.source_revision,
            "receipt_digest": receipt.receipt_digest,
            "delegation_id": receipt.delegation_id,
        }

    def _decode_authority_receipt(self, payload: Mapping[str, object]) -> AuthorityReceipt:
        return AuthorityReceipt(
            authority=self._enum(
                EvidenceAuthority,
                payload.get("authority"),
                "lineage.authority",
            ),
            issuer_id=self._text(payload.get("issuer_id"), "lineage.issuer_id"),
            subject_id=self._text(payload.get("subject_id"), "lineage.subject_id"),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "lineage.intent_revision",
            ),
            source_revision=self._text(
                payload.get("source_revision"),
                "lineage.source_revision",
            ),
            receipt_digest=self._text(
                payload.get("receipt_digest"),
                "lineage.receipt_digest",
            ),
            delegation_id=self._optional_text(
                payload.get("delegation_id"),
                "lineage.delegation_id",
            ),
        )

    def _decode_optional_authority_receipt(
        self,
        value: object,
        label: str,
    ) -> AuthorityReceipt | None:
        if value is None:
            return None
        return self._decode_authority_receipt(self._mapping(value, label))

    def _encode_user_deferral(self, deferral: UserDeferral) -> Mapping[str, object]:
        return {
            "gap_id": deferral.gap_id,
            "intent_revision": deferral.intent_revision,
            "reason": deferral.reason,
            "lineage": self._encode_authority_receipt(deferral.lineage),
            "decision_reference": deferral.decision_reference,
        }

    def _decode_user_deferral(self, payload: Mapping[str, object]) -> UserDeferral:
        return UserDeferral(
            gap_id=self._text(payload.get("gap_id"), "deferral.gap_id"),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "deferral.intent_revision",
            ),
            reason=self._text(payload.get("reason"), "deferral.reason"),
            lineage=self._decode_authority_receipt(
                self._mapping(payload.get("lineage"), "deferral.lineage")
            ),
            decision_reference=self._optional_text(
                payload.get("decision_reference"),
                "deferral.decision_reference",
            ),
        )

    def _decode_optional_user_deferral(
        self,
        value: object,
        label: str,
    ) -> UserDeferral | None:
        if value is None:
            return None
        return self._decode_user_deferral(self._mapping(value, label))

    def _encode_user_decision(self, decision: UserDecision) -> Mapping[str, object]:
        return {
            "claim": decision.claim.to_payload(),
            "decision_digest": decision.claim.decision_digest,
            "interpretation_lineage": self._encode_authority_receipt(
                decision.interpretation_lineage
            ),
        }

    def _decode_user_decision(self, payload: Mapping[str, object]) -> UserDecision:
        self._exact_fields(
            payload,
            {"claim", "decision_digest", "interpretation_lineage"},
            "user decision",
        )
        claim_payload = self._mapping(payload.get("claim"), "user decision.claim")
        legacy_fields = {
                "workflow_id",
                "question_workflow_revision",
                "source_goal_fingerprint",
                "source_intent_revision",
                "source_revision",
                "question_digest",
                "question_generation",
                "question_turn_revision",
                "prompt_digest",
                "prompt_reference",
                "prompt_generation",
                "prompt_turn_revision",
                "target_kind",
                "target_id",
                "disposition",
                "value_summary_digest",
                "result_goal_fingerprint",
                "result_intent_revision",
                "result_source_revision",
        }
        native_fields = (
            legacy_fields
            - {
                "question_workflow_revision",
                "question_digest",
                "question_generation",
                "question_turn_revision",
                "prompt_generation",
                "prompt_turn_revision",
            }
            | {"provenance", "source_workflow_revision"}
        )
        native_with_kernel_fields = native_fields | {
            "prompt_generation", "prompt_turn_revision"}
        actual_fields = set(claim_payload)
        if actual_fields == legacy_fields:
            provenance = UserDecisionProvenance.ADAPTIVE_QUESTION
        elif frozenset(actual_fields) in {
            frozenset(native_fields), frozenset(native_with_kernel_fields)
        }:
            provenance = self._enum(
                UserDecisionProvenance,
                claim_payload.get("provenance"),
                "decision.provenance",
            )
            if provenance is not UserDecisionProvenance.NATIVE_PROMPT:
                raise InvalidAdaptiveControlState(
                    "native user decision fields require native-prompt provenance")
        else:
            raise InvalidAdaptiveControlState(
                "user decision claim fields do not match a supported schema")
        claim = UserDecisionClaim(
            workflow_id=self._text(claim_payload.get("workflow_id"), "decision.workflow_id"),
            question_workflow_revision=None if provenance is UserDecisionProvenance.NATIVE_PROMPT else self._integer(
                claim_payload.get("question_workflow_revision"),
                "decision.question_workflow_revision",
            ),
            source_goal_fingerprint=self._text(
                claim_payload.get("source_goal_fingerprint"),
                "decision.source_goal_fingerprint",
            ),
            source_intent_revision=self._integer(
                claim_payload.get("source_intent_revision"),
                "decision.source_intent_revision",
            ),
            source_revision=self._text(
                claim_payload.get("source_revision"),
                "decision.source_revision",
            ),
            question_digest=None if provenance is UserDecisionProvenance.NATIVE_PROMPT else self._text(
                claim_payload.get("question_digest"),
                "decision.question_digest",
            ),
            question_generation=None if provenance is UserDecisionProvenance.NATIVE_PROMPT else self._integer(
                claim_payload.get("question_generation"),
                "decision.question_generation",
            ),
            question_turn_revision=None if provenance is UserDecisionProvenance.NATIVE_PROMPT else self._integer(
                claim_payload.get("question_turn_revision"),
                "decision.question_turn_revision",
            ),
            prompt_digest=self._text(
                claim_payload.get("prompt_digest"),
                "decision.prompt_digest",
            ),
            prompt_reference=self._text(
                claim_payload.get("prompt_reference"),
                "decision.prompt_reference",
            ),
            prompt_generation=None if "prompt_generation" not in actual_fields else self._integer(
                claim_payload.get("prompt_generation"),
                "decision.prompt_generation",
            ),
            prompt_turn_revision=None if "prompt_turn_revision" not in actual_fields else self._integer(
                claim_payload.get("prompt_turn_revision"),
                "decision.prompt_turn_revision",
            ),
            target_kind=self._enum(
                UserDecisionTarget,
                claim_payload.get("target_kind"),
                "decision.target_kind",
            ),
            target_id=self._text(claim_payload.get("target_id"), "decision.target_id"),
            disposition=self._enum(
                UserDecisionDisposition,
                claim_payload.get("disposition"),
                "decision.disposition",
            ),
            value_summary_digest=self._text(
                claim_payload.get("value_summary_digest"),
                "decision.value_summary_digest",
            ),
            result_goal_fingerprint=self._text(
                claim_payload.get("result_goal_fingerprint"),
                "decision.result_goal_fingerprint",
            ),
            result_intent_revision=self._integer(
                claim_payload.get("result_intent_revision"),
                "decision.result_intent_revision",
            ),
            result_source_revision=self._text(
                claim_payload.get("result_source_revision"),
                "decision.result_source_revision",
            ),
            provenance=provenance,
            source_workflow_revision=(
                None
                if provenance is UserDecisionProvenance.ADAPTIVE_QUESTION
                else self._integer(
                    claim_payload.get("source_workflow_revision"),
                    "decision.source_workflow_revision",
                )
            ),
        )
        stored_digest = self._text(payload.get("decision_digest"), "decision.decision_digest")
        if not hmac.compare_digest(stored_digest, claim.decision_digest):
            raise InvalidAdaptiveControlState(
                "user decision digest does not match its canonical claim"
            )
        lineage_payload = self._mapping(
            payload.get("interpretation_lineage"),
            "decision.interpretation_lineage",
        )
        self._exact_fields(
            lineage_payload,
            {
                "authority",
                "issuer_id",
                "subject_id",
                "intent_revision",
                "source_revision",
                "receipt_digest",
                "delegation_id",
            },
            "user decision lineage",
        )
        return UserDecision(
            claim=claim,
            interpretation_lineage=self._decode_authority_receipt(lineage_payload),
        )

    def _encode_evidence(self, evidence: CriterionEvidence) -> Mapping[str, object]:
        return {
            "goal_fingerprint": evidence.goal_fingerprint,
            "criterion_id": evidence.criterion_id,
            "kind": evidence.kind.value,
            "authority": evidence.authority.value,
            "status": evidence.status.value,
            "reference": evidence.reference,
            "lineage": self._encode_authority_receipt(evidence.lineage),
            "evaluation_revision": evidence.evaluation_revision,
        }

    def _decode_evidence(self, payload: Mapping[str, object]) -> CriterionEvidence:
        return CriterionEvidence(
            goal_fingerprint=self._text(
                payload.get("goal_fingerprint"),
                "evidence.goal_fingerprint",
            ),
            criterion_id=self._text(payload.get("criterion_id"), "evidence.criterion_id"),
            kind=self._enum(EvidenceKind, payload.get("kind"), "evidence.kind"),
            authority=self._enum(
                EvidenceAuthority,
                payload.get("authority"),
                "evidence.authority",
            ),
            status=self._enum(EvidenceStatus, payload.get("status"), "evidence.status"),
            reference=self._text(payload.get("reference"), "evidence.reference"),
            lineage=self._decode_authority_receipt(
                self._mapping(payload.get("lineage"), "evidence.lineage")
            ),
            evaluation_revision=self._integer(
                payload.get("evaluation_revision"),
                "evidence.evaluation_revision",
            ),
        )

    def _encode_coverage(self, coverage: GoalCoverage) -> Mapping[str, object]:
        return {
            "goal_fingerprint": coverage.goal_fingerprint,
            "criterion_ids": sorted(coverage.criterion_ids),
            "authority": coverage.authority.value,
            "status": coverage.status.value,
            "reference": coverage.reference,
            "goal_alignment": coverage.goal_alignment,
            "semantic_drift": coverage.semantic_drift,
            "uncertainty": coverage.uncertainty,
            "reward_hacking_risk": coverage.reward_hacking_risk,
            "lineage": self._encode_authority_receipt(coverage.lineage),
            "evaluation_revision": coverage.evaluation_revision,
        }

    def _decode_coverage(self, payload: Mapping[str, object]) -> GoalCoverage:
        return GoalCoverage(
            goal_fingerprint=self._text(
                payload.get("goal_fingerprint"),
                "coverage.goal_fingerprint",
            ),
            criterion_ids=frozenset(
                self._text(item, "coverage.criterion_id")
                for item in self._list(payload.get("criterion_ids"), "coverage.criterion_ids")
            ),
            authority=self._enum(
                EvidenceAuthority,
                payload.get("authority"),
                "coverage.authority",
            ),
            status=self._enum(EvidenceStatus, payload.get("status"), "coverage.status"),
            reference=self._text(payload.get("reference"), "coverage.reference"),
            goal_alignment=self._number(
                payload.get("goal_alignment"),
                "coverage.goal_alignment",
            ),
            semantic_drift=self._number(
                payload.get("semantic_drift"),
                "coverage.semantic_drift",
            ),
            uncertainty=self._number(payload.get("uncertainty"), "coverage.uncertainty"),
            reward_hacking_risk=self._number(
                payload.get("reward_hacking_risk"),
                "coverage.reward_hacking_risk",
            ),
            lineage=self._decode_authority_receipt(
                self._mapping(payload.get("lineage"), "coverage.lineage")
            ),
            evaluation_revision=self._integer(
                payload.get("evaluation_revision"),
                "coverage.evaluation_revision",
            ),
        )

    def _encode_observation(self, observation: IterationObservation) -> Mapping[str, object]:
        return {
            "goal_fingerprint": observation.goal_fingerprint,
            "generation": observation.generation,
            "output_fingerprint": observation.output_fingerprint,
            "active_criteria": list(observation.active_criteria),
            "root_causes": list(observation.root_causes),
            "progress": observation.progress,
            "material_change": observation.material_change,
            "reproducible_harness_gap": observation.reproducible_harness_gap,
            "recovery_epoch": observation.recovery_epoch,
            "efficiency_assessment": self._encode_efficiency(observation.efficiency_assessment),
        }

    def _decode_observation(self, payload: Mapping[str, object]) -> IterationObservation:
        return IterationObservation(
            goal_fingerprint=self._text(
                payload.get("goal_fingerprint"),
                "observation.goal_fingerprint",
            ),
            generation=self._integer(payload.get("generation"), "observation.generation"),
            output_fingerprint=self._text(
                payload.get("output_fingerprint"),
                "observation.output_fingerprint",
            ),
            active_criteria=self._text_tuple(
                payload.get("active_criteria"),
                "observation.active_criteria",
            ),
            root_causes=self._text_tuple(
                payload.get("root_causes"),
                "observation.root_causes",
            ),
            progress=self._number(payload.get("progress"), "observation.progress"),
            material_change=self._boolean(
                payload.get("material_change"),
                "observation.material_change",
            ),
            reproducible_harness_gap=self._boolean(
                payload.get("reproducible_harness_gap"),
                "observation.reproducible_harness_gap",
            ),
            recovery_epoch=self._integer(
                payload.get("recovery_epoch"),
                "observation.recovery_epoch",
            ),
            efficiency_assessment=self._decode_optional_efficiency(
                payload.get("efficiency_assessment")
            ),
        )

    def _encode_efficiency(
        self,
        assessment: EfficiencyAssessment | None,
    ) -> Mapping[str, object] | None:
        if assessment is None:
            return None
        return {
            "goal_delta": {
                "before": self._encode_goal_readback(assessment.goal_delta.before),
                "after": self._encode_goal_readback(assessment.goal_delta.after),
            },
            "resource_delta": self._encode_resource_delta(assessment.resource_delta),
            "status": assessment.status.value,
            "reason": assessment.reason,
        }

    def _decode_optional_efficiency(self, value: object) -> EfficiencyAssessment | None:
        if value is None:
            return None
        payload = self._mapping(value, "efficiency assessment")
        self._exact_fields(
            payload,
            {"goal_delta", "resource_delta", "status", "reason"},
            "efficiency assessment",
        )
        goal_payload = self._mapping(payload.get("goal_delta"), "efficiency goal delta")
        self._exact_fields(goal_payload, {"before", "after"}, "efficiency goal delta")
        goal_delta = VerifiedGoalAttainmentDelta(
            before=self._decode_goal_readback(
                self._mapping(goal_payload.get("before"), "efficiency before readback")
            ),
            after=self._decode_goal_readback(
                self._mapping(goal_payload.get("after"), "efficiency after readback")
            ),
        )
        resource_delta = self._decode_resource_delta(
            self._mapping(payload.get("resource_delta"), "efficiency resource delta")
        )
        derived = EfficiencyAssessor().assess(goal_delta, resource_delta)
        stored_status = self._enum(
            EfficiencyStatus,
            payload.get("status"),
            "efficiency status",
        )
        stored_reason = self._text(payload.get("reason"), "efficiency reason")
        if derived.status is not stored_status or derived.reason != stored_reason:
            raise InvalidAdaptiveControlState(
                "efficiency status and reason must derive from goal-resource delta"
            )
        return derived

    def _encode_goal_readback(
        self,
        readback: GoalAttainmentReadback,
    ) -> Mapping[str, object]:
        return {
            "goal_fingerprint": readback.goal_fingerprint,
            "evidence_basis_fingerprint": readback.evidence_basis_fingerprint,
            "evaluation_revision": readback.evaluation_revision,
            "settled_evidence_units": sorted(readback.settled_evidence_units),
            "failed_evidence_units": sorted(readback.failed_evidence_units),
            "reopened_evidence_units": sorted(readback.reopened_evidence_units),
            "open_blocker_ids": sorted(readback.open_blocker_ids),
            "authority_source_id": readback.authority_source_id,
            "readback_reference": readback.readback_reference,
            "receipt_digest": readback.receipt_digest,
        }

    def _decode_goal_readback(self, payload: Mapping[str, object]) -> GoalAttainmentReadback:
        self._exact_fields(
            payload,
            {
                "goal_fingerprint",
                "evidence_basis_fingerprint",
                "evaluation_revision",
                "settled_evidence_units",
                "failed_evidence_units",
                "reopened_evidence_units",
                "open_blocker_ids",
                "authority_source_id",
                "readback_reference",
                "receipt_digest",
            },
            "efficiency goal readback",
        )
        return GoalAttainmentReadback(
            goal_fingerprint=self._text(payload.get("goal_fingerprint"), "goal fingerprint"),
            evidence_basis_fingerprint=self._text(
                payload.get("evidence_basis_fingerprint"),
                "evidence basis fingerprint",
            ),
            evaluation_revision=self._integer(
                payload.get("evaluation_revision"),
                "goal evaluation revision",
            ),
            settled_evidence_units=frozenset(
                self._text_tuple(payload.get("settled_evidence_units"), "settled evidence unit")
            ),
            failed_evidence_units=frozenset(
                self._text_tuple(payload.get("failed_evidence_units"), "failed evidence unit")
            ),
            reopened_evidence_units=frozenset(
                self._text_tuple(payload.get("reopened_evidence_units"), "reopened evidence unit")
            ),
            open_blocker_ids=frozenset(
                self._text_tuple(payload.get("open_blocker_ids"), "open blocker id")
            ),
            authority_source_id=self._text(
                payload.get("authority_source_id"),
                "goal authority source",
            ),
            readback_reference=self._text(
                payload.get("readback_reference"),
                "goal readback reference",
            ),
            receipt_digest=self._text(payload.get("receipt_digest"), "goal receipt digest"),
        )

    def _encode_resource_delta(
        self,
        resource: AuthoritativeResourceDelta,
    ) -> Mapping[str, object]:
        return {
            "basis_fingerprint": resource.basis_fingerprint,
            "wall_clock_milliseconds": self._encode_resource_metric(
                resource.wall_clock_milliseconds
            ),
            "tool_invocations": self._encode_resource_metric(resource.tool_invocations),
            "input_tokens": self._encode_resource_metric(resource.input_tokens),
            "output_tokens": self._encode_resource_metric(resource.output_tokens),
            "evaluator_generations": self._encode_resource_metric(resource.evaluator_generations),
        }

    def _decode_resource_delta(
        self,
        payload: Mapping[str, object],
    ) -> AuthoritativeResourceDelta:
        fields = {
            "basis_fingerprint",
            "wall_clock_milliseconds",
            "tool_invocations",
            "input_tokens",
            "output_tokens",
            "evaluator_generations",
        }
        self._exact_fields(payload, fields, "efficiency resource delta")
        return AuthoritativeResourceDelta(
            basis_fingerprint=self._text(
                payload.get("basis_fingerprint"),
                "resource basis fingerprint",
            ),
            wall_clock_milliseconds=self._decode_resource_metric(
                payload.get("wall_clock_milliseconds")
            ),
            tool_invocations=self._decode_resource_metric(payload.get("tool_invocations")),
            input_tokens=self._decode_resource_metric(payload.get("input_tokens")),
            output_tokens=self._decode_resource_metric(payload.get("output_tokens")),
            evaluator_generations=self._decode_resource_metric(
                payload.get("evaluator_generations")
            ),
        )

    def _encode_resource_metric(self, metric: ResourceMetricDelta) -> Mapping[str, object]:
        return {
            "status": metric.status.value,
            "value": metric.value,
            "source_id": metric.source_id,
            "receipt_reference": metric.receipt_reference,
            "receipt_digest": metric.receipt_digest,
        }

    def _decode_resource_metric(self, value: object) -> ResourceMetricDelta:
        payload = self._mapping(value, "efficiency resource metric")
        self._exact_fields(
            payload,
            {"status", "value", "source_id", "receipt_reference", "receipt_digest"},
            "efficiency resource metric",
        )
        status = self._enum(
            ResourceTelemetryStatus,
            payload.get("status"),
            "resource telemetry status",
        )
        raw_value = payload.get("value")
        metric_value = None if raw_value is None else self._integer(raw_value, "resource value")
        return ResourceMetricDelta(
            status=status,
            value=metric_value,
            source_id=self._optional_text(payload.get("source_id"), "resource source id"),
            receipt_reference=self._optional_text(
                payload.get("receipt_reference"),
                "resource receipt reference",
            ),
            receipt_digest=self._optional_text(
                payload.get("receipt_digest"),
                "resource receipt digest",
            ),
        )

    def _mapping(self, value: object, label: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            raise InvalidAdaptiveControlState(f"{label} must be a string-keyed object")
        return {str(key): item for key, item in value.items()}

    def _exact_fields(
        self,
        payload: Mapping[str, object],
        expected: set[str],
        label: str,
    ) -> None:
        actual = set(payload)
        if actual != expected:
            raise InvalidAdaptiveControlState(f"{label} fields do not match schema")

    def _list(self, value: object, label: str) -> list[object]:
        if not isinstance(value, list):
            raise InvalidAdaptiveControlState(f"{label} must be a list")
        return value

    def _text(self, value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidAdaptiveControlState(f"{label} must be non-empty text")
        return value

    def _optional_text(self, value: object, label: str) -> str | None:
        if value is None:
            return None
        return self._text(value, label)

    def _text_tuple(self, value: object, label: str) -> tuple[str, ...]:
        return tuple(self._text(item, label) for item in self._list(value, label))

    def _boolean(self, value: object, label: str) -> bool:
        if not isinstance(value, bool):
            raise InvalidAdaptiveControlState(f"{label} must be a boolean")
        return value

    def _integer(self, value: object, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidAdaptiveControlState(f"{label} must be an integer")
        return value

    def _number(self, value: object, label: str) -> float:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise InvalidAdaptiveControlState(f"{label} must be a number")
        return float(value)

    def _enum(
        self,
        enum_type: type[EnumValue],
        value: object,
        label: str,
    ) -> EnumValue:
        if not isinstance(value, str):
            raise InvalidAdaptiveControlState(f"{label} must be a string enum")
        try:
            return enum_type(value)
        except ValueError as error:
            raise InvalidAdaptiveControlState(f"{label} has an unknown value") from error


def validate_adaptive_control_transition(
    previous: AdaptiveControlState | None,
    candidate: AdaptiveControlState,
    *,
    allow_goal_override: bool = False,
) -> None:
    """두 immutable snapshot 사이에 허용되는 단조 전이만 검증합니다.

    Args:
        previous: CAS readback에서 얻은 exact current state입니다.
        candidate: Pure mutation이 제안한 next state입니다.
        allow_goal_override: `override_goal` 전용 authority reset capability입니다.

    Raises:
        InvalidAdaptiveControlState: Authority, gap ledger 또는 reflection history가
            삭제·rollback·자가 증명되면 발생합니다.
    """
    if previous is None:
        _validate_fresh_adaptive_state(candidate)
        return
    goal_changed = previous.contract.fingerprint != candidate.contract.fingerprint
    if goal_changed:
        if not allow_goal_override:
            raise InvalidAdaptiveControlState("goal changes require explicit override_goal")
        if (
            candidate.evidence
            or candidate.coverage is not None
            or candidate.observations
            or candidate.execution_status is not ExecutionStatus.INCOMPLETE
        ):
            raise InvalidAdaptiveControlState("goal override must clear old authority and history")
        _validate_user_goal_override(previous, candidate)
        _validate_fresh_adaptive_state(candidate, allow_user_goal_decision=True)
        return
    if allow_goal_override:
        raise InvalidAdaptiveControlState("goal override requires a different goal fingerprint")
    if previous.contract != candidate.contract:
        raise InvalidAdaptiveControlState("same-goal contract is immutable")
    _validate_inventory_transition(previous.inventory, candidate.inventory)
    _validate_evidence_transition(previous.evidence, candidate.evidence)
    _validate_coverage_transition(previous.coverage, candidate.coverage)
    _validate_execution_transition(previous.execution_status, candidate.execution_status)
    _validate_user_decision_transition(previous, candidate)
    _validate_observation_transition(previous, candidate)


def _validate_fresh_adaptive_state(
    candidate: AdaptiveControlState,
    *,
    allow_user_goal_decision: bool = False,
) -> None:
    """Persisted history가 없는 최초 snapshot이 history를 사칭하지 않게 검증합니다."""
    if any(gap.is_blocked for gap in candidate.inventory.gaps):
        raise InvalidAdaptiveControlState("terminal blocker requires an existing open gap")
    if any(item.evaluation_revision != 1 for item in candidate.evidence):
        raise InvalidAdaptiveControlState("initial evidence must use evaluation revision one")
    if candidate.coverage is not None and candidate.coverage.evaluation_revision != 1:
        raise InvalidAdaptiveControlState("initial coverage must use evaluation revision one")
    if len(candidate.observations) > 1:
        raise InvalidAdaptiveControlState("initial state cannot import observation history")
    if candidate.user_decisions and not allow_user_goal_decision:
        raise InvalidAdaptiveControlState("initial state cannot import USER decision history")
    _validate_appended_observation(None, candidate)


def _validate_user_decision_transition(
    previous: AdaptiveControlState,
    candidate: AdaptiveControlState,
) -> None:
    """같은 goal에서 USER decision ledger의 exact append-only 전이만 허용합니다."""
    old = previous.user_decisions
    new = candidate.user_decisions
    if len(new) < len(old) or new[: len(old)] != old:
        raise InvalidAdaptiveControlState("USER decision history is append-only")
    current = candidate.contract
    for decision in new[len(old) :]:
        claim = decision.claim
        if (
            claim.source_goal_fingerprint != current.fingerprint
            or claim.source_intent_revision != current.intent_revision
            or claim.source_revision != current.source_revision
        ):
            raise InvalidAdaptiveControlState(
                "same-goal USER decision must originate from the current contract"
            )


def _validate_user_goal_override(
    previous: AdaptiveControlState,
    candidate: AdaptiveControlState,
) -> None:
    """User-driven goal override가 exact old-to-new semantic claim을 소비하게 합니다.

    Persisted v3 non-USER snapshot의 read compatibility와 live goal mutation authority는
    분리합니다. 새 override는 반드시 이번 old-to-new transition만 증명하는 typed
    USER decision을 하나 이상 소비해야 합니다.
    """
    if not candidate.user_decisions:
        raise InvalidAdaptiveControlState("goal override requires a typed USER decision")
    old_contract = previous.contract
    new_contract = candidate.contract
    old_gap_ids = frozenset(gap.gap_id for gap in previous.inventory.gaps)
    old_criterion_ids = frozenset(item.criterion_id for item in old_contract.criteria)
    for decision in candidate.user_decisions:
        claim = decision.claim
        if (
            claim.source_goal_fingerprint != old_contract.fingerprint
            or claim.source_intent_revision != old_contract.intent_revision
            or claim.source_revision != old_contract.source_revision
            or claim.result_goal_fingerprint != new_contract.fingerprint
            or claim.result_intent_revision != new_contract.intent_revision
            or claim.result_source_revision != new_contract.source_revision
        ):
            raise InvalidAdaptiveControlState(
                "goal override USER decision must bind the exact old and new contracts"
            )
        if claim.result_intent_revision != claim.source_intent_revision + 1:
            raise InvalidAdaptiveControlState(
                "user-driven goal override must advance intent revision exactly once"
            )
        known_target = (
            claim.target_kind is UserDecisionTarget.GAP and claim.target_id in old_gap_ids
        ) or (
            claim.target_kind is UserDecisionTarget.CRITERION
            and claim.target_id in old_criterion_ids
        )
        if not known_target:
            raise InvalidAdaptiveControlState(
                "goal override USER decision must target the previous contract"
            )


def _validate_inventory_transition(previous: GapInventory, candidate: GapInventory) -> None:
    """Same-intent requirement assessment와 gap ledger의 전진만 허용합니다."""
    if not previous.assessed_sections.issubset(candidate.assessed_sections):
        raise InvalidAdaptiveControlState("assessed requirement sections cannot shrink")
    previous_gaps = {item.gap_id: item for item in previous.gaps}
    candidate_gaps = {item.gap_id: item for item in candidate.gaps}
    if not previous_gaps.keys() <= candidate_gaps.keys():
        raise InvalidAdaptiveControlState("same-intent clarification gaps cannot disappear")
    for gap_id, old in previous_gaps.items():
        new = candidate_gaps[gap_id]
        if _gap_definition(old) != _gap_definition(new):
            raise InvalidAdaptiveControlState("clarification gap definition is immutable")
        if old.blocking != new.blocking and not _is_user_deferral_transition(old, new):
            raise InvalidAdaptiveControlState("clarification gap blocking policy is immutable")
        if new.is_blocked and not new.is_blocked_for(candidate):
            raise InvalidAdaptiveControlState(
                "terminal blocker must match the current inventory intent and source"
            )
        if old.is_blocked and new != old:
            raise InvalidAdaptiveControlState("terminal blocker cannot reopen or be superseded")
        if old.is_resolved and not new.is_resolved:
            raise InvalidAdaptiveControlState("resolved clarification gap cannot reopen")
        if old.deferral is not None and not (new.is_resolved or new.deferral is not None):
            raise InvalidAdaptiveControlState("deferred clarification gap cannot lose authority")


def _gap_definition(gap: ClarificationGap) -> tuple[object, ...]:
    """Resolution과 exact USER deferral policy를 제외한 immutable gap identity입니다."""
    return (
        gap.gap_id,
        gap.section,
        gap.authority,
        gap.dependency_rank,
        gap.weight,
        gap.reversible,
        gap.scope_local,
        gap.context,
        gap.question,
        gap.consequence,
        gap.recommendation,
        gap.recommendation_rationale,
        gap.intent_revision,
    )


def _is_user_deferral_transition(
    previous: ClarificationGap,
    candidate: ClarificationGap,
) -> bool:
    """Blocking USER question이 exact explicit deferral로 바뀌는 전이인지 반환합니다."""
    return (
        previous.authority is GapAuthority.USER
        and previous.blocking
        and not candidate.blocking
        and previous.resolution is GapResolution.OPEN
        and candidate.resolution is GapResolution.OPEN
        and previous.deferral is None
        and candidate.deferral is not None
    )


def _validate_evidence_transition(
    previous: tuple[CriterionEvidence, ...],
    candidate: tuple[CriterionEvidence, ...],
) -> None:
    """Evidence history를 append-only로 보존하고 revision 재평가를 검증합니다."""
    if len(candidate) < len(previous) or candidate[: len(previous)] != previous:
        raise InvalidAdaptiveControlState("criterion evidence history is append-only")
    latest: dict[tuple[str, EvidenceKind], int] = {}
    for item in previous:
        latest[(item.criterion_id, item.kind)] = item.evaluation_revision
    started: set[tuple[str, EvidenceKind]] = set()
    for item in candidate[len(previous) :]:
        surface = (item.criterion_id, item.kind)
        current = latest.get(surface, 0)
        if surface not in started:
            if item.evaluation_revision != current + 1:
                raise InvalidAdaptiveControlState(
                    "new evidence evaluation must use the next revision"
                )
            started.add(surface)
        elif item.evaluation_revision not in {current, current + 1}:
            raise InvalidAdaptiveControlState(
                "evidence evaluation revisions must be monotonic and contiguous"
            )
        latest[surface] = item.evaluation_revision


def _validate_coverage_transition(
    previous: GoalCoverage | None,
    candidate: GoalCoverage | None,
) -> None:
    """Coverage 삭제를 막고 exact next evaluation revision만 supersession으로 허용합니다."""
    if previous is None:
        if candidate is not None and candidate.evaluation_revision != 1:
            raise InvalidAdaptiveControlState("initial coverage must use evaluation revision one")
        return
    if candidate is None:
        raise InvalidAdaptiveControlState("goal coverage cannot be deleted")
    if candidate == previous:
        return
    if candidate.evaluation_revision != previous.evaluation_revision + 1:
        raise InvalidAdaptiveControlState("coverage supersession must use the next revision")


def _validate_execution_transition(
    previous: ExecutionStatus,
    candidate: ExecutionStatus,
) -> None:
    """같은 goal에서 terminal execution lifecycle의 rollback을 거부합니다."""
    if previous is not candidate and previous in {
        ExecutionStatus.FAILED,
        ExecutionStatus.COMPLETED,
    }:
        raise InvalidAdaptiveControlState("terminal execution status cannot be changed")


def _validate_observation_transition(
    previous: AdaptiveControlState,
    candidate: AdaptiveControlState,
) -> None:
    """Observation history를 보존하고 한 mutation에 generation 하나만 추가합니다."""
    old = previous.observations
    new = candidate.observations
    if len(new) < len(old) or new[: len(old)] != old:
        raise InvalidAdaptiveControlState("iteration observation history is append-only")
    if len(new) > len(old) + 1:
        raise InvalidAdaptiveControlState("append exactly one observation generation at a time")
    if len(new) == len(old) + 1:
        _validate_appended_observation(old[-1] if old else None, candidate)
        _validate_recovery_epoch_transition(previous, candidate)


def _validate_recovery_epoch_transition(
    previous: AdaptiveControlState,
    candidate: AdaptiveControlState,
) -> None:
    """직전 deterministic recovery decision이 승인한 material epoch만 허용합니다."""
    if not previous.observations:
        return
    prior_observation = previous.observations[-1]
    next_observation = candidate.observations[-1]
    if next_observation.recovery_epoch == prior_observation.recovery_epoch:
        return
    prior_ambiguity = assess_ambiguity(previous.inventory)
    prior_attainment = assess_goal_attainment(
        previous.contract,
        previous.evidence,
        previous.coverage,
        previous.execution_status,
    )
    prior_decision = ReflectionPolicy().decide(
        prior_ambiguity,
        prior_attainment,
        previous.observations,
    )
    prior_decision = _StoreAdmittedReflectionDecision().decide(
        prior_attainment,
        previous.observations,
        prior_decision,
    )
    if prior_decision.action not in {
        ControlAction.CHANGE_APPROACH,
        ControlAction.ENUMERATE_INVARIANT,
        ControlAction.PROMOTE_HARNESS,
    }:
        raise InvalidAdaptiveControlState(
            "new recovery epoch requires a prior deterministic recovery decision"
        )
    if not next_observation.material_change:
        raise InvalidAdaptiveControlState("new recovery epoch requires a material transition")


def _validate_appended_observation(
    previous: IterationObservation | None,
    candidate: AdaptiveControlState,
) -> None:
    """새 observation의 progress/output/material flag를 canonical state에서 재계산합니다."""
    if not candidate.observations:
        return
    observation = candidate.observations[-1]
    expected_fingerprint = adaptive_output_fingerprint(
        candidate.contract,
        candidate.inventory,
        candidate.evidence,
        candidate.coverage,
        candidate.execution_status,
        candidate.user_decisions,
    )
    attainment = assess_goal_attainment(
        candidate.contract,
        candidate.evidence,
        candidate.coverage,
        candidate.execution_status,
    )
    if observation.output_fingerprint != expected_fingerprint:
        raise InvalidAdaptiveControlState(
            "observation output fingerprint must derive from current adaptive state"
        )
    if observation.progress != attainment.progress:
        raise InvalidAdaptiveControlState(
            "observation progress must derive from current goal attainment"
        )
    expected_change = previous is None or previous.output_fingerprint != expected_fingerprint
    if observation.material_change is not expected_change:
        raise InvalidAdaptiveControlState(
            "observation material_change must derive from its canonical fingerprint"
        )


class _AdaptiveControlNamespaceMutation(SkillStateReservedMutation):
    """Domain mutation을 workflow skill-state replacement로 변환합니다."""

    def __init__(
        self,
        mutation: AdaptiveControlMutation,
        codec: _AdaptiveControlCodec,
        namespace: str,
        resource_context: _EfficiencyResourceContext,
        *,
        allow_goal_override: bool = False,
    ) -> None:
        """Retry 가능한 pure mutation과 deterministic codec을 고정합니다.

        Args:
            mutation: Latest typed state를 replacement state로 바꾸는 pure transform입니다.
            codec: Persisted namespace와 domain state를 canonical하게 왕복하는 codec입니다.
            namespace: 이 mutation만 변경할 수 있는 reserved skill-state namespace입니다.
            resource_context: Same-session material receipt attribution readback입니다.
            allow_goal_override: Old authority를 폐기하는 explicit goal 교체만 허용할지
                나타냅니다.
        """
        self._mutation = mutation
        self._codec = codec
        self._namespace = namespace
        self._resource_context = resource_context
        self._allow_goal_override = allow_goal_override

    @property
    def reserved_namespaces(self) -> frozenset[str]:
        """Typed transition이 소유하는 exact adaptive namespace를 반환합니다.

        Returns:
            Generic mutation이 변경할 수 없는 단일 adaptive namespace 집합입니다.
        """
        return frozenset({self._namespace})

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest state에서 mutation을 실행하고 sibling namespace를 보존합니다.

        Args:
            current: Adaptive namespace와 sibling payload를 포함한 current skill state입니다.

        Returns:
            Validated adaptive replacement와 unchanged sibling namespace를 결합한 object입니다.

        Raises:
            InvalidAdaptiveControlState: Mutation 결과나 domain transition이 invariant를
                위반하면 발생합니다.
        """
        previous = self._current(current)
        try:
            candidate = self._mutation(previous)
        except InvalidAdaptiveControlState:
            raise
        except ValueError as error:
            raise InvalidAdaptiveControlState(
                "adaptive control mutation returned an invalid domain state"
            ) from error
        if not isinstance(candidate, AdaptiveControlState):
            raise InvalidAdaptiveControlState(
                "adaptive control mutation must return AdaptiveControlState"
            )
        candidate = _EfficiencyAdmissionFactory().admit(
            previous,
            candidate,
            self._resource_context,
        )
        validate_adaptive_control_transition(
            previous,
            candidate,
            allow_goal_override=self._allow_goal_override,
        )
        return {**current, self._namespace: self._codec.encode(candidate)}

    def _current(self, current: Mapping[str, object]) -> AdaptiveControlState | None:
        raw_state = current.get(self._namespace)
        if raw_state is None:
            return None
        if not isinstance(raw_state, Mapping):
            raise InvalidAdaptiveControlState("skill_state.adaptive_control must be an object")
        return self._codec.decode(raw_state)


class _GoalOverrideMutation:
    """새 goal contract에 old authority가 없는 state를 만드는 pure mutation입니다."""

    def __init__(
        self,
        contract: GoalContract,
        inventory: GapInventory,
        user_decisions: tuple[UserDecision, ...],
    ) -> None:
        """Override retry 동안 동일하게 사용할 immutable input을 고정합니다.

        Args:
            contract: Old authority를 폐기한 뒤 시작할 new goal 계약입니다.
            inventory: New contract revision에 맞춰 다시 평가한 complete gap inventory입니다.
            user_decisions: Goal override 자체를 증명하고 new effect에 결속된 USER decision입니다.
        """
        self._contract = contract
        self._inventory = inventory
        self._user_decisions = user_decisions

    def __call__(self, _current: AdaptiveControlState | None) -> AdaptiveControlState:
        """이전 state와 authority를 공유하지 않는 새 goal state를 반환합니다.

        Returns:
            Evidence, coverage, observation, completion은 비우고 전달된 USER decision만
            유지한 new-goal state입니다.
        """
        return AdaptiveControlState(
            contract=self._contract,
            inventory=self._inventory,
            evidence=(),
            coverage=None,
            execution_status=ExecutionStatus.INCOMPLETE,
            observations=(),
            user_decisions=self._user_decisions,
        )


class _AdaptiveControlEvidenceVerifier:
    """Serialized receipt를 current derived receipt에 exact-match로 재대조합니다."""

    def verify(
        self,
        evidence: Mapping[str, object],
        expected: AdaptiveControlReceipt,
    ) -> None:
        """내부 digest와 current workflow-bound body가 모두 같은 경우만 허용합니다.

        Args:
            evidence: Phase transition이 제출한 serialized adaptive receipt입니다.
            expected: Current workflow snapshot에서 다시 계산한 authoritative receipt입니다.

        Raises:
            InvalidAdaptiveControlEvidence: JSON shape, digest 또는 current body가 다르면
                발생합니다.
        """
        candidate = self._json_object(evidence)
        raw_digest = candidate.pop("evidence_digest", None)
        if not isinstance(raw_digest, str):
            raise InvalidAdaptiveControlEvidence("adaptive evidence digest is missing")
        calculated = AdaptiveControlReceipt._digest_body(candidate)
        if not hmac.compare_digest(raw_digest, calculated):
            raise InvalidAdaptiveControlEvidence("adaptive evidence digest does not match its body")
        expected_evidence = dict(expected.to_evidence())
        expected_digest = expected_evidence.pop("evidence_digest")
        if not isinstance(expected_digest, str):  # pragma: no cover - internal invariant
            raise InvalidAdaptiveControlEvidence("derived adaptive evidence has no digest")
        if not hmac.compare_digest(raw_digest, expected_digest) or candidate != expected_evidence:
            raise InvalidAdaptiveControlEvidence(
                "adaptive evidence does not match the current workflow snapshot"
            )

    def _json_object(self, evidence: Mapping[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(
                dict(evidence),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            decoded: object = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise InvalidAdaptiveControlEvidence(
                "adaptive evidence must be JSON-compatible"
            ) from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise InvalidAdaptiveControlEvidence("adaptive evidence must be a string-keyed object")
        return {str(key): value for key, value in decoded.items()}


class AdaptiveControlStore:
    """Exact workflow SkillStateStore 위에 latest adaptive control snapshot을 제공합니다."""

    _NAMESPACE = "adaptive_control"

    def __init__(self, skill_state: SkillStateStore) -> None:
        """이미 current session/workflow에 고정된 optimistic store를 결속합니다.

        Args:
            skill_state: Exact workflow payload를 optimistic CAS하는 typed backing store입니다.
        """
        self._skill_state = skill_state
        self._codec = _AdaptiveControlCodec()

    def read(self) -> AdaptiveControlSnapshot:
        """Current exact workflow의 latest adaptive control snapshot을 읽습니다.

        Returns:
            Workflow revision과 validated adaptive domain state를 묶은 snapshot입니다.
        """
        return self._snapshot(self._skill_state.read())

    def update(self, mutation: AdaptiveControlMutation) -> AdaptiveControlSnapshot:
        """Pure domain mutation을 latest state에 bounded optimistic retry합니다.

        Args:
            mutation: Conflict retry마다 latest state를 입력받는 side-effect-free transform입니다.

        Returns:
            변경이면 commit된 snapshot, no-op이면 선형화된 current snapshot입니다.
        """
        snapshot = self._skill_state.update(
            _AdaptiveControlNamespaceMutation(
                mutation,
                self._codec,
                self._NAMESPACE,
                self._resource_context(),
            )
        )
        return self._snapshot(snapshot)

    def compare_and_update(
        self,
        expected_workflow_revision: int,
        mutation: AdaptiveControlMutation,
    ) -> AdaptiveControlSnapshot:
        """Caller가 읽은 workflow revision에 pure domain mutation을 한 번만 CAS합니다.

        Args:
            expected_workflow_revision: Caller가 admission에 사용한 workflow-local 원본입니다.
            mutation: Exact 원본 state를 replacement로 바꾸는 side-effect-free transform입니다.

        Returns:
            변경이면 exact 원본에 commit된 snapshot, no-op이면 같은 원본 snapshot입니다.
        """
        snapshot = self._skill_state.compare_and_update(
            expected_workflow_revision,
            _AdaptiveControlNamespaceMutation(
                mutation,
                self._codec,
                self._NAMESPACE,
                self._resource_context(),
            ),
        )
        return self._snapshot(snapshot)

    def compare_and_replace_payload(
        self,
        expected_workflow_revision: int,
        payload: Mapping[str, object],
    ) -> AdaptiveControlSnapshot:
        """Canonical payload를 typed state로 복원한 뒤 exact workflow revision에 CAS합니다.

        Args:
            expected_workflow_revision: Caller가 admission에 사용한 workflow-local 원본입니다.
            payload: Public codec schema를 만족하는 complete replacement object입니다.

        Returns:
            Exact 원본에 commit된 새 adaptive snapshot입니다.

        Raises:
            InvalidAdaptiveControlState: Payload schema 또는 domain invariant가 invalid하면
                발생합니다.
            SkillStateStoreError: Workflow CAS, authority 또는 lifecycle invariant가
                충돌하면 발생합니다.
        """
        candidate = self._codec.decode(payload)
        return self.compare_and_update(
            expected_workflow_revision,
            lambda _current: candidate,
        )

    def compare_and_override_payload(
        self,
        expected_workflow_revision: int,
        payload: Mapping[str, object],
    ) -> AdaptiveControlSnapshot:
        """Current typed candidate를 explicit goal-override transition으로 CAS합니다.

        Args:
            expected_workflow_revision: Override admission에 사용한 workflow-local 원본입니다.
            payload: New goal과 폐기된 old authority를 표현하는 complete current state입니다.

        Returns:
            Explicit override validation을 거쳐 commit된 new-goal snapshot입니다.
        """
        candidate = self._codec.decode(payload)
        snapshot = self._skill_state.compare_and_update(
            expected_workflow_revision,
            _AdaptiveControlNamespaceMutation(
                lambda _current: candidate,
                self._codec,
                self._NAMESPACE,
                self._resource_context(),
                allow_goal_override=True,
            ),
        )
        return self._snapshot(snapshot)

    def override_goal(
        self,
        expected_workflow_revision: int,
        contract: GoalContract,
        *,
        inventory: GapInventory,
        user_decisions: tuple[UserDecision, ...],
    ) -> AdaptiveControlSnapshot:
        """새 goal을 CAS하고 old evidence, coverage, observations, completion을 폐기합니다.

        Args:
            expected_workflow_revision: Goal override를 적용할 workflow-local 원본입니다.
            contract: Override 뒤 유일한 authority 기준이 되는 new goal 계약입니다.
            inventory: New goal의 intent/source revision에서 평가한 complete gap inventory입니다.
            user_decisions: New goal effect에 exact하게 소비되는 typed USER decision입니다.

        Returns:
            Old completion authority가 제거된 new-goal adaptive snapshot입니다.
        """
        snapshot = self._skill_state.compare_and_update(
            expected_workflow_revision,
            _AdaptiveControlNamespaceMutation(
                _GoalOverrideMutation(contract, inventory, user_decisions),
                self._codec,
                self._NAMESPACE,
                self._resource_context(),
                allow_goal_override=True,
            ),
        )
        return self._snapshot(snapshot)

    def _resource_context(self) -> _EfficiencyResourceContext:
        """Current workflow owner의 latest material batch를 admission input으로 읽습니다."""
        state = self._skill_state.read_process_state()
        workflow = state.workflows.get(self._skill_state.workflow_id)
        if workflow is None:  # pragma: no cover - backing store already validates this
            raise AdaptiveControlStateMissing("adaptive workflow is missing")
        actor_id = workflow.owner_actor_id
        return _EfficiencyResourceContext(
            session_id=str(state.session.id),
            actor_id=str(actor_id),
            workflow_id=str(workflow.id),
            workflow_revision=workflow.revision,
            material_batch=state.material_actions.get(actor_id),
        )

    def receipt(self, policy: ReflectionPolicy | None = None) -> AdaptiveControlReceipt:
        """Current exact workflow snapshot의 ReflectionPolicy decision receipt를 반환합니다.

        Args:
            policy: Current observation history에 적용할 reflection 판정 기준입니다.

        Returns:
            Latest snapshot에서 재현 가능하게 계산한 workflow-bound receipt입니다.
        """
        return self.read().receipt(policy)

    def verify_evidence(
        self,
        evidence: Mapping[str, object],
        policy: ReflectionPolicy | None = None,
    ) -> AdaptiveControlReceipt:
        """Phase evidence를 current workflow snapshot에서 재계산한 receipt와 대조합니다.

        Args:
            evidence: Phase transition이 제출한 serialized adaptive decision receipt입니다.
            policy: 제출 receipt와 동일하게 적용해야 하는 reflection 판정 기준입니다.

        Returns:
            Submitted body와 exact-match한 current authoritative receipt입니다.
        """
        current = self.receipt(policy)
        _AdaptiveControlEvidenceVerifier().verify(evidence, current)
        return current

    def _snapshot(self, snapshot: SkillStateSnapshot) -> AdaptiveControlSnapshot:
        raw_state = snapshot.skill_state.get(self._NAMESPACE)
        if raw_state is None:
            raise AdaptiveControlStateMissing("workflow has no adaptive_control snapshot")
        if not isinstance(raw_state, Mapping):
            raise InvalidAdaptiveControlState("skill_state.adaptive_control must be an object")
        return AdaptiveControlSnapshot(
            workflow_id=snapshot.workflow_id,
            workflow_revision=snapshot.workflow_revision,
            state=self._codec.decode(raw_state),
        )
