"""Versioned outer-service records, isolated from Task/phase progress ownership."""

import sqlite3
from hashlib import sha256
from pathlib import Path

from neurath.core.codec import encode
from neurath.core.domain import require
from neurath.core.store import Store
from neurath.project_paths import control_root


class StateSnapshot(dict):
    def __init__(self, value, revision, origin):
        super().__init__(value)
        self.revision = revision
        self.origin = origin


class LocalState:
    def __init__(self, root, namespace, legacy_path, decode, default):
        self.root = control_root(Path(root))
        self.namespace = namespace
        self.legacy = Path(legacy_path)
        self.key = self.legacy.relative_to(self.root).as_posix()
        self.kind = "service:" + namespace
        self.decode = decode
        self.default = default

    def _legacy(self):
        require(
            not self.legacy.is_symlink() and not self.legacy.parent.is_symlink(),
            "unsafe-service-source",
        )
        raw = self.legacy.read_bytes() if self.legacy.is_file() else None
        state = self.root / ".neurath/local/runtime.sqlite3"
        require(not state.is_symlink(), "unsafe-service-source")
        previous = None
        if state.is_file():
            old = sqlite3.connect(state.as_uri() + "?mode=ro", uri=True)
            old.row_factory = sqlite3.Row
            try:
                if old.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='runtime_records'"
                ).fetchone():
                    row = old.execute(
                        "SELECT payload,digest,legacy_path,legacy_digest FROM runtime_records WHERE namespace=? AND key=?",
                        (self.namespace, self.key),
                    ).fetchone()
                    if row is not None:
                        data = bytes(row["payload"])
                        require(sha256(data).hexdigest() == row["digest"], "service-source-corrupt")
                        if row["legacy_path"] is not None:
                            require(
                                Path(row["legacy_path"]) == self.legacy
                                and raw is not None
                                and sha256(raw).hexdigest() == row["legacy_digest"],
                                "service-source-changed",
                            )
                        elif raw is not None:
                            require(False, "service-source-changed")
                        previous = data
            finally:
                old.close()
        return previous if previous is not None else raw, {
            "json_digest": None if raw is None else sha256(raw).hexdigest(),
            "runtime_digest": None if previous is None else sha256(previous).hexdigest(),
        }

    def _database(self, create=False):
        if not create and not any(
            path.exists()
            for path in (
                self.root / ".neurath/local/core.sqlite3",
                self.root / ".neurath/local/runtime.sqlite3",
                self.legacy,
            )
        ):
            return None
        return Store(self.root)

    def read(self):
        store = self._database()
        if store is None:
            return StateSnapshot(self.default(), 0, {"json_digest": None, "runtime_digest": None})
        raw, origin = self._legacy()
        with store.transaction() as tx:
            record = tx.record(self.kind, self.key)
            guard = tx.record(self.kind + ":origin", self.key)
            if guard:
                require(guard["value"] == origin, "service-source-changed")
            if record is None and raw is not None:
                value = self.decode(raw)
                revision = tx.put_record(self.kind, self.key, value)
                tx.put_record(self.kind + ":origin", self.key, origin)
                return StateSnapshot(value, revision, origin)
            if record is None:
                return StateSnapshot(self.default(), 0, origin)
            return StateSnapshot(
                self.decode(encode(record["value"]).encode()), record["revision"], origin
            )

    def save(self, state):
        require(isinstance(state, StateSnapshot), "service-snapshot-required")
        raw = encode(dict(state)).encode()
        value = self.decode(raw)
        _, origin = self._legacy()
        require(state.origin == origin, "service-source-changed")
        with self._database(create=True).transaction() as tx:
            guard = tx.record(self.kind + ":origin", self.key)
            if guard:
                require(guard["value"] == origin, "service-source-changed")
            else:
                tx.put_record(self.kind + ":origin", self.key, origin)
            revision = tx.put_record(self.kind, self.key, value, state.revision)
        state.revision = revision
