"""Bounded verifier process가 descendant까지 terminalize하는지 검증합니다."""

import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts.agent_harness import bounded_process as bounded_process_module
from scripts.agent_harness.bounded_process import run_bounded_process


class BoundedProcessTest(TestCase):
    """Verifier와 hook이 공유할 process-group watchdog 계약을 실행합니다."""

    @patch.object(bounded_process_module, "_PROC_ROOT", Path("/unavailable-neurath-proc-fixture"))
    @patch("scripts.agent_harness.bounded_process.subprocess.run")
    def test_token_scan_falls_back_to_linux_process_table_syntax(
        self,
        run: Mock,
    ) -> None:
        """macOS ps option이 실패하면 GNU/Linux option으로 token process를 찾습니다."""
        run.side_effect = (
            Mock(returncode=1, stdout=""),
            Mock(
                returncode=0,
                stdout=" 321 python worker NEURATH_BOUNDED_PROCESS_TOKEN=sentinel\n",
            ),
        )

        discovered = bounded_process_module._process_ids_with_token("sentinel")

        self.assertEqual((321,), discovered)
        self.assertEqual(
            (
                (("ps", "eww", "-axo", "pid=,command="),),
                (("ps", "eww", "-eo", "pid=,command="),),
            ),
            tuple(call.args for call in run.call_args_list),
        )

    def test_timeout_kills_the_entire_process_group_without_orphaning_descendants(self) -> None:
        """Parent timeout 뒤 spawned child도 동일 process group에서 사라집니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child_pid = root / "child.pid"
            program = root / "spawn_child.py"
            program.write_text(
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"open({str(child_pid)!r}, 'w', encoding='utf-8').write(str(child.pid))\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )

            result = run_bounded_process(
                (sys.executable, str(program)),
                cwd=root,
                timeout_seconds=1.0,
            )
            deadline = time.monotonic() + 1.0
            self.assertTrue(child_pid.exists())
            pid = int(child_pid.read_text(encoding="utf-8"))
            while self._process_exists(pid) and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertTrue(result.timed_out)
        self.assertEqual(124, result.returncode)
        self.assertFalse(self._process_exists(pid))

    def test_success_returns_exact_streams_without_claiming_timeout(self) -> None:
        """Normal exit는 stdout, stderr와 process exit를 그대로 보존합니다."""
        with TemporaryDirectory() as temporary_directory:
            result = run_bounded_process(
                (
                    sys.executable,
                    "-c",
                    "import sys; print('out'); print('err', file=sys.stderr)",
                ),
                cwd=Path(temporary_directory),
                timeout_seconds=1.0,
            )

        self.assertFalse(result.timed_out)
        self.assertEqual(0, result.returncode)
        self.assertEqual(b"out\n", result.stdout)
        self.assertEqual(b"err\n", result.stderr)

    def test_timeout_bounds_drain_and_kills_a_re_sessioned_descendant(self) -> None:
        """Child가 새 session으로 PGID를 벗어나도 timeout wall-clock과 cleanup을 유지합니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child_pid = root / "escaped.pid"
            program = (
                "import subprocess, sys, time; "
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
                "start_new_session=True); "
                f"open({str(child_pid)!r}, 'w', encoding='utf-8').write(str(child.pid)); "
                "time.sleep(30)"
            )
            started = time.monotonic()

            result = run_bounded_process(
                (sys.executable, "-c", program),
                cwd=root,
                timeout_seconds=0.5,
            )
            elapsed = time.monotonic() - started
            self.assertTrue(child_pid.exists())
            pid = int(child_pid.read_text(encoding="utf-8"))

        self.assertTrue(result.timed_out)
        self.assertLess(elapsed, 2.0)
        self.assertFalse(self._process_exists(pid))

    def test_timeout_finds_a_reparented_re_sessioned_pipe_writer(self) -> None:
        """Leader가 먼저 끝나도 inherited token으로 escaped pipe writer를 종료합니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child_pid = root / "reparented.pid"
            program = (
                "import subprocess, sys; "
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
                "start_new_session=True); "
                f"open({str(child_pid)!r}, 'w', encoding='utf-8').write(str(child.pid))"
            )
            started = time.monotonic()

            result = run_bounded_process(
                (sys.executable, "-c", program),
                cwd=root,
                timeout_seconds=0.2,
            )
            elapsed = time.monotonic() - started
            self.assertTrue(child_pid.exists())
            pid = int(child_pid.read_text(encoding="utf-8"))

        self.assertTrue(result.timed_out)
        self.assertLess(elapsed, 2.0)
        self.assertFalse(self._process_exists(pid))

    def test_success_cleans_a_background_descendant_before_returning(self) -> None:
        """Leader exit 0도 owned process group의 background survivor를 남기지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child_pid = root / "background.pid"
            program = (
                "import subprocess, sys; "
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
                "stderr=subprocess.DEVNULL); "
                f"open({str(child_pid)!r}, 'w', encoding='utf-8').write(str(child.pid))"
            )

            result = run_bounded_process(
                (sys.executable, "-c", program),
                cwd=root,
                timeout_seconds=1.0,
            )
            self.assertTrue(child_pid.exists())
            pid = int(child_pid.read_text(encoding="utf-8"))

        self.assertFalse(result.timed_out)
        self.assertEqual(125, result.returncode)
        self.assertFalse(self._process_exists(pid))

    def test_external_termination_cleans_the_owned_verifier_process_tree(self) -> None:
        """Outer cancellation도 internal watchdog을 기다리지 않고 child group을 닫습니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child_pid = root / "cancelled.pid"
            wrapper = root / "run_helper.py"
            wrapper.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "from scripts.agent_harness.bounded_process import run_bounded_process\n"
                f"root = Path({str(root)!r})\n"
                "run_bounded_process((sys.executable, '-c', "
                f"\"import os,time; open({str(child_pid)!r}, 'w').write(str(os.getpid())); "
                'time.sleep(30)"), cwd=root, timeout_seconds=30)\n',
                encoding="utf-8",
            )
            environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])}
            owner = subprocess.Popen((sys.executable, str(wrapper)), env=environment)
            deadline = time.monotonic() + 2.0
            while not child_pid.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(child_pid.exists())
            pid = int(child_pid.read_text(encoding="utf-8"))

            owner.terminate()
            owner.wait(timeout=2.0)
            while self._process_exists(pid) and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertFalse(self._process_exists(pid))

    def _process_exists(self, pid: int) -> bool:
        """PID가 signal 가능한 live process인지 확인합니다."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True


class ProcfsFallbackTest(TestCase):
    def test_linux_token_lookup_uses_exact_environment_entries_without_ps(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, token in ((123, b'NEURATH_BOUNDED_PROCESS_TOKEN=sentinel'), (124, b'NEURATH_BOUNDED_PROCESS_TOKEN=sentinel-extra')):
                process = root / str(pid)
                process.mkdir()
                (process / 'environ').write_bytes(token + b'\0')
            with patch.object(bounded_process_module, '_PROC_ROOT', root), patch.object(bounded_process_module.subprocess, 'run', side_effect=AssertionError('ps must not run')):
                self.assertEqual((123,), bounded_process_module._process_ids_with_token('sentinel'))

    def test_linux_descendant_lookup_handles_spaces_and_parentheses_in_process_name(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, parent in ((321, 10), (322, 321), (323, 20)):
                process = root / str(pid)
                process.mkdir()
                (process / 'stat').write_text(f'{pid} (name with ) parentheses) S {parent} 0 0')
            with patch.object(bounded_process_module, '_PROC_ROOT', root), patch.object(bounded_process_module.subprocess, 'run', side_effect=AssertionError('ps must not run')):
                self.assertEqual({321, 322}, set(bounded_process_module._descendant_process_ids(10)))
