"""PR monitor launch critical section의 직렬화 회귀 테스트입니다."""

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.monitor_observation_store import MonitorObservationStore

ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/monitor_launch_lock.py"
SPEC = importlib.util.spec_from_file_location("monitor_launch_lock", HELPER_PATH)
assert SPEC is not None
monitor_launch_lock = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(monitor_launch_lock)
STARTER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/start_local_pr_monitor.sh"
LOCKED_STARTER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/start_local_pr_monitor_locked.sh"


FAKE_MONITOR_RUNTIME = r"""#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from scripts.agent_harness.monitor_observation_store import MonitorObservationStore

name = Path(sys.argv[0]).name
token = os.environ["MONITOR_STARTER_TOKEN"]
events_path = Path(os.environ["MONITOR_TEST_EVENTS_PATH"])
worktree = Path.cwd().resolve()
runtime_path = worktree / ".monitor-pr/monitor-state.json"
runtime_store = MonitorObservationStore(runtime_path)

def record(kind, **details):
    event = {"kind": kind, "token": token}
    event.update(details)
    with events_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")
        stream.flush()

if name == "monitor_runtime_handoff.py":
    record("handoff-start")
    if runtime_store.exists():
        previous = runtime_store.read_required()
        for key in ("pid", "manager_pid"):
            try:
                os.kill(int(previous[key]), signal.SIGTERM)
            except ProcessLookupError:
                pass
        record("runtime-stop")
    time.sleep(0.15)
    record("handoff-end")
    print(json.dumps({"retired": True}))
elif name == "app_server_resume.py":
    print(json.dumps({"probe_status": "available"}))
elif name == "launch_agent_plist.py":
    record("plist")
elif name == "monitor_process_manager.py":
    record(
        "launch-start",
        lock_marker=os.environ.get("NEURATH_MONITOR_LAUNCH_LOCK_HELD"),
    )
    sleepers = [
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(2)
    ]
    runtime = {
        "launcher": "nohup",
        "pid": sleepers[0].pid,
        "manager_pid": sleepers[1].pid,
        "token": token,
    }
    command = sys.argv[sys.argv.index("--") + 1:]
    workflow_id = command[command.index("--workflow-id") + 1]
    runtime_id = command[command.index("--runtime-id") + 1]
    runtime_state = {
        **runtime,
        "provider": "local-pr-monitor",
        "repo": os.environ["REPO"],
        "pr_number": int(os.environ["PR_NUMBER"]),
        "thread_id": os.environ["CODEX_THREAD_ID"],
        "session_id": os.environ["CODEX_THREAD_ID"],
        "workflow_id": workflow_id,
        "runtime_id": runtime_id,
        "worktree": str(worktree),
        "resume_adapter": "command",
        "heartbeat_at_epoch": time.time(),
        "last_observed": {"comments": {}, "terminal": {}},
    }
    runtime_store.write(runtime_state)
    record("launch-end", pid=sleepers[0].pid, manager_pid=sleepers[1].pid)
    print(json.dumps(runtime))
elif name == "monitor_runtime_readback.py":
    manager = json.loads(sys.argv[sys.argv.index("--manager-json") + 1])
    state = runtime_store.read_required()
    workflow_id = sys.argv[sys.argv.index("--workflow-id") + 1]
    runtime_id = sys.argv[sys.argv.index("--runtime-id") + 1]
    subscription = {
        "provider": "local-pr-monitor",
        "repo": os.environ["REPO"],
        "pr_number": int(os.environ["PR_NUMBER"]),
        "session_id": os.environ["CODEX_THREAD_ID"],
        "workflow_id": workflow_id,
        "runtime_id": runtime_id,
        "worktree_id": "fixture-worktree",
        "observation_resource": {
            "kind": "monitor-observation-cache",
            "worktree_id": "fixture-worktree",
        },
        "resume_adapter": "command",
        "launcher": manager["launcher"],
        "pid": state["pid"],
        "manager_pid": manager.get("manager_pid"),
        "last_seen": state["last_observed"],
    }
    print(json.dumps({"receipt": {**manager, **subscription}, "subscription": subscription}))
elif name == "process_state_evidence.py":
    field = sys.argv[sys.argv.index("--field") + 1]
    value = json.loads(sys.argv[sys.argv.index("--value-json") + 1])
    workflow_id = sys.argv[sys.argv.index("--workflow-id") + 1]
    record("evidence-" + field, value=value, workflow_id=workflow_id)
    print(json.dumps({field: value}))
else:
    raise SystemExit("unexpected fake helper: " + name)
"""


