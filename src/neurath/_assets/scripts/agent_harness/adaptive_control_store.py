"""Persist adaptive changes through the owning workflow CAS boundary."""

from __future__ import annotations

import hmac
import json
from collections.abc import (
    Callable,
    Mapping,
)
from typing import (
    TYPE_CHECKING,
)

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
from scripts.agent_harness.adaptive_resource_admission import (
    _EfficiencyAdmissionFactory,
    _EfficiencyResourceContext,
    validate_efficiency_resource_admission,
)
from scripts.agent_harness.adaptive_state import (
    AdaptiveControlReceipt,
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    AdaptiveControlStateMissing,
    AdaptiveControlStoreError,
    InvalidAdaptiveControlEvidence,
    InvalidAdaptiveControlState,
)
from scripts.agent_harness.adaptive_state_codec import (
    EnumValue,
    _AdaptiveControlCodec,
)
from scripts.agent_harness.adaptive_transition import (
    validate_adaptive_control_transition,
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
from scripts.agent_harness.material_action import (
    MaterialActionBatch,
)
from scripts.agent_harness.skill_state_contract import (
    SkillStateReservedMutation,
    SkillStateStoreError,
)

if TYPE_CHECKING:
    from scripts.agent_harness.skill_state_store import (
        SkillStateSnapshot,
        SkillStateStore,
    )

__all__ = [
    "AdaptiveControlMutation",
    "AdaptiveControlReceipt",
    "AdaptiveControlSnapshot",
    "AdaptiveControlState",
    "AdaptiveControlStateMissing",
    "AdaptiveControlStore",
    "AdaptiveControlStoreError",
    "AmbiguityAssessment",
    "AuthoritativeResourceDelta",
    "AuthorityReceipt",
    "ClarificationGap",
    "ControlAction",
    "ControlDecision",
    "CriterionEvidence",
    "CriterionSpec",
    "EfficiencyAssessment",
    "EfficiencyAssessor",
    "EfficiencyStatus",
    "EnumValue",
    "EvidenceAuthority",
    "EvidenceKind",
    "EvidenceStatus",
    "ExecutionStatus",
    "GapAuthority",
    "GapInventory",
    "GapResolution",
    "GoalAttainment",
    "GoalAttainmentReadback",
    "GoalContract",
    "GoalCoverage",
    "InvalidAdaptiveControlEvidence",
    "InvalidAdaptiveControlState",
    "IterationObservation",
    "MaterialActionBatch",
    "OracleOwner",
    "ReflectionPolicy",
    "RequirementSection",
    "ResourceMetricDelta",
    "ResourceTelemetryStatus",
    "SkillStateReservedMutation",
    "SkillStateStoreError",
    "UserDecision",
    "UserDecisionClaim",
    "UserDecisionDisposition",
    "UserDecisionProvenance",
    "UserDecisionTarget",
    "UserDeferral",
    "VerifiedGoalAttainmentDelta",
    "adaptive_output_fingerprint",
    "assess_ambiguity",
    "assess_goal_attainment",
    "effective_criterion_evidence",
    "validate_adaptive_control_transition",
    "validate_efficiency_resource_admission",
]


type AdaptiveControlMutation = Callable[[AdaptiveControlState | None], AdaptiveControlState]


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
