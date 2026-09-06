"""Frozen material-action acceptance matrix의 row, node와 digest drift를 검증합니다."""

import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from scripts.agent_harness.acceptance_matrix import canonical_matrix_digest
from scripts.agent_harness.material_action_acceptance_matrix import (
    MATERIAL_ACTION_ACCEPTANCE_MATRIX,
    MATERIAL_ACTION_ACCEPTANCE_MATRIX_DIGEST,
    MaterialActionAcceptanceId,
    MaterialActionEvidenceSurface,
)

EXPECTED_ROWS = tuple(f"MAT-{index:02d}" for index in range(1, 18))
EXPECTED_NODES = (
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_host_managed_tools_are_not_content_classified",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_host_managed_fast_path_does_not_require_session_identity",
    "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_host_managed_tools_require_neither_identity_nor_worktree_claim",
    "scripts/agent_harness/tests/test_tool_authority_boundary.py::ToolAuthorityBoundaryTest::test_host_managed_tools_bypass_worktree_and_material_authorization",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_no_skill_foreground_turn_persists_one_batch_and_multiple_invocations",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_only_structured_edit_tools_are_material_mutations",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_mutation_without_current_prepared_batch_is_denied",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest::test_started_target_must_be_within_the_prepared_exact_boundary",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_structured_edit_targets_are_exact_and_complete",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_relative_targets_resolve_from_payload_workdir",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_empty_structured_target_remains_unproven_for_downstream_denial",
    "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_multiedit_authorizes_every_nested_edit_target",
    "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_apply_patch_move_authorizes_destination_target",
    "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_claimed_worktree_command_cannot_escape_to_external_target",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_unknown_target_and_second_in_flight_call_fail_closed",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_explicit_session_cas_and_duplicate_runtime_delivery_are_stable",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_pre_tool_records_exact_start_cas_before_allow",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_pre_tool_denies_unobserved_drift_from_the_latest_known_digest",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_pre_tool_wrapper_records_action_only_after_worktree_allow",
    "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_unclaimed_worktree_requires_explicit_typed_claim_before_mutation",
    "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_denied_composite_pretool_does_not_claim_an_unexecuted_mutation",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest::test_duplicate_start_and_observation_are_idempotent_but_conflicts_fail_closed",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_pre_and_post_payloads_bind_the_same_request",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_result_failure_and_duration_are_bounded",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_post_tool_exact_match_records_readback_and_is_idempotent",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_post_validator_failure_still_closes_in_flight_with_failed_receipt",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_claude_post_tool_failure_records_failed_receipt_from_top_level_error",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_claude_permission_denial_records_unknown_receipt_without_claiming_execution",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_post_tool_wrapper_preserves_nonzero_process_exit_shape",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_post_tool_rejects_mismatched_tool_use_or_request_digest",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_file_mode_change_is_part_of_the_material_observable_digest",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest::test_completed_resolution_requires_successful_receipts_and_matching_latest_deltas",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest::test_prepared_but_unstarted_batch_can_abort_or_block_without_forging_receipt",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest::test_batch_supports_multiple_sequential_tool_receipts_without_raw_payloads",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_observed_receipt_allows_the_next_sequential_call",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_prepare_requires_exact_current_turn_and_new_batch_waits_for_resolution",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_resume_can_terminalize_orphaned_inflight_without_forging_success",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_adaptive_binding_is_optional_but_never_partially_constructed",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_semantic_batch_rejects_tool_start_observe_and_completion_after_adaptive_revision_or_goal_changes",
    "scripts/agent_harness/tests/test_session_rehydration.py::SessionRehydrationTest::test_material_action_summary_preserves_adaptive_goal_provenance",
    "scripts/agent_harness/tests/test_state_cli.py::StateCliApplicationTest::test_material_action_cli_rejects_unbound_semantic_and_opaque_external_intent",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_root_stop_blocks_current_open_material_action_without_workflow",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_open_material_action_blocks_before_external_stop_validation",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_stop_terminalizes_an_unobserved_inflight_invocation_as_unknown",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_root_stop_allows_resolved_material_action_without_workflow",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnGenerationCasTest::test_stop_rejects_material_action_aba_during_external_validation",
    "scripts/agent_harness/tests/test_session_rehydration.py::SessionRehydrationTest::test_compact_injects_only_bounded_current_actor_open_material_action",
    "scripts/agent_harness/tests/test_session_rehydration.py::SessionRehydrationTest::test_rehydration_omits_resolved_and_foreign_actor_material_actions",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_subagent_context_preserves_assignment_before_truncating_optional_enclave",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_subagent_start_blocks_when_load_bearing_assignment_exceeds_context_budget",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_post_tool_preserves_target_content_without_language_normalization",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_post_tool_propagates_material_validator_failure",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_codex_and_claude_share_one_structured_edit_post_tool_wrapper",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_claude_failure_event_uses_the_same_structured_edit_receipt_wrapper",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_claude_permission_denial_terminalizes_the_unexecuted_invocation",
    "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_native_hook_failure_sensor_is_preserved_and_drift_detected",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_post_tool_wrapper_preserves_original_tool_failure_exit",
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::MaterialActionRuntimeHookApplicationTest::test_validator_timeout_reaps_the_entire_process_group_before_post_readback",
    "scripts/agent_harness/tests/test_bounded_process.py::BoundedProcessTest::test_timeout_kills_the_entire_process_group_without_orphaning_descendants",
    "scripts/agent_harness/tests/test_bounded_process.py::BoundedProcessTest::test_timeout_bounds_drain_and_kills_a_re_sessioned_descendant",
    "scripts/agent_harness/tests/test_bounded_process.py::BoundedProcessTest::test_timeout_finds_a_reparented_re_sessioned_pipe_writer",
    "scripts/agent_harness/tests/test_bounded_process.py::BoundedProcessTest::test_success_cleans_a_background_descendant_before_returning",
    "scripts/agent_harness/tests/test_bounded_process.py::BoundedProcessTest::test_external_termination_cleans_the_owned_verifier_process_tree",
    "scripts/agent_harness/tests/test_state_cli.py::StateCliApplicationTest::test_material_action_cli_prepares_reads_and_resolves_exact_foreground_batch",
    "scripts/agent_harness/tests/test_tool_authority_boundary.py::ToolAuthorityBoundaryTest::test_shell_and_external_tools_are_host_managed_without_content_inference",
    "scripts/agent_harness/tests/test_tool_authority_boundary.py::ToolAuthorityBoundaryTest::test_only_structured_edit_tools_create_material_mutation_requests",
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_runtime_wiring_limits_repository_gates_to_structured_edits",
    "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest::test_invalid_payloads_fail_closed",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_request_maps_only_closed_verification_commands",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_cli_parser_covers_every_declared_verification_kind",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_actual_passing_pytest_node_emits_bounded_unchanged_receipt",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_function_style_package_pytest_node_is_supported",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_real_red_pytest_returns_bounded_transient_diagnostic",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_repository_change_during_verification_is_rejected",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_failed_verifier_still_reports_after_fingerprint_change",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_index_only_change_invalidates_verification_receipt",
    "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest::test_mise_check_is_an_exact_allowlisted_regression_entrypoint",
    "scripts/skill_harness/tests/test_harness_incident.py::HarnessIncidentTest::test_regression_command_cannot_leave_worktree_or_index_mutation",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest::test_process_state_without_material_actions_decodes_as_empty_projection",
    "scripts/agent_harness/tests/test_material_action.py::MaterialActionStateHandleTest::test_handle_rejects_cross_actor_and_cross_session_prepare",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_root_stop_ignores_foreign_actor_open_material_action",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_user_enclave_substring_cannot_move_structural_context_boundary",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_startup_effect_binds_exact_emitted_additional_context",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_compact_effect_binds_exact_truncated_additional_context",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_fork_effect_binds_exact_emitted_additional_context",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_fork_retry_replays_exact_pending_context_effect",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_fork_retry_rejects_foreign_pending_delivery",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_subagent_effect_binds_runtime_binding_and_enclave_exactly",
    "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_subagent_start_bootstraps_one_idempotent_active_foreground_turn",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_runtime_subagent_start_stop_fences_actor_and_late_child_tool",
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_subagent_stop_requires_owned_worktree_release_or_handoff",
    "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_hook_engine_imports_without_third_party_dependencies",
    "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_installed_hook_runs_without_source_project",
    "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_missing_installed_runtime_is_explicit_failure",
    "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_all_skill_phase_and_evidence_contracts_are_consistent",
    "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_distribution_rejects_added_modified_and_missing_files",
    "scripts/agent_harness/tests/test_harness_maintenance.py::HarnessMaintenanceTest::test_exact_actor_and_target_are_authorized_only_for_structured_edits",
    "scripts/agent_harness/tests/test_harness_maintenance.py::HarnessMaintenanceTest::test_close_moves_a_digest_readback_to_an_audit_receipt",
    "scripts/agent_harness/tests/test_harness_maintenance.py::HarnessMaintenanceTest::test_scope_ttl_and_owner_are_fail_closed",
)


