"""Versioned local service records; file locks retain service-level I/O ordering."""
from pathlib import Path

from neurath.memory.store import canonical, control_root
from neurath.runtime.database import RuntimeDatabase, LegacyStateChanged


class StateSnapshot(dict):
    """Carry the exact revision read without adding metadata to public payloads."""

    def __init__(self, value, revision):
        super().__init__(value)
        self.revision = revision


class LocalState:
    def __init__(self, root, namespace, legacy_path, decode, default):
        self.root = control_root(Path(root))
        self.namespace = namespace
        self.legacy = Path(legacy_path)
        # Reporting is common-project scoped; release choices use each Git
        # worktree's private directory. Preserve both identities in one DB.
        self.key = self.legacy.relative_to(self.root).as_posix()
        self.decode = decode
        self.default = default

    def _database(self, *, create=False):
        if self.legacy.is_symlink() or self.legacy.parent.is_symlink():
            raise ValueError("local state must not be a symlink")
        path = self.root / ".neurath/local/runtime.sqlite3"
        if not create and not path.exists() and not self.legacy.exists():
            return None
        return RuntimeDatabase(self.root)

    def read(self):
        store = self._database()
        if store is None:
            return StateSnapshot(self.default(), None)
        with store.transaction() as tx:
            record = tx.get(self.namespace, self.key)
            if record is not None and self.legacy.exists():
                source = tx.connection.execute("SELECT legacy_path FROM runtime_records WHERE namespace=? AND key=?",
                                               (self.namespace, self.key)).fetchone()[0]
                if source is None:
                    raise LegacyStateChanged("legacy JSON appeared after canonical state creation")
        if record is None and self.legacy.exists():
            def validate(raw):
                self.decode(raw)
                return 0
            record = store.import_legacy(self.namespace, self.key, self.legacy, validate)
        if record is None:
            return StateSnapshot(self.default(), None)
        return StateSnapshot(self.decode(record.payload), record.revision)

    def save(self, state):
        if not isinstance(state, StateSnapshot):
            raise ValueError("local state update requires its versioned snapshot")
        raw = canonical(state).encode()
        self.decode(raw)
        with self._database(create=True).transaction() as tx:
            record = tx.put(self.namespace, self.key, raw, expected_revision=state.revision)
        state.revision = record.revision
