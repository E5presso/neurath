"""Guarded import of the four pre-runtime SQLite authorities."""
from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

LEGACY_DATABASES = (
    ("memory", Path(".neurath/local/memory/project.sqlite3")),
    ("messages", Path(".neurath/local/agents/messages.sqlite3")),
    ("model-plans", Path(".neurath/local/models/plans.sqlite3")),
    ("maintenance", Path(".neurath/local/maintenance/calls.sqlite3")),
)


class LegacyStateChanged(ValueError):
    """A retained recovery database disappeared or changed after import."""


class LegacyTableCollision(ValueError):
    """Two authorities claim the same SQLite schema object."""


@dataclass(frozen=True)
class LegacyStat:
    component: str
    path: Path
    presence: str
    token: str


@dataclass(frozen=True)
class LegacySource:
    stat: LegacyStat
    connection: sqlite3.Connection
    digest: str


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _safe(root, path):
    current = path.parent
    while current != root:
        if current.is_symlink() or root not in current.parents:
            raise ValueError("legacy database escaped the runtime root")
        current = current.parent


def _stat_token(root, path):
    _safe(root, path)
    values = []
    for suffix in ("", "-wal", "-journal"):
        candidate = Path(str(path) + suffix)
        try:
            stat = candidate.lstat()
        except FileNotFoundError:
            values.append((suffix, None))
            continue
        if candidate.is_symlink():
            raise ValueError("legacy database paths must not be symlinks")
        values.append((suffix, stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size,
                       stat.st_mtime_ns, stat.st_ctime_ns))
    return hashlib.sha256(repr(values).encode()).hexdigest()


def source_stats(root):
    root = Path(root).resolve()
    return tuple(
        LegacyStat(component, root / relative,
                   "present" if (root / relative).is_file() else "absent",
                   _stat_token(root, root / relative))
        for component, relative in LEGACY_DATABASES
    )


@contextmanager
def migration_lock(root):
    path = Path(root) / ".neurath/local/runtime-migration.lock"
    if path.is_symlink():
        raise ValueError("runtime migration lock must not be a symlink")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _feed(digest, value):
    if value is None:
        tag, payload = b"n", b""
    elif type(value) is int:
        tag, payload = b"i", str(value).encode()
    elif type(value) is float:
        tag, payload = b"f", struct.pack("!d", value)
    elif isinstance(value, str):
        tag, payload = b"t", value.encode()
    elif isinstance(value, bytes):
        tag, payload = b"b", value
    else:
        raise ValueError("unsupported legacy SQLite value")
    digest.update(tag + len(payload).to_bytes(8, "big") + payload)


def _schema(db):
    rows = db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    if any(row["type"] not in {"table", "index", "view", "trigger"}
           or row["sql"] is None for row in rows):
        raise ValueError("unknown legacy SQLite schema object")
    return rows


def _columns(db, table):
    return db.execute(f"PRAGMA table_xinfo({_quote(table)})").fetchall()


def _rows(db, table, sql, insertable=False):
    columns = _columns(db, table)
    selected = [row["name"] for row in columns if not insertable or row["hidden"] == 0]
    names = {row["name"].casefold() for row in columns}
    rowid = None if "WITHOUT ROWID" in sql.upper() else next(
        (name for name in ("rowid", "_rowid_", "oid") if name not in names), None)
    primary = [row["name"] for row in sorted(columns, key=lambda row: row["pk"]) if row["pk"]]
    projection = ([rowid] if rowid else []) + [_quote(name) for name in selected]
    order = [rowid] if rowid else primary or selected
    statement = "SELECT " + ",".join(projection) + " FROM " + _quote(table)
    if order:
        statement += " ORDER BY " + ",".join(_quote(name) for name in order)
    return db.execute(statement), selected, rowid


def fingerprint(db):
    digest = hashlib.sha256()
    schemas = _schema(db)
    for value in (db.execute("PRAGMA application_id").fetchone()[0],
                  db.execute("PRAGMA user_version").fetchone()[0]):
        _feed(digest, value)
    for schema in schemas:
        for value in schema:
            _feed(digest, value)
    for schema in (row for row in schemas if row["type"] == "table"):
        cursor, _, _ = _rows(db, schema["name"], schema["sql"])
        for row in cursor:
            for value in row:
                _feed(digest, value)
    if db.execute("SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'").fetchone():
        for row in db.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name"):
            _feed(digest, row["name"])
            _feed(digest, row["seq"])
    return digest.hexdigest()


