"""Frozen A01-A27 session harness acceptance matrix를 executable evidence로 실행합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class AcceptanceId(StrEnum):
    """Frozen specification의 acceptance row identity입니다."""

    A01 = "A01"
    """Compaction이 exact session 문맥만 주입하는지 검증하는 row입니다."""

    A02 = "A02"
    """동일 workflow ID가 runtime session별로 격리되는지 검증하는 row입니다."""

    A03 = "A03"
    """Orphan pointer가 fallback 문맥이 되지 않는지 검증하는 row입니다."""

    A04 = "A04"
    """동시 actor와 delegation transaction이 identity를 보존하는지 검증하는 row입니다."""

    A05 = "A05"
    """동일 revision의 동시 writer가 lost update 없이 충돌하는지 검증하는 row입니다."""

    A06 = "A06"
    """Atomic replace 전 process 종료가 canonical JSON을 보존하는지 검증하는 row입니다."""

    A07 = "A07"
    """Cross-session worktree claim에 단일 winner만 생기는지 검증하는 row입니다."""

    A08 = "A08"
    """비소유 session의 read-only worktree 접근을 보존하는지 검증하는 row입니다."""

    A09 = "A09"
    """Retired actor가 해제한 worktree를 재점유하지 못하는지 검증하는 row입니다."""

    A10 = "A10"
    """Enclave set이 같은 key의 최신 사실만 남기는지 검증하는 row입니다."""

    A11 = "A11"
    """Enclave delete가 tombstone이나 history를 남기지 않는지 검증하는 row입니다."""

    A12 = "A12"
    """용량 제한을 넘은 enclave mutation이 기존 상태를 보존하는지 검증하는 row입니다."""

    A13 = "A13"
    """Terminal session이 resume와 compact를 거부하는지 검증하는 row입니다."""

    A14 = "A14"
    """Corrupt 또는 mismatched state가 cross-session fallback을 막는지 검증하는 row입니다."""

    A15 = "A15"
    """Lifecycle retry가 state와 outbox에서 idempotent한지 검증하는 row입니다."""

    A16 = "A16"
    """Subagent start가 같은 session의 assignment만 주입하는지 검증하는 row입니다."""

    A17 = "A17"
    """Runtime capability 부재가 global fallback 없이 차단되는지 검증하는 row입니다."""

    A18 = "A18"
    """Skill workflow가 state path 없이 runtime identity에서 시작하는지 검증하는 row입니다."""

    A19 = "A19"
    """Fork가 한 snapshot을 복제한 뒤 독립적으로 분기하는지 검증하는 row입니다."""

    A20 = "A20"
    """Handoff가 명시적인 fenced receipt로만 owner를 바꾸는지 검증하는 row입니다."""

    A21 = "A21"
    """만료된 terminal session이 한 번만 정리 가능한 상태가 되는지 검증하는 row입니다."""

    A22 = "A22"
    """Static harness가 global pointer와 두 번째 graph runtime을 거부하는지 검증하는 row입니다."""

    A23 = "A23"
    """Prompt가 root foreground turn generation을 단조롭게 여는지 검증하는 row입니다."""

    A24 = "A24"
    """Stop이 self-authored receipt 없이 control turn만 닫는지 검증하는 row입니다."""

    A25 = "A25"
    """Open incident, delegation, inner workflow가 Stop을 fail-closed하는지 검증하는 row입니다."""

    A26 = "A26"
    """Dual runtime과 inner workflow가 root actor authority를 섞지 않는지 검증하는 row입니다."""

    A27 = "A27"
    """Codex child가 host turn 증거로만 root direct-child authority를 얻는지 검증합니다."""


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    """한 normative row와 이를 직접 실행하는 pytest node를 결합합니다."""

    row: StrEnum
    """Frozen specification에서 이 case가 증명하는 acceptance identity입니다."""

    scenario: str
    """사람이 receipt에서 읽을 수 있는 불변 scenario 설명입니다."""

    nodes: tuple[str, ...]
    """해당 row를 직접 증명하도록 고정된 exact pytest node 목록입니다."""

    evidence_surfaces: tuple[StrEnum, ...] = ()
    """Row를 평가하는 자동·독립·원본·사용자 evidence surface입니다."""


ACCEPTANCE_MATRIX: tuple[AcceptanceCase, ...] = (
    AcceptanceCase(
        AcceptanceId.A01,
        "Exact session compact isolation",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_compact_injects_only_the_exact_session_as_additional_context",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A02,
        "Multiple active workflows resolve by exact runtime session",
        (
            "scripts/skill_harness/tests/test_session_phase_runner_application.py::"
            "SessionPhaseRunnerApplicationTest::"
            "test_same_workflow_id_isolated_by_runtime_session",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A03,
        "Orphan pointer never supplies fallback context",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_terminal_corrupt_and_orphan_sessions_never_fallback",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A04,
        "Concurrent root and subagent delegation claims preserve every identity",
        (
            "scripts/agent_harness/tests/test_session_kernel.py::"
            "SessionKernelAcceptanceTest::"
            "test_concurrent_actor_and_delegation_transactions_preserve_every_identity",
            "scripts/skill_harness/tests/test_delegate_state.py::"
            "DelegateStateTest::"
            "test_begin_uses_exact_registered_actor_and_typed_assignment",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A05,
        "Concurrent writers and implicit no-op retries never return a stale workflow snapshot",
        (
            "scripts/agent_harness/tests/test_session_kernel.py::"
            "SessionKernelAcceptanceTest::"
            "test_compare_and_transact_reports_one_conflict_without_lost_update",
            "scripts/agent_harness/tests/test_session_kernel.py::"
            "SessionKernelAcceptanceTest::"
            "test_explicit_compare_rechecks_revision_before_returning_no_op_snapshot",
            "scripts/agent_harness/tests/test_session_kernel.py::"
            "SessionKernelAcceptanceTest::"
            "test_implicit_workflow_no_op_reduces_again_after_competing_commit",
            "scripts/agent_harness/tests/test_skill_state_store.py::"
            "SkillStateStoreTest::"
            "test_explicit_no_op_rechecks_revision_after_competing_commit",
            "scripts/skill_harness/tests/test_process_state_evidence.py::"
            "ProcessStateEvidenceTest::"
            "test_external_merge_readback_conflict_requires_whole_command_retry",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A06,
        "Process death before atomic replace preserves canonical JSON",
        (
            "scripts/agent_harness/tests/test_session_kernel.py::"
            "SessionKernelAcceptanceTest::"
            "test_process_death_before_atomic_replace_preserves_previous_canonical_json",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A07,
        "Cross-session worktree claim has exactly one winner",
        (
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_concurrent_cross_session_claim_has_exactly_one_owner",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_claim_rechecks_actor_authority_inside_the_commit_fence",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_handoff_rechecks_target_authority_inside_the_commit_fence",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A08,
        "Unrelated session retains read-only worktree access",
        (
            "scripts/agent_harness/tests/test_worktree_hook.py::"
            "WorktreeHookApplicationTest::test_unrelated_session_can_read_claimed_worktree",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A09,
        "Retired actor cannot mutate or complete cleanup for its previous worktree",
        (
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_retired_actor_cannot_reclaim_a_released_worktree",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_retired_owner_cannot_authorize_mutation_release_or_handoff_current_lease",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_ended_owner_session_cannot_authorize_mutation_release_or_handoff_current_lease",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_release_and_handoff_compare_owner_authority_and_lease_under_one_fence",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_mutation_authorize_never_stale_allows_owner_after_concurrent_handoff",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_retired_owner_cannot_complete_cleanup_reservation",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A10,
        "Enclave overwrite retains only the latest value",
        (
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::"
            "test_set_overwrites_same_key_without_history_or_version_metadata",
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::"
            "test_explicit_noop_set_rechecks_digest_after_candidate_preparation",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A11,
        "Enclave delete leaves no tombstone or history",
        (
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::test_delete_removes_fact_without_tombstone_or_history",
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::"
            "test_explicit_noop_delete_rechecks_digest_after_candidate_preparation",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A12,
        "Oversized enclave mutation fails closed",
        (
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::"
            "test_oversized_mutation_fails_closed_without_changing_existing_enclave",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A13,
        "Terminal session rejects lifecycle rehydration",
        (
            "scripts/agent_harness/tests/test_session_lifecycle_outbox.py::"
            "SessionLifecycleOutboxTest::"
            "test_terminal_session_rejects_resume_and_compact",
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::"
            "test_session_end_winning_set_commit_fence_rejects_late_fact",
            "scripts/agent_harness/tests/test_enclave_store.py::"
            "EnclaveStoreAcceptanceTest::"
            "test_session_end_winning_noop_delete_fence_rejects_terminal_mutation",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A14,
        "Corrupt or mismatched state never falls back across sessions",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_terminal_corrupt_and_orphan_sessions_never_fallback",
            "scripts/agent_harness/tests/test_state_handle.py::"
            "StateHandleTest::test_apply_rejects_an_event_bound_to_another_session",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A15,
        "Lifecycle retry is state-and-outbox idempotent",
        (
            "scripts/agent_harness/tests/test_session_lifecycle_outbox.py::"
            "SessionLifecycleOutboxTest::"
            "test_compact_retry_after_ack_is_idempotent_and_outbox_remains_bounded",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A16,
        "Subagent start receives only same-session scoped assignments",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::test_subagent_start_injects_only_target_assignments",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A17,
        "Unavailable runtime capability is blocked without global fallback",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_unavailable_capability_is_blocked_without_global_fallback",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A18,
        "Skill workflow starts from runtime identity without a state path selector",
        (
            "scripts/skill_harness/tests/test_session_phase_runner_application.py::"
            "SessionPhaseRunnerApplicationTest::"
            "test_init_current_complete_finalize_use_one_session_workflow",
            "scripts/agent_harness/tests/test_state_cli.py::"
            "StateCliApplicationTest::"
            "test_manual_state_and_repository_selectors_are_rejected_as_typed_json",
            "scripts/agent_harness/tests/test_state_handle.py::"
            "StateHandleTest::"
            "test_apply_forwards_explicit_expected_revision_to_the_exact_session_kernel",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A19,
        "Fork copies one snapshot and then diverges independently",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_fork_copies_one_snapshot_then_keeps_enclaves_independent",
            "scripts/agent_harness/tests/test_runtime_hook.py::"
            "RuntimeHookApplicationTest::"
            "test_runtime_fork_creates_independent_target_or_blocks_unavailable",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A20,
        "Handoff changes owner only through an explicit fenced receipt",
        (
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_synthetic_handoff_retires_previous_actor",
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_handoff_retry_after_lease_commit_retires_previous_actor",
            "scripts/agent_harness/tests/test_session_rehydration.py::"
            "SessionRehydrationTest::"
            "test_handoff_retry_does_not_recover_another_proof_for_same_target_actor",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_cleanup_reservation_blocks_normal_owner_transitions",
            "scripts/agent_harness/tests/test_worktree_registry.py::"
            "WorktreeRegistryAcceptanceTest::"
            "test_cleanup_reservation_uses_the_planned_fencing_token",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_handoff_before_cleanup_is_fenced_before_ticket_removal",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_stale_cleanup_conflicts_before_any_git_mutation",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_git_failure_keeps_exact_reservation_for_safe_retry",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_new_invocation_resumes_after_worktree_removal_before_claim_completion",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_same_actor_resumes_two_workflow_cleanup_plans_without_scanning",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_cleanup_intent_cas_conflict_precedes_every_git_mutation",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_new_invocation_rebuilds_receipt_after_claim_release_crash",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_late_clean_commit_conflicts_then_fresh_command_replans",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_dirty_or_untracked_ticket_conflicts_without_reservation",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_foreign_recreated_reservation_with_same_owner_epoch_is_rejected",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_root_branch_is_rechecked_at_every_destructive_boundary",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_claim_release_recovery_fetches_and_syncs_latest_remote_head",
            "scripts/skill_harness/tests/test_merge_cleanup.py::"
            "MergeCleanupTest::"
            "test_branch_delete_compare_and_swap_preserves_a_concurrently_moved_ref",
            "scripts/skill_harness/tests/test_monitor_runtime_handoff.py::"
            "MonitorRuntimeHandoffTest::"
            "test_revision_conflict_before_prepare_causes_no_external_effect",
            "scripts/skill_harness/tests/test_monitor_runtime_handoff.py::"
            "MonitorRuntimeHandoffTest::"
            "test_new_invocation_resumes_prepared_handoff_after_retirement_crash",
            "scripts/skill_harness/tests/test_monitor_runtime_handoff.py::"
            "MonitorRuntimeHandoffTest::"
            "test_later_state_conflict_preflights_before_any_launch_agent_effect",
            "scripts/skill_harness/tests/test_monitor_runtime_handoff.py::"
            "MonitorRuntimeHandoffTest::"
            "test_foreign_handoff_claim_is_conflict_not_idempotent_missing",
            "scripts/skill_harness/tests/test_monitor_runtime_handoff.py::"
            "MonitorRuntimeHandoffTest::"
            "test_commit_lock_is_released_before_process_and_launchctl_io",
            "scripts/skill_harness/tests/test_monitor_runtime_handoff.py::"
            "MonitorRuntimeHandoffTest::"
            "test_new_invocation_adopts_durable_file_claims_after_abrupt_stop",
            "scripts/skill_harness/tests/test_launch_agent_plist.py::"
            "LaunchAgentPlistTest::"
            "test_prepared_handoff_claim_blocks_same_plist_path_reuse",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A21,
        "Expired terminal session deletes enclave and becomes collectible once",
        (
            "scripts/agent_harness/tests/test_session_retention.py::"
            "SessionRetentionAcceptanceTest::"
            "test_end_deletes_enclave_and_expired_state_is_collected_exactly_once",
            "scripts/agent_harness/tests/test_runtime_hook.py::"
            "RuntimeHookApplicationTest::"
            "test_runtime_session_end_transitions_or_blocks_unavailable",
            "scripts/agent_harness/tests/test_distribution_boundary.py::"
            "DistributionBoundaryTest::"
            "test_native_hook_failure_sensor_is_preserved_and_drift_detected",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A22,
        "Static harness rejects global pointers and a second LLM graph runtime",
        (
            "scripts/skill_harness/tests/test_checker.py::"
            "SkillHarnessCheckerTest::"
            "test_rejects_global_active_pointer_in_production_harness",
            "scripts/skill_harness/tests/test_checker.py::"
            "SkillHarnessCheckerTest::"
            "test_rejects_state_handle_open_and_agent_graph_runtime_dependency",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A23,
        "Prompt lifecycle opens and reuses one monotonic root foreground turn",
        (
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_session_start_does_not_create_turn",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_prompt_starts_turn",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_prompt_retry_reuses_active_turn",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_ready_prompt_reactivates_turn",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_next_prompt_opens_next_generation",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A24,
        "Stop closes control transport without requiring a self-authored terminal receipt",
        (
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_stop_active_turn_closes_without_agent_receipt",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_completed_yield_stop_closes",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_awaiting_input_yield_stop_closes",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_stale_yield_revision_denies",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A25,
        "Stop revalidates incidents, delegations and inner workflows before closing",
        (
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_inner_failure_invalidates_ready",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "StopTerminalReachabilityRemainingMatrixTest::test_open_incident_without_monitor_stop_denies",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "StopTerminalReachabilityRemainingMatrixTest::test_unresolved_delegation_without_monitor_stop_denies",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnGenerationCasTest::test_stop_close_revalidates_concurrent_inner_workflow",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnGenerationCasTest::"
            "test_stop_rejects_workflow_aba_during_external_validation",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnGenerationCasTest::"
            "test_stop_rejects_incident_aba_during_external_validation",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnGenerationCasTest::"
            "test_stop_rejects_delegation_aba_during_external_validation",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A26,
        "Runtime-neutral continuation keeps root and inner actor authority isolated",
        (
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_root_skill_workflow_coexists",
            "scripts/agent_harness/tests/test_distribution_boundary.py::"
            "DistributionBoundaryTest::test_installed_hook_runs_without_source_project",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "ForegroundTurnContinuationMatrixTest::test_foreign_actor_turn_cannot_authorize_root",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "AgentContinuationHookTest::test_codex_overlay_without_vendor_identity_fails_closed",
            "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
            "AgentContinuationHookTest::"
            "test_payload_actor_claim_cannot_inherit_root_vendor_identity",
        ),
    ),
    AcceptanceCase(
        AcceptanceId.A27,
        "Codex direct child requires an exact active root turn attested by the host",
        (
            "scripts/agent_harness/tests/test_runtime_adapter.py::"
            "RuntimeAdapterTest::"
            "test_official_codex_subagent_start_normalizes_state_free_child_identity",
            "scripts/agent_harness/tests/test_runtime_hook.py::"
            "RuntimeHookApplicationTest::"
            "test_codex_turn_attested_direct_child_is_registered_without_parent_extension",
            "scripts/agent_harness/tests/test_runtime_hook.py::"
            "RuntimeHookApplicationTest::"
            "test_codex_turn_attested_child_report_is_consumed_by_root_owner",
            "scripts/agent_harness/tests/test_runtime_hook.py::"
            "RuntimeHookApplicationTest::"
            "test_codex_missing_or_spoofed_turn_keeps_child_state_free",
            "scripts/agent_harness/tests/test_runtime_hook.py::"
            "RuntimeHookApplicationTest::"
            "test_codex_nested_turn_match_does_not_register_grandchild",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """한 acceptance row subprocess의 bounded execution result입니다."""

    returncode: int
    """Exact pytest subprocess가 반환한 process exit code입니다."""

    stdout: str
    """Receipt digest와 tail을 만들 때 사용하는 captured standard output입니다."""

    stderr: str
    """실패 원인과 output digest에 포함할 captured standard error입니다."""


class CommandRunner(Protocol):
    """Acceptance runner가 subprocess transport에서 분리해 사용하는 port입니다."""

    def run(self, arguments: Sequence[str], *, cwd: Path) -> CommandResult:
        """Command를 실행하고 output을 반환합니다.

        Args:
            arguments: Executable과 argument sequence입니다.
            cwd: Frozen repository root입니다.

        Returns:
            Exit status와 captured output입니다.
        """
        ...


class SubprocessCommandRunner:
    """현재 Python environment에서 exact pytest node를 실행합니다."""

    def run(self, arguments: Sequence[str], *, cwd: Path) -> CommandResult:
        """PYTHONPATH를 repository root로 고정해 child pytest를 실행합니다.

        Args:
            arguments: Executable과 argument sequence입니다.
            cwd: Frozen repository root입니다.

        Returns:
            Exit status와 captured UTF-8 output입니다.
        """
        environment = dict(os.environ)
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(cwd) if not existing_pythonpath else f"{cwd}{os.pathsep}{existing_pythonpath}"
        )
        completed = subprocess.run(
            tuple(arguments),
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class AcceptanceMatrixRunner:
    """Frozen matrix row를 각각 독립 실행하고 machine-readable receipt를 만듭니다."""

    def __init__(
        self,
        repository: Path,
        command_runner: CommandRunner,
        *,
        receipt_schema: str = "neurath.session-harness-acceptance-receipt.v1",
        matrix_digest: str | None = None,
    ) -> None:
        """Repository와 command transport를 명시적으로 주입합니다.

        Args:
            repository: Matrix node가 상대 경로로 해석될 repository root입니다.
            command_runner: Exact node를 실행할 subprocess port입니다.
            receipt_schema: Matrix contract별 machine-readable receipt schema입니다.
            matrix_digest: Full frozen matrix를 식별하는 optional canonical digest입니다.
        """
        self._repository = repository.resolve()
        self._command_runner = command_runner
        self._receipt_schema = receipt_schema
        self._matrix_digest = matrix_digest

    def execute(
        self,
        cases: Sequence[AcceptanceCase],
        *,
        fail_fast: bool,
    ) -> dict[str, object]:
        """선택한 row를 실행하고 row별 node/output digest를 반환합니다.

        Args:
            cases: Frozen matrix에서 선택한 ordered cases입니다.
            fail_fast: 첫 실패 뒤 나머지 row 실행을 중단할지 여부입니다.

        Returns:
            Aggregate verdict와 각 row의 exact node evidence입니다.
        """
        results: list[dict[str, object]] = []
        for case in cases:
            started_at = time.monotonic()
            result = self._command_runner.run(
                (sys.executable, "-m", "pytest", "-q", *case.nodes),
                cwd=self._repository,
            )
            elapsed_ms = round((time.monotonic() - started_at) * 1000)
            output = f"{result.stdout}\n{result.stderr}".strip()
            row_result: dict[str, object] = {
                "row": case.row.value,
                "scenario": case.scenario,
                "nodes": list(case.nodes),
                "passed": result.returncode == 0,
                "returncode": result.returncode,
                "elapsed_ms": elapsed_ms,
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                "output_tail": output[-4000:],
            }
            if case.evidence_surfaces:
                row_result["evidence_surfaces"] = [
                    surface.value for surface in case.evidence_surfaces
                ]
            results.append(row_result)
            if result.returncode != 0 and fail_fast:
                break
        passed = len(results) == len(cases) and all(bool(result["passed"]) for result in results)
        receipt: dict[str, object] = {
            "schema": "neurath.session-harness-acceptance-receipt.v1",
            "matrix_rows": [case.row.value for case in cases],
            "executed_rows": [str(result["row"]) for result in results],
            "passed": passed,
            "results": results,
        }
        if self._receipt_schema != "neurath.session-harness-acceptance-receipt.v1":
            receipt["schema"] = self._receipt_schema
        if self._matrix_digest is not None:
            receipt["matrix_digest"] = self._matrix_digest
        return receipt


def canonical_matrix_digest(cases: Sequence[AcceptanceCase]) -> str:
    """Frozen matrix의 semantic inputs를 canonical SHA-256으로 결속합니다.

    Args:
        cases: Identity, scenario, surface, exact node를 가진 ordered matrix입니다.

    Returns:
        Key-order와 공백 표현에 독립적인 lowercase SHA-256 digest입니다.
    """
    payload = [
        {
            "id": case.row.value,
            "nodes": list(case.nodes),
            "scenario": case.scenario,
            "surfaces": [surface.value for surface in case.evidence_surfaces],
        }
        for case in cases
    ]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _parser() -> argparse.ArgumentParser:
    """Acceptance matrix public CLI parser를 구성합니다.

    Returns:
        Row selection과 fail-fast 외 state selector가 없는 parser입니다.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--row",
        action="append",
        choices=tuple(row.value for row in AcceptanceId),
        help="실행할 acceptance row입니다. 생략하면 A01-A27 전체를 실행합니다.",
    )
    parser.add_argument("--fail-fast", action="store_true")
    return parser


def _selected_cases(rows: Sequence[str] | None) -> tuple[AcceptanceCase, ...]:
    """CLI row selection을 frozen matrix order로 정규화합니다.

    Args:
        rows: Repeated `--row` values 또는 전체 선택을 뜻하는 None입니다.

    Returns:
        Duplicate가 제거된 frozen-order cases입니다.
    """
    if rows is None:
        return ACCEPTANCE_MATRIX
    selected = frozenset(AcceptanceId(row) for row in rows)
    return tuple(case for case in ACCEPTANCE_MATRIX if case.row in selected)


def main(arguments: Sequence[str] | None = None) -> int:
    """Frozen acceptance matrix를 실행하고 JSON receipt를 출력합니다.

    Args:
        arguments: Test에서 주입할 optional CLI arguments입니다.

    Returns:
        모든 선택 row가 통과하면 0, 하나라도 실패하면 1입니다.
    """
    parsed = _parser().parse_args(arguments)
    repository = __import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(Path(__file__).resolve().parents[2])
    receipt = AcceptanceMatrixRunner(repository, SubprocessCommandRunner()).execute(
        _selected_cases(parsed.row),
        fail_fast=bool(parsed.fail_fast),
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if bool(receipt["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
