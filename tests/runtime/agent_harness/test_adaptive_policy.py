"""Adaptive control required-kind 독립 정책의 허용·거부 경계를 검증합니다."""

from unittest import TestCase

from scripts.agent_harness.adaptive_policy import (
    ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS,
    requires_adaptive_control,
    requires_adaptive_control_for_workflow,
)


class AdaptivePolicyTest(TestCase):
    """Contract metadata와 무관한 runtime fail-closed applicability를 고정합니다."""

    def test_operational_projection_exemptions_are_exact(self) -> None:
        """의미 목표를 재판정하지 않는 lifecycle projection만 exact하게 면제합니다."""
        self.assertEqual(
            frozenset({
                "checkpoint",
                "commit",
                "create-pr",
                "create-ticket",
                "create-worktree",
                "monitor-pr",
                "finish-session",
                "update-project-status",
            }),
            ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS,
        )
        for workflow_kind in ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS:
            with self.subTest(workflow_kind=workflow_kind):
                self.assertFalse(requires_adaptive_control(workflow_kind))

    def test_semantic_and_unknown_workflows_require_adaptive_control_by_default(self) -> None:
        """Known semantic, unknown, non-skill workflow가 이름 누락으로 gate를 우회하지 않습니다."""
        for workflow_kind in (
            "audit-spec",
            "investigate",
            "pr-review",
            "process-ticket",
            "sync-user-docs",
            "custom-runtime-workflow",
            "",
        ):
            with self.subTest(workflow_kind=workflow_kind):
                self.assertTrue(requires_adaptive_control(workflow_kind))

    def test_persisted_phase_policy_controls_existing_workflow_completion(self) -> None:
        """시작 때 저장된 phase policy는 이후 global policy 변경에 소급되지 않습니다."""
        self.assertFalse(
            requires_adaptive_control_for_workflow(
                "evaluate-harness",
                {"phase_run": {"adaptive_control_required": False}},
            )
        )
        self.assertTrue(
            requires_adaptive_control_for_workflow(
                "evaluate-harness",
                {"phase_run": {"adaptive_control_required": True}},
            )
        )
        self.assertTrue(requires_adaptive_control_for_workflow("evaluate-harness", {}))
