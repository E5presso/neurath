"""Common SQLite monitor observation and event store regression tests."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
STORE_PATH = ROOT / ".agents/skills/monitor-pr/scripts/monitor_observation_store.py"
SPEC = importlib.util.spec_from_file_location(
    "monitor_observation_store", STORE_PATH
)
assert SPEC is not None and SPEC.loader is not None
monitor_observation_store = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor_observation_store
SPEC.loader.exec_module(monitor_observation_store)


class MonitorObservationStoreTest(TestCase):
    def repository(self, directory):
        root = Path(directory)
        subprocess.run(("git", "init", "-q", str(root)), check=True)
        return root

    def test_round_trips_without_runtime_json(self):
        with TemporaryDirectory() as directory:
            root = self.repository(directory)
            path = root / ".monitor-pr/monitor-state.json"
            store = monitor_observation_store.MonitorObservationStore(path)
            expected = {
                "runtime_id": "runtime-a",
                "last_observed": {"head": "abc"},
            }
            store.write(expected)
            self.assertEqual(expected, store.read())
            self.assertFalse(path.exists())

    def test_invalid_legacy_object_fails_without_deleting_source(self):
        with TemporaryDirectory() as directory:
            root = self.repository(directory)
            path = root / ".monitor-pr/monitor-state.json"
            path.parent.mkdir(parents=True)
            original = json.dumps(["invalid"]).encode()
            path.write_bytes(original)
            store = monitor_observation_store.MonitorObservationStore(path)
            with self.assertRaisesRegex(TypeError, "JSON object"):
                store.read()
            self.assertEqual(original, path.read_bytes())

    def test_imports_observation_and_event_once(self):
        with TemporaryDirectory() as directory:
            root = self.repository(directory)
            path = root / ".monitor-pr/monitor-state.json"
            event = path.parent / "events/one.json"
            event.parent.mkdir(parents=True)
            path.write_text(json.dumps({"runtime_id": "old"}))
            event.write_text(json.dumps({"reason": "ci-failed"}))
            store = monitor_observation_store.MonitorObservationStore(path)
            self.assertEqual({"runtime_id": "old"}, store.read())
            self.assertFalse(path.exists())
            self.assertFalse(event.exists())
            database = root / ".neurath/local/runtime.sqlite3"
            with sqlite3.connect(database) as db:
                self.assertEqual(
                    1,
                    db.execute(
                        "SELECT count(*) FROM monitor_observations"
                    ).fetchone()[0],
                )
                self.assertEqual(
                    1,
                    db.execute(
                        "SELECT count(*) FROM monitor_runtime_events"
                    ).fetchone()[0],
                )
                self.assertEqual(
                    2,
                    db.execute(
                        "SELECT count(*) FROM monitor_runtime_legacy_files "
                        "WHERE status='removed'"
                    ).fetchone()[0],
                )

    def test_concurrent_cutover_has_one_canonical_row(self):
        with TemporaryDirectory() as directory:
            root = self.repository(directory)
            path = root / ".monitor-pr/monitor-state.json"
            path.parent.mkdir(parents=True)
            expected = {"runtime_id": "old"}
            path.write_text(json.dumps(expected))

            def read_one(_):
                return monitor_observation_store.MonitorObservationStore(
                    path
                ).read()

            with ThreadPoolExecutor(max_workers=2) as workers:
                self.assertEqual(
                    [expected, expected],
                    list(workers.map(read_one, range(2))),
                )
            with sqlite3.connect(
                root / ".neurath/local/runtime.sqlite3"
            ) as db:
                self.assertEqual(
                    1,
                    db.execute(
                        "SELECT count(*) FROM monitor_observations"
                    ).fetchone()[0],
                )

    def test_symlink_event_directory_is_not_followed(self):
        with TemporaryDirectory() as directory:
            root = self.repository(directory)
            outside = root / "outside-events"
            outside.mkdir()
            external = outside / "one.json"
            external.write_text(json.dumps({"reason": "keep"}))
            state = root / ".monitor-pr"
            state.mkdir()
            (state / "events").symlink_to(outside, target_is_directory=True)
            store = monitor_observation_store.MonitorObservationStore(
                state / "monitor-state.json"
            )
            with self.assertRaisesRegex(ValueError, "event directory"):
                store.read()
            self.assertTrue(external.exists())
