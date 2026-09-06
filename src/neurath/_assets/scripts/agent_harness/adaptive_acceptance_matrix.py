"""Frozen 56-row adaptive-control acceptance matrix를 실행합니다."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from scripts.agent_harness.acceptance_matrix import (
    AcceptanceCase,
    AcceptanceMatrixRunner,
    SubprocessCommandRunner,
)


class AdaptiveAcceptanceId(StrEnum):
    """Adaptive-control frozen specification의 stable row identity입니다."""

    Q01 = "ADP-Q01"
    """Assessment가 수행되지 않은 inventory 상태를 검증합니다."""

    Q02 = "ADP-Q02"
    """Requirement section 전체 assessment를 검증합니다."""

    Q03 = "ADP-Q03"
    """Hard user gap의 non-compensating 성질을 검증합니다."""

    Q04 = "ADP-Q04"
    """Upstream question selection을 검증합니다."""

    Q05 = "ADP-Q05"
    """동일 frontier의 authority 우선순위를 검증합니다."""

    Q06 = "ADP-Q06"
    """Canonical Socratic prompt를 검증합니다."""

    Q07 = "ADP-Q07"
    """Repository research와 source invalidation을 검증합니다."""

    Q08 = "ADP-Q08"
    """Intent-scoped gap authority를 검증합니다."""

    Q09 = "ADP-Q09"
    """Authoritative terminal blocker routing을 검증합니다."""

    R01 = "ADP-R01"
    """Nontrivial goal의 criterion 최소 조건을 검증합니다."""

    R02 = "ADP-R02"
    """Criterion requirement lineage를 검증합니다."""

    R03 = "ADP-R03"
    """Closed requirement ledger coverage를 검증합니다."""

    R04 = "ADP-R04"
    """Requirement ledger fingerprint 결속을 검증합니다."""

    E01 = "ADP-E01"
    """Exact independent goal coverage를 검증합니다."""

    E02 = "ADP-E02"
    """Test와 semantic/user acceptance의 분리를 검증합니다."""

    E03 = "ADP-E03"
    """Non-code goal의 evidence 적합성을 검증합니다."""

    E04 = "ADP-E04"
    """Hard와 soft criterion의 non-compensating veto를 검증합니다."""

    E05 = "ADP-E05"
    """Evaluation revision supersession을 검증합니다."""

    E06 = "ADP-E06"
    """Goal과 intent revision receipt invalidation을 검증합니다."""

    E07 = "ADP-E07"
    """Independent coverage authority를 검증합니다."""

    E08 = "ADP-E08"
    """Semantic threshold와 execution completion을 검증합니다."""

    P01 = "ADP-P01"
    """Current repository source readback을 검증합니다."""

    P02 = "ADP-P02"
    """Repository fact authority를 검증합니다."""

    P03 = "ADP-P03"
    """Safe-assumption authority를 검증합니다."""

    P04 = "ADP-P04"
    """Exact evaluator claim set을 검증합니다."""

    P05 = "ADP-P05"
    """Evaluator delegation과 lineage fencing을 검증합니다."""

    P06 = "ADP-P06"
    """Executable claim report signature를 검증합니다."""

    P07 = "ADP-P07"
    """Primary-source claim의 이중 증거를 검증합니다."""

    P08 = "ADP-P08"
    """Runtime receipt가 없는 user authority의 pending 상태를 검증합니다."""

    P09 = "ADP-P09"
    """Await-user prompt context 결속을 검증합니다."""

    P10 = "ADP-P10"
    """User acceptance의 joint authority를 검증합니다."""

    P11 = "ADP-P11"
    """User gap fact와 deferral receipt를 검증합니다."""

    P12 = "ADP-P12"
    """Content-addressed evaluator candidate의 end-to-end identity를 검증합니다."""

    P13 = "ADP-P13"
    """실제 executable receipt replay와 completion claim을 검증합니다."""

    P14 = "ADP-P14"
    """Raw-free typed USER decision authority를 검증합니다."""

    S01 = "ADP-S01"
    """Adaptive state CAS와 namespace isolation을 검증합니다."""

    S02 = "ADP-S02"
    """Goal override의 authority reset을 검증합니다."""

    S03 = "ADP-S03"
    """Same-goal history monotonicity를 검증합니다."""

    S04 = "ADP-S04"
    """Evidence revision monotonicity를 검증합니다."""

    S05 = "ADP-S05"
    """Coverage revision과 gap monotonicity를 검증합니다."""

    S06 = "ADP-S06"
    """Canonical observation과 recovery epoch를 검증합니다."""

    S07 = "ADP-S07"
    """Reserved adaptive namespace isolation을 검증합니다."""

    S08 = "ADP-S08"
    """USER decision effect consumption과 monotonic ledger를 검증합니다."""

    F01 = "ADP-F01"
    """Adaptive phase initialization과 north-star binding을 검증합니다."""

    F02 = "ADP-F02"
    """모든 phase transition의 adaptive readback을 검증합니다."""

    F03 = "ADP-F03"
    """Completion과 finalization authority를 검증합니다."""

    F04 = "ADP-F04"
    """Exact adaptive control-return authority를 검증합니다."""

    L01 = "ADP-L01"
    """Reflection active scope를 검증합니다."""

    L02 = "ADP-L02"
    """Repeated root-cause recovery routing을 검증합니다."""

    L03 = "ADP-L03"
    """Recovery epoch history isolation을 검증합니다."""

    L04 = "ADP-L04"
    """Oscillation과 plateau stop을 검증합니다."""

    L05 = "ADP-L05"
    """Exhaustion, promotion, success의 분리를 검증합니다."""

    A01 = "ADP-A01"
    """Runtime adaptive policy closed set을 검증합니다."""

    A02 = "ADP-A02"
    """Skill adaptive policy static enforcement를 검증합니다."""

    A03 = "ADP-A03"
    """Agent harness adaptive oracle pinning을 검증합니다."""

    A04 = "ADP-A04"
    """Frozen matrix의 literal digest와 executable node inventory를 검증합니다."""


class EvidenceSurface(StrEnum):
    """Acceptance result를 판단하는 서로 다른 evidence authority 표면입니다."""

    AUTO = "AUTO"
    """Deterministic executable check가 직접 판단하는 표면입니다."""

    COLD = "COLD"
    """구현 문맥과 분리된 independent cold-read가 판단하는 표면입니다."""

    SOURCE = "SOURCE"
    """현재 repository primary source readback이 판단하는 표면입니다."""

    USER = "USER"
    """Runtime-bound current user authority가 판단하는 표면입니다."""


_D = "scripts/agent_harness/tests/test_adaptive_control.py::AdaptiveControlTest"
_S = "scripts/agent_harness/tests/test_adaptive_control_store.py::AdaptiveControlStoreTest"
_V = (
    "scripts/agent_harness/tests/test_adaptive_control_authority.py::"
    "AdaptiveControlAuthorityVerifierTest"
)
_HS = (
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
    "StopTerminalReachabilityMatrixTest"
)
_HT = (
    "scripts/agent_harness/tests/test_agent_continuation_hook.py::"
    "ForegroundTurnContinuationMatrixTest"
)
_CLI = "scripts/agent_harness/tests/test_state_cli.py::StateCliApplicationTest"
_PH = "scripts/skill_harness/tests/test_phase_runner.py::PhaseRunnerApplicationTest"
_POL = "scripts/agent_harness/tests/test_adaptive_policy.py::AdaptivePolicyTest"
_AH = "scripts/agent_harness/tests/test_checker.py::AgentHarnessCheckerTest"
_SH = "scripts/skill_harness/tests/test_checker.py::SkillHarnessCheckerTest"
_RR = "scripts/agent_harness/tests/test_repository_readback.py::RepositoryWorktreeReadbackTest"
_CANDIDATE = (
    "scripts/agent_harness/tests/test_adaptive_evaluation_candidate.py::"
    "AdaptiveEvaluationCandidateStoreTest"
)
_EXECUTION = (
    "scripts/agent_harness/tests/test_adaptive_execution_receipt.py::"
    "AdaptiveExecutionReceiptStoreTest"
)
_USER_DECISION = (
    "scripts/agent_harness/tests/test_adaptive_user_decision.py::UserDecisionContractTest"
)
_SESSION_KERNEL = "scripts/agent_harness/tests/test_session_kernel.py::SessionKernelAcceptanceTest"
_SKILL_STORE = "scripts/agent_harness/tests/test_skill_state_store.py::SkillStateStoreTest"
_MATRIX = (
    "scripts/agent_harness/tests/test_adaptive_acceptance_matrix.py::AdaptiveAcceptanceMatrixTest"
)
_PHASE_STORE = "scripts/skill_harness/tests/test_session_phase_store.py::SessionPhaseStateStoreTest"
_AGGREGATE = (
    "scripts/agent_harness/tests/test_adaptive_aggregate_boundary.py::AdaptiveAggregateBoundaryTest"
)


def _node(suite: str, test_name: str) -> str:
    """Suite identity와 test name을 exact pytest node로 결합합니다.

    Args:
        suite: Module과 test class를 포함한 stable suite prefix입니다.
        test_name: `test_`로 시작하는 exact method name입니다.

    Returns:
        Pytest가 직접 collect하고 실행할 fully qualified node입니다.
    """
    return f"{suite}::{test_name}"


AUTO = (EvidenceSurface.AUTO,)
AUTO_COLD = (EvidenceSurface.AUTO, EvidenceSurface.COLD)
AUTO_SOURCE = (EvidenceSurface.AUTO, EvidenceSurface.SOURCE)
AUTO_USER = (EvidenceSurface.AUTO, EvidenceSurface.USER)
AUTO_COLD_SOURCE = (
    EvidenceSurface.AUTO,
    EvidenceSurface.COLD,
    EvidenceSurface.SOURCE,
)
AUTO_COLD_USER = (
    EvidenceSurface.AUTO,
    EvidenceSurface.COLD,
    EvidenceSurface.USER,
)
AUTO_SOURCE_USER = (
    EvidenceSurface.AUTO,
    EvidenceSurface.SOURCE,
    EvidenceSurface.USER,
)


ADAPTIVE_ACCEPTANCE_MATRIX: tuple[AcceptanceCase, ...] = (
    AcceptanceCase(
        AdaptiveAcceptanceId.Q01,
        "Unassessed inventory remains distinct from assessed-empty inventory",
        (_node(_D, "test_unassessed_inventory_is_distinct_from_assessed_empty_inventory"),),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q02,
        "Every requirement section is assessed before intent becomes ready",
        (_node(_D, "test_every_requirement_section_must_be_assessed_before_intent_is_ready"),),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q03,
        "A hard user gap cannot be hidden by aggregate ambiguity",
        (_node(_D, "test_hard_user_gap_cannot_be_hidden_by_low_aggregate_ambiguity"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q04,
        "Question selection is upstream and permutation invariant",
        (_node(_D, "test_question_selection_is_upstream_and_permutation_invariant"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q05,
        "Same-frontier gaps prioritize repository, safe assumption, then user",
        (_node(_D, "test_same_frontier_uses_repository_then_safe_assumption_then_user"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q06,
        "Socratic prompts are canonical and preserve every explanatory field",
        (_node(_D, "test_socratic_prompt_is_canonical_and_uses_every_explanatory_field"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q07,
        "Repository-answerable gaps research current source and reopen on source change",
        (
            _node(_D, "test_repository_answerable_gap_routes_to_research"),
            _node(_D, "test_repository_resolution_reopens_when_its_source_basis_changes"),
        ),
        AUTO_SOURCE,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q08,
        "Gap resolution is intent-scoped and authority-matched",
        (
            _node(_D, "test_gap_resolution_requires_matching_authority"),
            _node(_D, "test_gap_must_belong_to_the_inventory_intent_revision"),
            _node(_D, "test_user_owned_nonblocking_gap_requires_current_user_deferral"),
        ),
        AUTO_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.Q09,
        "Current USER and repository blockers terminate deterministically without reasking or self-authored authority",
        (
            _node(
                _D,
                "test_authoritative_user_and_repository_blockers_route_blocked_without_reasking",
            ),
            _node(_D, "test_blocker_requires_external_authority_and_cannot_be_directly_unproven"),
            _node(_D, "test_blocker_selection_is_upstream_and_permutation_invariant"),
            _node(_S, "test_authoritative_blocker_is_terminal_and_cannot_reopen_or_become_fact"),
            _node(_S, "test_blocker_requires_an_existing_open_gap_and_current_source_basis"),
            _node(_V, "test_terminal_blocker_reuses_user_and_repository_runtime_authority"),
            _node(_V, "test_current_user_prompt_and_independent_decision_verify_user_blocker"),
            _node(
                _PH,
                "test_adaptive_incomplete_inventory_cannot_masquerade_as_terminal_blocker",
            ),
            _node(
                _PH,
                "test_adaptive_authoritative_repository_blocker_can_terminalize_the_phase",
            ),
        ),
        AUTO_SOURCE_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.R01,
        "Nontrivial goals require nonempty criteria including a hard criterion",
        (
            _node(_D, "test_nontrivial_goal_rejects_empty_acceptance_criteria"),
            _node(_D, "test_nontrivial_goal_requires_at_least_one_hard_criterion"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.R02,
        "Every criterion has approved requirement and observable lineage",
        (
            _node(_D, "test_criterion_requires_approved_requirement_and_observable_lineage"),
            _node(_D, "test_contract_rejects_criterion_from_another_approved_requirement"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.R03,
        "The requirement ledger is nonempty, closed, and fully covered",
        (_node(_D, "test_requirement_ledger_is_nonempty_closed_and_fully_covered"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.R04,
        "Requirement ledger changes invalidate the goal fingerprint",
        (_node(_D, "test_requirement_ledger_participates_in_goal_fingerprint"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E01,
        "Goal completion requires exact independent coverage and all evidence",
        (_node(_D, "test_goal_requires_exact_independent_coverage_and_all_evidence"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E02,
        "Passing tests never substitute for semantic or user acceptance",
        (_node(_D, "test_passing_tests_do_not_satisfy_semantic_or_user_acceptance"),),
        AUTO_COLD_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E03,
        "Non-code goals can complete without invented example tests",
        (_node(_D, "test_non_code_goal_can_complete_without_example_tests"),),
        AUTO_COLD_SOURCE,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E04,
        "Hard failures and missing soft criteria are non-compensating vetoes",
        (
            _node(_D, "test_hard_failure_is_not_compensated_by_soft_passes"),
            _node(_D, "test_missing_soft_criterion_cannot_be_reclassified_as_complete"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E05,
        "Latest evaluation revision supersedes history while retaining same-revision vetoes",
        (
            _node(_D, "test_failure_vetoes_pass_on_the_same_required_surface"),
            _node(_D, "test_not_evaluated_vetoes_pass_on_the_same_required_surface"),
            _node(_D, "test_newer_evaluation_revision_supersedes_an_old_failure"),
            _node(_D, "test_failure_veto_applies_only_within_the_latest_evaluation_revision"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E06,
        "Goal or intent revision changes invalidate old receipts",
        (
            _node(_D, "test_goal_override_invalidates_old_receipts"),
            _node(_D, "test_same_text_new_intent_revision_invalidates_old_receipts"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E07,
        "Self-authored or user-only coverage cannot authorize completion",
        (
            _node(_D, "test_self_authored_coverage_cannot_authorize_goal_completion"),
            _node(_D, "test_user_acceptance_does_not_replace_independent_goal_coverage"),
        ),
        AUTO_COLD_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.E08,
        "Semantic threshold failures and incomplete execution veto completion",
        (
            _node(_D, "test_semantic_thresholds_are_non_compensating_goal_vetoes"),
            _node(_D, "test_completed_evidence_cannot_hide_incomplete_execution"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P01,
        "Repository readback binds canonical path, current bytes, and worktree identity",
        (
            _node(
                _RR,
                "test_tracked_file_readback_binds_canonical_path_fingerprint_and_current_bytes",
            ),
            _node(
                _RR,
                "test_absolute_traversal_symlink_escape_missing_ignored_and_untracked_are_denied",
            ),
            _node(
                _RR,
                "test_exact_dirty_current_bytes_are_readable_with_new_worktree_and_content_fingerprints",
            ),
        ),
        AUTO_SOURCE,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P02,
        "Repository facts require current tracked primary-source authority",
        (
            _node(_V, "test_repository_fact_requires_primary_source_readback"),
            _node(_V, "test_repository_fact_accepts_only_current_tracked_primary_source"),
            _node(_V, "test_repository_fact_rejects_source_changed_after_authority_receipt"),
        ),
        AUTO_SOURCE,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P03,
        "Safe assumptions require structured current-context authority",
        (_node(_V, "test_safe_assumption_requires_structure_and_current_same_context"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P04,
        "One consumed evaluator report signs the exact complete claim set",
        (_node(_V, "test_one_consumed_evaluator_report_signs_the_exact_complete_claim_set"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P05,
        "Evaluator delegation, claim set, lineage, and artifact identity fail closed",
        (
            _node(_V, "test_missing_pending_reported_and_cancelled_delegations_are_denied"),
            _node(_V, "test_evaluator_report_with_missing_or_extra_claim_is_denied"),
            _node(_V, "test_mismatched_foreign_and_forged_authority_rows_are_denied"),
            _node(_V, "test_distinct_lineages_cannot_reuse_one_delegation_identity"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P06,
        "Executable claims require the exact independent report signature",
        (
            _node(
                _V,
                "test_executable_claim_requires_and_accepts_exact_independent_report_signature",
            ),
            _node(_V, "test_arbitrary_executable_reference_without_exact_signed_report_is_denied"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P07,
        "Primary-source claims require signed report plus current direct readback",
        (
            _node(
                _V,
                "test_primary_source_claim_requires_signed_report_and_direct_current_readback",
            ),
            _node(_V, "test_signed_but_forged_primary_source_digest_is_denied"),
        ),
        AUTO_COLD_SOURCE,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P08,
        "User facts and deferrals remain pending without runtime user receipt",
        (_node(_V, "test_user_fact_and_deferral_are_pending_without_runtime_user_receipt"),),
        AUTO_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P09,
        "Await-user context binds exact goal, question, claims, and prompt digest",
        (
            _node(
                _HS,
                "test_adaptive_await_user_response_binds_exact_goal_question_and_claims",
            ),
            _node(
                _HT,
                "test_root_prompt_preserves_only_canonical_digest_and_runtime_metadata",
            ),
            _node(_HT, "test_root_prompt_without_text_keeps_normal_turn_without_user_authority"),
        ),
        AUTO_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P10,
        "User acceptance requires both current prompt and independent report",
        (
            _node(
                _V,
                "test_current_user_prompt_and_independent_report_jointly_verify_acceptance",
            ),
            _node(_V, "test_user_acceptance_rejects_stale_or_foreign_prompt_receipt"),
        ),
        AUTO_COLD_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P11,
        "Current prompt verifies only exact user gap facts and deferrals",
        (_node(_V, "test_current_user_prompt_verifies_user_gap_fact_and_deferral"),),
        AUTO_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P12,
        "Content-addressed candidate binds source and target workflow revisions, bounded trajectory assessment, result, and admitted state",
        (
            _node(
                _CANDIDATE,
                "test_owner_prepares_content_addressed_candidate_and_child_reads_typed_state",
            ),
            _node(
                _CANDIDATE,
                "test_material_trajectory_is_content_bound_and_stale_before_evaluation",
            ),
            _node(
                _CANDIDATE,
                "test_owner_verifies_registered_candidate_against_exact_expected_state",
            ),
            _node(
                _CANDIDATE,
                "test_candidate_requires_owner_registered_pending_assignment",
            ),
            _node(
                _CANDIDATE,
                "test_sibling_workflow_mutation_invalidates_prepared_candidate_revision",
            ),
            _node(_V, "test_candidate_artifact_must_equal_the_state_being_admitted"),
            _node(
                _V,
                "test_independent_report_must_assess_the_exact_bounded_trajectory",
            ),
            _node(_V, "test_typed_result_summary_must_bind_the_exact_candidate_reference"),
            _node(_V, "test_missing_or_tampered_candidate_reference_is_denied"),
            _node(_V, "test_one_candidate_assignment_cannot_be_reused_by_two_delegations"),
            _node(
                _CLI,
                "test_adaptive_evaluation_candidate_cli_prepares_and_direct_child_reads",
            ),
            _node(
                _CLI,
                "test_adaptive_read_evaluation_rejects_assignment_after_sibling_revision",
            ),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P13,
        "Executable evidence runs and replays an exact pytest node while fabrication, stale identity, no-op, and unsigned completion fail closed",
        (
            _node(
                _EXECUTION,
                "test_actual_passing_pytest_node_issues_and_replays_current_receipt",
            ),
            _node(_EXECUTION, "test_fabricated_or_missing_receipt_cannot_verify"),
            _node(
                _EXECUTION,
                "test_receipt_rejects_wrong_goal_worktree_and_workflow_revision",
            ),
            _node(_EXECUTION, "test_failed_or_no_op_pytest_node_cannot_issue_receipt"),
            _node(_EXECUTION, "test_verifier_memoizes_only_within_one_readback_instance"),
            _node(
                _V,
                "test_fabricated_executable_receipt_is_denied_even_with_exact_independent_report",
            ),
            _node(_V, "test_completed_execution_requires_exact_independent_completion_claim"),
            _node(
                _CLI,
                "test_adaptive_execute_evidence_runs_exact_node_and_returns_runtime_lineage",
            ),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.P14,
        "Schema v5 stores typed USER effect plus efficiency admission while v4/v3 legacy or uninterpreted prompts remain bounded",
        (
            _node(_USER_DECISION, "test_decision_digest_contains_only_typed_provenance_and_effect"),
            _node(
                _USER_DECISION,
                "test_schema_v5_is_raw_free_and_legacy_non_user_states_remain_decodable",
            ),
            _node(_USER_DECISION, "test_schema_v5_rejects_raw_user_response_fields"),
            _node(
                _V,
                "test_user_authority_is_explicitly_pending_without_runtime_receipt_source",
            ),
            _node(
                _V,
                "test_typed_user_decision_without_transient_prompt_capability_remains_pending",
            ),
            _node(_V, "test_direct_user_prompt_does_not_interpret_itself_as_acceptance"),
            _node(
                _V,
                "test_independent_report_cannot_omit_the_exact_user_acceptance_claim",
            ),
        ),
        AUTO_COLD_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S01,
        "Adaptive state uses canonical payload, exact CAS, and session-workflow isolation",
        (
            _node(_S, "test_compare_and_replace_payload_uses_canonical_codec_and_exact_cas"),
            _node(_S, "test_compare_and_update_rejects_stale_workflow_revision"),
            _node(_S, "test_same_namespace_is_isolated_by_current_workflow_and_session"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S02,
        "Goal override discards old authority and consumes an explicit typed old-to-new USER decision through CAS",
        (
            _node(_S, "test_goal_override_discards_old_authority_observations_and_completion"),
            _node(_S, "test_goal_changing_general_mutation_cannot_carry_authority_forward"),
            _node(
                _USER_DECISION,
                "test_user_driven_goal_override_consumes_exact_old_to_new_decision",
            ),
            _node(_CLI, "test_adaptive_override_goal_uses_explicit_typed_cas_boundary"),
        ),
        AUTO_COLD_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S03,
        "Same-goal transitions cannot delete evidence, coverage, or observations",
        (_node(_S, "test_same_goal_cannot_delete_evidence_coverage_or_observation_history"),),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S04,
        "Evidence supersession is append-only with monotonic revisions",
        (_node(_S, "test_evidence_supersession_is_append_only_and_revision_monotonic"),),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S05,
        "Coverage revisions are exact and gap inventories never shrink or reopen",
        (
            _node(_S, "test_coverage_supersession_requires_exact_next_revision"),
            _node(_S, "test_gap_inventory_cannot_shrink_or_reopen_a_settled_gap"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S06,
        "Observations append canonically while terminal execution and recovery epochs require authorized material transitions",
        (
            _node(_S, "test_observation_is_single_append_with_canonical_derived_fields"),
            _node(_S, "test_terminal_execution_status_cannot_toggle_or_rollback"),
            _node(_S, "test_recovery_epoch_requires_a_prior_recovery_decision"),
            _node(
                _S,
                "test_recovery_epoch_advances_once_after_recovery_decision_and_material_transition",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S07,
        "Aggregate-sealed generic workflow mutations cannot create, change, delete, or bypass the typed adaptive namespace",
        (
            _node(
                _SESSION_KERNEL,
                "test_generic_workflow_events_cannot_mutate_reserved_adaptive_namespace",
            ),
            _node(_SKILL_STORE, "test_generic_mutation_cannot_create_reserved_adaptive_state"),
            _node(
                _CLI,
                "test_generic_workflow_commands_preserve_reserved_adaptive_namespace_exactly",
            ),
            _node(
                _PHASE_STORE,
                "test_advance_preserves_unrelated_workflow_payload_namespaces",
            ),
            _node(
                _AGGREGATE,
                "test_arbitrary_reserved_mutation_subclass_cannot_persist_invalid_adaptive_payload",
            ),
            _node(
                _AGGREGATE,
                "test_direct_reserved_event_rejects_invalid_schema_and_preserves_revision",
            ),
            _node(
                _AGGREGATE,
                "test_direct_reserved_event_rejects_invalid_transition_and_preserves_revision",
            ),
            _node(
                _AGGREGATE,
                "test_direct_reserved_event_rejects_unverified_external_authority",
            ),
            _node(
                _AGGREGATE,
                "test_public_adaptive_control_store_cannot_bypass_external_admission",
            ),
            _node(
                _AGGREGATE,
                "test_valid_adaptive_control_store_transition_is_admitted",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.S08,
        "Typed USER dispositions consume their exact gap or criterion effect and same-goal decision history is append-only without orphans",
        (
            _node(_USER_DECISION, "test_target_and_disposition_matrix_is_closed"),
            _node(_USER_DECISION, "test_user_criterion_evidence_must_consume_exact_decision"),
            _node(
                _USER_DECISION,
                "test_user_gap_fact_deferral_and_blocker_consume_exact_dispositions",
            ),
            _node(
                _USER_DECISION,
                "test_same_goal_user_decisions_are_append_only_and_cannot_be_orphaned",
            ),
        ),
        AUTO_COLD_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.F01,
        "Required workflows initialize adaptive gates and bind goal to north star",
        (
            _node(_PH, "test_adaptive_policy_adds_first_and_final_gates_for_new_runs_only"),
            _node(_PH, "test_adaptive_initialization_rejects_unresolved_ambiguity_actions"),
            _node(_PH, "test_adaptive_readback_binds_goal_to_current_phase_north_star"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.F02,
        "Every adaptive phase transition rechecks intent, authority, and recovery decision",
        (
            _node(_PH, "test_every_adaptive_phase_transition_rechecks_current_intent_readiness"),
            _node(
                _PH,
                "test_adaptive_phase_transition_rejects_ready_user_gap_without_runtime_authority",
            ),
            _node(_PH, "test_adaptive_phase_transition_rejects_recovery_decisions"),
            _node(_PH, "test_adaptive_phase_transition_allows_continue_with_verified_authority"),
            _node(_PH, "test_adaptive_phase_transition_bounds_await_user_to_user_acceptance"),
            _node(
                _PHASE_STORE,
                "test_adaptive_transition_readback_binds_authority_and_criteria_to_one_revision",
            ),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.F03,
        "Completion and finalization require current trusted adaptive authority",
        (
            _node(_PH, "test_adaptive_control_receipt_rejects_label_only_and_forged_claims"),
            _node(_PH, "test_adaptive_control_receipt_rejects_stale_workflow_revision"),
            _node(_PH, "test_finalize_rechecks_current_adaptive_completion_after_phase_receipt"),
            _node(_CLI, "test_adaptive_untrusted_receipts_cannot_finalize_completed"),
            _node(_CLI, "test_adaptive_consumed_independent_authority_can_finalize_completed"),
            _node(
                _AGGREGATE,
                "test_direct_completed_finalization_rejects_semantic_and_unknown_without_adaptive",
            ),
            _node(
                _AGGREGATE,
                "test_direct_completed_finalization_rejects_unachieved_adaptive_projection",
            ),
            _node(
                _AGGREGATE,
                "test_failed_finalization_preserves_adaptive_state_without_completion_authority",
            ),
            _node(
                _PH,
                "test_adaptive_missing_evaluator_cannot_terminalize_the_current_phase_as_blocked",
            ),
            _node(
                _PH,
                "test_adaptive_missing_evaluator_cannot_relabel_pending_as_failed",
            ),
            _node(_PH, "test_adaptive_typed_execution_failure_can_terminalize_the_phase"),
            _node(
                _PH,
                "test_adaptive_repairable_criterion_failure_cannot_relabel_as_terminal_failed",
            ),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.F04,
        "Stop returns user control only for exact current adaptive questions",
        (
            _node(_HS, "test_adaptive_ask_user_stop_returns_question_and_leaves_workflow_active"),
            _node(_HS, "test_adaptive_ask_user_rejects_unrelated_foreground_question"),
            _node(
                _HS,
                "test_adaptive_ask_user_cannot_persist_gap_from_another_intent_revision",
            ),
            _node(_HS, "test_multiple_adaptive_questions_cannot_share_one_foreground_receipt"),
            _node(
                _HS,
                "test_adaptive_await_user_stop_returns_control_and_leaves_workflow_active",
            ),
            _node(_HS, "test_adaptive_await_user_requires_matching_awaiting_input_turn"),
            _node(_HS, "test_adaptive_await_user_with_unverified_independent_claim_denies"),
            _node(_HS, "test_adaptive_nonawait_or_stale_receipt_stop_denies"),
        ),
        AUTO_USER,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.L01,
        "Reflection excludes settled criteria from active scope",
        (_node(_D, "test_reflection_keeps_settled_criteria_out_of_active_scope"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.L02,
        "Repeated root causes deterministically change approach or exhaust invariants",
        (
            _node(_D, "test_repeated_introduced_root_cause_requires_approach_change"),
            _node(_D, "test_repeated_preexisting_root_cause_switches_to_exhaustive_invariant"),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.L03,
        "A recovered epoch ignores stale plateau history but the same root cause across epochs remains a global veto",
        (
            _node(_D, "test_recovered_epoch_does_not_replay_old_root_cause_or_stagnation"),
            _node(_D, "test_same_root_cause_reintroduced_after_recovery_is_a_global_veto"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.L04,
        "Oscillation and plateau stop without claiming success",
        (_node(_D, "test_oscillation_and_plateau_stop_without_claiming_success"),),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.L05,
        "Generation limits, bounded source-inventory saturation, harness promotion, and first-generation success remain distinct",
        (
            _node(_D, "test_generation_cap_counts_all_recovery_epochs"),
            _node(_D, "test_generation_cap_is_exhaustion_not_success"),
            _node(_D, "test_reproducible_harness_gap_routes_to_promotion"),
            _node(_D, "test_reproducible_harness_gap_does_not_reopen_an_achieved_goal"),
            _node(_D, "test_goal_can_finish_in_first_generation_when_every_authority_passes"),
            _node(
                _PH,
                "test_evaluate_harness_allows_saturated_inventory_within_three_pass_budget",
            ),
            _node(
                _PH,
                "test_evaluate_harness_requires_saturated_source_inventory_without_pass_cap",
            ),
            _node(
                _PH,
                "test_evaluate_harness_rejects_label_without_consumed_direct_child_report",
            ),
            _node(
                _PH,
                "test_adaptive_evaluate_harness_watchdog_can_return_blocked_control",
            ),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.A01,
        "Runtime policy has exactly 21 semantic workflows, 8 operational projections, fail-closed unknown kinds, and immutable persisted phase policy",
        (
            _node(_POL, "test_operational_projection_exemptions_are_exact"),
            _node(
                _POL,
                "test_semantic_and_unknown_workflows_require_adaptive_control_by_default",
            ),
            _node(_MATRIX, "test_workflow_policy_inventory_is_21_semantic_and_8_operational"),
            _node(
                _CLI,
                "test_semantic_and_unknown_workflows_cannot_finalize_without_adaptive_snapshot",
            ),
            _node(
                _POL,
                "test_persisted_phase_policy_controls_existing_workflow_completion",
            ),
            _node(
                _AGGREGATE,
                "test_persisted_legacy_policy_is_immutable_and_can_reach_terminal_state",
            ),
            _node(
                _AGGREGATE,
                "test_exact_operational_workflow_can_complete_without_adaptive_state",
            ),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.A02,
        "Static skill policy rejects missing or downgraded adaptive control",
        (
            _node(_SH, "test_all_declared_skills_classify_adaptive_control_policy"),
            _node(_SH, "test_rejects_skill_without_adaptive_control_classification"),
            _node(_SH, "test_rejects_skill_without_workflow_semantics_classification"),
            _node(_SH, "test_rejects_single_phase_semantic_workflow_without_adaptive_control"),
            _node(_SH, "test_exact_operational_projection_is_not_adaptive"),
            _node(_PH, "test_semantic_single_phase_contract_initializes_adaptive_policy"),
        ),
        AUTO,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.A03,
        "Static agent harness pins adaptive runtime and behavioral oracles",
        (
            _node(_AH, "test_adaptive_control_runtime_and_behavioral_oracles_are_pinned"),
            _node(_AH, "test_rejects_adaptive_replace_that_persists_before_authority_admission"),
            _node(_AH, "test_rejects_adaptive_contract_without_hard_failure_veto_oracle"),
            _node(
                _AH, "test_rejects_adaptive_harness_without_question_and_phase_readiness_oracles"
            ),
            _node(_AH, "test_rejects_adaptive_contract_without_runtime_execution_receipt"),
            _node(
                _AH,
                "test_rejects_adaptive_contract_without_raw_free_user_decision_oracle",
            ),
            _node(
                _AH,
                "test_rejects_adaptive_contract_without_fail_closed_applicability_policy",
            ),
            _node(
                _AH,
                "test_rejects_joint_matrix_and_test_shrink_even_with_a_new_shared_digest",
            ),
        ),
        AUTO_COLD,
    ),
    AcceptanceCase(
        AdaptiveAcceptanceId.A04,
        "Frozen rows, metadata, literal digest, CLI receipt, and every exact pytest node remain executable",
        (
            _node(_MATRIX, "test_matrix_contains_exactly_the_frozen_rows_and_metadata"),
            _node(_MATRIX, "test_matrix_digest_is_literal_and_matches_canonical_payload"),
            _node(
                _MATRIX,
                "test_cli_receipt_exposes_full_matrix_digest_and_selected_surface_metadata",
            ),
            _node(_MATRIX, "test_every_matrix_node_is_collectable_from_the_repository"),
        ),
        AUTO_COLD,
    ),
)


ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST = (
    "df3dd5497fbf17cea0fbe9a77fc66b4c2365a6e7cecd2b7b79ef84ab668751af"
)
"""ID, scenario, evidence surface, exact node를 결속한 full-matrix SHA-256입니다."""


def _parser() -> argparse.ArgumentParser:
    """Adaptive acceptance matrix public CLI parser를 구성합니다.

    Returns:
        Stable adaptive row 선택과 fail-fast만 노출하는 parser입니다.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--row",
        action="append",
        choices=tuple(row.value for row in AdaptiveAcceptanceId),
        help="실행할 adaptive row입니다. 생략하면 ADP-Q01..ADP-A03 전체를 실행합니다.",
    )
    parser.add_argument("--fail-fast", action="store_true")
    return parser


