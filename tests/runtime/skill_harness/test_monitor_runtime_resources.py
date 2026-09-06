"""Monitor helper가 runtime env와 Git cwd에서 resource를 파생하는 회귀 테스트입니다."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
RESOURCE_PATH = ROOT / ".agents/skills/monitor-pr/scripts/monitor_runtime_resources.py"
SPEC = importlib.util.spec_from_file_location("monitor_runtime_resources", RESOURCE_PATH)
assert SPEC is not None and SPEC.loader is not None
monitor_runtime_resources = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor_runtime_resources
SPEC.loader.exec_module(monitor_runtime_resources)


class MonitorRuntimeResourcesTest(TestCase):
    """Public path selector 없이 exact runtime resource handle을 구성하는지 검증합니다."""

    def test_resolves_session_and_worktree_from_runtime_owned_inputs(self) -> None:
        """Nested cwd도 canonical Git top-level과 opaque worktree ID로 수렴합니다."""
        with TemporaryDirectory() as directory:
            worktree = Path(directory) / "worktree"
            nested = worktree / "nested"
            nested.mkdir(parents=True)
            subprocess.run(("git", "init", "-q", str(worktree)), check=True)

            resources = monitor_runtime_resources.MonitorRuntimeResources.resolve(
                cwd=nested,
                environment={"CODEX_THREAD_ID": "owner-thread"},
            )

        self.assertEqual("owner-thread", resources.session_id)
        self.assertEqual(worktree.resolve(), resources.worktree)
        self.assertEqual(
            "monitor-observation-cache",
            resources.observation_resource()["kind"],
        )
        self.assertNotIn(str(worktree), resources.observation_resource().values())

    def test_rejects_path_traversal_in_launch_label(self) -> None:
        """Runtime-derived directory 밖으로 plist resource를 만들 수 없습니다."""
        with TemporaryDirectory() as directory:
            worktree = Path(directory) / "worktree"
            worktree.mkdir()
            subprocess.run(("git", "init", "-q", str(worktree)), check=True)
            resources = monitor_runtime_resources.MonitorRuntimeResources.resolve(
                cwd=worktree,
                environment={"CODEX_THREAD_ID": "owner-thread"},
            )

            with self.assertRaisesRegex(ValueError, "label"):
                resources.launch_plist_path("../foreign")
