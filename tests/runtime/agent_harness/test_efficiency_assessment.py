"""목표 달성 변화와 자원 소비를 분리한 효율 계약을 검증합니다."""

import hashlib
import unittest

from scripts.agent_harness.efficiency_assessment import (
    AuthoritativeResourceDelta,
    EfficiencyAssessor,
    EfficiencyComparator,
    EfficiencyComparison,
    EfficiencyStatus,
    EvaluatorGenerationAction,
    EvaluatorGenerationDecision,
    EvaluatorGenerationPolicy,
    GoalAttainmentReadback,
    ResourceMetricDelta,
    ResourceTelemetryStatus,
    VerifiedGoalAttainmentDelta,
)


class EfficiencyAssessmentTest(unittest.TestCase):
    """비용 최소화가 목표 수렴을 대신하지 못하도록 닫힌 판정을 검증합니다."""

    def test_eff_01_low_cost_with_zero_goal_delta_requires_approach_change(self) -> None:
        """아주 적은 자원을 썼어도 검증된 목표 변화가 0이면 실패한 generation입니다."""
        assessment = EfficiencyAssessor().assess(
            self._goal_delta(before=2, after=2),
            self._resources(wall_clock=1, tool_invocations=1, input_tokens=1, output_tokens=1),
        )

        self.assertEqual(EfficiencyStatus.ZERO_PROGRESS, assessment.status)
        self.assertTrue(assessment.requires_approach_change)

    def test_eff_02_high_cost_with_material_goal_delta_is_not_automatically_waste(self) -> None:
        """비용이 커도 검증된 목표 변화가 있으면 비용 크기만으로 실패 처리하지 않습니다."""
        assessment = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=3),
            self._resources(
                wall_clock=9_000_000,
                tool_invocations=10_000,
                input_tokens=20_000_000,
                output_tokens=5_000_000,
                evaluator_generations=17,
            ),
        )

        self.assertEqual(EfficiencyStatus.PROVEN, assessment.status)
        self.assertFalse(assessment.requires_approach_change)

    def test_eff_03_missing_telemetry_preserves_progress_but_is_unproven(self) -> None:
        """Runtime 계측이 전부 없으면 목표 변화는 보존하되 효율을 입증하지 않습니다."""
        resources = self._resources(
            wall_clock=None,
            tool_invocations=None,
            input_tokens=None,
            output_tokens=None,
            evaluator_generations=None,
        )

        assessment = EfficiencyAssessor().assess(self._goal_delta(before=1, after=2), resources)

        self.assertEqual(1, assessment.goal_delta.delta_units)
        self.assertEqual(EfficiencyStatus.UNPROVEN, assessment.status)
        self.assertFalse(assessment.requires_approach_change)

    def test_partial_verified_vector_has_explicit_partially_proven_status(self) -> None:
        """Token 계측이 없어도 검증된 동일-mask 자원 벡터는 부분 입증으로 보존합니다."""
        resources = self._resources(input_tokens=None, output_tokens=None)

        assessment = EfficiencyAssessor().assess(self._goal_delta(before=1, after=2), resources)

        self.assertEqual(EfficiencyStatus.PARTIALLY_PROVEN, assessment.status)
        self.assertEqual((True, True, False, False, True), resources.availability_mask)

    def test_verified_resource_metric_requires_runtime_receipt(self) -> None:
        """VERIFIED resource 값은 runtime source, reference와 digest 없는 자기 주장으로 만들 수 없습니다."""
        with self.assertRaises(ValueError):
            ResourceMetricDelta(
                status=ResourceTelemetryStatus.VERIFIED,
                value=1,
                source_id=None,
                receipt_reference=None,
                receipt_digest=None,
            )
        with self.assertRaises(ValueError):
            ResourceMetricDelta(
                status=ResourceTelemetryStatus.UNAVAILABLE,
                value=None,
                source_id="runtime-hook",
                receipt_reference="runtime-receipt:generation-1",
                receipt_digest=self._digest("runtime-receipt:generation-1"),
            )

    def test_stale_resource_receipt_is_preserved_but_not_compared(self) -> None:
        """과거 runtime receipt가 남아도 STALE telemetry는 current 효율로 승격하지 않습니다."""
        current = self._metric(1)
        stale = ResourceMetricDelta(
            status=ResourceTelemetryStatus.STALE,
            value=1,
            source_id="runtime-hook",
            receipt_reference="runtime-receipt:stale-generation",
            receipt_digest=self._digest("runtime-receipt:stale-generation"),
        )
        resources = AuthoritativeResourceDelta(
            basis_fingerprint=self._digest("default-resource-basis"),
            wall_clock_milliseconds=current,
            tool_invocations=current,
            input_tokens=stale,
            output_tokens=current,
            evaluator_generations=current,
        )

        assessment = EfficiencyAssessor().assess(self._goal_delta(before=1, after=2), resources)

        self.assertEqual(EfficiencyStatus.NONCOMPARABLE, assessment.status)
        self.assertEqual("runtime-receipt:stale-generation", stale.receipt_reference)

    def test_goal_delta_requires_revisioned_authoritative_readbacks(self) -> None:
        """Goal delta는 caller count가 아니라 서로 다른 revision의 exact readback 집합에서만 계산됩니다."""
        before = self._readback(
            revision=1,
            settled=frozenset({"AC1:example-test"}),
        )
        with self.assertRaises(ValueError):
            GoalAttainmentReadback(
                goal_fingerprint=before.goal_fingerprint,
                evidence_basis_fingerprint=before.evidence_basis_fingerprint,
                evaluation_revision=2,
                settled_evidence_units=frozenset({"AC1:example-test", "AC2:source-readback"}),
                failed_evidence_units=frozenset(),
                reopened_evidence_units=frozenset(),
                authority_source_id="",
                readback_reference="",
                receipt_digest="",
            )
        with self.assertRaises(ValueError):
            VerifiedGoalAttainmentDelta(
                before=before,
                after=self._readback(
                    revision=3,
                    settled=frozenset({"AC1:example-test", "AC2:source-readback"}),
                ),
            )
        with self.subTest(disappearing_state="failed"), self.assertRaises(ValueError):
            VerifiedGoalAttainmentDelta(
                before=self._readback(
                    revision=1,
                    settled=frozenset({"AC1:example-test"}),
                    failed=frozenset({"AC2:source-readback"}),
                ),
                after=self._readback(
                    revision=2,
                    settled=frozenset({"AC1:example-test", "AC3:property-test"}),
                ),
            )
        with self.subTest(disappearing_state="reopened"), self.assertRaises(ValueError):
            VerifiedGoalAttainmentDelta(
                before=self._readback(
                    revision=1,
                    settled=frozenset({"AC1:example-test"}),
                    reopened=frozenset({"AC2:source-readback"}),
                ),
                after=self._readback(
                    revision=2,
                    settled=frozenset({"AC1:example-test", "AC3:property-test"}),
                ),
            )

    def test_new_failures_cannot_be_hidden_by_more_newly_settled_units(self) -> None:
        """새 PASS 수가 더 많아도 같은 generation의 failure나 reopen은 material progress가 아닙니다."""
        goal_delta = VerifiedGoalAttainmentDelta(
            before=self._readback(
                revision=1,
                settled=frozenset({"AC1:example-test"}),
            ),
            after=self._readback(
                revision=2,
                settled=frozenset({"AC1:example-test", "AC2:source-readback", "AC3:property-test"}),
                failed=frozenset({"AC4:independent-semantic"}),
            ),
        )

        assessment = EfficiencyAssessor().assess(goal_delta, self._resources())

        self.assertEqual(1, assessment.goal_delta.delta_units)
        self.assertEqual(
            frozenset({"AC4:independent-semantic"}),
            assessment.goal_delta.newly_failed_evidence_units,
        )
        self.assertEqual(EfficiencyStatus.ZERO_PROGRESS, assessment.status)
        self.assertTrue(assessment.requires_approach_change)

    def test_eff_04_same_cost_prefers_greater_verified_goal_delta(self) -> None:
        """동일한 goal과 비용 벡터에서는 검증된 목표 변화가 큰 generation만 지배합니다."""
        resources = self._resources()
        smaller = EfficiencyAssessor().assess(self._goal_delta(before=1, after=2), resources)
        greater = EfficiencyAssessor().assess(self._goal_delta(before=1, after=3), resources)

        comparison = EfficiencyComparator().compare(smaller, greater)

        self.assertEqual(EfficiencyComparison.RIGHT_DOMINATES, comparison)

    def test_eff_05_same_goal_delta_prefers_pareto_lower_resource_vector(self) -> None:
        """동일한 목표 변화에서는 모든 비용이 같거나 작고 하나가 더 작은 쪽만 지배합니다."""
        goal_delta = self._goal_delta(before=1, after=3)
        lower = EfficiencyAssessor().assess(
            goal_delta,
            self._resources(
                wall_clock=90,
                tool_invocations=4,
                input_tokens=900,
                output_tokens=200,
            ),
        )
        higher = EfficiencyAssessor().assess(
            goal_delta,
            self._resources(
                wall_clock=100,
                tool_invocations=5,
                input_tokens=1_000,
                output_tokens=200,
            ),
        )

        comparison = EfficiencyComparator().compare(lower, higher)

        self.assertEqual(EfficiencyComparison.LEFT_DOMINATES, comparison)

    def test_partial_vectors_are_pareto_comparable_only_with_the_same_availability_mask(
        self,
    ) -> None:
        """부분 입증 벡터는 같은 dimension mask에서만 Pareto 비교할 수 있습니다."""
        goal_delta = self._goal_delta(before=1, after=3)
        lower = EfficiencyAssessor().assess(
            goal_delta,
            self._resources(
                wall_clock=90,
                tool_invocations=4,
                input_tokens=None,
                output_tokens=None,
            ),
        )
        higher = EfficiencyAssessor().assess(
            goal_delta,
            self._resources(
                wall_clock=100,
                tool_invocations=5,
                input_tokens=None,
                output_tokens=None,
            ),
        )
        different_mask = EfficiencyAssessor().assess(
            goal_delta,
            self._resources(
                wall_clock=100,
                tool_invocations=None,
                input_tokens=None,
                output_tokens=None,
            ),
        )

        self.assertEqual(EfficiencyStatus.PARTIALLY_PROVEN, lower.status)
        self.assertEqual(
            EfficiencyComparison.LEFT_DOMINATES,
            EfficiencyComparator().compare(lower, higher),
        )
        self.assertEqual(
            EfficiencyComparison.NONCOMPARABLE,
            EfficiencyComparator().compare(lower, different_mask),
        )

    def test_eff_06_cross_goal_or_resource_basis_comparison_fails_closed(self) -> None:
        """Goal 또는 resource basis가 다르면 임의 환산 없이 비교 불가로 닫습니다."""
        baseline = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=2),
            self._resources(),
        )
        other_goal = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=3, goal="other-goal"),
            self._resources(),
        )
        other_resource_basis = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=3),
            self._resources(resource_basis="other-resource-basis"),
        )
        same_basis_tradeoff = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=2),
            self._resources(
                wall_clock=90,
                tool_invocations=6,
                input_tokens=1_100,
                output_tokens=150,
            ),
        )

        with self.subTest("cross-goal"):
            self.assertEqual(
                EfficiencyComparison.NONCOMPARABLE,
                EfficiencyComparator().compare(baseline, other_goal),
            )
        with self.subTest("cross-resource-basis"):
            self.assertEqual(
                EfficiencyComparison.NONCOMPARABLE,
                EfficiencyComparator().compare(baseline, other_resource_basis),
            )
        with self.subTest("same-basis-pareto-tradeoff"):
            self.assertEqual(
                EfficiencyComparison.NONCOMPARABLE,
                EfficiencyComparator().compare(baseline, same_basis_tradeoff),
            )

    def test_eff_07_generation_count_does_not_block_material_convergence(self) -> None:
        """두 번째 이후라도 blocker나 criterion 변화가 material하면 evaluator loop를 계속합니다."""
        assessment = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=2),
            self._resources(evaluator_generations=12),
        )
        policy = EvaluatorGenerationPolicy()

        blocker_decision = policy.decide(
            generation=12,
            efficiency=assessment,
            has_material_blocker=True,
            repeated_root_cause=False,
            repeated_approach=False,
            watchdog_exhausted=False,
        )
        criterion_decision = policy.decide(
            generation=12,
            efficiency=assessment,
            has_material_blocker=False,
            repeated_root_cause=False,
            repeated_approach=False,
            watchdog_exhausted=False,
        )

        self.assertEqual(EvaluatorGenerationAction.CONTINUE, blocker_decision.action)
        self.assertEqual(EvaluatorGenerationAction.CONTINUE, criterion_decision.action)

    def test_resolved_material_blocker_is_verified_goal_progress(self) -> None:
        """Criterion PASS가 없어도 current material blocker를 닫은 generation은 0 delta가 아닙니다."""
        goal_delta = VerifiedGoalAttainmentDelta(
            before=self._readback(
                revision=1,
                settled=frozenset(),
                open_blockers=frozenset({"gap:scope"}),
            ),
            after=self._readback(
                revision=2,
                settled=frozenset(),
                open_blockers=frozenset(),
            ),
        )

        assessment = EfficiencyAssessor().assess(goal_delta, self._resources())
        decision = EvaluatorGenerationPolicy().decide(
            generation=4,
            efficiency=assessment,
            has_material_blocker=False,
            repeated_root_cause=False,
            repeated_approach=False,
            watchdog_exhausted=False,
        )

        self.assertEqual(frozenset({"gap:scope"}), goal_delta.resolved_blocker_ids)
        self.assertEqual(EfficiencyStatus.PROVEN, assessment.status)
        self.assertEqual(EvaluatorGenerationAction.CONTINUE, decision.action)

    def test_different_goal_units_are_not_collapsed_into_a_scalar_score(self) -> None:
        """Criterion settlement와 blocker resolution이 서로 다른 경우 임의 1:1 환산하지 않습니다."""
        criterion_progress = VerifiedGoalAttainmentDelta(
            before=self._readback(revision=1, settled=frozenset()),
            after=self._readback(
                revision=2,
                settled=frozenset({"AC1:example-test"}),
            ),
        )
        blocker_progress = VerifiedGoalAttainmentDelta(
            before=self._readback(
                revision=1,
                settled=frozenset(),
                open_blockers=frozenset({"gap:scope"}),
            ),
            after=self._readback(
                revision=2,
                settled=frozenset(),
                open_blockers=frozenset(),
            ),
        )
        resources = self._resources()

        comparison = EfficiencyComparator().compare(
            EfficiencyAssessor().assess(criterion_progress, resources),
            EfficiencyAssessor().assess(blocker_progress, resources),
        )

        self.assertEqual(EfficiencyComparison.NONCOMPARABLE, comparison)

    def test_eff_08_zero_delta_repetition_and_watchdog_never_claim_success(self) -> None:
        """0 변화나 동일 접근 반복은 교체하고 watchdog 소진은 성공이 아닌 중단입니다."""
        policy = EvaluatorGenerationPolicy()
        self.assertEqual(
            {
                EvaluatorGenerationAction.CONTINUE,
                EvaluatorGenerationAction.CHANGE_APPROACH,
                EvaluatorGenerationAction.EXHAUSTED,
            },
            set(EvaluatorGenerationAction),
        )
        with self.assertRaises(ValueError):
            EvaluatorGenerationDecision(
                action=EvaluatorGenerationAction.CONTINUE,
                achieved=True,
                reason="forged generation success",
            )
        zero_progress = EfficiencyAssessor().assess(
            self._goal_delta(before=2, after=2),
            self._resources(),
        )
        material_progress = EfficiencyAssessor().assess(
            self._goal_delta(before=1, after=2),
            self._resources(),
        )

        decisions = (
            policy.decide(
                generation=1,
                efficiency=zero_progress,
                has_material_blocker=True,
                repeated_root_cause=False,
                repeated_approach=False,
                watchdog_exhausted=False,
            ),
            policy.decide(
                generation=2,
                efficiency=material_progress,
                has_material_blocker=True,
                repeated_root_cause=True,
                repeated_approach=False,
                watchdog_exhausted=False,
            ),
            policy.decide(
                generation=2,
                efficiency=material_progress,
                has_material_blocker=True,
                repeated_root_cause=False,
                repeated_approach=True,
                watchdog_exhausted=False,
            ),
        )
        exhausted = policy.decide(
            generation=99,
            efficiency=material_progress,
            has_material_blocker=True,
            repeated_root_cause=False,
            repeated_approach=False,
            watchdog_exhausted=True,
        )

        self.assertTrue(
            all(item.action is EvaluatorGenerationAction.CHANGE_APPROACH for item in decisions)
        )
        self.assertEqual(EvaluatorGenerationAction.EXHAUSTED, exhausted.action)
        self.assertFalse(exhausted.achieved)

    def _goal_delta(
        self,
        *,
        before: int,
        after: int,
        goal: str = "current-goal",
    ) -> VerifiedGoalAttainmentDelta:
        """동일 acceptance basis의 검증된 목표 단위 변화를 만듭니다."""
        units = tuple(f"AC{index}:example-test" for index in range(1, 5))
        before_settled = frozenset(units[:before])
        after_settled = frozenset(units[:after])
        return VerifiedGoalAttainmentDelta(
            before=self._readback(
                revision=1,
                settled=before_settled,
                goal=goal,
            ),
            after=self._readback(
                revision=2,
                settled=after_settled,
                reopened=before_settled - after_settled,
                goal=goal,
            ),
        )

    def _readback(
        self,
        *,
        revision: int,
        settled: frozenset[str],
        failed: frozenset[str] = frozenset(),
        reopened: frozenset[str] = frozenset(),
        open_blockers: frozenset[str] = frozenset(),
        goal: str = "current-goal",
    ) -> GoalAttainmentReadback:
        """Exact evidence-unit 집합과 authority receipt를 가진 goal readback을 만듭니다."""
        return GoalAttainmentReadback(
            goal_fingerprint=self._digest(goal),
            evidence_basis_fingerprint=self._digest(f"{goal}:evidence-basis"),
            evaluation_revision=revision,
            settled_evidence_units=settled,
            failed_evidence_units=failed,
            reopened_evidence_units=reopened,
            open_blocker_ids=open_blockers,
            authority_source_id="adaptive-control-store",
            readback_reference=f"adaptive-readback:{goal}:{revision}",
            receipt_digest=self._digest(f"{goal}:readback:{revision}"),
        )

    def _resources(
        self,
        *,
        wall_clock: int | None = 100,
        tool_invocations: int | None = 5,
        input_tokens: int | None = 1_000,
        output_tokens: int | None = 200,
        evaluator_generations: int | None = 1,
        resource_basis: str = "default-resource-basis",
    ) -> AuthoritativeResourceDelta:
        """None을 unavailable로 보존하는 같은 basis의 자원 벡터를 만듭니다."""
        return AuthoritativeResourceDelta(
            basis_fingerprint=self._digest(resource_basis),
            wall_clock_milliseconds=self._metric(wall_clock),
            tool_invocations=self._metric(tool_invocations),
            input_tokens=self._metric(input_tokens),
            output_tokens=self._metric(output_tokens),
            evaluator_generations=self._metric(evaluator_generations),
        )

    def _metric(self, value: int | None) -> ResourceMetricDelta:
        """실측값과 unavailable 값을 서로 다른 typed 상태로 만듭니다."""
        if value is None:
            return ResourceMetricDelta(
                status=ResourceTelemetryStatus.UNAVAILABLE,
                value=None,
                source_id=None,
                receipt_reference=None,
                receipt_digest=None,
            )
        return ResourceMetricDelta(
            status=ResourceTelemetryStatus.VERIFIED,
            value=value,
            source_id="runtime-hook",
            receipt_reference="runtime-receipt:generation-1",
            receipt_digest=self._digest("runtime-receipt:generation-1"),
        )

    def _digest(self, value: str) -> str:
        """Test identity를 안정적인 SHA-256 digest로 변환합니다."""
        return hashlib.sha256(value.encode()).hexdigest()


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
