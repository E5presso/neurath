"""Canonical installation state, recovery journals and immutable receipts."""
import hashlib
import fcntl
import os
import subprocess
import json
import time
from pathlib import Path

from neurath.memory.store import control_root
from neurath.runtime.database import RuntimeDatabase


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def projection(state):
    if state is None:
        return None
    state_digest = digest(state)
    return {
        "schema": 2,
        "authority": "reference-only",
        "state_ref": "sqlite:installation-state:" + state_digest,
        "digest": state_digest,
    }


def validate_plan(plan, root):
    if not isinstance(plan, dict) or plan.get("root") != str(Path(root).resolve()):
        raise ValueError("installation record belongs to another target")
    identity = plan.get("id")
    content = {key: value for key, value in plan.items() if key != "id"}
    if not isinstance(identity, str) or digest(content) != identity:
        raise ValueError("installation record integrity mismatch")
    return plan


def _legacy_install_kind(control, path):
    journal = control / "neurath-journal.json"
    receipts = control / "neurath-receipts"
    if path == journal:
        return "journal"
    if (path.parent == receipts and path.suffix == ".json"
            and len(path.stem) == 64
            and all(character in "0123456789abcdef" for character in path.stem)):
        return "receipt"
    raise ValueError("legacy installation path has invalid scope")


def _check_legacy_install_file(control, path, *, may_be_missing=False):
    _legacy_install_kind(control, path)
    current = path
    while current != control:
        if current.is_symlink():
            raise ValueError(
                "legacy installation record uses a symlink ancestor")
        current = current.parent
    if not path.exists() and may_be_missing:
        return
    if not path.is_file():
        raise ValueError("legacy installation record is missing")


