"""Runtime hook process boundary가 exact-session application을 실행하는지 검증합니다."""

import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.agent_harness.runtime_hook_command import RuntimeHookCommand
from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator


class RuntimeHookCommandTest(unittest.TestCase):
    """Hook stdin/environment/cwd를 canonical control root에 결속합니다."""

    def setUp(self) -> None:
        """실제 git common directory를 가진 격리 repository를 준비합니다."""
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        subprocess.run(
            ["git", "init", "--quiet", str(self.root)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_codex_startup_reads_stdin_and_writes_one_hook_json(self) -> None:
        """Codex startup은 cwd의 common root에 exact session을 초기화합니다."""
        stdout = io.StringIO()
        command = RuntimeHookCommand(
            enclave_max_bytes=16_384,
            additional_context_max_bytes=24_576,
        )
        payload = json.dumps({
            "cwd": str(self.root),
            "hook_event_name": "SessionStart",
            "model": "gpt-5.6",
            "permission_mode": "default",
            "session_id": "session-a",
            "source": "startup",
            "transcript_path": None,
        })

        exit_code = command.run(
            raw_input=payload,
            environment={
                "NEURATH_HOOK_RUNTIME": "codex",
                "CODEX_THREAD_ID": "session-a",
            },
            cwd=self.root,
            stdout=stdout,
        )

        self.assertEqual(0, exit_code)
        output: object = json.loads(stdout.getvalue())
        self.assertIsInstance(output, dict)
        locator = SessionLocator.from_worktree(self.root)
        state = SessionKernel(locator).inspect(SessionId("session-a"))
        self.assertEqual(SessionId("session-a"), state.session.id)
        self.assertEqual({}, state.outbox)
        self.assertEqual(2, state.revision)
        turn = state.foreground_turns[state.session.root_actor_id]
        self.assertEqual(1, turn.generation)
        self.assertEqual(0, turn.revision)
        self.assertIsNone(turn.vendor_turn_id)
        self.assertIsNone(turn.user_prompt_receipt)
        self.assertFalse(locator.locate(SessionId("other")).process_state.exists())

    def test_invalid_hook_input_is_nonzero_without_fallback_state(self) -> None:
        """Malformed stdin은 typed empty hook output만 내고 state를 만들지 않습니다."""
        stdout = io.StringIO()
        command = RuntimeHookCommand(
            enclave_max_bytes=16_384,
            additional_context_max_bytes=24_576,
        )

        exit_code = command.run(
            raw_input="{invalid",
            environment={"NEURATH_HOOK_RUNTIME": "codex"},
            cwd=self.root,
            stdout=stdout,
        )

        self.assertNotEqual(0, exit_code)
        self.assertEqual({}, json.loads(stdout.getvalue()))
        runs = self.root / ".agents" / "runs"
        self.assertFalse(runs.exists())



if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
