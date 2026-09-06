"""Frozen resource-efficiency structural 및 runtime-admission acceptance matrix입니다."""

from enum import StrEnum

from scripts.agent_harness.acceptance_matrix import AcceptanceCase


class EfficiencyAcceptanceId(StrEnum):
    """Resource-efficiency frozen specification의 stable row identity입니다."""

    EFF_01 = "EFF-01"
    """저비용이어도 goal delta가 0이면 approach change인지 검증합니다."""
    EFF_02 = "EFF-02"
    """고비용과 material goal delta가 자동 실패로 합쳐지지 않는지 검증합니다."""
    EFF_03 = "EFF-03"
    """Unavailable telemetry가 0이 아니라 unproven으로 남는지 검증합니다."""
    EFF_04 = "EFF-04"
    """동일 비용에서 더 큰 verified goal delta가 Pareto 지배하는지 검증합니다."""
    EFF_05 = "EFF-05"
    """동일 goal delta에서 더 낮은 resource vector만 지배하는지 검증합니다."""
    EFF_06 = "EFF-06"
    """다른 goal 또는 resource basis가 current action과 비교를 얻지 못하는지 검증합니다."""
    EFF_07 = "EFF-07"
    """고정 generation 횟수가 material convergence를 막지 않는지 검증합니다."""
    EFF_08 = "EFF-08"
    """0 delta, 반복 접근과 watchdog이 성공으로 변환되지 않는지 검증합니다."""
    EFF_09 = "EFF-09"
    """Resource verified 상태가 runtime receipt shape를 요구하는지 검증합니다."""
    EFF_10 = "EFF-10"
    """Goal delta가 exact consecutive authoritative readback만 허용하는지 검증합니다."""
    EFF_11 = "EFF-11"
    """새 failure나 reopen을 더 많은 pass로 숨길 수 없는지 검증합니다."""
    EFF_12 = "EFF-12"
    """Stale receipt는 보존하되 current efficiency로 비교하지 않는지 검증합니다."""
    EFF_13 = "EFF-13"
    """Current adaptive store만 reflection용 goal-resource readback을 발행하는지 검증합니다."""
    EFF_14 = "EFF-14"
    """Optional runtime duration이 parser와 bounded receipt를 거쳐 보존되는지 검증합니다."""
    EFF_15 = "EFF-15"
    """Partial current vector가 explicit 상태와 exact-mask 비교만 얻는지 검증합니다."""
    EFF_16 = "EFF-16"
    """Material receipt 일부가 total tool/evaluator 자원 권위를 사칭하지 않는지 검증합니다."""
    EFF_17 = "EFF-17"
    """Tool duration과 stale binding이 generation 전체 자원을 위조하지 않는지 검증합니다."""
    EFF_18 = "EFF-18"
    """Final process aggregate가 forged total-resource authority를 거부하는지 검증합니다."""


class EfficiencyEvidenceSurface(StrEnum):
    """Matrix가 실제로 증명하는 분리된 evidence surface입니다."""

    STRUCTURAL = "STRUCTURAL"
    """Typed shape와 deterministic transition을 증명합니다."""
    RUNTIME_ADMISSION = "RUNTIME_ADMISSION"
    """Canonical adaptive store가 current generation receipt를 파생하는지 증명합니다."""


_EFFICIENCY_TEST = (
    "scripts/agent_harness/tests/test_efficiency_assessment.py::EfficiencyAssessmentTest"
)
_ADAPTIVE_TEST = "scripts/agent_harness/tests/test_adaptive_control.py::AdaptiveControlTest"
_ADAPTIVE_STORE_TEST = (
    "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest"
)
_PARSER_TEST = "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest"
_MATERIAL_TEST = "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest"
_STRUCTURAL = (EfficiencyEvidenceSurface.STRUCTURAL,)
_RUNTIME = (
    EfficiencyEvidenceSurface.STRUCTURAL,
    EfficiencyEvidenceSurface.RUNTIME_ADMISSION,
)