class InstallStateStore:
    def __init__(self, root, *, create=False):
        self.root = Path(root).resolve()
        try:
            self.control_root = control_root(self.root)
        except subprocess.CalledProcessError:
            if create:
                raise
            # Configuration inspection also runs in directories without Git.
            # Absence of an installation must not turn that read into a write.
            self.control_root, self.path, self.database = None, None, None
            return
        self.path = self.control_root / ".neurath/local/runtime.sqlite3"
        self.database = None
        if self.path.exists() or create:
            self.database = RuntimeDatabase(self.control_root)
            with self.database.connection() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS installation_states(
                    root TEXT PRIMARY KEY,digest TEXT NOT NULL,payload TEXT NOT NULL,
                    updated REAL NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS installation_journals(
                    root TEXT PRIMARY KEY,plan_id TEXT NOT NULL,payload TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS installation_receipts(
                    root TEXT NOT NULL,id TEXT NOT NULL,digest TEXT NOT NULL,
                    payload TEXT NOT NULL,PRIMARY KEY(root,id))""")
                db.execute("""CREATE TABLE IF NOT EXISTS installation_legacy_files(
                    root TEXT NOT NULL,path TEXT NOT NULL,digest TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','removed')),
                    PRIMARY KEY(root,path))""")
                db.execute("""CREATE TABLE IF NOT EXISTS installation_json_cutovers(
                    root TEXT PRIMARY KEY,version INTEGER NOT NULL CHECK(version=1))""")

    def _connection(self):
        if self.database is None:
            return None
        return self.database.connection()

    @staticmethod
    def _payload(row, label):
        if row is None:
            return None
        try:
            value = json.loads(row["payload"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid installation {label}") from error
        if digest(value) != row["digest"]:
            raise ValueError(f"installation {label} integrity mismatch")
        return value

    def state(self):
        if self.database is None:
            return None
        with self.database.connection() as db:
            return self._payload(db.execute(
                "SELECT digest,payload FROM installation_states WHERE root=?",
                (str(self.root),)).fetchone(), "state")

    def ensure_state(self, expected):
        if self.database is None:
            raise ValueError("installation database is unavailable")
        with self.database.connection() as db:
            row = db.execute("SELECT digest,payload FROM installation_states WHERE root=?",
                             (str(self.root),)).fetchone()
            actual = self._payload(row, "state")
            if row is None and expected is not None:
                db.execute("INSERT INTO installation_states VALUES(?,?,?,?)",
                           (str(self.root), digest(expected), canonical(expected), time.time()))
            elif actual != expected:
                raise ValueError("canonical installation state changed")

    def receipt(self, identity):
        if self.database is None:
            return None
        with self.database.connection() as db:
            row = db.execute(
                "SELECT digest,payload FROM installation_receipts WHERE root=? AND id=?",
                (str(self.root), identity)).fetchone()
            value = self._payload(row, "record")
        return None if value is None else validate_plan(value, self.root)

    def journal(self):
        if self.database is None:
            return None
        with self.database.connection() as db:
            row = db.execute(
                "SELECT plan_id,payload FROM installation_journals WHERE root=?",
                (str(self.root),)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["payload"])
        except (TypeError, ValueError) as error:
            raise ValueError("invalid installation journal") from error
        if value.get("id") != row["plan_id"]:
            raise ValueError("installation journal identity mismatch")
        return validate_plan(value, self.root)

    def begin(self, plan):
        validate_plan(plan, self.root)
        encoded = canonical(plan)
        with self.database.connection() as db:
            old = db.execute(
                "SELECT plan_id,payload FROM installation_journals WHERE root=?",
                (str(self.root),)).fetchone()
            if old is not None:
                if (old["plan_id"], old["payload"]) != (plan["id"], encoded):
                    raise ValueError("another installation journal is active")
                return
            db.execute("INSERT INTO installation_journals VALUES(?,?,?)",
                       (str(self.root), plan["id"], encoded))

    def discard(self, plan_id):
        with self.database.connection() as db:
            db.execute("DELETE FROM installation_journals WHERE root=? AND plan_id=?",
                       (str(self.root), plan_id))

    def finish(self, plan, state):
        validate_plan(plan, self.root)
        encoded = canonical(plan)
        with self.database.connection() as db:
            journal = db.execute(
                "SELECT plan_id,payload FROM installation_journals WHERE root=?",
                (str(self.root),)).fetchone()
            if journal is None or (journal["plan_id"], journal["payload"]) != (
                    plan["id"], encoded):
                raise ValueError("installation journal changed before commit")
            receipt = db.execute(
                "SELECT digest,payload FROM installation_receipts WHERE root=? AND id=?",
                (str(self.root), plan["id"])).fetchone()
            if receipt is not None and self._payload(receipt, "record") != plan:
                raise ValueError("installation record ID collision")
            db.execute("INSERT OR IGNORE INTO installation_receipts VALUES(?,?,?,?)",
                       (str(self.root), plan["id"], digest(plan), encoded))
            if state is None:
                db.execute("DELETE FROM installation_states WHERE root=?", (str(self.root),))
            else:
                db.execute("""INSERT INTO installation_states VALUES(?,?,?,?)
                    ON CONFLICT(root) DO UPDATE SET digest=excluded.digest,
                    payload=excluded.payload,updated=excluded.updated""",
                    (str(self.root), digest(state), canonical(state), time.time()))
            db.execute("DELETE FROM installation_journals WHERE root=? AND plan_id=?",
                       (str(self.root), plan["id"]))

    def import_legacy_files(self, git_control):
        """Crash-recoverable one-time cutover for this worktree's JSON."""
        control = Path(git_control)
        lock_path = (
            self.control_root
            / ".neurath/local/installation-json-cutover.lock"
        )
        if lock_path.is_symlink():
            raise ValueError("installation cutover lock must not be a symlink")
        descriptor = os.open(
            lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if control.is_symlink() or not control.is_dir():
                raise ValueError("Git control directory is invalid")
            receipts = control / "neurath-receipts"
            if receipts.exists() and (
                    receipts.is_symlink() or not receipts.is_dir()):
                raise ValueError(
                    "legacy installation receipt directory is invalid")
            journal = control / "neurath-journal.json"
            paths = ([journal] if journal.is_file() else []) + (
                sorted(receipts.glob("*.json"))
                if receipts.is_dir() else []
            )
            documents = {}
            for path in paths:
                _check_legacy_install_file(control, path)
                data = path.read_bytes()
                documents[str(path)] = (
                    hashlib.sha256(data).hexdigest(), data)

            root_key = str(self.root)
            with self.database.connection() as db:
                tracked = {
                    row["path"]: row
                    for row in db.execute(
                        "SELECT * FROM installation_legacy_files "
                        "WHERE root=?", (root_key,))
                }
                cutover = db.execute(
                    "SELECT 1 FROM installation_json_cutovers WHERE root=?",
                    (root_key,),
                ).fetchone() is not None
                for name, (file_digest, data) in documents.items():
                    previous = tracked.get(name)
                    if previous is not None:
                        if (previous["status"] == "removed"
                                or previous["digest"] != file_digest):
                            raise ValueError(
                                "legacy installation JSON reappeared or changed")
                        continue
                    if cutover:
                        raise ValueError(
                            "legacy installation JSON appeared after SQLite cutover")
                    path = Path(name)
                    kind = _legacy_install_kind(control, path)
                    try:
                        value = validate_plan(json.loads(data), self.root)
                    except (TypeError, ValueError) as error:
                        raise ValueError(
                            f"legacy installation {kind} is invalid") from error
                    encoded = canonical(value)
                    if kind == "journal":
                        previous = db.execute(
                            "SELECT plan_id,payload FROM installation_journals "
                            "WHERE root=?", (root_key,)
                        ).fetchone()
                        if previous is not None and (
                                previous["plan_id"], previous["payload"]) != (
                                value["id"], encoded):
                            raise ValueError(
                                "legacy installation journal collision")
                        db.execute(
                            "INSERT OR IGNORE INTO installation_journals "
                            "VALUES(?,?,?)",
                            (root_key, value["id"], encoded))
                    else:
                        if path.stem != value["id"]:
                            raise ValueError(
                                "legacy installation record filename mismatch")
                        previous = db.execute(
                            "SELECT digest,payload FROM installation_receipts "
                            "WHERE root=? AND id=?",
                            (root_key, value["id"]),
                        ).fetchone()
                        if (previous is not None
                                and self._payload(previous, "record") != value):
                            raise ValueError(
                                "legacy installation record collision")
                        db.execute(
                            "INSERT OR IGNORE INTO installation_receipts "
                            "VALUES(?,?,?,?)",
                            (root_key, value["id"], digest(value), encoded))
                    db.execute(
                        "INSERT INTO installation_legacy_files "
                        "VALUES(?,?,?,'pending')",
                        (root_key, name, file_digest))
                db.execute(
                    "INSERT OR IGNORE INTO installation_json_cutovers "
                    "VALUES(?,1)", (root_key,))
                pending = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM installation_legacy_files "
                        "WHERE root=? AND status='pending'", (root_key,))
                ]

            for row in pending:
                path = Path(row["path"])
                _check_legacy_install_file(
                    control, path, may_be_missing=True)
                if path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != row["digest"]:
                        raise ValueError(
                            "legacy installation JSON changed before removal")
                    path.unlink()

            with self.database.connection() as db:
                db.execute(
                    "UPDATE installation_legacy_files SET status='removed' "
                    "WHERE root=? AND status='pending'", (root_key,))
