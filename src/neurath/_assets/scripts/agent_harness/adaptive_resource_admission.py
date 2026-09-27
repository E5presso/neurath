"""Derive and verify efficiency authority from consecutive adaptive snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import (
    Mapping,
)
from dataclasses import (
    dataclass,
    replace,
)

from scripts.agent_harness.adaptive_control import (
    EvidenceAuthority,
    EvidenceStatus,
    ExecutionStatus,
    effective_criterion_evidence,
)
from scripts.agent_harness.adaptive_state import (
    AdaptiveControlState,
    InvalidAdaptiveControlState,
)
from scripts.agent_harness.efficiency_assessment import (
    AuthoritativeResourceDelta,
    EfficiencyAssessor,
    GoalAttainmentReadback,
    ResourceMetricDelta,
    ResourceTelemetryStatus,
    VerifiedGoalAttainmentDelta,
)
from scripts.agent_harness.material_action import (
    MaterialActionBatch,
)


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
            sorted(
                {
                    execution_unit,
                    *coverage_units,
                    *(
                        f"{criterion.criterion_id}:{kind.value}"
                        for criterion in state.contract.criteria
                        for kind in criterion.required_evidence
                    ),
                }
            )
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
        return frozenset(
            {
                "goal-coverage:authority",
                "goal-coverage:goal-alignment",
                "goal-coverage:reward-hacking-risk",
                "goal-coverage:semantic-drift",
                "goal-coverage:semantic-uncertainty",
            }
        )

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
