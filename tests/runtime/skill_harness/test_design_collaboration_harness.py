"""Design collaboration authority와 단계별 skill 경계를 검증합니다."""

import json
from pathlib import Path
from unittest import TestCase

from scripts.agent_harness.capability_retirement_hook import (
    CapabilityRetirementDecisionCode,
    CapabilityRetirementHookApplication,
)


class DesignCollaborationHarnessTest(TestCase):
    """Canvas exploration과 repository implementation 권한이 섞이지 않아야 합니다."""

    def setUp(self) -> None:
        """Canonical repository root와 policy payload를 준비합니다."""
        self.root = Path(__file__).resolve().parents[3]
        policy_path = self.root / ".agents" / "design-collaboration-policy.json"
        self.policy = json.loads(policy_path.read_text(encoding="utf-8"))

    def test_policy_separates_visual_and_implementation_authority(self) -> None:
        """Canvas는 방향을 소유하지만 token·component 구현 정본이 될 수 없습니다."""
        self.assertEqual("neurath-design-collaboration-v3", self.policy["schema"])
        self.assertEqual("penpot", self.policy["canvas"]["preferred"])
        self.assertIn("figma", self.policy["canvas"]["alternatives"])
        self.assertFalse(self.policy["canvas"]["implementation_source_of_truth"])
        self.assertFalse(self.policy["canvas"]["visualize_product_direction_allowed"])
        self.assertEqual(
            "user-approved-canvas-node",
            self.policy["authorities"]["visual_direction"],
        )
        self.assertEqual(
            "repository-design-source-if-present",
            self.policy["authorities"]["token_values"],
        )
        self.assertEqual(
            "runtime-capture-or-static-export-or-slot",
            self.policy["runtime_owned_visuals"]["canvas_representation"],
        )
        self.assertEqual("user", self.policy["authorities"]["visual_acceptance"])

    def test_policy_keeps_token_sync_one_way_and_requires_exact_node(self) -> None:
        """Canvas proposal은 승인 없이 repository token이나 구현을 바꾸지 못합니다."""
        self.assertEqual("repository-to-canvas", self.policy["token_sync"]["direction"])
        self.assertEqual(
            "explicit-user-approved-proposal-only",
            self.policy["token_sync"]["canvas_to_repository"],
        )
        self.assertTrue(self.policy["implementation_gate"]["exact_canvas_node_required"])
        self.assertTrue(self.policy["implementation_gate"]["surface_required"])
        self.assertTrue(self.policy["implementation_gate"]["state_required"])

    def test_content_reset_preserves_collaboration_capability_and_connector(self) -> None:
        """Design content 삭제는 workflow와 connector retirement 권한이 아닙니다."""
        reset = self.policy["content_reset"]
        connector = self.policy["connector_lifecycle"]

        self.assertEqual("clean-slate", reset["missing_design_source"])
        self.assertEqual("fail-closed", reset["cross_plane_deletion"])
        self.assertIn("design-values", reset["deletable_content"])
        self.assertIn("design-workflow-skills", reset["protected_capabilities"])
        self.assertIn("connector-registration", reset["protected_capabilities"])
        self.assertIn(
            "capability-retirement-runtime-guard",
            reset["protected_capabilities"],
        )
        self.assertFalse(connector["artifact_deletion_implies_uninstall"])
        self.assertTrue(connector["uninstall_requires_explicit_connector_retirement"])
        self.assertEqual("forbidden", connector["credential_recovery_from_logs"])
        self.assertEqual(
            "design.collaboration.preservation-boundary",
            self.policy["compaction"]["preservation_fact_key"],
        )
        self.assertEqual(
            "content-may-reset;capability-and-connector-preserved",
            self.policy["compaction"]["preservation_fact_value"],
        )

    def test_design_data_purge_keeps_capability_inventory_unchanged(self) -> None:
        """Deletable content와 protected capability는 겹치지 않습니다."""
        reset = self.policy["content_reset"]

        self.assertTrue(set(reset["deletable_content"]).isdisjoint(reset["protected_capabilities"]))
        self.assertEqual("clean-slate", reset["missing_design_source"])

    def test_penpot_artifact_purge_does_not_authorize_connector_unregistration(self) -> None:
        """Cloud artifact 삭제와 connector retirement는 서로 다른 사용자 권한입니다."""
        connector = self.policy["connector_lifecycle"]

        self.assertEqual("capability", connector["registration_class"])
        self.assertFalse(connector["artifact_deletion_implies_uninstall"])
        self.assertTrue(connector["uninstall_requires_explicit_connector_retirement"])
        class ExplicitConnectorPolicy(CapabilityRetirementHookApplication):
            _PROTECTED_CONNECTORS = frozenset({"penpot"})

        result = ExplicitConnectorPolicy().run(
            json.dumps({
                "hook_event_name": "PreToolUse",
                "tool_name": "functions.exec_command",
                "tool_input": {"cmd": "codex mcp remove penpot"},
            }),
            self.root,
        )
        self.assertEqual(2, result.exit_code)
        self.assertIs(CapabilityRetirementDecisionCode.PROTECTED_CONNECTOR, result.code)

    def test_compaction_boundary_is_declared_for_enclave_readback(self) -> None:
        """Compaction 뒤 resume aid가 같은 preservation boundary를 가리킵니다."""
        compaction = self.policy["compaction"]

        self.assertEqual(
            "design.collaboration.preservation-boundary",
            compaction["preservation_fact_key"],
        )
        self.assertEqual(
            "content-may-reset;capability-and-connector-preserved",
            compaction["preservation_fact_value"],
        )

    def test_mixed_destructive_scope_and_rejected_transition_fail_closed(self) -> None:
        """Cross-plane cleanup의 protected shell mutation은 application에서 거부됩니다."""
        behavioral = (self.root / ".agents" / "rules" / "behavioral.md").read_text(encoding="utf-8")
        normalized = " ".join(behavioral.split())
        class ExplicitConnectorPolicy(CapabilityRetirementHookApplication):
            _PROTECTED_CONNECTORS = frozenset({"penpot"})

        result = ExplicitConnectorPolicy().run(
            json.dumps({
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git clean -fd"},
            }),
            self.root,
        )

        self.assertEqual("fail-closed", self.policy["content_reset"]["cross_plane_deletion"])
        self.assertIn("Plane 간 승인을 확대하지 않습니다", normalized)
        self.assertIn(
            "workflow transition이 거부되면 capability·connector mutation을",
            normalized,
        )
        self.assertIn("막고 요구사항을 확정", normalized)
        self.assertEqual(2, result.exit_code)
        self.assertIs(CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY, result.code)

    def test_skills_encode_non_substitutable_phase_boundaries(self) -> None:
        """Exploration, mirror sync, implementation, review가 서로의 권한을 대신하지 않습니다."""
        skills = self.root / ".agents" / "skills"
        art_direction = (skills / "explore-ui" / "SKILL.md").read_text(encoding="utf-8")
        mirror_sync = (skills / "sync-design" / "SKILL.md").read_text(encoding="utf-8")
        implementation = (skills / "implement-ui" / "SKILL.md").read_text(encoding="utf-8")
        review = (skills / "review-ui" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("tool:design_canvas", art_direction)
        self.assertIn("제품 UI 방향을 `visualize`로 대체하지 않습니다", art_direction)
        self.assertIn("exact canvas node", art_direction.casefold())
        self.assertIn("repository → canvas", mirror_sync)
        self.assertIn("exact canvas node", implementation)
        self.assertIn("없으면 `blocked`", implementation)
        self.assertIn("사용자만 최종 시각 승인을 내립니다", review)
