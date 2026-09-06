"""Admitted 목표 readback과 자원 receipt를 가중치 없이 비교합니다.

이 boundary는 이미 runtime/store admission을 통과한 receipt의 shape와 revision continuity만
검증합니다. Source와 digest가 실제 runtime 산출물인지 확인하는 authenticity admission은 해당
runtime/store boundary의 책임이며 이 순수 계약이 대신하지 않습니다.
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class ResourceTelemetryStatus(StrEnum):
    """자원 계측값이 효율 판정에 쓰일 수 있는 현재 상태입니다."""

    VERIFIED = "verified"
    """Runtime admission을 통과한 receipt가 소비량을 현재 basis에 결속한 상태입니다."""
    UNAVAILABLE = "unavailable"
    """해당 소비량을 계측할 수 없어 0으로 대체하면 안 되는 상태입니다."""
    STALE = "stale"
    """계측값은 있지만 현재 generation 또는 basis에 적용할 수 없는 상태입니다."""
    NONCOMPARABLE = "noncomparable"
    """단위나 수집 경계가 달라 동일 resource basis에서 비교할 수 없는 상태입니다."""


class EfficiencyStatus(StrEnum):
    """목표 변화와 자원 벡터의 결합에서 파생되는 효율 증거 상태입니다."""

    PROVEN = "proven"
    """양의 목표 변화와 모든 resource dimension의 current 계측이 존재합니다."""
    PARTIALLY_PROVEN = "partially_proven"
    """양의 목표 변화와 일부 current 계측이 있으며 누락 dimension은 명시적입니다."""
    UNPROVEN = "unproven"
    """양의 목표 변화는 있지만 current resource dimension을 하나도 계측하지 못했습니다."""
    NONCOMPARABLE = "noncomparable"
    """양의 목표 변화는 있지만 stale하거나 basis가 다른 자원 계측이 섞였습니다."""
    ZERO_PROGRESS = "zero_progress"
    """소비 자원 크기와 무관하게 검증된 목표 변화가 양수가 아닌 상태입니다."""


class EfficiencyComparison(StrEnum):
    """가중치 없는 goal-resource Pareto 비교 결과입니다."""

    LEFT_DOMINATES = "left_dominates"
    """왼쪽이 목표 변화에서 열등하지 않고 모든 자원 소비에서 우월하거나 같습니다."""
    RIGHT_DOMINATES = "right_dominates"
    """오른쪽이 목표 변화에서 열등하지 않고 모든 자원 소비에서 우월하거나 같습니다."""
    EQUIVALENT = "equivalent"
    """Goal delta와 모든 resource dimension이 정확히 같습니다."""
    NONCOMPARABLE = "noncomparable"
    """Basis, telemetry 상태 또는 Pareto trade-off 때문에 어느 쪽도 지배하지 않습니다."""


class EvaluatorGenerationAction(StrEnum):
    """현재 evaluator generation 뒤에 허용되는 제어 action입니다."""

    CONTINUE = "continue"
    """검증된 목표 변화나 material blocker가 남아 다음 generation을 허용합니다."""
    CHANGE_APPROACH = "change_approach"
    """0 변화 또는 반복 원인 때문에 같은 접근의 다음 generation을 금지합니다."""
    EXHAUSTED = "exhausted"
    """Emergency watchdog이 소진되어 성공을 주장하지 않고 실행을 중단합니다."""


@dataclass(frozen=True, slots=True)
class ResourceMetricDelta:
    """하나의 resource dimension에서 실제 generation이 소비한 양입니다."""

    status: ResourceTelemetryStatus
    """값의 current authority와 비교 가능성을 나타내는 closed 상태입니다."""
    value: int | None
    """Unavailable을 제외한 receipt-backed 상태에서 존재하는 0 이상의 소비량입니다."""
    source_id: str | None
    """계측값을 실제로 관찰한 runtime 또는 provider source identity입니다."""
    receipt_reference: str | None
    """현재 generation의 원본 runtime receipt를 다시 읽을 수 있는 reference입니다."""
    receipt_digest: str | None
    """Reference가 가리키는 current receipt payload의 SHA-256 digest입니다."""

    def __post_init__(self) -> None:
        """계측 누락과 실제 0을 구조적으로 구분합니다.

        Raises:
            TypeError: Status 또는 receipt-backed 값이 선언된 type과 다를 때 발생합니다.
            ValueError: Receipt-backed 상태의 authority가 없거나 unavailable에 값 또는
                authority가 섞일 때 발생합니다.
        """
        if not isinstance(self.status, ResourceTelemetryStatus):
            raise TypeError("status must be a ResourceTelemetryStatus")
        if self.status is ResourceTelemetryStatus.UNAVAILABLE:
            if any(
                item is not None
                for item in (
                    self.value,
                    self.source_id,
                    self.receipt_reference,
                    self.receipt_digest,
                )
            ):
                raise ValueError("unavailable resource metric must not carry value or authority")
            return
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise TypeError("receipt-backed resource metric must have an integer value")
        if self.value < 0:
            raise ValueError("receipt-backed resource metric must have a non-negative value")
        if (
            self.source_id is None
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
                self.source_id,
            )
            is None
        ):
            raise ValueError("receipt-backed resource metric must have a stable source_id")
        if (
            self.receipt_reference is None
            or re.fullmatch(
                r"\S{1,256}",
                self.receipt_reference,
            )
            is None
        ):
            raise ValueError("receipt-backed resource metric must have a receipt_reference")
        if (
            self.receipt_digest is None
            or re.fullmatch(
                r"[0-9a-f]{64}",
                self.receipt_digest,
            )
            is None
        ):
            raise ValueError("receipt-backed resource metric must have a SHA-256 receipt_digest")


@dataclass(frozen=True, slots=True)
class GoalAttainmentReadback:
    """한 evaluation revision의 exact evidence 상태와 authority receipt입니다."""

    goal_fingerprint: str
    """Readback이 판정한 immutable goal boundary의 SHA-256 fingerprint입니다."""
    evidence_basis_fingerprint: str
    """Criterion과 evidence-surface identity 집합을 고정한 SHA-256 fingerprint입니다."""
    evaluation_revision: int
    """Append-only evaluation history에서 이 readback의 정확한 revision입니다."""
    settled_evidence_units: frozenset[str]
    """현재 revision에서 모든 authority를 통과한 exact criterion/surface identity입니다."""
    failed_evidence_units: frozenset[str]
    """현재 revision에서 authoritative FAIL인 exact criterion/surface identity입니다."""
    reopened_evidence_units: frozenset[str]
    """Challenge나 regression으로 다시 열린 exact criterion/surface identity입니다."""
    authority_source_id: str
    """Readback을 발행한 canonical store 또는 evaluator source identity입니다."""
    readback_reference: str
    """Current source payload를 다시 조회할 수 있는 opaque reference입니다."""
    receipt_digest: str
    """Reference가 가리키는 immutable readback payload의 SHA-256 digest입니다."""
    open_blocker_ids: frozenset[str] = frozenset()
    """Current revision에서 목표 수렴을 막는 authoritative blocker identity입니다."""

    def __post_init__(self) -> None:
        """Self-attested count 대신 exact revisioned authority surface를 검증합니다.

        Raises:
            TypeError: Revision 또는 evidence 상태 집합이 declared type과 다를 때 발생합니다.
            ValueError: Fingerprint, revision, evidence identity, 상태 배타성 또는 authority
                receipt가 readback 계약과 다를 때 발생합니다.
        """
        self._require_digest(self.goal_fingerprint, "goal_fingerprint")
        self._require_digest(self.evidence_basis_fingerprint, "evidence_basis_fingerprint")
        if not isinstance(self.evaluation_revision, int) or isinstance(
            self.evaluation_revision,
            bool,
        ):
            raise TypeError("evaluation_revision must be an integer")
        if self.evaluation_revision < 1:
            raise ValueError("evaluation_revision must be positive")
        evidence_sets = (
            self.settled_evidence_units,
            self.failed_evidence_units,
            self.reopened_evidence_units,
        )
        if any(not isinstance(items, frozenset) for items in evidence_sets):
            raise TypeError("evidence unit collections must be frozensets")
        for identity in set().union(*evidence_sets):
            if not isinstance(identity, str) or re.fullmatch(r"\S{1,256}", identity) is None:
                raise ValueError("evidence unit must be a stable opaque identity")
        if (
            self.settled_evidence_units & self.failed_evidence_units
            or self.settled_evidence_units & self.reopened_evidence_units
            or self.failed_evidence_units & self.reopened_evidence_units
        ):
            raise ValueError("evidence unit states must be pairwise disjoint")
        if not isinstance(self.open_blocker_ids, frozenset):
            raise TypeError("open_blocker_ids must be a frozenset")
        for identity in self.open_blocker_ids:
            if not isinstance(identity, str) or re.fullmatch(r"\S{1,256}", identity) is None:
                raise ValueError("open blocker must be a stable opaque identity")
        if (
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
                self.authority_source_id,
            )
            is None
        ):
            raise ValueError("authority_source_id must be a stable identity")
        if re.fullmatch(r"\S{1,256}", self.readback_reference) is None:
            raise ValueError("readback_reference must be a stable opaque identity")
        self._require_digest(self.receipt_digest, "receipt_digest")

    def _require_digest(self, value: str, label: str) -> None:
        """Goal 비교 identity가 canonical SHA-256인지 검증합니다.

        Args:
            value: Authority boundary에서 전달된 fingerprint 문자열입니다.
            label: 잘못된 field를 식별하는 안정적인 계약 이름입니다.

        Raises:
            ValueError: 전달된 identity가 소문자 SHA-256 형식이 아닐 때 발생합니다.
        """
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"{label} must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class VerifiedGoalAttainmentDelta:
    """연속된 authoritative readback 두 개에서만 파생되는 goal 변화입니다."""

    before: GoalAttainmentReadback
    """Material generation 직전의 exact evidence-state readback입니다."""
    after: GoalAttainmentReadback
    """Material generation 직후의 exact next-revision evidence-state readback입니다."""

    def __post_init__(self) -> None:
        """Goal/basis continuity와 exact next evaluation revision을 검증합니다.

        Raises:
            ValueError: Goal, evidence basis, authority source, revision continuity 또는 receipt
                freshness가 서로 다른 readback을 결합할 때 발생합니다.
        """
        if self.before.goal_fingerprint != self.after.goal_fingerprint:
            raise ValueError("goal readbacks must have the same goal_fingerprint")
        if self.before.evidence_basis_fingerprint != self.after.evidence_basis_fingerprint:
            raise ValueError("goal readbacks must have the same evidence basis")
        if self.before.authority_source_id != self.after.authority_source_id:
            raise ValueError("goal readbacks must have the same authority source")
        if self.after.evaluation_revision != self.before.evaluation_revision + 1:
            raise ValueError("goal readbacks must use exact consecutive evaluation revisions")
        if self.before.readback_reference == self.after.readback_reference:
            raise ValueError("goal readbacks must have distinct readback references")
        if self.before.receipt_digest == self.after.receipt_digest:
            raise ValueError("goal readbacks must have distinct receipt digests")
        removed_settled = self.before.settled_evidence_units - self.after.settled_evidence_units
        if not removed_settled.issubset(
            self.after.failed_evidence_units | self.after.reopened_evidence_units
        ):
            raise ValueError("removed settled evidence must be failed or reopened")
        removed_failed = self.before.failed_evidence_units - self.after.failed_evidence_units
        if not removed_failed.issubset(
            self.after.settled_evidence_units | self.after.reopened_evidence_units
        ):
            raise ValueError("removed failed evidence must be settled or reopened")
        removed_reopened = self.before.reopened_evidence_units - self.after.reopened_evidence_units
        if not removed_reopened.issubset(
            self.after.settled_evidence_units | self.after.failed_evidence_units
        ):
            raise ValueError("removed reopened evidence must be settled or failed")

    @property
    def goal_fingerprint(self) -> str:
        """두 readback이 공유하는 immutable goal identity를 반환합니다.

        Returns:
            Before/after continuity 검사로 고정된 SHA-256 goal fingerprint입니다.
        """
        return self.after.goal_fingerprint

    @property
    def evidence_basis_fingerprint(self) -> str:
        """두 readback이 공유하는 exact evidence basis identity를 반환합니다.

        Returns:
            Criterion/evidence-surface universe를 고정한 SHA-256 fingerprint입니다.
        """
        return self.after.evidence_basis_fingerprint

    @property
    def newly_settled_evidence_units(self) -> frozenset[str]:
        """Current generation에서 새로 authoritative PASS가 된 단위를 반환합니다.

        Returns:
            After settled 집합에서 before settled 집합을 제외한 exact identity입니다.
        """
        return self.after.settled_evidence_units - self.before.settled_evidence_units

    @property
    def newly_failed_evidence_units(self) -> frozenset[str]:
        """Current generation에서 새로 authoritative FAIL이 된 단위를 반환합니다.

        Returns:
            After failed 집합에서 before failed 집합을 제외한 exact identity입니다.
        """
        return self.after.failed_evidence_units - self.before.failed_evidence_units

    @property
    def newly_reopened_evidence_units(self) -> frozenset[str]:
        """Current generation에서 challenge나 regression으로 다시 열린 단위를 반환합니다.

        Returns:
            After reopened 집합에서 before reopened 집합을 제외한 exact identity입니다.
        """
        return self.after.reopened_evidence_units - self.before.reopened_evidence_units

    @property
    def resolved_blocker_ids(self) -> frozenset[str]:
        """Current generation이 authoritative readback에서 제거한 blocker를 반환합니다.

        Returns:
            Before에는 open이었지만 after에는 남지 않은 exact blocker identity입니다.
        """
        return self.before.open_blocker_ids - self.after.open_blocker_ids

    @property
    def newly_opened_blocker_ids(self) -> frozenset[str]:
        """Current generation에서 새로 생긴 authoritative blocker를 반환합니다.

        Returns:
            After에 새로 등장했지만 before에는 없던 exact blocker identity입니다.
        """
        return self.after.open_blocker_ids - self.before.open_blocker_ids

    @property
    def progress_units(self) -> frozenset[str]:
        """서로 환산하지 않은 exact goal-progress identity를 반환합니다.

        Returns:
            Evidence settlement와 blocker resolution을 namespace로 구분한 집합입니다.
        """
        return frozenset({
            *(f"evidence:{identity}" for identity in self.newly_settled_evidence_units),
            *(f"blocker:{identity}" for identity in self.resolved_blocker_ids),
        })

    @property
    def has_regression(self) -> bool:
        """새 failure 또는 reopen이 goal progress와 함께 숨겨졌는지 반환합니다.

        Returns:
            새 authoritative failure나 reopened evidence가 하나라도 있으면 참입니다.
        """
        return bool(
            self.newly_failed_evidence_units
            or self.newly_reopened_evidence_units
            or self.newly_opened_blocker_ids
        )

    @property
    def has_material_progress(self) -> bool:
        """Regression 없이 criterion이나 blocker 축에서 전진했는지 반환합니다.

        Returns:
            Exact progress unit이 있고 새 failure, reopen, blocker가 없을 때만 참입니다.
        """
        return bool(self.progress_units) and not self.has_regression

    @property
    def delta_units(self) -> int:
        """Progress과 regression 개수를 남기는 진단용 net 변화를 반환합니다.

        Returns:
            Progress unit 개수에서 failure, reopen, new blocker 개수를 뺀 값입니다.
            이 값은 다른 종류의 goal unit을 효율 비교에서 환산하지 않습니다.
        """
        return (
            len(self.progress_units)
            - len(self.newly_failed_evidence_units)
            - len(self.newly_reopened_evidence_units)
            - len(self.newly_opened_blocker_ids)
        )


@dataclass(frozen=True, slots=True)
class AuthoritativeResourceDelta:
    """동일 수집 basis에서 generation 하나가 소비한 다차원 자원 벡터입니다."""

    basis_fingerprint: str
    """단위, 계측 구간과 runtime source를 함께 고정한 SHA-256 fingerprint입니다."""
    wall_clock_milliseconds: ResourceMetricDelta
    """Generation 전체의 authoritative wall-clock이며 per-tool duration만으로 채우지 않습니다."""
    tool_invocations: ResourceMetricDelta
    """Runtime이 관찰한 tool invocation 소비량입니다."""
    input_tokens: ResourceMetricDelta
    """Provider가 노출한 input token 소비량이며 누락 시 unavailable입니다."""
    output_tokens: ResourceMetricDelta
    """Provider가 노출한 output token 소비량이며 누락 시 unavailable입니다."""
    evaluator_generations: ResourceMetricDelta
    """Current evaluation lineage에서 소비한 evaluator generation 수입니다."""

    def __post_init__(self) -> None:
        """Resource 비교 basis가 canonical identity인지 검증합니다.

        Raises:
            ValueError: Basis가 소문자 SHA-256 fingerprint가 아닐 때 발생합니다.
        """
        if re.fullmatch(r"[0-9a-f]{64}", self.basis_fingerprint) is None:
            raise ValueError("basis_fingerprint must be a SHA-256 digest")

    @property
    def metrics(self) -> tuple[ResourceMetricDelta, ...]:
        """고정된 resource dimension 순서의 전체 계측 벡터를 반환합니다.

        Returns:
            Wall-clock, tool, input token, output token, evaluator 순서의 metric입니다.
        """
        return (
            self.wall_clock_milliseconds,
            self.tool_invocations,
            self.input_tokens,
            self.output_tokens,
            self.evaluator_generations,
        )

    @property
    def verified_vector(self) -> tuple[int, ...] | None:
        """Verified dimension만 availability 순서대로 Pareto 비용 벡터로 반환합니다.

        Returns:
            최소 한 값이 current이면 고정 순서의 부분 비용 벡터, 아니면 `None`입니다.
        """
        if any(
            item.status
            not in {ResourceTelemetryStatus.VERIFIED, ResourceTelemetryStatus.UNAVAILABLE}
            for item in self.metrics
        ):
            return None
        values = tuple(
            item.value
            for item in self.metrics
            if item.status is ResourceTelemetryStatus.VERIFIED and item.value is not None
        )
        return values or None

    @property
    def availability_mask(self) -> tuple[bool, ...]:
        """고정 resource dimension별 current VERIFIED 존재 여부를 반환합니다.

        Returns:
            Wall-clock, tool, input, output, evaluator 순서의 boolean mask입니다.
        """
        return tuple(item.status is ResourceTelemetryStatus.VERIFIED for item in self.metrics)


@dataclass(frozen=True, slots=True)
class EfficiencyAssessment:
    """한 generation의 goal delta와 resource delta를 보존한 비율 없는 판정입니다."""

    goal_delta: VerifiedGoalAttainmentDelta
    """비용과 독립적으로 보존되는 externally verified 목표 변화입니다."""
    resource_delta: AuthoritativeResourceDelta
    """가중 합산하지 않는 current resource consumption 벡터입니다."""
    status: EfficiencyStatus
    """목표 수렴과 telemetry 완전성에서 파생한 closed evidence 상태입니다."""
    reason: str
    """상태를 goal delta 또는 telemetry 사실로 설명하는 결정 근거입니다."""

    @property
    def requires_approach_change(self) -> bool:
        """검증된 목표 변화가 양수가 아닌 generation인지 반환합니다.

        Returns:
            같은 접근을 반복하면 안 되는 `ZERO_PROGRESS` 상태에서만 참입니다.
        """
        return self.status is EfficiencyStatus.ZERO_PROGRESS


class EfficiencyAssessor:
    """목표 변화 우선으로 resource telemetry의 증거 상태를 판정합니다."""

    def assess(
        self,
        goal_delta: VerifiedGoalAttainmentDelta,
        resource_delta: AuthoritativeResourceDelta,
    ) -> EfficiencyAssessment:
        """비용 크기를 성공 대리값으로 쓰지 않고 한 generation을 판정합니다.

        Args:
            goal_delta: 동일 goal/evidence basis에서 검증된 달성 단위 변화입니다.
            resource_delta: 동일 runtime basis에서 수집한 자원 소비 벡터입니다.

        Returns:
            목표 변화와 원래 자원 벡터를 잃지 않는 efficiency evidence입니다.
        """
        if not goal_delta.has_material_progress:
            return EfficiencyAssessment(
                goal_delta,
                resource_delta,
                EfficiencyStatus.ZERO_PROGRESS,
                "verified goal attainment did not increase without regression",
            )
        statuses = frozenset(item.status for item in resource_delta.metrics)
        if statuses & {
            ResourceTelemetryStatus.STALE,
            ResourceTelemetryStatus.NONCOMPARABLE,
        }:
            return EfficiencyAssessment(
                goal_delta,
                resource_delta,
                EfficiencyStatus.NONCOMPARABLE,
                "resource telemetry is stale or uses a noncomparable basis",
            )
        verified_count = sum(
            item.status is ResourceTelemetryStatus.VERIFIED for item in resource_delta.metrics
        )
        if verified_count == 0:
            return EfficiencyAssessment(
                goal_delta,
                resource_delta,
                EfficiencyStatus.UNPROVEN,
                "goal progress is verified but all resource telemetry is unavailable",
            )
        if ResourceTelemetryStatus.UNAVAILABLE in statuses:
            return EfficiencyAssessment(
                goal_delta,
                resource_delta,
                EfficiencyStatus.PARTIALLY_PROVEN,
                "goal progress and a partial current resource vector are verified",
            )
        return EfficiencyAssessment(
            goal_delta,
            resource_delta,
            EfficiencyStatus.PROVEN,
            "positive goal delta and complete resource telemetry are present",
        )


class EfficiencyComparator:
    """동일 goal과 resource basis에서만 Pareto dominance를 판정합니다."""

    def compare(
        self,
        left: EfficiencyAssessment,
        right: EfficiencyAssessment,
    ) -> EfficiencyComparison:
        """임의 가중치나 goal 간 환산 없이 두 generation을 비교합니다.

        Args:
            left: 비교할 첫 번째 generation의 efficiency evidence입니다.
            right: 비교할 두 번째 generation의 efficiency evidence입니다.

        Returns:
            한쪽의 Pareto dominance, 완전 동등 또는 비교 불가 상태입니다.
        """
        if not self._has_same_basis(left, right):
            return EfficiencyComparison.NONCOMPARABLE
        comparable_statuses = {
            EfficiencyStatus.PROVEN,
            EfficiencyStatus.PARTIALLY_PROVEN,
        }
        if left.status not in comparable_statuses:
            return EfficiencyComparison.NONCOMPARABLE
        if right.status not in comparable_statuses:
            return EfficiencyComparison.NONCOMPARABLE
        if left.resource_delta.availability_mask != right.resource_delta.availability_mask:
            return EfficiencyComparison.NONCOMPARABLE
        left_resources = left.resource_delta.verified_vector
        right_resources = right.resource_delta.verified_vector
        if left_resources is None or right_resources is None:
            return EfficiencyComparison.NONCOMPARABLE
        left_goal = left.goal_delta.progress_units
        right_goal = right.goal_delta.progress_units
        left_dominates = self._dominates(
            left_goal,
            left_resources,
            right_goal,
            right_resources,
        )
        right_dominates = self._dominates(
            right_goal,
            right_resources,
            left_goal,
            left_resources,
        )
        if left_dominates:
            return EfficiencyComparison.LEFT_DOMINATES
        if right_dominates:
            return EfficiencyComparison.RIGHT_DOMINATES
        if left_goal == right_goal and left_resources == right_resources:
            return EfficiencyComparison.EQUIVALENT
        return EfficiencyComparison.NONCOMPARABLE

    def _has_same_basis(
        self,
        left: EfficiencyAssessment,
        right: EfficiencyAssessment,
    ) -> bool:
        """두 assessment가 같은 goal, evidence와 resource basis인지 확인합니다.

        Args:
            left: 첫 번째 generation의 세 identity를 제공합니다.
            right: 두 번째 generation의 세 identity를 제공합니다.

        Returns:
            Goal, evidence와 resource fingerprint가 모두 같을 때만 참입니다.
        """
        return (
            left.goal_delta.goal_fingerprint == right.goal_delta.goal_fingerprint
            and left.goal_delta.evidence_basis_fingerprint
            == right.goal_delta.evidence_basis_fingerprint
            and left.resource_delta.basis_fingerprint == right.resource_delta.basis_fingerprint
        )

    def _dominates(
        self,
        candidate_goal: frozenset[str],
        candidate_resources: tuple[int, ...],
        other_goal: frozenset[str],
        other_resources: tuple[int, ...],
    ) -> bool:
        """목표는 높을수록, 각 자원은 낮을수록 좋은 Pareto 관계를 확인합니다.

        Args:
            candidate_goal: 지배 후보가 추가한 exact 검증 목표 identity 집합입니다.
            candidate_resources: 지배 후보의 고정 차원 비용 벡터입니다.
            other_goal: 비교 대상이 추가한 exact 검증 목표 identity 집합입니다.
            other_resources: 비교 대상의 동일 차원 비용 벡터입니다.

        Returns:
            후보가 모든 축에서 열등하지 않고 최소 한 축에서 우월할 때 참입니다.
        """
        no_worse = candidate_goal.issuperset(other_goal) and all(
            candidate <= other
            for candidate, other in zip(
                candidate_resources,
                other_resources,
                strict=True,
            )
        )
        strictly_better = candidate_goal > other_goal or any(
            candidate < other
            for candidate, other in zip(
                candidate_resources,
                other_resources,
                strict=True,
            )
        )
        return no_worse and strictly_better


@dataclass(frozen=True, slots=True)
class EvaluatorGenerationDecision:
    """Evaluator 횟수가 아니라 goal delta에서 파생된 non-success action입니다."""

    action: EvaluatorGenerationAction
    """Current generation 뒤에 허용되는 loop lifecycle action입니다."""
    achieved: bool
    """Generation policy가 completion authority를 갖지 않으므로 항상 거짓입니다."""
    reason: str
    """Goal, repetition 또는 watchdog 사실에 결속된 결정 근거입니다."""

    def __post_init__(self) -> None:
        """Generation policy가 success authority를 위조하지 못하게 닫습니다.

        Raises:
            TypeError: Action 또는 achieved가 declared closed type과 다를 때 발생합니다.
            ValueError: Achieved가 참이거나 결정 근거가 비어 있을 때 발생합니다.
        """
        if not isinstance(self.action, EvaluatorGenerationAction):
            raise TypeError("action must be an EvaluatorGenerationAction")
        if not isinstance(self.achieved, bool):
            raise TypeError("achieved must be a boolean")
        if self.achieved:
            raise ValueError("evaluator generation policy cannot claim goal achievement")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be non-empty")


class EvaluatorGenerationPolicy:
    """Completion은 소유하지 않고 목표 수렴과 watchdog으로 다음 generation만 제어합니다."""

    def decide(
        self,
        *,
        generation: int,
        efficiency: EfficiencyAssessment,
        has_material_blocker: bool,
        repeated_root_cause: bool,
        repeated_approach: bool,
        watchdog_exhausted: bool,
    ) -> EvaluatorGenerationDecision:
        """Current generation의 authoritative next action을 판정합니다.

        Args:
            generation: 감사와 monotonic ordering에만 쓰는 1 이상의 회차입니다.
            efficiency: 목표 변화와 resource telemetry를 분리해 보존한 판정입니다.
            has_material_blocker: Frozen acceptance에 남은 blocking finding 여부입니다.
            repeated_root_cause: 같은 실패 원인이 generation을 넘어 재발했는지 여부입니다.
            repeated_approach: 같은 접근 fingerprint가 변화 없이 반복됐는지 여부입니다.
            watchdog_exhausted: Emergency 실행 상한이 소진됐는지 여부입니다.

        Returns:
            계속, 접근 변경 또는 성공 아닌 소진 상태입니다.

        Raises:
            TypeError: Generation이 bool을 포함한 정수가 아닐 때 발생합니다.
            ValueError: Generation이 양의 정수가 아닐 때 발생합니다.
        """
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise TypeError("generation must be an integer")
        if generation < 1:
            raise ValueError("generation must be a positive integer")
        if watchdog_exhausted:
            return EvaluatorGenerationDecision(
                EvaluatorGenerationAction.EXHAUSTED,
                False,
                "emergency watchdog exhausted without goal completion",
            )
        if repeated_root_cause or repeated_approach:
            return EvaluatorGenerationDecision(
                EvaluatorGenerationAction.CHANGE_APPROACH,
                False,
                "root cause or approach repeated across generations",
            )
        if efficiency.requires_approach_change:
            return EvaluatorGenerationDecision(
                EvaluatorGenerationAction.CHANGE_APPROACH,
                False,
                "generation consumed resources without verified goal progress",
            )
        if has_material_blocker or efficiency.goal_delta.has_material_progress:
            return EvaluatorGenerationDecision(
                EvaluatorGenerationAction.CONTINUE,
                False,
                "material blocker or verified criterion delta remains",
            )
        return EvaluatorGenerationDecision(
            EvaluatorGenerationAction.CHANGE_APPROACH,
            False,
            "no material convergence signal remains",
        )
