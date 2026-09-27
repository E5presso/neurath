"""Pure admission rules for changes to the adaptive aggregate."""

from __future__ import annotations

from scripts.agent_harness.adaptive_control import (
    ClarificationGap,
    ControlAction,
    CriterionEvidence,
    EvidenceKind,
    ExecutionStatus,
    GapAuthority,
    GapInventory,
    GapResolution,
    GoalCoverage,
    IterationObservation,
    ReflectionPolicy,
    UserDecisionTarget,
    adaptive_output_fingerprint,
    assess_ambiguity,
    assess_goal_attainment,
)
from scripts.agent_harness.adaptive_state import (
    AdaptiveControlState,
    InvalidAdaptiveControlState,
    _StoreAdmittedReflectionDecision,
)


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
