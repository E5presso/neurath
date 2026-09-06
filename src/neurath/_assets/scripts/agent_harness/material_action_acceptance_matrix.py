"""Frozen MAT-01..17 material-action acceptance matrix입니다.

이 matrix는 host-managed fast path부터 actor-bound intent, runtime receipt, Stop과
compaction까지 이어지는 current material-action contract를 exact public pytest node에
결속합니다. Live vendor delivery 자체의 진위를 주장하지 않으며, source wiring을 읽는
row는 별도 SOURCE surface로 표시합니다.
"""

from enum import StrEnum

from scripts.agent_harness.acceptance_matrix import AcceptanceCase


class MaterialActionAcceptanceId(StrEnum):
    """Material-action frozen specification의 stable row identity입니다."""

    MAT_01 = "MAT-01"
    """Host-managed tool이 repository material state와 runtime identity를 요구하지 않습니다."""
    MAT_02 = "MAT-02"
    """Workflow가 없어도 current foreground actor가 intent를 준비할 수 있습니다."""
    MAT_03 = "MAT-03"
    """Prepared intent 없는 material mutation은 fail-closed합니다."""
    MAT_04 = "MAT-04"
    """Literal exact target만 허용하고 dynamic 또는 foreign scope를 거부합니다."""
    MAT_05 = "MAT-05"
    """PreTool allow 전에 ownership, baseline과 exact CAS를 검증합니다."""
    MAT_06 = "MAT-06"
    """PostTool은 matching request에서 derived receipt를 기록하고 retry를 멱등 처리합니다."""
    MAT_07 = "MAT-07"
    """Completed resolution은 expected-vs-actual strict match를 요구합니다."""
    MAT_08 = "MAT-08"
    """Batch 안 invocation과 batch sequence는 한 번에 하나씩 단조롭게 진행합니다."""
    MAT_09 = "MAT-09"
    """Semantic decision은 완전한 adaptive workflow와 goal provenance를 요구합니다."""
    MAT_10 = "MAT-10"
    """Opaque external mutation과 unbound semantic intent는 열리지 않습니다."""
    MAT_11 = "MAT-11"
    """Stop은 open batch를 차단하고 resolved batch와 ABA/CAS를 구분합니다."""
    MAT_12 = "MAT-12"
    """Compaction은 current actor open intent의 bounded raw-free summary만 복원합니다."""
    MAT_13 = "MAT-13"
    """Composite PostTool 순서와 Codex/Claude structured-edit parity를 고정합니다."""
    MAT_14 = "MAT-14"
    """Host tool semantics는 provider가, typed CLI grammar는 실제 CLI가 소유합니다."""
    MAT_15 = "MAT-15"
    """Legacy decode와 exact session/actor projection isolation을 보존합니다."""
    MAT_16 = "MAT-16"
    """Structural context, exact outbox bytes와 child lifecycle을 하나로 결속합니다."""
    MAT_17 = "MAT-17"
    """Fresh bootstrap과 documented typed control surface를 실제 runtime에 결속합니다."""


class MaterialActionEvidenceSurface(StrEnum):
    """Matrix가 구분하는 deterministic evidence authority입니다."""

    AUTO = "AUTO"
    """Public deterministic test가 domain 또는 application behavior를 실행합니다."""
    SOURCE = "SOURCE"
    """Current hook wrapper와 runtime config source를 직접 판독합니다."""


_DOMAIN = "scripts/agent_harness/tests/test_material_action.py::MaterialActionDomainTest"
_KERNEL = "scripts/agent_harness/tests/test_material_action.py::MaterialActionKernelTest"
_HANDLE = "scripts/agent_harness/tests/test_material_action.py::MaterialActionStateHandleTest"
_PARSER = "scripts/agent_harness/tests/test_tool_action_parser.py::ToolActionParserTest"
_RUNTIME = (
    "scripts/agent_harness/tests/test_material_action_runtime_hook.py::"
    "MaterialActionRuntimeHookApplicationTest"
)
_WIRING = (
    "scripts/agent_harness/tests/test_material_action_hook_wiring.py::MaterialActionHookWiringTest"
)
_WORKTREE = "scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest"
_AUTHORITY = (
    "scripts/agent_harness/tests/test_tool_authority_boundary.py::ToolAuthorityBoundaryTest"
)
_MAINTENANCE = "scripts/agent_harness/tests/test_harness_maintenance.py::HarnessMaintenanceTest"
_CLI = "scripts/agent_harness/tests/test_state_cli.py::StateCliApplicationTest"
_STOP = (
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
    "ForegroundTurnContinuationMatrixTest"
)
_STOP_CAS = (
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::ForegroundTurnGenerationCasTest"
)
_REHYDRATION = "scripts/agent_harness/tests/test_session_rehydration.py::SessionRehydrationTest"
_SESSION_RUNTIME = "scripts/agent_harness/tests/test_runtime_hook.py::RuntimeHookApplicationTest"
_VERIFICATION = "scripts/agent_harness/tests/test_verification_runner.py::VerificationRunnerTest"
_INCIDENT = "scripts/skill_harness/tests/test_harness_incident.py::HarnessIncidentTest"
_BOUNDED = "scripts/agent_harness/tests/test_bounded_process.py::BoundedProcessTest"
_CHECKER = "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest"
_HOOK_BOOTSTRAP = "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest"
_SKILL_CHECKER = "scripts/agent_harness/tests/test_distribution_boundary.py::DistributionBoundaryTest"