class MonitorLaunchLockTest(TestCase):
    """서로 다른 starter process가 같은 launch 구간에 겹치지 않도록 검증합니다."""

    def test_concurrent_starters_enter_critical_section_serially(self) -> None:
        """두 process가 경쟁해도 start/end pair 사이에 다른 start가 끼지 않습니다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "monitor-launch.lock"
            events_path = root / "events.jsonl"
            worker = (
                "import json,sys,time; "
                "path,label=sys.argv[1:]; "
                "stream=open(path,'a',encoding='utf-8'); "
                "stream.write(json.dumps({'kind':'start','label':label})+'\\n'); "
                "stream.flush(); time.sleep(0.2); "
                "stream.write(json.dumps({'kind':'end','label':label})+'\\n'); "
                "stream.close()"
            )
            commands = [
                [
                    sys.executable,
                    str(HELPER_PATH),
                    "--lock-path",
                    str(lock_path),
                    "--",
                    sys.executable,
                    "-c",
                    worker,
                    str(events_path),
                    label,
                ]
                for label in ("first", "second")
            ]

            processes = [subprocess.Popen(command) for command in commands]
            returncodes = [process.wait(timeout=5) for process in processes]
            events = [
                json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual([0, 0], returncodes)
        self.assertEqual(["start", "end", "start", "end"], [event["kind"] for event in events])
        self.assertEqual(events[0]["label"], events[1]["label"])
        self.assertEqual(events[2]["label"], events[3]["label"])
        self.assertNotEqual(events[0]["label"], events[2]["label"])

    def test_propagates_locked_command_failure(self) -> None:
        """Lock 안의 starter 실패를 성공으로 숨기지 않습니다."""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER_PATH),
                    "--lock-path",
                    str(Path(directory) / "monitor-launch.lock"),
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(23)",
                ],
                check=False,
            )

        self.assertEqual(23, result.returncode)

    def test_locked_starter_uses_runtime_session_and_workflow_contract(self) -> None:
        """Launcher는 legacy state route 없이 runtime identity를 child에 보존합니다."""
        source = LOCKED_STARTER_PATH.read_text(encoding="utf-8")

        self.assertIn("${WORKFLOW_ID:?WORKFLOW_ID env required}", source)
        self.assertIn("CODEX_THREAD_ID", source)
        self.assertIn("CLAUDE_CODE_SESSION_ID", source)
        self.assertIn('--workflow-id "$WORKFLOW_ID"', source)
        self.assertIn('--runtime-id "$runtime_id"', source)
        self.assertIn("process_state_evidence.py", source)
        self.assertNotIn("PROCESS_STATE_PATH", source)
        self.assertNotIn("process_state_path", source)
        self.assertIn("monitor_runtime_readback.py", source)
        self.assertNotIn("Path(state_path).read_text", source)
        self.assertNotIn("--worktree", source)
        self.assertNotIn("--state-path", source)
        self.assertNotIn("--thread-id", source)
        self.assertNotIn("--field monitor_started --value-json", source)

    def test_public_starter_derives_runtime_paths_without_legacy_selectors(self) -> None:
        """Public wrapper는 cwd와 runtime identity만 사용하고 path/session override를 받지 않습니다."""
        source = STARTER_PATH.read_text(encoding="utf-8")

        self.assertIn("${WORKFLOW_ID:?WORKFLOW_ID env required}", source)
        self.assertIn("git rev-parse --show-toplevel", source)
        self.assertIn("$worktree/.monitor-pr/monitor-launch.lock", source)
        self.assertNotIn("${WORKTREE:?", source)
        self.assertNotIn("${THREAD_ID:?", source)
        self.assertNotIn("MONITOR_STATE_DIR", source)
        self.assertNotIn("MONITOR_LAUNCH_LOCK_PATH", source)

    def test_reused_foreign_process_group_reads_as_terminated(self) -> None:
        """kill-0 probe의 EPERM은 재사용된 남의 group이므로 종료로 판정합니다."""
        with patch.object(
            monitor_launch_lock.os,
            "killpg",
            side_effect=PermissionError(1, "Operation not permitted"),
        ):
            self.assertFalse(monitor_launch_lock._process_group_exists(12345))

    def test_signal_to_reused_foreign_process_group_does_not_crash(self) -> None:
        """재사용된 남의 group으로의 signal 거부는 wrapper를 죽이지 않습니다."""

        class FakeStarter:
            """재사용된 group id만 남긴 starter process stand-in입니다."""

            pid = 12345
            """Signal 대상 process group id입니다."""

        with patch.object(
            monitor_launch_lock.os,
            "killpg",
            side_effect=PermissionError(1, "Operation not permitted"),
        ):
            monitor_launch_lock._signal_process_group(FakeStarter(), signal.SIGTERM)

    def test_sigterm_reaps_starter_process_group_before_unlock(self) -> None:
        """Wrapper 중단은 starter와 descendant를 모두 끝낸 뒤 lock을 해제합니다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "monitor-launch.lock"
            pids_path = root / "starter-pids.json"
            descendant_ready_path = root / "descendant-ready"
            descendant = (
                "import signal,sys,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "open(sys.argv[1],'w',encoding='utf-8').write('ready'); "
                "time.sleep(30)"
            )
            worker = (
                "import json,os,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[3]]); "
                "open(sys.argv[1],'w',encoding='utf-8').write("
                "json.dumps({'starter':os.getpid(),'descendant':child.pid})); "
                "time.sleep(30)"
            )
            wrapper = subprocess.Popen([
                sys.executable,
                str(HELPER_PATH),
                "--lock-path",
                str(lock_path),
                "--",
                sys.executable,
                "-c",
                worker,
                str(pids_path),
                descendant,
                str(descendant_ready_path),
            ])
            deadline = time.monotonic() + 5
            while (
                not pids_path.is_file() or not descendant_ready_path.is_file()
            ) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(pids_path.is_file())
            self.assertTrue(descendant_ready_path.is_file())
            pids = {int(pid) for pid in json.loads(pids_path.read_text()).values()}

            try:
                wrapper.send_signal(signal.SIGTERM)
                returncode = wrapper.wait(timeout=5)
                death_deadline = time.monotonic() + 2
                while time.monotonic() < death_deadline:
                    if not any(self._process_is_alive(pid) for pid in pids):
                        break
                    time.sleep(0.02)
                surviving_pids = {pid for pid in pids if self._process_is_alive(pid)}
                follow_up = subprocess.run(
                    [
                        sys.executable,
                        str(HELPER_PATH),
                        "--lock-path",
                        str(lock_path),
                        "--",
                        sys.executable,
                        "-c",
                        "raise SystemExit(0)",
                    ],
                    check=False,
                    timeout=5,
                )
            finally:
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        self.assertEqual(128 + signal.SIGTERM, returncode)
        self.assertEqual(0, follow_up.returncode)
        self.assertEqual(set(), surviving_pids)

    def test_concurrent_real_starters_leave_one_matching_runtime(self) -> None:
        """실제 starter 둘의 전체 launch 구간과 최종 runtime receipt를 검증합니다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_scripts = root / "skill/scripts"
            skill_scripts.mkdir(parents=True)
            shutil.copy2(STARTER_PATH, skill_scripts / STARTER_PATH.name)
            shutil.copy2(LOCKED_STARTER_PATH, skill_scripts / LOCKED_STARTER_PATH.name)
            shutil.copy2(HELPER_PATH, skill_scripts / HELPER_PATH.name)
            for helper_name in (
                "app_server_resume.py",
                "launch_agent_plist.py",
                "monitor_process_manager.py",
                "monitor_runtime_readback.py",
                "monitor_runtime_handoff.py",
            ):
                helper_path = skill_scripts / helper_name
                helper_path.write_text(FAKE_MONITOR_RUNTIME, encoding="utf-8")
                helper_path.chmod(0o755)

            worktree = root / "worktree"
            subprocess.run(("git", "init", "-q", str(worktree)), check=True)
            # The real shell starter's inline imports must ignore target modules,
            # while file-based helper imports continue using their own directory.
            for module in ("uuid", "json"):
                (worktree / f"{module}.py").write_text(
                    "raise RuntimeError('PROJECT_MODULE_EXECUTED')\n", encoding="utf-8"
                )
            evidence_helper = root / "process-ticket/scripts/process_state_evidence.py"
            evidence_helper.parent.mkdir(parents=True)
            evidence_helper.write_text(FAKE_MONITOR_RUNTIME, encoding="utf-8")
            evidence_helper.chmod(0o755)
            runtime_path = worktree / ".monitor-pr/monitor-state.json"
            events_path = root / "events.jsonl"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            launchctl = fake_bin / "launchctl"
            launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            launchctl.chmod(0o755)

            base_environment = os.environ.copy()
            base_environment.update({
                "PATH": f"{fake_bin}:{base_environment['PATH']}",
                "PYTHON_BIN": sys.executable,
                "REPO": "E5presso/neurath",
                "PR_NUMBER": "131",
                "WORKFLOW_ID": "process-ticket-131",
                "CODEX_THREAD_ID": "owner-thread",
                "MONITOR_TEST_EVENTS_PATH": str(events_path),
                "MONITOR_STARTUP_READBACK_ATTEMPTS": "3",
            })
            processes = []
            for token in ("first", "second"):
                environment = base_environment | {"MONITOR_STARTER_TOKEN": token}
                processes.append(
                    subprocess.Popen(
                        ["/bin/bash", str(skill_scripts / STARTER_PATH.name)],
                        env=environment,
                        cwd=worktree,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                )

            results = [process.communicate(timeout=10) for process in processes]
            returncodes = [process.returncode for process in processes]
            if not events_path.is_file():
                self.fail(
                    f"starter events are missing: returncodes={returncodes!r}; results={results!r}"
                )
            events = [
                json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            final_runtime = MonitorObservationStore(runtime_path).read_required()
            live_pids = [int(final_runtime[key]) for key in ("pid", "manager_pid")]
            launched_pids = [
                int(event[key])
                for event in events
                if event["kind"] == "launch-end"
                for key in ("pid", "manager_pid")
            ]
            try:
                for pid in live_pids:
                    os.kill(pid, 0)
                retired_pids = set(launched_pids) - set(live_pids)
                self._wait_until_dead(retired_pids)
                token_runs = []
                for event in events:
                    if not token_runs or token_runs[-1] != event["token"]:
                        token_runs.append(event["token"])

                self.assertEqual([0, 0], returncodes, results)
                self.assertEqual(2, len(token_runs), events)
                self.assertEqual({"first", "second"}, set(token_runs))
                self.assertEqual(token_runs[-1], final_runtime["token"])
                evidence_events = [
                    event
                    for event in events
                    if event["kind"] == "evidence-monitor_event_subscription"
                ]
                self.assertEqual(2, len(evidence_events))
                final_subscription = evidence_events[-1]["value"]
                self.assertEqual("owner-thread", final_subscription["session_id"])
                self.assertEqual("process-ticket-131", final_subscription["workflow_id"])
                self.assertNotIn("process_state_path", final_subscription)
                self.assertEqual(
                    1,
                    sum(event["kind"] == "runtime-stop" for event in events),
                )
                self.assertFalse(
                    any(event["kind"] == "evidence-monitor_started" for event in events)
                )
                self.assertTrue(
                    all(
                        event.get("lock_marker") is None
                        for event in events
                        if event["kind"] == "launch-start"
                    ),
                    events,
                )
                self.assertEqual(
                    set(live_pids),
                    {pid for pid in launched_pids if self._process_is_alive(pid)},
                )
            finally:
                for pid in live_pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                self._wait_until_dead(set(live_pids))

    @staticmethod
    def _process_is_alive(pid: int) -> bool:
        """PID가 현재 signal을 받을 수 있는 process인지 확인합니다."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _wait_until_dead(self, pids: set[int]) -> None:
        """테스트 runtime 종료를 기다리고 잔여 process를 강제 정리합니다."""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not any(self._process_is_alive(pid) for pid in pids):
                return
            time.sleep(0.02)
        for pid in pids:
            if self._process_is_alive(pid):
                os.kill(pid, signal.SIGKILL)