@contextmanager
def locked_sources(root):
    opened = []
    try:
        for stat in source_stats(root):
            if stat.presence == "absent":
                continue
            db = sqlite3.connect(stat.path, timeout=20, isolation_level=None)
            db.row_factory = sqlite3.Row
            # Closing our read-only-in-intent migration connection must not
            # checkpoint or remove the WAL after its guard token is committed.
            db.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
            db.execute("BEGIN IMMEDIATE")
            opened.append((stat.component, db))
        guarded = source_stats(root)
        if {stat.component for stat in guarded if stat.presence == "present"} != {
                component for component, _ in opened}:
            raise LegacyStateChanged("legacy database presence changed during migration")
        by_component = {stat.component: stat for stat in guarded}
        sources = tuple(LegacySource(by_component[component], db, fingerprint(db))
                        for component, db in opened)
        if source_stats(root) != guarded:
            raise LegacyStateChanged("legacy database changed during migration")
        yield sources, guarded
    finally:
        for _, db in reversed(opened):
            db.rollback()
            db.close()


def tracking_exists(db):
    return db.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' "
        "AND name='runtime_legacy_sqlite_sources'"
    ).fetchone() is not None


def _tracking_schema(db):
    db.execute(
        "CREATE TABLE runtime_legacy_sqlite_sources("
        "component TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,"
        "presence TEXT NOT NULL CHECK(presence IN ('present','absent')),"
        "digest TEXT,stat_token TEXT NOT NULL,imported REAL NOT NULL,"
        "CHECK((presence='present')=(digest IS NOT NULL)))"
    )
    db.execute("INSERT INTO runtime_schema VALUES('legacy-sqlite',1)")


def verify_stats(db, stats):
    rows = {row["component"]: row for row in db.execute(
        "SELECT * FROM runtime_legacy_sqlite_sources")}
    if set(rows) != {component for component, _ in LEGACY_DATABASES}:
        raise LegacyStateChanged("legacy source registry is incomplete")
    for stat in stats:
        row = rows[stat.component]
        if (row["path"], row["presence"], row["stat_token"]) != (
                str(stat.path), stat.presence, stat.token):
            raise LegacyStateChanged(f"retained legacy database {stat.component!r} changed")


def _copy_table(target, source, row):
    if row["sql"].lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
        raise ValueError("legacy virtual tables require an explicit migration")
    cursor, columns, rowid = _rows(source, row["name"], row["sql"], True)
    destination = ([rowid] if rowid else []) + columns
    statement = ("INSERT INTO " + _quote(row["name"]) + "("
                 + ",".join(_quote(name) for name in destination) + ") VALUES("
                 + ",".join("?" for _ in destination) + ")")
    while batch := cursor.fetchmany(512):
        target.executemany(statement, (tuple(item) for item in batch))


def initial_migrate(target, sources, stats):
    _tracking_schema(target)
    known = {row["name"]: row["type"] for row in target.execute(
        "SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'")}
    schemas = []
    for source in sources:
        rows = _schema(source.connection)
        for row in rows:
            if row["name"] in known:
                raise LegacyTableCollision(
                    f"legacy {row['type']} {row['name']!r} collides with {known[row['name']]}")
            known[row["name"]] = row["type"]
        schemas.append((source, rows))
    # Referenced tables must exist before any row is inserted, even when FK
    # constraints are deferred. Table names alone do not define dependency order.
    for _, rows in schemas:
        for row in rows:
            if row["type"] == "table":
                if row["sql"].lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
                    raise ValueError("legacy virtual tables require an explicit migration")
                target.execute(row["sql"])
    for source, rows in schemas:
        for row in rows:
            if row["type"] == "table":
                _copy_table(target, source.connection, row)
        names = {row["name"] for row in rows if row["type"] == "table"}
        if source.connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'").fetchone():
            for row in source.connection.execute("SELECT name,seq FROM sqlite_sequence"):
                if row["name"] in names:
                    target.execute("DELETE FROM sqlite_sequence WHERE name=?", (row["name"],))
                    target.execute("INSERT INTO sqlite_sequence VALUES(?,?)", tuple(row))
        for kind in ("view", "index", "trigger"):
            for row in rows:
                if row["type"] == kind:
                    target.execute(row["sql"])
    source_map = {source.stat.component: source for source in sources}
    for stat in stats:
        source = source_map.get(stat.component)
        target.execute("INSERT INTO runtime_legacy_sqlite_sources VALUES(?,?,?,?,?,?)",
                       (stat.component, str(stat.path), stat.presence,
                        None if source is None else source.digest, stat.token, time.time()))


def full_revalidate(db, sources, stats):
    verify_stats(db, tuple(LegacyStat(
        stat.component, stat.path, stat.presence,
        db.execute("SELECT stat_token FROM runtime_legacy_sqlite_sources "
                   "WHERE component=?", (stat.component,)).fetchone()[0]) for stat in stats))
    current = {source.stat.component: source.digest for source in sources}
    for row in db.execute("SELECT component,presence,digest FROM runtime_legacy_sqlite_sources"):
        if row["presence"] == "present" and current.get(row["component"]) != row["digest"]:
            raise LegacyStateChanged(f"retained legacy database {row['component']!r} changed")
    for stat in stats:
        db.execute("UPDATE runtime_legacy_sqlite_sources SET stat_token=? WHERE component=?",
                   (stat.token, stat.component))
