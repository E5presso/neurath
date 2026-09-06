"""Local monitor LaunchAgent crash-restart receipt를 검증합니다."""

import importlib.util
import plistlib
import subprocess
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
PLIST_HELPER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/launch_agent_plist.py"
sys.path.insert(0, str(PLIST_HELPER_PATH.parent))
from monitor_runtime_lock import monitor_runtime_claim_path  # noqa: E402 - helper path is configured above

SPEC = importlib.util.spec_from_file_location("launch_agent_plist", PLIST_HELPER_PATH)
assert SPEC is not None
launch_agent_plist = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["launch_agent_plist"] = launch_agent_plist
SPEC.loader.exec_module(launch_agent_plist)


class LaunchAgentPlistTest(TestCase):
    """Launchd monitor lifetime invariant를 고정합니다."""

    def test_nonzero_exit_is_restarted_but_terminal_success_is_not(self) -> None:
        """Crash는 KeepAlive하고 정상 terminal exit는 재시작하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            worktree = directory / "worktree"
            worktree.mkdir()
            subprocess.run(("git", "init", "-q", str(worktree)), check=True)
            resources = launch_agent_plist.MonitorRuntimeResources.resolve(
                cwd=worktree,
                environment={"CODEX_THREAD_ID": "owner-thread"},
            )

            written = launch_agent_plist.LaunchAgentPlistWriter(resources).write(
                label="com.neurath.pr131.local-monitor",
                command=["/usr/bin/env", "PATH=/usr/bin", "/usr/bin/python3", "monitor.py"],
            )
            with written.open("rb") as stream:
                payload = plistlib.load(stream)

        self.assertEqual({"SuccessfulExit": False}, payload["KeepAlive"])
        self.assertTrue(payload["RunAtLoad"])
        self.assertEqual(5, payload["ThrottleInterval"])
        self.assertEqual("Background", payload["ProcessType"])
        self.assertEqual("/bin/bash", payload["ProgramArguments"][0])
        self.assertEqual(str(worktree.resolve()), payload["ProgramArguments"][4])
        self.assertEqual("/usr/bin/env", payload["ProgramArguments"][5])

    def test_empty_command_is_rejected(self) -> None:
        """실행 identity 없는 KeepAlive job은 생성하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            subprocess.run(("git", "init", "-q", str(directory)), check=True)
            resources = launch_agent_plist.MonitorRuntimeResources.resolve(
                cwd=directory,
                environment={"CODEX_THREAD_ID": "owner-thread"},
            )
            with self.assertRaisesRegex(ValueError, "command"):
                launch_agent_plist.LaunchAgentPlistWriter(resources).write(
                    label="com.neurath.pr131.local-monitor",
                    command=[],
                )

    def test_prepared_handoff_claim_blocks_same_plist_path_reuse(self) -> None:
        """Slow unload 동안 durable claim이 있으면 같은 label/path를 다시 쓰지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            subprocess.run(("git", "init", "-q", str(directory)), check=True)
            resources = launch_agent_plist.MonitorRuntimeResources.resolve(
                cwd=directory,
                environment={"CODEX_THREAD_ID": "owner-thread"},
            )
            output = resources.launch_plist_path("com.neurath.pr131.local-monitor")
            output.parent.mkdir(parents=True)
            claim = monitor_runtime_claim_path(
                output.parent,
                handoff_id="a" * 32,
                target_name=output.name,
            )
            claim.write_bytes(b"prepared original plist")

            with self.assertRaisesRegex(
                launch_agent_plist.MonitorRuntimeCommitConflict,
                "claimed by prepared handoff",
            ):
                launch_agent_plist.LaunchAgentPlistWriter(resources).write(
                    label="com.neurath.pr131.local-monitor",
                    command=["/usr/bin/python3", "monitor.py"],
                )

            self.assertFalse(output.exists())
            self.assertEqual(b"prepared original plist", claim.read_bytes())

    def test_public_cli_rejects_worktree_and_output_path_selectors(self) -> None:
        """Plist helper는 current runtime resource 밖의 path를 public input으로 받지 않습니다."""
        parser = launch_agent_plist.LaunchAgentPlistApplication().parser()

        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args((
                "--label",
                "com.neurath.pr131.local-monitor",
                "--worktree",
                "/tmp/foreign",
            ))
