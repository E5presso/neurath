"""Serialized managed app-server receipts and legacy cutover, independent of process control."""

import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

from scripts.agent_harness.runtime_database import RuntimeDatabase, StoredRecord
from scripts.agent_harness.session_kernel import SessionLocator

APP_SERVER_NAMESPACE = "managed-app-server"


def managed_app_server_pid_path(socket_path: Path) -> Path:
    """Worktree-local app-server process-group receipt 경로를 반환합니다.

    Args:
        socket_path: Managed app-server의 UNIX socket 경로입니다.

    Returns:
        같은 basename의 pid receipt 경로입니다.
    """
    return socket_path.with_suffix(".pid")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _decode_managed_record(record, socket_path):
    try:
        value = json.loads(record.payload)
    except (TypeError, ValueError, UnicodeError) as error:
        raise RuntimeError("managed app-server receipt is invalid in SQLite") from error
    if not isinstance(value, dict):
        raise RuntimeError("managed app-server receipt is invalid in SQLite")
    status = value.get("status")
    required = (
        {"schema", "status", "socket_path"}
        if status == "absent"
        else {"schema", "status", "pid", "socket_path", "executable_path"}
    )
    allowed = required | {"legacy_digest"}
    if (
        not required <= set(value) <= allowed
        or value.get("schema") != 1
        or status not in {"active", "absent"}
        or value.get("socket_path") != str(socket_path)
        or (
            "legacy_digest" in value
            and (
                not isinstance(value["legacy_digest"], str)
                or len(value["legacy_digest"]) != 64
                or any(character not in "0123456789abcdef" for character in value["legacy_digest"])
            )
        )
    ):
        raise RuntimeError("managed app-server receipt identity mismatch")
    if status == "active" and (
        not isinstance(value.get("pid"), int)
        or isinstance(value.get("pid"), bool)
        or value["pid"] <= 1
        or not isinstance(value.get("executable_path"), str)
        or not value["executable_path"].strip()
    ):
        raise RuntimeError("managed app-server receipt identity mismatch")
    return value


def _legacy_managed_record(data, socket_path):
    try:
        value = json.loads(data)
    except (TypeError, ValueError, UnicodeError) as error:
        raise RuntimeError("legacy managed app-server receipt is invalid") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"pid", "socket_path", "executable_path"}
        or not isinstance(value.get("pid"), int)
        or isinstance(value.get("pid"), bool)
        or value["pid"] <= 1
        or value.get("socket_path") != str(socket_path)
        or not isinstance(value.get("executable_path"), str)
        or not value["executable_path"].strip()
    ):
        raise RuntimeError("legacy managed app-server receipt identity mismatch")
    return {
        "schema": 1,
        "status": "active",
        "pid": value["pid"],
        "socket_path": str(socket_path),
        "executable_path": str(Path(value["executable_path"]).resolve()),
        "legacy_digest": hashlib.sha256(data).hexdigest(),
    }


@contextmanager
def _managed_app_server_lifecycle(socket_path):
    supplied = Path(socket_path).absolute()
    worktree = supplied.parent.parent.resolve()
    canonical_socket = worktree / ".monitor-pr/app-server.sock"
    if supplied != canonical_socket or supplied.parent.is_symlink() or not worktree.is_dir():
        raise RuntimeError("managed app-server socket path is not canonical")
    locator = SessionLocator.from_worktree(worktree)
    supplied.parent.mkdir(parents=True, exist_ok=True)
    lock_path = supplied.parent / ".app-server.lifecycle.lock"
    if lock_path.is_symlink():
        raise RuntimeError("managed app-server lifecycle lock must not be a symlink")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield RuntimeDatabase(locator.control_root), str(worktree), canonical_socket


def _managed_record_locked(database, key, socket_path):
    legacy_path = managed_app_server_pid_path(socket_path)
    if legacy_path.is_symlink():
        raise RuntimeError("legacy managed app-server receipt must not be a symlink")
    with database.transaction() as tx:
        record = tx.get(APP_SERVER_NAMESPACE, key)
    if record is None:
        if legacy_path.exists() and not legacy_path.is_file():
            raise RuntimeError("legacy managed app-server receipt must be a regular file")
        data = legacy_path.read_bytes() if legacy_path.is_file() else None
        value = (
            {
                "schema": 1,
                "status": "absent",
                "socket_path": str(socket_path),
            }
            if data is None
            else _legacy_managed_record(data, socket_path)
        )
        with database.transaction() as tx:
            record = tx.put(APP_SERVER_NAMESPACE, key, _canonical(value), expected_revision=None)
    value = _decode_managed_record(record, socket_path)
    legacy_digest = value.get("legacy_digest")
    if legacy_digest is None:
        if legacy_path.exists():
            raise RuntimeError("legacy managed app-server receipt reappeared after cutover")
        return record, value
    if legacy_path.exists():
        if (
            not legacy_path.is_file()
            or hashlib.sha256(legacy_path.read_bytes()).hexdigest() != legacy_digest
        ):
            raise RuntimeError("legacy managed app-server receipt changed before removal")
        legacy_path.unlink()
    completed = dict(value)
    del completed["legacy_digest"]
    with database.transaction() as tx:
        current = tx.get(APP_SERVER_NAMESPACE, key)
        if current is None or current.revision != record.revision:
            raise RuntimeError("managed app-server receipt changed during legacy cutover")
        record = tx.put(
            APP_SERVER_NAMESPACE, key, _canonical(completed), expected_revision=current.revision
        )
    return record, completed


def _write_managed_record_locked(database, key, socket_path, pid, codex_binary):
    record, current = _managed_record_locked(database, key, socket_path)
    if current["status"] != "absent":
        raise RuntimeError("an active managed app-server receipt already exists")
    value = {
        "schema": 1,
        "status": "active",
        "pid": pid,
        "socket_path": str(socket_path),
        "executable_path": str(codex_binary.resolve()),
    }
    _decode_managed_record(StoredRecord(record.revision, _canonical(value)), socket_path)
    with database.transaction() as tx:
        return tx.put(
            APP_SERVER_NAMESPACE, key, _canonical(value), expected_revision=record.revision
        )


def _read_managed_identity_locked(database, key, socket_path):
    record, value = _managed_record_locked(database, key, socket_path)
    if value["status"] != "active":
        raise RuntimeError("managed app-server receipt is absent")
    return (
        int(value["pid"]),
        Path(str(value["executable_path"])).resolve(),
        record,
    )


def write_managed_app_server_receipt(socket_path, pid, codex_binary):
    with _managed_app_server_lifecycle(socket_path) as (database, key, canonical_socket):
        _write_managed_record_locked(database, key, canonical_socket, pid, codex_binary)


def read_managed_app_server_identity(socket_path):
    with _managed_app_server_lifecycle(socket_path) as (database, key, canonical_socket):
        pid, executable, _record = _read_managed_identity_locked(database, key, canonical_socket)
        return pid, executable


def managed_app_server_receipt_exists(socket_path):
    with _managed_app_server_lifecycle(socket_path) as (database, key, canonical_socket):
        _record, value = _managed_record_locked(database, key, canonical_socket)
        return value["status"] == "active"