EXPECTED_CRITICAL_NODES = frozenset(
    (
        "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnContinuationMatrixTest::test_runtime_subagent_start_stop_fences_actor_and_late_child_tool",
        "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_all_skill_phase_and_evidence_contracts_are_consistent",
        "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest::test_installed_hook_runs_without_source_project",
        "scripts/agent_harness/tests/test_harness_maintenance.py::HarnessMaintenanceTest::test_exact_actor_and_target_are_authorized_only_for_structured_edits",
        "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest::test_runtime_wiring_limits_repository_gates_to_structured_edits",
        "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_fork_retry_replays_exact_pending_context_effect",
        "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_startup_effect_binds_exact_emitted_additional_context",
        "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest::test_user_enclave_substring_cannot_move_structural_context_boundary",
    )
)

FROZEN_MATERIAL_ACTION_ACCEPTANCE_MATRIX_DIGEST = (
    "4388921773db2f8ab3267861c113ec4f632f6bfc33c91efd02f7a5bdf532d511"
)


class MaterialActionAcceptanceMatrixTest(TestCase):
    """MAT-01..17의 exact row, surface, digest와 public node를 고정합니다."""

    def test_matrix_contains_exact_rows_and_unique_public_nodes(self) -> None:
        """Frozen row와 digest-backed node inventory는 중복 없이 유지됩니다."""
        rows = tuple(case.row.value for case in MATERIAL_ACTION_ACCEPTANCE_MATRIX)
        nodes = tuple(node for case in MATERIAL_ACTION_ACCEPTANCE_MATRIX for node in case.nodes)

        self.assertEqual(EXPECTED_ROWS, rows)
        self.assertEqual(EXPECTED_ROWS, tuple(row.value for row in MaterialActionAcceptanceId))
        self.assertEqual(EXPECTED_NODES, nodes)
        self.assertEqual(17, len(rows))
        self.assertEqual(17, len(frozenset(rows)))
        self.assertEqual(99, len(nodes))
        self.assertEqual(99, len(frozenset(nodes)))
        self.assertLessEqual(EXPECTED_CRITICAL_NODES, frozenset(nodes))
        self.assertTrue(all(case.scenario.strip() for case in MATERIAL_ACTION_ACCEPTANCE_MATRIX))
        self.assertTrue(all(case.evidence_surfaces for case in MATERIAL_ACTION_ACCEPTANCE_MATRIX))

    def test_evidence_surfaces_are_canonical_and_source_claims_are_explicit(self) -> None:
        """자동 실행과 source wiring evidence를 서로 다른 ordered surface로 보존합니다."""
        self.assertEqual(
            ("AUTO", "SOURCE"),
            tuple(surface.value for surface in MaterialActionEvidenceSurface),
        )
        source_rows = tuple(
            case.row.value
            for case in MATERIAL_ACTION_ACCEPTANCE_MATRIX
            if MaterialActionEvidenceSurface.SOURCE in case.evidence_surfaces
        )
        self.assertEqual(("MAT-05", "MAT-13", "MAT-17"), source_rows)
        self.assertTrue(
            all(
                case.evidence_surfaces
                in {
                    (MaterialActionEvidenceSurface.AUTO,),
                    (
                        MaterialActionEvidenceSurface.AUTO,
                        MaterialActionEvidenceSurface.SOURCE,
                    ),
                }
                for case in MATERIAL_ACTION_ACCEPTANCE_MATRIX
            )
        )

    def test_matrix_digest_is_literal_and_matches_canonical_payload(self) -> None:
        """Literal digest와 canonical payload가 같은 row/node/surface contract를 가리킵니다."""
        self.assertEqual(
            FROZEN_MATERIAL_ACTION_ACCEPTANCE_MATRIX_DIGEST,
            MATERIAL_ACTION_ACCEPTANCE_MATRIX_DIGEST,
        )
        self.assertEqual(
            FROZEN_MATERIAL_ACTION_ACCEPTANCE_MATRIX_DIGEST,
            canonical_matrix_digest(MATERIAL_ACTION_ACCEPTANCE_MATRIX),
        )

    def test_every_frozen_node_exists_and_is_collectable(self) -> None:
        """Exact public pytest node는 현재 repository에서 모두 collect 가능합니다."""
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
