"""Process-local monitor observation cache의 file boundary 회귀 테스트입니다."""

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
STORE_PATH = ROOT / ".agents/skills/monitor-pr/scripts/monitor_observation_store.py"
SPEC = importlib.util.spec_from_file_location("monitor_observation_store", STORE_PATH)
assert SPEC is not None and SPEC.loader is not None
monitor_observation_store = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor_observation_store
SPEC.loader.exec_module(monitor_observation_store)


class MonitorObservationStoreTest(TestCase):
    """Local cache가 canonical state helper 없이 atomic object IO만 제공하는지 검증합니다."""

    def test_round_trips_one_observation_object(self) -> None:
        """Atomic replacement 뒤 같은 JSON object를 읽습니다."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".monitor-pr/monitor-state.json"
            store = monitor_observation_store.MonitorObservationStore(path)

            store.write({"runtime_id": "runtime-a", "last_observed": {"head": "abc"}})

            self.assertEqual(
                {"runtime_id": "runtime-a", "last_observed": {"head": "abc"}},
                store.read(),
            )

    def test_rejects_non_object_cache_payload(self) -> None:
        """Observation cache root가 JSON object가 아니면 fail closed합니다."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".monitor-pr/monitor-state.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(["invalid"]), encoding="utf-8")
            store = monitor_observation_store.MonitorObservationStore(path)

            with self.assertRaisesRegex(TypeError, "JSON object"):
                store.read()
