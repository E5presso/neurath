"""Portable distribution and native hook wiring replace source-project shell contracts."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.skill_harness.checker import SkillHarnessChecker

from neurath.doctor import doctor, integrity
from neurath.install.transaction import apply_plan, make_plan
from neurath.resources import BUNDLE


class DistributionBoundaryTest(TestCase):
    def test_all_skill_phase_and_evidence_contracts_are_consistent(self):
        self.assertEqual([], SkillHarnessChecker(BUNDLE).check())

    def test_native_hook_failure_sensor_is_preserved_and_drift_detected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            apply_plan(root, make_plan(root))
            path = root / ".claude/settings.json"
            hooks = json.loads(path.read_text())
            self.assertIn("PermissionDenied", hooks["hooks"])
            self.assertIn("SessionEnd", hooks["hooks"])
            del hooks["hooks"]["PermissionDenied"]
            path.write_text(json.dumps(hooks))
            self.assertEqual("failed", doctor(root)["placement"]["status"])

    def test_installed_hook_runs_without_source_project(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            apply_plan(root, make_plan(root))
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_", "PYTHONPATH"))
            }
            for host in ("codex", "claude-code"):
                result = subprocess.run(
                    [str(root / ".neurath/run"), "hook", "--host", host],
                    input=json.dumps(
                        {
                            "session_id": "independent-" + host,
                            "hook_event_name": "SessionStart",
                            "source": "startup",
                            "cwd": temp,
                        }
                    ),
                    capture_output=True,
                    text=True,
                    env=env,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("neurath", result.stdout.lower())

    def test_missing_installed_runtime_is_explicit_failure(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            apply_plan(root, make_plan(root))
            (root / ".neurath/run").unlink()
            self.assertEqual("failed", doctor(root)["placement"]["status"])

    def test_distribution_rejects_added_modified_and_missing_files(self):
        import hashlib

        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "code.py"
            source.write_text("value=1\n")
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "files": {"code.py": hashlib.sha256(source.read_bytes()).hexdigest()},
                    }
                )
            )
            self.assertEqual("passed", integrity(root)["status"])
            source.write_text("value=2\n")
            self.assertEqual("failed", integrity(root)["status"])
            source.unlink()
            self.assertEqual("failed", integrity(root)["status"])

    def test_hook_engine_imports_without_third_party_dependencies(self):
        code = "import sys; sys.path.insert(0, sys.argv[1]); import scripts.agent_harness.runtime_hook; import scripts.agent_harness.material_action_runtime_hook; import scripts.agent_harness.worktree_hook"
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code, str(BUNDLE)], capture_output=True, text=True
        )
        self.assertEqual(0, result.returncode, result.stderr)