def _node(suite: str, name: str) -> str:
    """Stable suite prefix와 public test method를 exact pytest node로 결합합니다."""
    return f"{suite}::{name}"


AUTO = (MaterialActionEvidenceSurface.AUTO,)
AUTO_SOURCE = (
    MaterialActionEvidenceSurface.AUTO,
    MaterialActionEvidenceSurface.SOURCE,
)


MATERIAL_ACTION_ACCEPTANCE_MATRIX: tuple[AcceptanceCase, ...] = (
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_01,
        "Host-managed tools preserve a repository-state-free and identity-free fast path",
        (
            _node(_PARSER, "test_host_managed_tools_are_not_content_classified"),
            _node(_RUNTIME, "test_host_managed_fast_path_does_not_require_session_identity"),
            _node(
                _WORKTREE,
                "test_host_managed_tools_require_neither_identity_nor_worktree_claim",
            ),
            _node(
                _AUTHORITY,
                "test_host_managed_tools_bypass_worktree_and_material_authorization",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_02,
        "A current foreground actor prepares a persisted batch without a skill workflow",
        (
            _node(
                _KERNEL,
                "test_no_skill_foreground_turn_persists_one_batch_and_multiple_invocations",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_03,
        "A material mutation without the current prepared batch is denied before state change",
        (
            _node(_PARSER, "test_only_structured_edit_tools_are_material_mutations"),
            _node(_RUNTIME, "test_mutation_without_current_prepared_batch_is_denied"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_04,
        "Structured edit targets remain exact, complete, local, and non-concurrent",
        (
            _node(_DOMAIN, "test_started_target_must_be_within_the_prepared_exact_boundary"),
            _node(_PARSER, "test_structured_edit_targets_are_exact_and_complete"),
            _node(_PARSER, "test_relative_targets_resolve_from_payload_workdir"),
            _node(
                _PARSER,
                "test_empty_structured_target_remains_unproven_for_downstream_denial",
            ),
            _node(_WORKTREE, "test_multiedit_authorizes_every_nested_edit_target"),
            _node(_WORKTREE, "test_apply_patch_move_authorizes_destination_target"),
            _node(_WORKTREE, "test_claimed_worktree_command_cannot_escape_to_external_target"),
            _node(_RUNTIME, "test_unknown_target_and_second_in_flight_call_fail_closed"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_05,
        "PreTool ownership, baseline readback, request identity, and state CAS precede allow",
        (
            _node(_KERNEL, "test_explicit_session_cas_and_duplicate_runtime_delivery_are_stable"),
            _node(_RUNTIME, "test_pre_tool_records_exact_start_cas_before_allow"),
            _node(_RUNTIME, "test_pre_tool_denies_unobserved_drift_from_the_latest_known_digest"),
            _node(_WIRING, "test_pre_tool_wrapper_records_action_only_after_worktree_allow"),
            _node(
                _WORKTREE,
                "test_unclaimed_worktree_requires_explicit_typed_claim_before_mutation",
            ),
            _node(
                _WORKTREE,
                "test_denied_composite_pretool_does_not_claim_an_unexecuted_mutation",
            ),
        ),
        AUTO_SOURCE,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_06,
        "PostTool binds exact request/result digests, derived readback, failures, and retries",
        (
            _node(
                _DOMAIN,
                "test_duplicate_start_and_observation_are_idempotent_but_conflicts_fail_closed",
            ),
            _node(_PARSER, "test_pre_and_post_payloads_bind_the_same_request"),
            _node(_PARSER, "test_result_failure_and_duration_are_bounded"),
            _node(_RUNTIME, "test_post_tool_exact_match_records_readback_and_is_idempotent"),
            _node(
                _RUNTIME,
                "test_post_validator_failure_still_closes_in_flight_with_failed_receipt",
            ),
            _node(
                _RUNTIME,
                "test_claude_post_tool_failure_records_failed_receipt_from_top_level_error",
            ),
            _node(
                _RUNTIME,
                "test_claude_permission_denial_records_unknown_receipt_without_claiming_execution",
            ),
            _node(_WIRING, "test_post_tool_wrapper_preserves_nonzero_process_exit_shape"),
            _node(_RUNTIME, "test_post_tool_rejects_mismatched_tool_use_or_request_digest"),
            _node(_RUNTIME, "test_file_mode_change_is_part_of_the_material_observable_digest"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_07,
        "Completed resolution rejects failed, missing, mismatched, or stale observable deltas",
        (
            _node(
                _DOMAIN,
                "test_completed_resolution_requires_successful_receipts_and_matching_latest_deltas",
            ),
            _node(
                _DOMAIN,
                "test_prepared_but_unstarted_batch_can_abort_or_block_without_forging_receipt",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_08,
        "Sequential tool receipts and batch sequences advance without parallel in-flight work",
        (
            _node(
                _DOMAIN,
                "test_batch_supports_multiple_sequential_tool_receipts_without_raw_payloads",
            ),
            _node(_RUNTIME, "test_observed_receipt_allows_the_next_sequential_call"),
            _node(
                _KERNEL,
                "test_prepare_requires_exact_current_turn_and_new_batch_waits_for_resolution",
            ),
            _node(
                _KERNEL,
                "test_resume_can_terminalize_orphaned_inflight_without_forging_success",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_09,
        "Semantic decisions carry a complete adaptive workflow revision and goal fingerprint",
        (
            _node(_KERNEL, "test_adaptive_binding_is_optional_but_never_partially_constructed"),
            _node(
                _KERNEL,
                "test_semantic_batch_rejects_tool_start_observe_and_completion_after_adaptive_revision_or_goal_changes",
            ),
            _node(_REHYDRATION, "test_material_action_summary_preserves_adaptive_goal_provenance"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_10,
        "Unbound semantic and opaque external targets fail closed without opening a batch",
        (
            _node(
                _CLI,
                "test_material_action_cli_rejects_unbound_semantic_and_opaque_external_intent",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_11,
        "Stop blocks open work before external validation and closes only resolved stable state",
        (
            _node(
                _STOP,
                "test_root_stop_blocks_current_open_material_action_without_workflow",
            ),
            _node(_STOP, "test_open_material_action_blocks_before_external_stop_validation"),
            _node(
                _STOP,
                "test_stop_terminalizes_an_unobserved_inflight_invocation_as_unknown",
            ),
            _node(_STOP, "test_root_stop_allows_resolved_material_action_without_workflow"),
            _node(_STOP_CAS, "test_stop_rejects_material_action_aba_during_external_validation"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_12,
        "Compaction restores only current actor open intent with a bounded raw-free allowlist",
        (
            _node(
                _REHYDRATION,
                "test_compact_injects_only_bounded_current_actor_open_material_action",
            ),
            _node(
                _REHYDRATION,
                "test_rehydration_omits_resolved_and_foreign_actor_material_actions",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_subagent_context_preserves_assignment_before_truncating_optional_enclave",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_subagent_start_blocks_when_load_bearing_assignment_exceeds_context_budget",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_13,
        "PostTool preserves target content and tool outcomes through portable material readback",
        (
            _node(_WIRING, "test_post_tool_preserves_target_content_without_language_normalization"),
            _node(_WIRING, "test_post_tool_propagates_material_validator_failure"),
            _node(
                _WIRING,
                "test_codex_and_claude_share_one_structured_edit_post_tool_wrapper",
            ),
            _node(
                _WIRING,
                "test_claude_failure_event_uses_the_same_structured_edit_receipt_wrapper",
            ),
            _node(
                _WIRING,
                "test_claude_permission_denial_terminalizes_the_unexecuted_invocation",
            ),
            _node(_CHECKER, "test_native_hook_failure_sensor_is_preserved_and_drift_detected"),
            _node(_WIRING, "test_post_tool_wrapper_preserves_original_tool_failure_exit"),
            _node(
                _RUNTIME,
                "test_validator_timeout_reaps_the_entire_process_group_before_post_readback",
            ),
            _node(
                _BOUNDED,
                "test_timeout_kills_the_entire_process_group_without_orphaning_descendants",
            ),
            _node(
                _BOUNDED,
                "test_timeout_bounds_drain_and_kills_a_re_sessioned_descendant",
            ),
            _node(
                _BOUNDED,
                "test_timeout_finds_a_reparented_re_sessioned_pipe_writer",
            ),
            _node(
                _BOUNDED,
                "test_success_cleans_a_background_descendant_before_returning",
            ),
            _node(
                _BOUNDED,
                "test_external_termination_cleans_the_owned_verifier_process_tree",
            ),
        ),
        AUTO_SOURCE,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_14,
        "Host tools keep provider authority while typed CLIs validate their own exact grammar",
        (
            _node(
                _CLI,
                "test_material_action_cli_prepares_reads_and_resolves_exact_foreground_batch",
            ),
            _node(
                _AUTHORITY,
                "test_shell_and_external_tools_are_host_managed_without_content_inference",
            ),
            _node(
                _AUTHORITY,
                "test_only_structured_edit_tools_create_material_mutation_requests",
            ),
            _node(
                _WIRING,
                "test_runtime_wiring_limits_repository_gates_to_structured_edits",
            ),
            _node(_PARSER, "test_invalid_payloads_fail_closed"),
            _node(_VERIFICATION, "test_request_maps_only_closed_verification_commands"),
            _node(_VERIFICATION, "test_cli_parser_covers_every_declared_verification_kind"),
            _node(
                _VERIFICATION,
                "test_actual_passing_pytest_node_emits_bounded_unchanged_receipt",
            ),
            _node(_VERIFICATION, "test_function_style_package_pytest_node_is_supported"),
            _node(_VERIFICATION, "test_real_red_pytest_returns_bounded_transient_diagnostic"),
            _node(_VERIFICATION, "test_repository_change_during_verification_is_rejected"),
            _node(
                _VERIFICATION,
                "test_failed_verifier_still_reports_after_fingerprint_change",
            ),
            _node(
                _VERIFICATION,
                "test_index_only_change_invalidates_verification_receipt",
            ),
            _node(
                _VERIFICATION,
                "test_mise_check_is_an_exact_allowlisted_regression_entrypoint",
            ),
            _node(
                _INCIDENT,
                "test_regression_command_cannot_leave_worktree_or_index_mutation",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_15,
        "Legacy snapshots and foreign session or actor batches remain isolated",
        (
            _node(
                _KERNEL, "test_process_state_without_material_actions_decodes_as_empty_projection"
            ),
            _node(_HANDLE, "test_handle_rejects_cross_actor_and_cross_session_prepare"),
            _node(_STOP, "test_root_stop_ignores_foreign_actor_open_material_action"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_16,
        "Structural context boundaries, exact emitted outbox bytes, and child lifecycle agree",
        (
            _node(
                _SESSION_RUNTIME,
                "test_user_enclave_substring_cannot_move_structural_context_boundary",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_startup_effect_binds_exact_emitted_additional_context",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_compact_effect_binds_exact_truncated_additional_context",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_fork_effect_binds_exact_emitted_additional_context",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_fork_retry_replays_exact_pending_context_effect",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_fork_retry_rejects_foreign_pending_delivery",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_subagent_effect_binds_runtime_binding_and_enclave_exactly",
            ),
            _node(
                _SESSION_RUNTIME,
                "test_subagent_start_bootstraps_one_idempotent_active_foreground_turn",
            ),
            _node(
                _STOP,
                "test_runtime_subagent_start_stop_fences_actor_and_late_child_tool",
            ),
            _node(
                _STOP,
                "test_subagent_stop_requires_owned_worktree_release_or_handoff",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        MaterialActionAcceptanceId.MAT_17,
        "Fresh runtime bootstrap and bounded harness maintenance remain executable",
        (
            _node(
                _HOOK_BOOTSTRAP,
                "test_hook_engine_imports_without_third_party_dependencies",
            ),
            _node(
                _HOOK_BOOTSTRAP,
                "test_installed_hook_runs_without_source_project",
            ),
            _node(
                _HOOK_BOOTSTRAP,
                "test_missing_installed_runtime_is_explicit_failure",
            ),
            _node(
                _SKILL_CHECKER,
                "test_all_skill_phase_and_evidence_contracts_are_consistent",
            ),
            _node(
                _SKILL_CHECKER,
                "test_distribution_rejects_added_modified_and_missing_files",
            ),
            _node(
                _MAINTENANCE,
                "test_exact_actor_and_target_are_authorized_only_for_structured_edits",
            ),
            _node(
                _MAINTENANCE,
                "test_close_moves_a_digest_readback_to_an_audit_receipt",
            ),
            _node(_MAINTENANCE, "test_scope_ttl_and_owner_are_fail_closed"),
        ),
        AUTO_SOURCE,
    ),
)
"""MAT-01..17과 exact unique public pytest node를 결속한 frozen matrix입니다."""

MATERIAL_ACTION_ACCEPTANCE_MATRIX_DIGEST = (
    "4388921773db2f8ab3267861c113ec4f632f6bfc33c91efd02f7a5bdf532d511"
)
"""ID, scenario, evidence surface와 exact node를 결속한 literal SHA-256입니다."""
