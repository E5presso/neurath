"""Frozen resource-efficiency acceptance matrix의 축소와 node drift를 검증합니다."""

import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from scripts.agent_harness.acceptance_matrix import canonical_matrix_digest
from scripts.agent_harness.efficiency_acceptance_matrix import (
    EFFICIENCY_ACCEPTANCE_MATRIX,
    EFFICIENCY_ACCEPTANCE_MATRIX_DIGEST,
    EfficiencyAcceptanceId,
    EfficiencyEvidenceSurface,
)

EXPECTED_ROWS = tuple(f"EFF-{index:02d}" for index in range(1, 19))
EXPECTED_NODES = (
    "scripts/agent_harness/tests/test_efficiency_assessment.py::"
    "EfficiencyAssessmentTest::test_eff_01_low_cost_with_zero_goal_delta_requires_approach_change",
    "scripts/agent_harness/tests/test_adaptive_control.py::AdaptiveControlTest::"
    "test_zero_goal_delta_changes_approach_without_waiting_for_a_stagnation_window",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_02_high_cost_with_material_goal_delta_is_not_automatically_waste",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_03_missing_telemetry_preserves_progress_but_is_unproven",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_04_same_cost_prefers_greater_verified_goal_delta",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_different_goal_units_are_not_collapsed_into_a_scalar_score",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_05_same_goal_delta_prefers_pareto_lower_resource_vector",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_06_cross_goal_or_resource_basis_comparison_fails_closed",
    "scripts/agent_harness/tests/test_adaptive_control.py::AdaptiveControlTest::"
    "test_foreign_goal_efficiency_cannot_control_current_reflection",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_07_generation_count_does_not_block_material_convergence",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_resolved_material_blocker_is_verified_goal_progress",
    "scripts/agent_harness/tests/test_adaptive_control.py::AdaptiveControlTest::"
    "test_default_reflection_has_no_arbitrary_generation_cap",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_eff_08_zero_delta_repetition_and_watchdog_never_claim_success",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_verified_resource_metric_requires_runtime_receipt",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_goal_delta_requires_revisioned_authoritative_readbacks",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_new_failures_cannot_be_hidden_by_more_newly_settled_units",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_stale_resource_receipt_is_preserved_but_not_compared",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_unadmitted_efficiency_shape_cannot_control_reflection",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_post_first_generation_reflection_requires_current_store_admitted_goal_resource_readback",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_efficiency_admission_derives_goal_delta_from_consecutive_adaptive_snapshots",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_missing_runtime_telemetry_is_admitted_as_unavailable_not_zero",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_efficiency_admission_uses_non_compensating_current_evidence",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_efficiency_admission_tracks_coverage_and_execution_as_exact_goal_surfaces",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_efficiency_readback_reference_is_bound_to_exact_snapshot_content",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_coverage_risk_regression_vetoes_other_goal_progress",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_schema_v4_without_efficiency_admission_remains_readable",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::"
    "test_claude_duration_is_preserved_as_optional_bounded_runtime_telemetry",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest::"
    "test_tool_receipt_round_trip_preserves_optional_duration_without_defaulting_to_zero",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_partial_verified_vector_has_explicit_partially_proven_status",
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest::"
    "test_partial_vectors_are_pareto_comparable_only_with_the_same_availability_mask",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_material_batch_does_not_claim_total_tool_invocation_resource_authority",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_tool_duration_is_not_promoted_to_generation_wall_clock_or_provider_tokens",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_stale_material_binding_is_not_admitted_as_current_resource_telemetry",
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest::"
    "test_final_aggregate_rejects_forged_total_resource_authority",
)
FROZEN_EFFICIENCY_ACCEPTANCE_MATRIX_DIGEST = (
    "781a5db90c1d490f55622933df4c03bdc14f4049d223012242e1c593fb48f7a6"
)


class EfficiencyAcceptanceMatrixTest(TestCase):
    """EFF-01..18의 exact row, evidence surface, digest와 node 존재를 고정합니다."""

    def test_matrix_contains_exact_rows_and_public_nodes_without_shrinkage(self) -> None:
        """Frozen row와 node inventory는 누락, 중복 또는 재정렬 없이 정확히 유지됩니다."""
        rows = tuple(case.row.value for case in EFFICIENCY_ACCEPTANCE_MATRIX)
        nodes = tuple(node for case in EFFICIENCY_ACCEPTANCE_MATRIX for node in case.nodes)

        self.assertEqual(EXPECTED_ROWS, rows)
        self.assertEqual(EXPECTED_ROWS, tuple(row.value for row in EfficiencyAcceptanceId))
        self.assertEqual(EXPECTED_NODES, nodes)
        self.assertEqual(18, len(rows))
        self.assertEqual(18, len(frozenset(rows)))
        self.assertEqual(34, len(nodes))
        self.assertEqual(34, len(frozenset(nodes)))
        self.assertTrue(all(case.scenario.strip() for case in EFFICIENCY_ACCEPTANCE_MATRIX))

    def test_matrix_claims_structural_admission_not_runtime_authenticity(self) -> None:
        """Matrix는 structural shape와 adaptive-store runtime admission을 구분합니다."""
        self.assertEqual(
            ("STRUCTURAL", "RUNTIME_ADMISSION"),
            tuple(item.value for item in EfficiencyEvidenceSurface),
        )
        self.assertTrue(
            all(
                case.evidence_surfaces == (EfficiencyEvidenceSurface.STRUCTURAL,)
                for case in (
                    *EFFICIENCY_ACCEPTANCE_MATRIX[:12],
                    EFFICIENCY_ACCEPTANCE_MATRIX[13],
                    EFFICIENCY_ACCEPTANCE_MATRIX[14],
                )
            )
        )
        self.assertTrue(
            all(
                case.evidence_surfaces
                == (
                    EfficiencyEvidenceSurface.STRUCTURAL,
                    EfficiencyEvidenceSurface.RUNTIME_ADMISSION,
                )
                for case in (
                    EFFICIENCY_ACCEPTANCE_MATRIX[12],
                    *EFFICIENCY_ACCEPTANCE_MATRIX[15:],
                )
            )
        )

    def test_matrix_digest_is_literal_and_matches_canonical_payload(self) -> None:
        """Literal digest와 canonical payload가 같은 frozen row/node contract를 가리킵니다."""
        self.assertEqual(
            FROZEN_EFFICIENCY_ACCEPTANCE_MATRIX_DIGEST,
            EFFICIENCY_ACCEPTANCE_MATRIX_DIGEST,
        )
        self.assertEqual(
            FROZEN_EFFICIENCY_ACCEPTANCE_MATRIX_DIGEST,
            canonical_matrix_digest(EFFICIENCY_ACCEPTANCE_MATRIX),
        )

    def test_every_frozen_node_exists_and_is_collectable(self) -> None:
        """Exact public pytest node는 현재 repository에서 모두 파일과 collector를 통과합니다."""
        repository = Path(__file__).resolve().parents[3]
        for node in EXPECTED_NODES:
            self.assertTrue((repository / node.split("::", maxsplit=1)[0]).is_file())
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-o",
                "addopts=",
                *EXPECTED_NODES,
            ),
            cwd=repository,
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(0, completed.returncode, f"{completed.stdout}\n{completed.stderr}")
