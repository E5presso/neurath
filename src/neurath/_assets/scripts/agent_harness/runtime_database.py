"""Project SQLite transactions shared by standalone and packaged runtime owners.

This layer stores bytes and revisions. Domain codecs and reducers retain authority
over their contents. Legacy imports are guarded staging records: installation must
fence old writers before cutover; an import alone never certifies that cutover.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .sqlite_migration import (
    LegacyStateChanged, LegacyTableCollision as LegacyTableCollision, full_revalidate, initial_migrate,
    locked_sources, migration_lock, source_stats, tracking_exists, verify_stats,
)
_CONNECTIONS = ContextVar("neurath_runtime_connections", default=None)


class RuntimeConnection(sqlite3.Connection):
    """One transaction's deferred notifications and nested savepoint sequence."""

    after_commit: dict
    notices: list
    savepoint_sequence: int


class RecordConflict(ValueError):
    """The caller's revision no longer names the current record."""


class CorruptRecord(ValueError):
    """Stored bytes or their metadata failed integrity validation."""


@dataclass(frozen=True)
class StoredRecord:
    revision: int
    payload: bytes


def _identity(namespace: str, key: str) -> None:
    for value in (namespace, key):
        if not isinstance(value, str) or not value or len(value.encode()) > 4096 or "\0" in value:
            raise ValueError("runtime records require bounded namespace and key")


def _revision(value: int) -> None:
    if type(value) is not int or not 0 <= value < 2**63 - 1:
        raise ValueError("record revision must be a nonnegative SQLite integer")


def _bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise ValueError("runtime payload must be bytes")
    return hashlib.sha256(value).hexdigest()


