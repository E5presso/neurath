"""Effectful repository verification을 closed typed runner로 격리하는 계약을 검증합니다."""

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.harness_incident import (
    HarnessIncidentValidationError,
    run_regression_commands,
)
from scripts.agent_harness.verification_runner import (
    VerificationExecutionFailed,
    VerificationKind,
    VerificationRequest,
    VerificationRequestInvalid,
    VerificationRunner,
    VerificationRunnerApplication,
    VerificationWorktreeChanged,
)


class VerificationRunnerTest(TestCase):
    """Exact verifier intent와 before/after repository readback을 함께 고정합니다."""

    def setUp(self) -> None:
        """Current repository root와 disposable Git fixture를 준비합니다."""
        self.repository_root = Path(__file__).resolve().parents[3]

    def test_cli_parser_covers_every_declared_verification_kind(self) -> None:
        """Enum에 추가된 verifier kind는 argparse surface에서 자동으로 실행 가능해야 합니다."""
        application = VerificationRunnerApplication()

        parsed = {
            application._request((kind.value,)).kind
            for kind in VerificationKind
            if kind is not VerificationKind.PYTEST
        }
        pytest = application._request((
            "pytest",
            "--node",
            "scripts/agent_harness/tests/test_verification_runner.py::"
            "VerificationRunnerTest::test_cli_parser_covers_every_declared_verification_kind",
        ))

        self.assertEqual(set(VerificationKind) - {VerificationKind.PYTEST}, parsed)
        self.assertIs(VerificationKind.PYTEST, pytest.kind)

    def test_request_maps_only_closed_verification_commands(self) -> None:
        """Public request는 exact pytest node, pre-commit, mise check만 명령으로 만듭니다."""
        pytest_request = VerificationRequest(
            kind=VerificationKind.PYTEST,
            nodes=(
                "scripts/agent_harness/tests/test_tool_action_parser.py::"
                "ToolActionParserTest::test_host_managed_tools_are_not_content_classified",
                "scripts/agent_harness/tests/test_function_node.py::"
                "test_function_node",
            ),
        )

        self.assertEqual(
            (
                ".neurath/run verify pytest --node "
                "scripts/agent_harness/tests/test_tool_action_parser.py::"
                "ToolActionParserTest::test_host_managed_tools_are_not_content_classified "
                "--node scripts/agent_harness/tests/test_function_node.py::"
                "test_function_node",
            ),
            pytest_request.commands,
        )
        self.assertEqual(
            (".neurath/run verify pre-commit",),
            VerificationRequest(VerificationKind.PRE_COMMIT).commands,
        )
        self.assertEqual(
            (".neurath/run verify check",),
            VerificationRequest(VerificationKind.CHECK).commands,
        )
        module_commands = {kind: f".neurath/run verify {kind.value}" for kind in VerificationKind if kind is not VerificationKind.PYTEST}
        for kind, command in module_commands.items():
            with self.subTest(kind=kind):
                self.assertEqual((command,), VerificationRequest(kind).commands)
        for nodes in ((), ("tests/test.py",), ("scripts/test.py::Case::helper",)):
            with self.subTest(nodes=nodes), self.assertRaises(VerificationRequestInvalid):
                VerificationRequest(VerificationKind.PYTEST, nodes=nodes)

    def test_actual_passing_pytest_node_emits_bounded_unchanged_receipt(self) -> None:
        """Real public pytest node를 실행하고 raw output 없이 stable worktree receipt를 만듭니다."""
        request = VerificationRequest(
            VerificationKind.PYTEST,
            nodes=(
                "scripts/agent_harness/tests/test_tool_action_parser.py::"
                "ToolActionParserTest::test_host_managed_tools_are_not_content_classified",
            ),
        )

        receipt = VerificationRunner(self.repository_root).run(request)
        payload = receipt.to_payload()

        self.assertEqual("neurath.verification-receipt.v1", payload["schema"])
        self.assertEqual("passed", payload["status"])
        self.assertEqual("pytest", payload["kind"])
        self.assertEqual(64, len(str(payload["worktree_fingerprint"])))
        self.assertNotIn("stdout", json.dumps(payload))
        self.assertNotIn("stderr", json.dumps(payload))

    def test_function_style_package_pytest_node_is_supported(self) -> None:
        """Neurath package의 function-style public node도 broad pytest 없이 exact 실행합니다."""
        request = VerificationRequest(
            VerificationKind.PYTEST,
            nodes=(
                "scripts/agent_harness/tests/test_function_node.py::"
                "test_function_node",
            ),
        )

        receipt = VerificationRunner(self.repository_root).run(request)

        self.assertEqual(VerificationKind.PYTEST, receipt.kind)

    def test_real_red_pytest_returns_bounded_transient_diagnostic(self) -> None:
        """Failing Red node는 durable raw log 없이 현재 CLI에 capped assertion tail을 제공합니다."""
        request = VerificationRequest(
            VerificationKind.PYTEST,
            nodes=(
                "scripts/agent_harness/tests/test_verification_runner.py::"
                "VerificationRunnerTest::test_failure_diagnostic_fixture",
            ),
        )

        with (
            patch.dict(os.environ, {"NEURATH_VERIFICATION_RED_FIXTURE": "1"}),
            self.assertRaises(VerificationExecutionFailed) as captured,
        ):
            VerificationRunner(self.repository_root).run(request)

        self.assertIn("verification-red-sentinel", captured.exception.diagnostic_tail)
        self.assertLessEqual(len(captured.exception.diagnostic_tail), 8192)
        self.assertFalse(captured.exception.worktree_changed)
        payload = captured.exception.to_payload()
        self.assertEqual("failed", payload["status"])
        self.assertEqual(captured.exception.before, payload["before_fingerprint"])
        self.assertEqual(captured.exception.after, payload["after_fingerprint"])
        self.assertFalse(payload["worktree_changed"])

    def test_failure_diagnostic_fixture(self) -> None:
        """Nested typed runner가 실제 pytest assertion diagnostic을 캡처할 때만 Red가 됩니다."""
        if os.environ.get("NEURATH_VERIFICATION_RED_FIXTURE") == "1":
            self.fail("verification-red-sentinel")

    def test_repository_change_during_verification_is_rejected(self) -> None:
        """Verifier가 exit 0이어도 current worktree bytes가 바뀌면 receipt를 발행하지 않습니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._initialize_repository(root)
            source = root / "tracked.txt"

            def mutate(
                worktree: Path,
                commands: list[str],
            ) -> list[dict[str, object]]:
                """Fixture repository를 바꾼 뒤 성공 모양 receipt를 반환합니다.

                Args:
                    worktree: Verifier가 전달한 exact fixture root입니다.
                    commands: 실행 요청한 closed command 목록입니다.

                Returns:
                    Mutation을 숨기려는 forged success receipt입니다.
                """
                self.assertEqual(root.resolve(), worktree)
                self.assertEqual([".neurath/run verify check"], commands)
                source.write_text("changed\n", encoding="utf-8")
                return [{"command": commands[0], "exit_code": 0}]

            with self.assertRaises(VerificationWorktreeChanged):
                VerificationRunner(root, execute_commands=mutate).run(
                    VerificationRequest(VerificationKind.CHECK)
                )

    def test_failed_verifier_still_reports_after_fingerprint_change(self) -> None:
        """Command failure가 worktree mutation의 after readback을 건너뛰지 못합니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._initialize_repository(root)

            def fail_after_mutation(
                worktree: Path,
                commands: list[str],
            ) -> list[dict[str, object]]:
                """Fixture bytes를 바꾼 뒤 execution failure를 발생시킵니다.

                Args:
                    worktree: Verifier가 전달한 exact fixture root입니다.
                    commands: 실행 요청한 closed command 목록입니다.

                Raises:
                    HarnessIncidentValidationError: Mutation 뒤 command failure를 재현합니다.
                """
                (worktree / "tracked.txt").write_text("failed-and-changed\n", encoding="utf-8")
                raise HarnessIncidentValidationError(f"failed: {commands[0]}")

            with self.assertRaises(VerificationExecutionFailed) as captured:
                VerificationRunner(root, execute_commands=fail_after_mutation).run(
                    VerificationRequest(VerificationKind.CHECK)
                )

            self.assertTrue(captured.exception.worktree_changed)
            self.assertNotEqual(captured.exception.before, captured.exception.after)

    def test_index_only_change_invalidates_verification_receipt(self) -> None:
        """Working bytes가 같아도 staged index tree가 바뀌면 verification은 conflict입니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._initialize_repository(root)

            def stage_without_worktree_change(
                worktree: Path,
                commands: list[str],
            ) -> list[dict[str, object]]:
                """Working bytes를 유지한 채 index만 바꾸고 성공 receipt를 반환합니다.

                Args:
                    worktree: Verifier가 전달한 exact fixture root입니다.
                    commands: 실행 요청한 closed command 목록입니다.

                Returns:
                    Index mutation을 숨기려는 forged success receipt입니다.
                """
                blob = (
                    subprocess
                    .run(
                        ("git", "hash-object", "-w", "--stdin"),
                        cwd=worktree,
                        input=b"staged-only\n",
                        capture_output=True,
                        check=True,
                    )
                    .stdout.decode()
                    .strip()
                )
                subprocess.run(
                    (
                        "git",
                        "update-index",
                        "--cacheinfo",
                        "100644",
                        blob,
                        "tracked.txt",
                    ),
                    cwd=worktree,
                    check=True,
                )
                return [{"command": commands[0], "exit_code": 0}]

            with self.assertRaises(VerificationWorktreeChanged):
                VerificationRunner(root, execute_commands=stage_without_worktree_change).run(
                    VerificationRequest(VerificationKind.CHECK)
                )

    def test_mise_check_is_an_exact_allowlisted_regression_entrypoint(self) -> None:
        """Mise SSOT의 exact check task만 shell-free regression runner에서 실행됩니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._initialize_repository(root)
            bin_directory = root / "bin"
            bin_directory.mkdir()
            mise = bin_directory / "mise"
            mise.write_text(
                '#!/bin/sh\n[ "$1" = run ] || exit 2\n[ "$2" = check ]\n',
                encoding="utf-8",
            )
            mise.chmod(0o755)
            (root / '.neurath').mkdir()
            (root / '.neurath/project.json').write_text(json.dumps({'verification': {'check': {'argv': [str(mise), 'run', 'check']}}}))
            environment = {**os.environ, "PATH": f"{bin_directory}:{os.environ['PATH']}"}

            with patch.dict(os.environ, environment, clear=True):
                receipts = run_regression_commands(root, [".neurath/run verify check"])

            self.assertEqual(0, receipts[0]["exit_code"])
            with self.assertRaises(ValueError):
                run_regression_commands(root, ["mise run arbitrary"])

    def test_verification_child_cannot_inherit_runtime_actor_authority(self) -> None:
        """Verifier child는 foreground actor/session capability를 상속하지 않습니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._initialize_repository(root)
            bin_directory = root / "bin"
            bin_directory.mkdir()
            mise = bin_directory / "mise"
            mise.write_text(
                "#!/bin/sh\n"
                '[ "$1" = run ] || exit 2\n'
                '[ "$2" = check ] || exit 3\n'
                '[ -z "$NEURATH_AGENT_ACTOR_ID" ] || exit 11\n'
                '[ -z "$NEURATH_AGENT_RUNTIME" ] || exit 12\n'
                '[ -z "$NEURATH_AGENT_SESSION_ID" ] || exit 13\n'
                '[ -z "$NEURATH_AGENT_ROOT_ACTOR_ID" ] || exit 14\n'
                '[ -z "$CLAUDE_CODE_SESSION_ID" ] || exit 15\n'
                '[ -z "$CODEX_THREAD_ID" ] || exit 16\n',
                encoding="utf-8",
            )
            mise.chmod(0o755)
            (root / '.neurath').mkdir()
            (root / '.neurath/project.json').write_text(json.dumps({'verification': {'check': {'argv': [str(mise), 'run', 'check']}}}))
            environment = {
                **os.environ,
                "PATH": f"{bin_directory}:{os.environ['PATH']}",
                "NEURATH_AGENT_ACTOR_ID": "claude-code:child",
                "NEURATH_AGENT_RUNTIME": "claude-code",
                "NEURATH_AGENT_SESSION_ID": "session-1",
                "NEURATH_AGENT_ROOT_ACTOR_ID": "claude-code:root",
                "CLAUDE_CODE_SESSION_ID": "session-1",
                "CODEX_THREAD_ID": "thread-1",
            }

            with patch.dict(os.environ, environment, clear=True):
                receipts = run_regression_commands(root, [".neurath/run verify check"])

            self.assertEqual(0, receipts[0]["exit_code"])

    def _initialize_repository(self, root: Path) -> None:
        """Tracked file과 HEAD를 가진 isolated Git repository를 만듭니다."""
        subprocess.run(("git", "init", "-q", "-b", "develop"), cwd=root, check=True)
        (root / "tracked.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(("git", "add", "tracked.txt"), cwd=root, check=True)
        subprocess.run(
            (
                "git",
                "-c",
                "user.name=Neurath Test",
                "-c",
                "user.email=neurath@example.invalid",
                "commit",
                "-q",
                "-m",
                "initial",
            ),
            cwd=root,
            check=True,
        )
