"""Exact-target 하네스 유지보수 superuser lease를 검증합니다."""

import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.agent_harness.harness_maintenance import (
    HarnessMaintenanceAuthority,
    HarnessMaintenanceCli,
)
from scripts.agent_harness.material_action_runtime_hook import (
    MaterialActionHookDecisionCode,
    MaterialActionRuntimeHookApplication,
)
from scripts.agent_harness.session_kernel import SessionRuntime
from scripts.agent_harness.worktree_hook import (
    WorktreeHookApplication,
    WorktreeHookDecisionCode,
)


class HarnessMaintenanceTest(unittest.TestCase):
    """Maintenance mode가 ambient authority 없이 repository gate를 우회하는지 검증합니다."""

    def setUp(self) -> None:
        """격리 Git repository와 current Codex actor를 준비합니다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        subprocess.run(("git", "init", "-q"), cwd=self.repository, check=True)
        self.environment = {"CODEX_THREAD_ID": "session-1"}
        self.target = self.repository / "scripts/agent_harness/example.py"

    def _run(self, *arguments: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = HarnessMaintenanceCli().run(
                arguments,
                environment=self.environment,
                cwd=self.repository,
            )
        return exit_code, json.loads(output.getvalue())

    def test_exact_actor_and_target_are_authorized_only_for_structured_edits(self) -> None:
        """Lease는 exact target edit만 양 gate에서 batch 없이 승인합니다."""
        exit_code, payload = self._run(
            "begin",
            "--reason",
            "repair parser",
            "--target",
            str(self.target),
        )
        self.assertEqual(0, exit_code, payload)

        authorized = HarnessMaintenanceAuthority.authorizes(
            cwd=self.repository,
            environment=self.environment,
            hook_runtime=SessionRuntime.CODEX,
            runtime_agent_id=None,
            runtime_session_id="session-1",
            tool_name="apply_patch",
            targets=(self.target,),
        )
        shell = HarnessMaintenanceAuthority.authorizes(
            cwd=self.repository,
            environment=self.environment,
            hook_runtime=SessionRuntime.CODEX,
            runtime_agent_id=None,
            runtime_session_id="session-1",
            tool_name="exec_command",
            targets=(self.target,),
        )
        foreign = HarnessMaintenanceAuthority.authorizes(
            cwd=self.repository,
            environment=self.environment,
            hook_runtime=SessionRuntime.CODEX,
            runtime_agent_id=None,
            runtime_session_id="session-1",
            tool_name="apply_patch",
            targets=(self.repository / "apps/backend/product.py",),
        )

        self.assertTrue(authorized)
        self.assertFalse(shell)
        self.assertFalse(foreign)

        raw_input = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "session-1",
            "tool_name": "functions.apply_patch",
            "tool_use_id": "maintenance-edit-1",
            "cwd": str(self.repository),
            "tool_input": {
                "input": (
                    "*** Begin Patch\n"
                    "*** Add File: scripts/agent_harness/example.py\n"
                    "+fixed = True\n"
                    "*** End Patch"
                )
            },
        })
        worktree = WorktreeHookApplication(SessionRuntime.CODEX).run(
            raw_input,
            self.environment,
            self.repository,
        )
        material = MaterialActionRuntimeHookApplication(SessionRuntime.CODEX).run(
            "pre",
            raw_input,
            self.environment,
            self.repository,
        )

        self.assertEqual(0, worktree.exit_code, worktree.stderr)
        self.assertEqual(
            WorktreeHookDecisionCode.HARNESS_MAINTENANCE,
            worktree.decision.code,
        )
        self.assertEqual(0, material.exit_code, material.stderr)
        self.assertEqual(
            MaterialActionHookDecisionCode.HARNESS_MAINTENANCE,
            material.decision.code,
        )
        process_state = self.repository / ".agents/runs/session-1/.process-state.json"
        self.assertFalse(process_state.exists())

    def test_close_moves_a_digest_readback_to_an_audit_receipt(self) -> None:
        """Lease 종료는 대상별 digest readback을 immutable receipt로 이동합니다."""
        exit_code, begin = self._run(
            "begin",
            "--reason",
            "repair hook",
            "--target",
            str(self.target),
        )
        self.assertEqual(0, exit_code, begin)
        self.target.parent.mkdir(parents=True)
        self.target.write_text("fixed\n", encoding="utf-8")

        exit_code, ended = self._run("end", "--summary", "parser boundary replaced")

        self.assertEqual(0, exit_code, ended)
        result = ended["result"]
        self.assertIsInstance(result, dict)
        assert isinstance(result, dict)
        self.assertEqual("sqlite:harness-maintenance:" + str(result["lease_id"]), result["receipt"])
        from scripts.agent_harness.runtime_database import RuntimeDatabase
        with RuntimeDatabase(self.repository).connection() as db:
            receipt = db.execute("SELECT payload FROM harness_maintenance_receipts WHERE lease_id=?",
                                 (result["lease_id"],)).fetchone()
            active = db.execute("SELECT 1 FROM harness_maintenance_leases WHERE session_id='session-1'").fetchone()
        self.assertIsNotNone(receipt)
        self.assertIsNone(active)
        self.assertEqual("closed", json.loads(receipt["payload"])["status"])
        readback = result["readback"]
        self.assertIsInstance(readback, list)
        assert isinstance(readback, list)
        self.assertEqual(
            hashlib.sha256(b"fixed\n").hexdigest(),
            readback[0]["sha256"],
        )

    def test_all_harness_source_surfaces_are_leaseable_without_runtime_state(self) -> None:
        """Gate entrypoint, checker와 normative spec은 한 exact lease로 수리할 수 있습니다."""
        targets = tuple(
            self.repository / relative
            for relative in (
                ".agents/rules/behavioral.md",
                ".agents/skills/contracts.json",
                ".codex/hooks.json",
                ".claude/settings.json",
                ".github/workflows/ci.yml",
                ".pre-commit-config.yaml",
                "mise.toml",
                "pyproject.toml",
                "uv.lock",
                "scripts/static_harness/checker.py",
                "scripts/workspace_hooks/run_task.py",
                "docs/decisions/ADR-0004-harness-anti-drift-architecture.md",
                "docs/decisions/ADR-0023-prose-guides-gates-enforce.md",
                "docs/decisions/ADR-0024-harness-for-autonomous-sdd.md",
                "docs/decisions/ADR-0037-session-scoped-coding-agent-harness.md",
                "docs/decisions/ADR-0039-adaptive-agent-control-loop.md",
                "docs/decisions/ADR-0040-korean-agent-narrative-standard.md",
                "docs/decisions/README.md",
                "docs/context/harness-authorization-audit.md",
                "docs/plans/coding-agent-session-harness-spec.md",
            )
        )
        arguments = ["begin", "--reason", "repair harness source"]
        for target in targets:
            arguments.extend(("--target", str(target)))

        exit_code, payload = self._run(*arguments)

        self.assertEqual(0, exit_code, payload)
        self.assertTrue(
            HarnessMaintenanceAuthority.authorizes(
                cwd=self.repository,
                environment=self.environment,
                hook_runtime=SessionRuntime.CODEX,
                runtime_agent_id=None,
                runtime_session_id="session-1",
                tool_name="apply_patch",
                targets=targets,
            )
        )

    def test_scope_ttl_and_owner_are_fail_closed(self) -> None:
        """Product target, invalid TTL과 foreign owner는 maintenance authority를 얻지 못합니다."""
        denied_targets = (
            self.repository / "apps/backend/product.py",
            self.repository / ".agents/runs/session-1/harness-maintenance.json",
            self.repository / ".agents/runs/session-1/.process-state.json",
            self.repository / ".agents/resources/worktrees/claim.json",
            self.repository / ".agents/loops/loop.json",
            self.repository / ".agents/worktrees/feature.json",
            self.repository / ".claude/worktrees/feature/claim.json",
            self.repository / ".claude/settings.local.json",
            self.repository / "docs/decisions/ADR-0014-surface-application-stacks.md",
            self.repository / "docs/decisions/ADR-0012-personal-context-storage.md",
            self.repository / "docs/decisions/ADR-0030-account-isolation-enforcement.md",
        )
        for target in denied_targets:
            with self.subTest(target=target):
                exit_code, payload = self._run(
                    "begin",
                    "--reason",
                    "out of maintenance scope",
                    "--target",
                    str(target),
                )
                self.assertEqual(2, exit_code, payload)

        exit_code, payload = self._run(
            "begin",
            "--reason",
            "invalid ttl",
            "--target",
            str(self.target),
            "--ttl-seconds",
            "0",
        )
        self.assertEqual(2, exit_code, payload)

        exit_code, payload = self._run(
            "begin",
            "--reason",
            "owner test",
            "--target",
            str(self.target),
        )
        self.assertEqual(0, exit_code, payload)
        self.environment = {"CODEX_THREAD_ID": "session-2"}
        exit_code, payload = self._run("end", "--summary", "forged close")
        self.assertEqual(2, exit_code, payload)


if __name__ == "__main__":
    unittest.main()
