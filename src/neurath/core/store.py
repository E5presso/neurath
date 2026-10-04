"""Single transactional persistence boundary for work, provenance and writer leases."""

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from neurath.core.codec import decode_task, encode
from neurath.core.domain import CoreError, Source, require

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leases(checkout TEXT PRIMARY KEY, writer TEXT NOT NULL, generation INTEGER NOT NULL, active INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS commands(actor TEXT NOT NULL, id TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(actor,id));
CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(kind,id));
"""


class Store:
    def __init__(self, project_root):
        self.root = Path(project_root).resolve()
        directory = self.root
        for part in (".neurath", "local"):
            directory /= part
            require(not directory.is_symlink(), "unsafe-store-path")
            directory.mkdir(mode=0o700, exist_ok=True)
            require(directory.is_dir(), "unsafe-store-path")
        self.path = directory / "core.sqlite3"
        for suffix in ("", "-wal", "-shm", "-journal"):
            require(not Path(str(self.path) + suffix).is_symlink(), "unsafe-store-path")
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        os.close(descriptor)
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield Transaction(db)
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @contextmanager
    def sql_transaction(self):
        """Outer services use the same atomic boundary for their own tables."""
        with self.transaction() as tx:
            yield tx.db

    def command(self, actor, key, name, payload, operation, *, authenticate=None):
        require(bool(actor and key and name), "command-identity")
        request = sha256(encode([name, payload]).encode()).hexdigest()
        with self.transaction() as tx:
            if authenticate is not None:
                authenticate(tx)
            row = tx.db.execute(
                "SELECT request,result FROM commands WHERE actor=? AND id=?", (actor, key)
            ).fetchone()
            if row:
                require(row["request"] == request, "request-conflict")
                return json.loads(row["result"])
            result = operation(tx)
            encoded = encode(result)
            tx.db.execute("INSERT INTO commands VALUES(?,?,?,?)", (actor, key, request, encoded))
            return json.loads(encoded)


class Transaction:
    def __init__(self, connection):
        self.db = connection

    def task(self, identifier):
        row = self.db.execute(
            "SELECT revision,document FROM tasks WHERE id=?", (identifier,)
        ).fetchone()
        require(row is not None, "task-missing", task_id=identifier)
        value = decode_task(row["document"])
        require(value.revision == row["revision"], "invalid-task-record")
        return value

    def tasks(self):
        return tuple(
            decode_task(row["document"])
            for row in self.db.execute("SELECT document FROM tasks ORDER BY id")
        )

    def create_task(self, task):
        require(task.revision == 1, "revision-conflict")
        try:
            self.db.execute(
                "INSERT INTO tasks VALUES(?,?,?)", (task.id, task.revision, encode(task))
            )
        except sqlite3.IntegrityError as error:
            raise CoreError("task-exists", task_id=task.id) from error

    def save_task(self, task, *, expected_revision):
        require(task.revision == expected_revision + 1, "revision-conflict")
        result = self.db.execute(
            "UPDATE tasks SET revision=?, document=? WHERE id=? AND revision=?",
            (task.revision, encode(task), task.id, expected_revision),
        )
        require(
            result.rowcount == 1, "revision-conflict", task_id=task.id, expected=expected_revision
        )

    def source(self, identifier):
        row = self.db.execute("SELECT document FROM sources WHERE id=?", (identifier,)).fetchone()
        require(row is not None, "source-missing", source_id=identifier)
        value = json.loads(row["document"])
        source = Source.create(value["id"], value["kind"], value["text"], value["event_id"])
        require(source.digest == value["digest"], "source-changed")
        return source

    def put_source(self, source):
        document = encode(asdict(source))
        existing = self.db.execute(
            "SELECT document FROM sources WHERE id=? OR event_id=?", (source.id, source.event_id)
        ).fetchall()
        if existing:
            require(len(existing) == 1 and existing[0]["document"] == document, "source-conflict")
            return
        self.db.execute("INSERT INTO sources VALUES(?,?,?)", (source.id, source.event_id, document))

    def lease(self, checkout):
        row = self.db.execute(
            "SELECT writer,generation FROM leases WHERE checkout=? AND active=1", (checkout,)
        ).fetchone()
        return (
            None
            if row is None
            else {"checkout": checkout, "writer": row["writer"], "generation": row["generation"]}
        )

    def claim(self, checkout, actor):
        require(bool(checkout and actor), "lease-identity")
        current = self.lease(checkout)
        if current:
            require(current["writer"] == actor, "lease-conflict", writer=current["writer"])
            return current
        row = self.db.execute(
            "SELECT generation FROM leases WHERE checkout=?", (checkout,)
        ).fetchone()
        generation = 1 if row is None else row["generation"] + 1
        self.db.execute(
            "INSERT INTO leases VALUES(?,?,?,1) ON CONFLICT(checkout) DO UPDATE SET writer=excluded.writer,generation=excluded.generation,active=1",
            (checkout, actor, generation),
        )
        return {"checkout": checkout, "writer": actor, "generation": generation}

    def release(self, checkout, actor, generation):
        require(
            self.lease(checkout)
            == {"checkout": checkout, "writer": actor, "generation": generation},
            "stale-lease",
        )
        self.db.execute("UPDATE leases SET active=0 WHERE checkout=?", (checkout,))

    def record(self, kind, identifier):
        row = self.db.execute(
            "SELECT revision,document FROM records WHERE kind=? AND id=?", (kind, identifier)
        ).fetchone()
        return (
            None
            if row is None
            else {"revision": row["revision"], "value": json.loads(row["document"])}
        )

    def records(self, kind, *, chronological=False):
        return tuple(
            {"id": row["id"], "revision": row["revision"], "value": json.loads(row["document"])}
            for row in self.db.execute(
                "SELECT id,revision,document FROM records WHERE kind=? ORDER BY "
                + ("rowid" if chronological else "id"),
                (kind,),
            )
        )

    def put_record(self, kind, identifier, value, expected_revision=0):
        current = self.record(kind, identifier)
        revision = 0 if current is None else current["revision"]
        require(revision == expected_revision, "revision-conflict", record_id=identifier)
        document = encode(value)
        self.db.execute(
            "INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET revision=excluded.revision,document=excluded.document",
            (kind, identifier, revision + 1, document),
        )
        return revision + 1