class RuntimeTransaction:
    """One connection boundary for related domain records and tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get(self, namespace: str, key: str) -> StoredRecord | None:
        _identity(namespace, key)
        row = self.connection.execute(
            "SELECT revision,payload,digest,legacy_path,legacy_digest FROM runtime_records "
            "WHERE namespace=? AND key=?", (namespace, key)
        ).fetchone()
        if row is None:
            return None
        revision, payload, digest, legacy_path, legacy_digest = row
        try:
            _revision(revision)
            if _bytes(payload) != digest:
                raise ValueError("digest mismatch")
        except ValueError as error:
            raise CorruptRecord("runtime record integrity mismatch") from error
        if legacy_path is not None:
            path = Path(legacy_path)
            try:
                if path.is_symlink() or _bytes(path.read_bytes()) != legacy_digest:
                    raise LegacyStateChanged("imported legacy state changed")
            except OSError as error:
                raise LegacyStateChanged("imported legacy state is unavailable") from error
        return StoredRecord(revision, payload)

    def put(self, namespace: str, key: str, payload: bytes, *,
            expected_revision: int | None) -> StoredRecord:
        _identity(namespace, key)
        digest = _bytes(payload)
        if expected_revision is not None:
            _revision(expected_revision)
        old = self.get(namespace, key)
        if old is None and self.was_deleted(namespace, key):
            raise RecordConflict("collected runtime identity cannot be reused")
        actual = None if old is None else old.revision
        if actual != expected_revision:
            raise RecordConflict(f"expected revision {expected_revision}, got {actual}")
        revision = 0 if old is None else old.revision + 1
        _revision(revision)
        self.connection.execute(
            "INSERT INTO runtime_records(namespace,key,revision,payload,digest,updated) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(namespace,key) DO UPDATE SET revision=excluded.revision, "
            "payload=excluded.payload,digest=excluded.digest,updated=excluded.updated",
            (namespace, key, revision, payload, digest, time.time()),
        )
        return StoredRecord(revision, payload)

    def was_deleted(self, namespace: str, key: str) -> bool:
        _identity(namespace, key)
        return self.connection.execute(
            "SELECT 1 FROM runtime_tombstones WHERE namespace=? AND key=?", (namespace, key)
        ).fetchone() is not None

    def delete(self, namespace: str, key: str, *, expected_revision: int) -> None:
        _revision(expected_revision)
        old = self.get(namespace, key)
        if old is None or old.revision != expected_revision:
            raise RecordConflict("collected record revision changed")
        self.connection.execute("INSERT INTO runtime_tombstones VALUES(?,?,?)",
                                (namespace, key, expected_revision))
        self.connection.execute("DELETE FROM runtime_records WHERE namespace=? AND key=?",
                                (namespace, key))


class RuntimeDatabase:
    """Use a caller-resolved common project root, independent of host environment."""

    def __init__(self, control_root: Path) -> None:
        root = Path(control_root).absolute()
        self.root = root
        if not root.is_dir():
            raise ValueError("runtime control root must exist")
        directory = root
        for part in (".neurath", "local"):
            directory /= part
            if directory.is_symlink():
                raise ValueError("runtime database directory must not be a symlink")
            directory.mkdir(exist_ok=True, mode=0o700)
        self.path = directory / "runtime.sqlite3"
        self._check_paths()
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        key = str(self.path.resolve())
        if key not in (_CONNECTIONS.get() or {}):
            self._initialize()

    def _open(self):
        db = sqlite3.connect(
            self.path, timeout=20, isolation_level=None, factory=RuntimeConnection)
        db.row_factory = sqlite3.Row
        db.after_commit, db.notices, db.savepoint_sequence = {}, [], 0
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _initialize(self):
        with migration_lock(self.root):
            db = self._open()
            try:
                db.execute("BEGIN IMMEDIATE")
                self._create_schema(db)
                if tracking_exists(db):
                    verify_stats(db, source_stats(self.root))
                    db.commit()
                else:
                    db.execute("PRAGMA defer_foreign_keys=ON")
                    with locked_sources(self.root) as (sources, stats):
                        initial_migrate(db, sources, stats)
                        if db.execute("PRAGMA foreign_key_check").fetchone():
                            raise ValueError("legacy SQLite foreign key check failed")
                        db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def _create_schema(db):
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime_tombstones (namespace TEXT NOT NULL,"
                "key TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(namespace,key))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime_records ("
                "namespace TEXT NOT NULL,key TEXT NOT NULL,revision INTEGER NOT NULL "
                "CHECK(revision>=0),payload BLOB NOT NULL,digest TEXT NOT NULL,"
                "legacy_path TEXT,legacy_digest TEXT,updated REAL NOT NULL DEFAULT 0,"
                "PRIMARY KEY(namespace,key),"
                "CHECK((legacy_path IS NULL)=(legacy_digest IS NULL)))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime_schema (component TEXT PRIMARY KEY,"
                "version INTEGER NOT NULL CHECK(version>0))"
            )
            version = db.execute(
                "SELECT version FROM runtime_schema WHERE component='records'"
            ).fetchone()
            if version is not None and version[0] != 1:
                raise ValueError("unsupported runtime records schema")
            db.execute("INSERT OR IGNORE INTO runtime_schema VALUES('records',1)")

    def _check_paths(self) -> None:
        if any(Path(str(self.path) + suffix).is_symlink()
               for suffix in ("", "-journal", "-wal", "-shm")):
            raise ValueError("runtime database or journal must not be a symlink")

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            yield RuntimeTransaction(db)

    @contextmanager
    def connection(self):
        """Synchronous nested domain stores share one atomic connection.

        Nested failures roll back their savepoint and deferred notifications.
        Only the outer boundary commits and dispatches after-commit callbacks.
        Do not suspend an async task while holding this synchronous transaction.
        """
        self._check_paths()
        key = str(self.path.resolve())
        current = _CONNECTIONS.get() or {}
        if key in current:
            db = current[key]
            db.savepoint_sequence += 1
            name = f"neurath_nested_{db.savepoint_sequence}"
            callbacks, notice_count = dict(db.after_commit), len(db.notices)
            db.execute(f"SAVEPOINT {name}")
            try:
                yield db
                db.execute(f"RELEASE SAVEPOINT {name}")
            except BaseException:
                db.execute(f"ROLLBACK TO SAVEPOINT {name}")
                db.execute(f"RELEASE SAVEPOINT {name}")
                db.after_commit = callbacks
                del db.notices[notice_count:]
                raise
            return
        callbacks = ()
        with migration_lock(self.root):
            before = source_stats(self.root)
            db = self._open()
            token = _CONNECTIONS.set({**current, key: db})
            try:
                db.execute("BEGIN IMMEDIATE")
                verify_stats(db, before)
                yield db
                verify_stats(db, source_stats(self.root))
                db.commit()
                callbacks = tuple(db.after_commit.values())
            except BaseException:
                db.rollback()
                raise
            finally:
                _CONNECTIONS.reset(token)
                db.close()
        for callback in callbacks:
            callback()

    def revalidate_legacy(self):
        """Explicitly accept metadata-only drift after a full logical comparison."""
        key = str(self.path.resolve())
        if key in (_CONNECTIONS.get() or {}):
            raise ValueError("legacy revalidation requires an outer transaction boundary")
        with migration_lock(self.root):
            with locked_sources(self.root) as (sources, stats):
                db = self._open()
                try:
                    db.execute("BEGIN IMMEDIATE")
                    full_revalidate(db, sources, stats)
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                finally:
                    db.close()

    def import_legacy(self, namespace: str, key: str, path: Path, validate) -> StoredRecord:
        """Stage validated bytes with their original revision and drift guard.

        Callers provide the existing strict domain decoder, returning its revision.
        The legacy lock order is preserved during copying. Deployment remains
        responsible for fencing old readers/writers before activating DB adapters.
        """
        _identity(namespace, key)
        path = Path(path).absolute()
        lock_path = path.with_name(path.name + ".lock")
        if path.is_symlink() or lock_path.is_symlink():
            raise ValueError("legacy state or lock must not be a symlink")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            payload = path.read_bytes()
            revision = validate(payload)
            _revision(revision)
            digest = _bytes(payload)
            with self.transaction() as tx:
                if tx.was_deleted(namespace, key):
                    raise RecordConflict("collected legacy identity cannot be imported again")
                old = tx.get(namespace, key)
                if old is not None:
                    source = tx.connection.execute(
                        "SELECT legacy_path,legacy_digest FROM runtime_records "
                        "WHERE namespace=? AND key=?", (namespace, key)
                    ).fetchone()
                    if tuple(source) != (str(path), digest):
                        raise RecordConflict("legacy import conflicts with existing record")
                    return old
                tx.connection.execute(
                    "INSERT INTO runtime_records VALUES(?,?,?,?,?,?,?,?)",
                    (namespace, key, revision, payload, digest, str(path), digest, path.stat().st_mtime),
                )
                return StoredRecord(revision, payload)
