"""Portable semantic/operational contracts keep their runtime admission boundary."""

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.skill_harness.checker import SkillHarnessChecker

from neurath.resources import BUNDLE


class SkillHarnessCheckerTest(TestCase):
    def check_mutation(self, key, value):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(BUNDLE / ".agents", root / ".agents")
            path = root / ".agents/skills/contracts.json"
            data = json.loads(path.read_text())
            data["skills"]["review-code"][key] = value
            path.write_text(json.dumps(data))
            self.assertTrue(SkillHarnessChecker(root).check())

    def test_all_declared_skills_classify_adaptive_control_policy(self):
        self.assertFalse(SkillHarnessChecker(BUNDLE).check())

    def test_rejects_skill_without_adaptive_control_classification(self):
        self.check_mutation("adaptive_control", None)

    def test_rejects_skill_without_workflow_semantics_classification(self):
        self.check_mutation("workflow_semantics", None)

    def test_rejects_single_phase_semantic_workflow_without_adaptive_control(self):
        self.check_mutation("adaptive_control", "not-applicable")

    def test_exact_operational_projection_is_not_adaptive(self):
        data = json.loads((BUNDLE / ".agents/skills/contracts.json").read_text())
        self.assertEqual("not-applicable", data["skills"]["commit"]["adaptive_control"])
        self.assertFalse(SkillHarnessChecker(BUNDLE).check())

    def test_rejects_global_active_pointer_in_production_harness(self):
        # Any new state-routing code differs from the shipped immutable manifest.
        from scripts.agent_harness.tests.test_checker import AgentHarnessCheckerTest

        AgentHarnessCheckerTest().assert_module_change_rejected(
            "skill_harness/phase_runner.py", '\nactive_pointer="global"\n'
        )

    def test_rejects_state_handle_open_and_agent_graph_runtime_dependency(self):
        from scripts.agent_harness.tests.test_checker import AgentHarnessCheckerTest

        AgentHarnessCheckerTest().assert_module_change_rejected(
            "agent_harness/state_handle.py", "\nimport agent_graph_runtime\n"
        )
