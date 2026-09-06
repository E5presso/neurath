"""The distribution manifest pins runtime gates and oracles without source AST policy."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.checker import AgentHarnessChecker

from neurath.resources import BUNDLE


class AgentHarnessCheckerTest(TestCase):
    def assert_module_change_rejected(self, module, suffix):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / module
            path.parent.mkdir(parents=True)
            content = (BUNDLE / "scripts" / module).read_bytes()
            path.write_bytes(content)
            (root / "manifest.json").write_text(
                json.dumps({"schema": 1, "files": {module: hashlib.sha256(content).hexdigest()}})
            )
            with patch("neurath.doctor.PACKAGE", root):
                self.assertFalse(AgentHarnessChecker(root).check())
                path.write_bytes(content + suffix.encode())
                self.assertTrue(AgentHarnessChecker(root).check())

    def test_adaptive_control_runtime_and_behavioral_oracles_are_pinned(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_control.py", "\n# changed control\n"
        )

    def test_rejects_adaptive_replace_that_persists_before_authority_admission(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_control_store.py", "\n# bypass authority\n"
        )

    def test_rejects_adaptive_contract_without_hard_failure_veto_oracle(self):
        self.assert_module_change_rejected(
            "agent_harness/evaluation_admission.py", "\n# removed veto\n"
        )

    def test_rejects_adaptive_harness_without_question_and_phase_readiness_oracles(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_control_authority.py", "\n# altered readiness\n"
        )

    def test_rejects_adaptive_contract_without_runtime_execution_receipt(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_execution_receipt.py", "\n# altered receipt\n"
        )

    def test_rejects_adaptive_contract_without_raw_free_user_decision_oracle(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_policy.py", "\n# changed policy\n"
        )

    def test_rejects_adaptive_contract_without_fail_closed_applicability_policy(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_policy.py", "\n# changed applicability\n"
        )

    def test_rejects_joint_matrix_and_test_shrink_even_with_a_new_shared_digest(self):
        self.assert_module_change_rejected(
            "agent_harness/adaptive_acceptance_matrix.py", "\n# changed matrix digest\n"
        )
