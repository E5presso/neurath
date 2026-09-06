"""Local PR monitor process manager의 launch readiness fallback을 검증합니다."""

import importlib.util
import subprocess
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast
from unittest import TestCase
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[3]
MANAGER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/monitor_process_manager.py"
sys.path.insert(0, str(MANAGER_PATH.parent))
SPEC = importlib.util.spec_from_file_location("monitor_process_manager", MANAGER_PATH)
assert SPEC is not None
monitor_process_manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["monitor_process_manager"] = monitor_process_manager
SPEC.loader.exec_module(monitor_process_manager)


class MonitorProcessManagerView(Protocol):
    """Dynamic manager module의 test-facing contract입니다."""

    def launch(
        self,
        *,
        launcher: str,
        label: str,
        poll_interval_seconds: int,
        command: list[str],
        user_id: int,
        readiness_attempts: int = 50,
    ) -> dict[str, object]:
        """Exact runtime resource에서 monitor를 시작합니다."""


class MonitorProcessManagerTest(TestCase):
    """Process manager가 등록과 실제 생존을 구분하는지 고정합니다."""

    def test_falls_back_when_launchctl_job_never_becomes_live(self) -> None:
        """LaunchAgent 초기화 실패는 detached process로 복구합니다."""
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            manager = self._manager(directory)
            process = Mock(pid=321)
            process.poll.return_value = None
            launchctl_results = [
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                *[
                    subprocess.CompletedProcess([], 0, "-\t0\tcom.neurath.pr131.local-monitor\n", "")
                    for _ in range(10)
                ],
                subprocess.CompletedProcess(
                    [],
                    0,
                    "service details\nlast exit code = 78: EX_CONFIG\nresource coalition",
                    "",
                ),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
            ]
            with (
                patch.object(
                    monitor_process_manager.subprocess,
                    "run",
                    side_effect=launchctl_results,
                ) as run,
                patch.object(
                    monitor_process_manager.subprocess,
                    "Popen",
                    return_value=process,
                ) as popen,
                patch.object(monitor_process_manager.time, "sleep"),
            ):
                receipt = manager.launch(
                    launcher="launchctl",
                    label="com.neurath.pr131.local-monitor",
                    poll_interval_seconds=30,
                    command=["python3", "monitor.py", "--launcher", "launchctl"],
                    user_id=501,
                    readiness_attempts=10,
                )

        self.assertEqual("nohup", receipt["launcher"])
        self.assertEqual(321, receipt["manager_pid"])
        self.assertNotIn("pid", receipt)
        self.assertTrue(receipt["keep_alive_on_failure"])
        self.assertEqual("last exit code = 78: EX_CONFIG", receipt["launchctl_failure"])
        self.assertEqual("nohup", popen.call_args.args[0][-1])
        self.assertIn("while true", popen.call_args.args[0][2])
        self.assertIn("trap", popen.call_args.args[0][2])
        self.assertIn(
            call(
                ["launchctl", "bootout", "gui/501/com.neurath.pr131.local-monitor"],
                check=False,
                capture_output=True,
                text=True,
            ),
            run.call_args_list,
        )

    def test_preserves_launchctl_when_job_has_live_pid(self) -> None:
        """실제 PID가 확인된 LaunchAgent에는 fallback을 적용하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            manager = self._manager(directory)
            launchctl_results = [
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                *[
                    subprocess.CompletedProcess(
                        [],
                        0,
                        "456\t0\tcom.neurath.pr131.local-monitor\n",
                        "",
                    )
                    for _ in range(10)
                ],
            ]
            with (
                patch.object(
                    monitor_process_manager.subprocess,
                    "run",
                    side_effect=launchctl_results,
                ),
                patch.object(monitor_process_manager.subprocess, "Popen") as popen,
            ):
                receipt = manager.launch(
                    launcher="launchctl",
                    label="com.neurath.pr131.local-monitor",
                    poll_interval_seconds=30,
                    command=["python3", "monitor.py", "--launcher", "launchctl"],
                    user_id=501,
                    readiness_attempts=10,
                )

        self.assertEqual("launchctl", receipt["launcher"])
        self.assertEqual(456, receipt["pid"])
        self.assertTrue(receipt["keep_alive_on_failure"])
        popen.assert_not_called()

    def test_falls_back_when_launchctl_pid_is_only_transient(self) -> None:
        """한 번 보인 뒤 죽는 PID를 monitor 생존으로 오인하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            manager = self._manager(directory)
            process = Mock(pid=654)
            process.poll.return_value = None
            launchctl_results = [
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess(
                    [],
                    0,
                    "456\t0\tcom.neurath.pr131.local-monitor\n",
                    "",
                ),
                *[
                    subprocess.CompletedProcess(
                        [],
                        0,
                        "-\t78\tcom.neurath.pr131.local-monitor\n",
                        "",
                    )
                    for _ in range(9)
                ],
                subprocess.CompletedProcess([], 0, "last exit code = 78: EX_CONFIG", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
            ]
            with (
                patch.object(
                    monitor_process_manager.subprocess,
                    "run",
                    side_effect=launchctl_results,
                ),
                patch.object(
                    monitor_process_manager.subprocess,
                    "Popen",
                    return_value=process,
                ),
                patch.object(monitor_process_manager.time, "sleep"),
            ):
                receipt = manager.launch(
                    launcher="launchctl",
                    label="com.neurath.pr131.local-monitor",
                    poll_interval_seconds=30,
                    command=["python3", "monitor.py", "--launcher", "launchctl"],
                    user_id=501,
                    readiness_attempts=10,
                )

        self.assertEqual("nohup", receipt["launcher"])
        self.assertEqual(654, receipt["manager_pid"])
        self.assertNotIn("pid", receipt)
        self.assertTrue(receipt["keep_alive_on_failure"])
        self.assertEqual("last exit code = 78: EX_CONFIG", receipt["launchctl_failure"])

    def test_public_cli_rejects_worktree_and_state_path_selectors(self) -> None:
        """Process manager는 current runtime resource 밖의 path를 public input으로 받지 않습니다."""
        parser = monitor_process_manager.MonitorProcessManagerApplication().parser()

        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args((
                "--launcher",
                "nohup",
                "--label",
                "com.neurath.pr131.local-monitor",
                "--poll-interval-seconds",
                "30",
                "--user-id",
                "501",
                "--state-path",
                "/tmp/foreign.json",
            ))

    def _manager(self, directory: Path) -> MonitorProcessManagerView:
        """Temporary Git worktree에 runtime-derived manager를 생성합니다."""
        subprocess.run(("git", "init", "-q", str(directory)), check=True)
        resources = monitor_process_manager.MonitorRuntimeResources.resolve(
            cwd=directory,
            environment={"CODEX_THREAD_ID": "owner-thread"},
        )
        return cast(
            MonitorProcessManagerView,
            monitor_process_manager.MonitorProcessManager(resources),
        )