def _selected_cases(rows: Sequence[str] | None) -> tuple[AcceptanceCase, ...]:
    """CLI selection을 duplicate 없는 frozen matrix order로 정규화합니다.

    Args:
        rows: Repeated `--row` values 또는 전체 선택을 뜻하는 None입니다.

    Returns:
        Full matrix 또는 stable-order selected cases입니다.
    """
    if rows is None:
        return ADAPTIVE_ACCEPTANCE_MATRIX
    selected = frozenset(AdaptiveAcceptanceId(row) for row in rows)
    return tuple(case for case in ADAPTIVE_ACCEPTANCE_MATRIX if case.row in selected)


def main(arguments: Sequence[str] | None = None) -> int:
    """Frozen adaptive acceptance matrix를 실행하고 JSON receipt를 출력합니다.

    Args:
        arguments: Test에서 주입할 optional CLI arguments입니다.

    Returns:
        선택된 모든 row가 통과하면 0, 하나라도 실패하면 1입니다.
    """
    parsed = _parser().parse_args(arguments)
    repository = __import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(Path(__file__).resolve().parents[2])
    receipt = AcceptanceMatrixRunner(
        repository,
        SubprocessCommandRunner(),
        receipt_schema="neurath.adaptive-control-acceptance-receipt.v1",
        matrix_digest=ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST,
    ).execute(
        _selected_cases(parsed.row),
        fail_fast=bool(parsed.fail_fast),
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if bool(receipt["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
