"""Common SQLite owner for monitor observations and local event history."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import SessionLocator


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _object(value, label):
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must contain a JSON object")
    return dict(value)


class MonitorObservationStore:
    """One Git worktree's mutable observation and append-only event rows."""

    def __init__(self, legacy_path: Path) -> None:
        path = Path(legacy_path).absolute()
        worktree = path.parent.parent
        expected = worktree / ".monitor-pr/monitor-state.json"
        if path != expected or worktree.is_symlink() or not worktree.is_dir():
            raise ValueError("monitor observation path is not canonical")
        locator = SessionLocator.from_worktree(worktree)
        self._worktree = str(worktree.resolve())
        self._legacy_path = path
        self._event_directory = path.parent / "events"
        self._database = RuntimeDatabase(locator.control_root)
        self._lock_path = (
            locator.control_root
            / ".neurath/local/monitor-observation-cutover.lock"
        )
        with self._database.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS monitor_observations(
                worktree TEXT PRIMARY KEY,payload TEXT NOT NULL,
                updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS monitor_runtime_events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                worktree TEXT NOT NULL,payload TEXT NOT NULL,
                created REAL NOT NULL,legacy_path TEXT UNIQUE)""")
            db.execute("""CREATE TABLE IF NOT EXISTS monitor_runtime_legacy_files(
                worktree TEXT NOT NULL,path TEXT NOT NULL,digest TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('observation','event')),
                status TEXT NOT NULL CHECK(status IN ('pending','removed')),
                PRIMARY KEY(worktree,path))""")
            db.execute("""CREATE TABLE IF NOT EXISTS monitor_runtime_cutovers(
                worktree TEXT PRIMARY KEY,version INTEGER NOT NULL CHECK(version=1))""")

    def _legacy_kind(self, path):
        if path == self._legacy_path:
            return "observation"
        if (path.parent == self._event_directory and path.suffix == ".json"
                and path.name not in {"", ".", ".."}):
            return "event"
        raise ValueError("legacy monitor runtime path has invalid scope")

    def _check_legacy_file(self, path, *, may_be_missing=False):
        self._legacy_kind(path)
        current = path
        state_root = self._legacy_path.parent
        while current != state_root:
            if current.is_symlink():
                raise ValueError("legacy monitor runtime uses a symlink ancestor")
            current = current.parent
        if state_root.is_symlink():
            raise ValueError("monitor runtime directory must not be a symlink")
        if not path.exists() and may_be_missing:
            return
        if not path.is_file():
            raise FileNotFoundError("legacy monitor runtime file is missing")

    def _cutover(self):
        if self._lock_path.is_symlink():
            raise ValueError("monitor observation cutover lock must not be a symlink")
        descriptor = os.open(
            self._lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (self._event_directory.exists() or self._event_directory.is_symlink()) and (
                    self._event_directory.is_symlink()
                    or not self._event_directory.is_dir()):
                raise ValueError("legacy monitor event directory is invalid")
            if self._legacy_path.is_symlink() or self._legacy_path.parent.is_symlink():
                raise ValueError("legacy monitor runtime uses a symlink ancestor")
            paths = ([self._legacy_path] if self._legacy_path.is_file() else []) + (
                sorted(self._event_directory.glob("*.json"))
                if self._event_directory.is_dir() else [])
            documents = {}
            for path in paths:
                self._check_legacy_file(path)
                data = path.read_bytes()
                try:
                    payload = _object(
                        json.loads(data), "monitor observation"
                        if path == self._legacy_path else "monitor runtime event")
                except (UnicodeError, json.JSONDecodeError):
                    raise
                documents[str(path)] = (
                    self._legacy_kind(path),
                    hashlib.sha256(data).hexdigest(),
                    payload,
                )
            with self._database.connection() as db:
                tracked = {
                    row["path"]: row
                    for row in db.execute(
                        "SELECT * FROM monitor_runtime_legacy_files "
                        "WHERE worktree=?", (self._worktree,))
                }
                cutover = db.execute(
                    "SELECT 1 FROM monitor_runtime_cutovers WHERE worktree=?",
                    (self._worktree,),
                ).fetchone() is not None
                for name, (kind, digest, payload) in documents.items():
                    previous = tracked.get(name)
                    if previous is not None:
                        if (previous["status"] == "removed"
                                or previous["digest"] != digest
                                or previous["kind"] != kind):
                            raise ValueError(
                                "legacy monitor runtime reappeared or changed")
                        continue
                    if cutover:
                        raise ValueError(
                            "legacy monitor runtime appeared after SQLite cutover")
                    encoded = _canonical(payload)
                    if kind == "observation":
                        current = db.execute(
                            "SELECT payload FROM monitor_observations "
                            "WHERE worktree=?", (self._worktree,)
                        ).fetchone()
                        if current is not None and current["payload"] != encoded:
                            raise ValueError(
                                "legacy monitor observation collides with SQLite")
                        db.execute(
                            "INSERT OR IGNORE INTO monitor_observations "
                            "VALUES(?,?,?)",
                            (self._worktree, encoded, time.time()))
                    else:
                        current = db.execute(
                            "SELECT payload FROM monitor_runtime_events "
                            "WHERE legacy_path=?", (name,)
                        ).fetchone()
                        if current is not None and current["payload"] != encoded:
                            raise ValueError(
                                "legacy monitor event collides with SQLite")
                        db.execute(
                            "INSERT OR IGNORE INTO monitor_runtime_events"
                            "(worktree,payload,created,legacy_path) VALUES(?,?,?,?)",
                            (self._worktree, encoded, Path(name).stat().st_mtime, name))
                    db.execute(
                        "INSERT INTO monitor_runtime_legacy_files "
                        "VALUES(?,?,?,?,?)",
                        (self._worktree, name, digest, kind, "pending"))
                db.execute(
                    "INSERT OR IGNORE INTO monitor_runtime_cutovers VALUES(?,1)",
                    (self._worktree,))
                pending = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM monitor_runtime_legacy_files "
                        "WHERE worktree=? AND status='pending'",
                        (self._worktree,))
                ]
            for row in pending:
                path = Path(row["path"])
                if self._legacy_kind(path) != row["kind"]:
                    raise ValueError("pending monitor runtime path kind changed")
                self._check_legacy_file(path, may_be_missing=True)
                if path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != row["digest"]:
                        raise ValueError(
                            "legacy monitor runtime changed before removal")
                    path.unlink()
            with self._database.connection() as db:
                db.execute(
                    "UPDATE monitor_runtime_legacy_files SET status='removed' "
                    "WHERE worktree=? AND status='pending'", (self._worktree,))

    def exists(self):
        self._cutover()
        with self._database.connection() as db:
            return db.execute(
                "SELECT 1 FROM monitor_observations WHERE worktree=?",
                (self._worktree,)).fetchone() is not None

    def read(self):
        self._cutover()
        with self._database.connection() as db:
            row = db.execute(
                "SELECT payload FROM monitor_observations WHERE worktree=?",
                (self._worktree,)).fetchone()
        return {} if row is None else _object(
            json.loads(row["payload"]), "monitor observation")

    def read_required(self):
        self._cutover()
        with self._database.connection() as db:
            row = db.execute(
                "SELECT payload FROM monitor_observations WHERE worktree=?",
                (self._worktree,)).fetchone()
        if row is None:
            raise FileNotFoundError("monitor observation is missing")
        return _object(json.loads(row["payload"]), "monitor observation")

    def write(self, payload: Mapping[str, object]):
        self._cutover()
        encoded = _canonical(_object(payload, "monitor observation"))
        with self._database.connection() as db:
            db.execute("""INSERT INTO monitor_observations VALUES(?,?,?)
                ON CONFLICT(worktree) DO UPDATE SET payload=excluded.payload,
                updated=excluded.updated""",
                (self._worktree, encoded, time.time()))

    def write_if_absent(self, payload: Mapping[str, object]):
        self._cutover()
        encoded = _canonical(_object(payload, "monitor observation"))
        with self._database.connection() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO monitor_observations VALUES(?,?,?)",
                (self._worktree, encoded, time.time()))
            return cursor.rowcount == 1

    def append_event(self, payload: Mapping[str, object]):
        self._cutover()
        encoded = _canonical(_object(payload, "monitor runtime event"))
        with self._database.connection() as db:
            cursor = db.execute(
                "INSERT INTO monitor_runtime_events"
                "(worktree,payload,created,legacy_path) VALUES(?,?,?,NULL)",
                (self._worktree, encoded, time.time()))
            return cursor.lastrowid
