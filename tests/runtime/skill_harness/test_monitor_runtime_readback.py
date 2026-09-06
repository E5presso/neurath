"""Runtime-derived local monitor observation readback 회귀 테스트입니다."""

import importlib.util
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/monitor_runtime_readback.py"
sys.path.insert(0, str(HELPER_PATH.parent))
SPEC = importlib.util.spec_from_file_location("monitor_runtime_readback", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
monitor_runtime_readback = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor_runtime_readback
SPEC.loader.exec_module(monitor_runtime_readback)


class MonitorRuntimeResourcesView(Protocol):
    """Dynamic resource module의 readback test-facing contract입니다."""

    observation_path: Path
    """Current worktree에서 파생된 private observation cache path입니다."""

    worktree_id: str
    """Canonical Git identity에서 파생된 opaque worktree identity입니다."""


class MonitorRuntimeReadbackTest(TestCase):
    """Session/workflow/runtime identity, heartbeat, process 생존을 함께 검증합니다."""

    def test_accepts_exact_live_runtime_without_raw_state_route(self) -> None:
        """Runtime resource handle에서 exact observation receipt를 구성합니다."""
        with TemporaryDirectory() as directory:
            resources = self._resources(Path(directory))
            resources.observation_path.parent.mkdir(parents=True, exist_ok=True)
            resources.observation_path.write_text(
                json.dumps(self._state(resources, heartbeat=200.0)),
                encoding="utf-8",
            )

            receipt = monitor_runtime_readback.MonitorRuntimeReadback(
                resources,
                self._expected(minimum_heartbeat=100.0),
                clock=lambda: 220.0,
            ).receipt()

        self.assertEqual(os.getpid(), receipt["pid"])
        self.assertEqual(4, receipt["schema_version"])
        self.assertEqual(200.0, receipt["heartbeat_at_epoch"])
        self.assertEqual("owner-thread", receipt["session_id"])
        self.assertEqual("process-ticket-131", receipt["workflow_id"])
        self.assertNotIn("state_path", receipt)
        self.assertNotIn("process_state_path", receipt)
        self.assertEqual("monitor-observation-cache", receipt["observation_resource"]["kind"])

    def test_rejects_stale_heartbeat_from_previous_launch(self) -> None:
        """PID가 우연히 같아도 이전 launch observation은 거부합니다."""
        with TemporaryDirectory() as directory:
            resources = self._resources(Path(directory))
            resources.observation_path.parent.mkdir(parents=True, exist_ok=True)
            resources.observation_path.write_text(
                json.dumps(self._state(resources, heartbeat=99.0)),
                encoding="utf-8",
            )
            readback = monitor_runtime_readback.MonitorRuntimeReadback(
                resources,
                self._expected(minimum_heartbeat=100.0),
                clock=lambda: 120.0,
            )

            with self.assertRaisesRegex(ValueError, "predates this launch"):
                readback.receipt()

    def test_rejects_mismatched_workflow_route(self) -> None:
        """다른 workflow observation은 current subscription evidence가 될 수 없습니다."""
        with TemporaryDirectory() as directory:
            resources = self._resources(Path(directory))
            state = self._state(resources, heartbeat=200.0)
            state["workflow_id"] = "foreign-workflow"
            resources.observation_path.parent.mkdir(parents=True, exist_ok=True)
            resources.observation_path.write_text(json.dumps(state), encoding="utf-8")
            readback = monitor_runtime_readback.MonitorRuntimeReadback(
                resources,
                self._expected(minimum_heartbeat=100.0),
                clock=lambda: 220.0,
            )

            with self.assertRaisesRegex(ValueError, "workflow_id mismatch"):
                readback.receipt()

    def test_rejects_mismatched_monitor_pid(self) -> None:
        """살아 있는 다른 PID도 launch가 고정한 exact PID를 대신할 수 없습니다."""
        with TemporaryDirectory() as directory:
            resources = self._resources(Path(directory))
            state = self._state(resources, heartbeat=200.0)
            state["pid"] = os.getppid()
            resources.observation_path.parent.mkdir(parents=True, exist_ok=True)
            resources.observation_path.write_text(json.dumps(state), encoding="utf-8")
            readback = monitor_runtime_readback.MonitorRuntimeReadback(
                resources,
                self._expected(minimum_heartbeat=100.0),
                clock=lambda: 220.0,
            )

            with self.assertRaisesRegex(ValueError, "pid mismatch"):
                readback.receipt()

    def test_rejects_unknown_observation_schema(self) -> None:
        """공유 liveness 판정은 정의되지 않은 observation schema를 추정하지 않습니다."""
        with TemporaryDirectory() as directory:
            resources = self._resources(Path(directory))
            state = self._state(resources, heartbeat=200.0)
            state["schema_version"] = 5
            resources.observation_path.parent.mkdir(parents=True, exist_ok=True)
            resources.observation_path.write_text(json.dumps(state), encoding="utf-8")
            readback = monitor_runtime_readback.MonitorRuntimeReadback(
                resources,
                self._expected(minimum_heartbeat=100.0),
                clock=lambda: 220.0,
            )

            with self.assertRaisesRegex(ValueError, "schema is unsupported"):
                readback.receipt()

    def test_rejects_heartbeat_older_than_poll_window_even_when_pid_is_alive(self) -> None:
        """Launch 이후 heartbeat도 poll freshness window를 넘으면 live가 아닙니다."""
        with TemporaryDirectory() as directory:
            resources = self._resources(Path(directory))
            resources.observation_path.parent.mkdir(parents=True, exist_ok=True)
            resources.observation_path.write_text(
                json.dumps(self._state(resources, heartbeat=200.0)),
                encoding="utf-8",
            )
            readback = monitor_runtime_readback.MonitorRuntimeReadback(
                resources,
                self._expected(minimum_heartbeat=100.0),
                clock=lambda: 300.0,
            )

            with self.assertRaisesRegex(ValueError, "heartbeat is stale"):
                readback.receipt()

    def test_public_cli_rejects_state_worktree_and_thread_selectors(self) -> None:
        """Readback helper의 identity/path는 runtime env와 Git cwd만 소유합니다."""
        parser = monitor_runtime_readback.MonitorRuntimeReadbackApplication().parser()
        base = (
            "--repo",
            "E5presso/neurath",
            "--pr-number",
            "131",
            "--workflow-id",
            "process-ticket-131",
            "--runtime-id",
            "runtime-a",
            "--resume-adapter",
            "command",
            "--minimum-heartbeat-at-epoch",
            "100",
        )

        for option in ("--state-path", "--worktree", "--thread-id", "--process-state-path"):
            with (
                self.subTest(option=option),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args((*base, option, "/tmp/foreign"))

    def _resources(self, worktree: Path) -> MonitorRuntimeResourcesView:
        worktree.mkdir(exist_ok=True)
        subprocess.run(("git", "init", "-q", str(worktree)), check=True)
        return cast(
            MonitorRuntimeResourcesView,
            monitor_runtime_readback.MonitorRuntimeResources.resolve(
                cwd=worktree,
                environment={"CODEX_THREAD_ID": "owner-thread"},
            ),
        )

    def _state(
        self,
        resources: MonitorRuntimeResourcesView,
        *,
        heartbeat: float,
    ) -> dict[str, object]:
        return {
            "schema_version": 4,
            "provider": "local-pr-monitor",
            "repo": "E5presso/neurath",
            "pr_number": 131,
            "thread_id": "owner-thread",
            "session_id": "owner-thread",
            "workflow_id": "process-ticket-131",
            "runtime_id": "runtime-a",
            "worktree_id": resources.worktree_id,
            "resume_adapter": "command",
            "pid": os.getpid(),
            "heartbeat_at_epoch": heartbeat,
            "poll_interval_seconds": 30,
            "last_observed": {"headRefOid": "abc123"},
        }

    def _expected(self, *, minimum_heartbeat: float) -> object:
        return monitor_runtime_readback.ExpectedMonitorRuntime(
            repo="E5presso/neurath",
            pr_number=131,
            workflow_id="process-ticket-131",
            runtime_id="runtime-a",
            resume_adapter="command",
            pid=os.getpid(),
            manager_pid=None,
            minimum_heartbeat_at_epoch=minimum_heartbeat,
            poll_interval_seconds=30,
        )