EFFICIENCY_ACCEPTANCE_MATRIX: tuple[AcceptanceCase, ...] = (
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_01,
        "Low resource cost never compensates for zero verified goal-attainment delta",
        (
            f"{_EFFICIENCY_TEST}::"
            "test_eff_01_low_cost_with_zero_goal_delta_requires_approach_change",
            f"{_ADAPTIVE_TEST}::"
            "test_zero_goal_delta_changes_approach_without_waiting_for_a_stagnation_window",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_02,
        "High resource cost with material verified goal delta is not automatically waste",
        (
            f"{_EFFICIENCY_TEST}::"
            "test_eff_02_high_cost_with_material_goal_delta_is_not_automatically_waste",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_03,
        "Unavailable telemetry preserves verified goal progress as unproven efficiency",
        (f"{_EFFICIENCY_TEST}::test_eff_03_missing_telemetry_preserves_progress_but_is_unproven",),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_04,
        "Equal resource vectors compare only nested exact progress identities without scalar conversion",
        (
            f"{_EFFICIENCY_TEST}::test_eff_04_same_cost_prefers_greater_verified_goal_delta",
            f"{_EFFICIENCY_TEST}::test_different_goal_units_are_not_collapsed_into_a_scalar_score",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_05,
        "Equal goal delta prefers only a Pareto-lower resource vector",
        (f"{_EFFICIENCY_TEST}::test_eff_05_same_goal_delta_prefers_pareto_lower_resource_vector",),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_06,
        "Cross-goal and cross-resource-basis claims fail closed without controlling reflection",
        (
            f"{_EFFICIENCY_TEST}::test_eff_06_cross_goal_or_resource_basis_comparison_fails_closed",
            f"{_ADAPTIVE_TEST}::test_foreign_goal_efficiency_cannot_control_current_reflection",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_07,
        "Generation count never overrides a material convergence signal",
        (
            f"{_EFFICIENCY_TEST}::test_eff_07_generation_count_does_not_block_material_convergence",
            f"{_EFFICIENCY_TEST}::test_resolved_material_blocker_is_verified_goal_progress",
            f"{_ADAPTIVE_TEST}::test_default_reflection_has_no_arbitrary_generation_cap",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_08,
        "Zero delta, repeated approach, and watchdog exhaustion remain non-success states",
        (
            f"{_EFFICIENCY_TEST}::"
            "test_eff_08_zero_delta_repetition_and_watchdog_never_claim_success",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_09,
        "Verified resource metrics require receipt source, reference, and digest",
        (f"{_EFFICIENCY_TEST}::test_verified_resource_metric_requires_runtime_receipt",),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_10,
        "Goal delta requires exact consecutive revisioned authoritative readbacks",
        (f"{_EFFICIENCY_TEST}::test_goal_delta_requires_revisioned_authoritative_readbacks",),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_11,
        "New failures or reopened evidence cannot be hidden by newly settled evidence",
        (f"{_EFFICIENCY_TEST}::test_new_failures_cannot_be_hidden_by_more_newly_settled_units",),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_12,
        "Stale resource receipts remain traceable but noncomparable",
        (f"{_EFFICIENCY_TEST}::test_stale_resource_receipt_is_preserved_but_not_compared",),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_13,
        "Only current adaptive-store admission can control post-generation reflection",
        (
            f"{_ADAPTIVE_STORE_TEST}::test_unadmitted_efficiency_shape_cannot_control_reflection",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_post_first_generation_reflection_requires_current_store_admitted_goal_resource_readback",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_efficiency_admission_derives_goal_delta_from_consecutive_adaptive_snapshots",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_missing_runtime_telemetry_is_admitted_as_unavailable_not_zero",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_efficiency_admission_uses_non_compensating_current_evidence",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_efficiency_admission_tracks_coverage_and_execution_as_exact_goal_surfaces",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_efficiency_readback_reference_is_bound_to_exact_snapshot_content",
            f"{_ADAPTIVE_STORE_TEST}::test_coverage_risk_regression_vetoes_other_goal_progress",
            f"{_ADAPTIVE_STORE_TEST}::test_schema_v4_without_efficiency_admission_remains_readable",
        ),
        _RUNTIME,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_14,
        "Optional runtime duration survives bounded parsing and receipt round-trip without a zero default",
        (
            f"{_PARSER_TEST}::"
            "test_claude_duration_is_preserved_as_optional_bounded_runtime_telemetry",
            f"{_MATERIAL_TEST}::"
            "test_tool_receipt_round_trip_preserves_optional_duration_without_defaulting_to_zero",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_15,
        "Partial current resource vectors are explicit and Pareto-comparable only under the same availability mask",
        (
            f"{_EFFICIENCY_TEST}::"
            "test_partial_verified_vector_has_explicit_partially_proven_status",
            f"{_EFFICIENCY_TEST}::"
            "test_partial_vectors_are_pareto_comparable_only_with_the_same_availability_mask",
        ),
        _STRUCTURAL,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_16,
        "A material batch never promotes its partial receipts into total tool or evaluator resource authority",
        (
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_material_batch_does_not_claim_total_tool_invocation_resource_authority",
        ),
        _RUNTIME,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_17,
        "Tool duration and stale material bindings remain unavailable as generation-total resources",
        (
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_tool_duration_is_not_promoted_to_generation_wall_clock_or_provider_tokens",
            f"{_ADAPTIVE_STORE_TEST}::"
            "test_stale_material_binding_is_not_admitted_as_current_resource_telemetry",
        ),
        _RUNTIME,
    ),
    AcceptanceCase(
        EfficiencyAcceptanceId.EFF_18,
        "Final aggregate admission rejects injected total-resource authority without a trusted total ledger",
        (f"{_ADAPTIVE_STORE_TEST}::test_final_aggregate_rejects_forged_total_resource_authority",),
        _RUNTIME,
    ),
)
"""EFF-01..18과 34개 exact public pytest node를 결속한 frozen matrix입니다."""

EFFICIENCY_ACCEPTANCE_MATRIX_DIGEST = (
    "781a5db90c1d490f55622933df4c03bdc14f4049d223012242e1c593fb48f7a6"
)
"""ID, scenario, evidence surface와 exact node를 결속한 full-matrix SHA-256입니다."""
