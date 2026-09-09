"""Neurath 하네스 자체를 수리할 때 쓰는 bounded superuser lease를 제공합니다."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.agent_harness.session_kernel import SessionLocator, SessionRuntime
from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityConflict,
    RuntimeIdentityUnavailable,
)

LEGACY_LEASE_FILENAME = "harness-maintenance.json"
LEGACY_RECEIPT_DIRECTORY = "harness-maintenance-receipts"
RECEIPT_PREFIX = "sqlite:harness-maintenance:"
MAX_TTL_SECONDS = 14_400
DIRECT_MUTATION_TOOLS = frozenset({
    "apply_patch",
    "edit",
    "multiedit",
    "notebookedit",
    "write",
})
HARNESS_ROOTS = (
    Path(".agents"),
    Path(".claude"),
    Path(".codex"),
    Path(".github"),
    Path("scripts"),
)
RUNTIME_STATE_ROOTS = (
    Path(".agents/loops"),
    Path(".agents/resources"),
    Path(".agents/runs"),
    Path(".agents/worktrees"),
    Path(".claude/monitor-pr-seen"),
    Path(".claude/worktrees"),
)
HARNESS_FILES = frozenset({
    Path("AGENTS.md"),
    Path(".pre-commit-config.yaml"),
    Path(".python-version"),
    Path(".gitignore"),
    Path("docs/README.md"),
    Path("docs/context/harness-authorization-audit.md"),
    Path("docs/decisions/ADR-0004-harness-anti-drift-architecture.md"),
    Path("docs/decisions/ADR-0023-prose-guides-gates-enforce.md"),
    Path("docs/decisions/ADR-0024-harness-for-autonomous-sdd.md"),
    Path("docs/decisions/ADR-0037-session-scoped-coding-agent-harness.md"),
    Path("docs/decisions/ADR-0039-adaptive-agent-control-loop.md"),
    Path("docs/decisions/ADR-0040-korean-agent-narrative-standard.md"),
    Path("docs/decisions/README.md"),
    Path("docs/plans/coding-agent-session-harness-spec.md"),
    Path("mise.toml"),
    Path("pyproject.toml"),
    Path("uv.lock"),
})
RUNTIME_STATE_FILES = frozenset({Path(".claude/settings.local.json")})


class HarnessMaintenanceError(RuntimeError):
    """Maintenance lease를 안전하게 열거나 사용하거나 닫을 수 없습니다."""


def _canonical_target(repository: Path, raw_target: str | Path) -> Path:
    candidate = Path(raw_target)
    if not candidate.is_absolute():
        candidate = repository / candidate
    return candidate.resolve(strict=False)


def _is_harness_target(repository: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(repository)
    except ValueError:
        return False
    if relative in RUNTIME_STATE_FILES or any(
        relative == root or root in relative.parents for root in RUNTIME_STATE_ROOTS
    ):
        return False
    if relative in HARNESS_FILES:
        return True
    return any(relative == root or root in relative.parents for root in HARNESS_ROOTS)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise HarnessMaintenanceError("maintenance lease timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise HarnessMaintenanceError("maintenance lease timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise HarnessMaintenanceError("maintenance lease timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _maintenance_payload(value, expected_status, *, path=None, base=None):
    active = {
        "schema_version", "lease_id", "status", "session_id", "actor_id",
        "reason", "targets", "opened_at", "expires_at",
    }
    closed = active | {"closed_at", "summary", "readback"}
    required = active if expected_status == "active" else closed
    if not isinstance(value, dict) or set(value) != required:
        raise HarnessMaintenanceError(
            f"maintenance {expected_status} record schema is invalid")
    if value["schema_version"] != 1 or value["status"] != expected_status:
        raise HarnessMaintenanceError(
            f"maintenance {expected_status} record status is invalid")
    for field in ("lease_id", "session_id", "actor_id", "reason"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise HarnessMaintenanceError(
                f"maintenance {expected_status} record identity is invalid")
    if (len(value["lease_id"]) != 32
            or any(character not in "0123456789abcdef"
                   for character in value["lease_id"])):
        raise HarnessMaintenanceError("maintenance lease ID is invalid")
    targets = value["targets"]
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(target, str) or not target for target in targets)
            or len(set(targets)) != len(targets)):
        raise HarnessMaintenanceError("maintenance target list is invalid")
    opened = _parse_time(value["opened_at"])
    expires = _parse_time(value["expires_at"])
    if not 0 < (expires - opened).total_seconds() <= MAX_TTL_SECONDS:
        raise HarnessMaintenanceError("maintenance lease lifetime is invalid")
    if expected_status == "closed":
        _parse_time(value["closed_at"])
        if not isinstance(value["summary"], str) or not value["summary"].strip():
            raise HarnessMaintenanceError("maintenance summary is invalid")
        readback = value["readback"]
        if not isinstance(readback, list) or len(readback) != len(targets):
            raise HarnessMaintenanceError("maintenance receipt readback is invalid")
        for target, row in zip(targets, readback, strict=True):
            if (not isinstance(row, dict)
                    or set(row) != {"target", "state", "sha256"}
                    or row["target"] != target
                    or row["state"] not in {"present", "missing", "non-file"}):
                raise HarnessMaintenanceError(
                    "maintenance receipt readback is invalid")
            saved_digest = row["sha256"]
            if row["state"] == "present":
                if (not isinstance(saved_digest, str)
                        or len(saved_digest) != 64
                        or any(character not in "0123456789abcdef"
                               for character in saved_digest)):
                    raise HarnessMaintenanceError(
                        "maintenance receipt digest is invalid")
            elif saved_digest is not None:
                raise HarnessMaintenanceError(
                    "maintenance receipt digest is invalid")
    if path is not None:
        relative = _legacy_maintenance_relative(base, path)
        if expected_status == "active":
            valid_path = (
                len(relative.parts) == 2
                and relative.parts[0] == value["session_id"]
                and relative.parts[1] == LEGACY_LEASE_FILENAME
            )
        else:
            leaf = Path(relative.parts[2]) if len(relative.parts) == 3 else None
            valid_path = (
                leaf is not None
                and relative.parts[0] == value["session_id"]
                and relative.parts[1] == LEGACY_RECEIPT_DIRECTORY
                and leaf.suffix == ".json"
                and leaf.stem == value["lease_id"]
            )
            # The old close wrote a complete closed payload before renaming
            # the active filename. Preserve that exact interrupted stage.
            valid_path = valid_path or (len(relative.parts) == 2
                and relative.parts[0] == value["session_id"]
                and relative.parts[1] == LEGACY_LEASE_FILENAME)
        if not valid_path:
            raise HarnessMaintenanceError(
                "legacy maintenance pathname does not match its record identity")
    return value


def _legacy_maintenance_relative(base, path):
    try:
        relative = path.relative_to(base)
    except ValueError as error:
        raise HarnessMaintenanceError(
            "legacy maintenance path escaped its state root") from error
    if not (
        (len(relative.parts) == 2
         and relative.parts[1] == LEGACY_LEASE_FILENAME)
        or (len(relative.parts) == 3
            and relative.parts[1] == LEGACY_RECEIPT_DIRECTORY
            and Path(relative.parts[2]).suffix == ".json")
    ):
        raise HarnessMaintenanceError(
            "legacy maintenance path has invalid scope")
    return relative


def _check_legacy_maintenance_file(base, path, *, may_be_missing=False):
    _legacy_maintenance_relative(base, path)
    current = path
    while current != base:
        if current.is_symlink():
            raise HarnessMaintenanceError(
                "legacy maintenance state uses a symlink ancestor")
        current = current.parent
    if not path.exists() and may_be_missing:
        return
    if not path.is_file():
        raise HarnessMaintenanceError("legacy maintenance state is missing")


class HarnessMaintenanceStore:
    """Canonical active leases and immutable close receipts."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.database = RuntimeDatabase(self.root)
        with self.database.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS harness_maintenance_leases(
                session_id TEXT PRIMARY KEY, lease_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS harness_maintenance_receipts(
                lease_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                actor_id TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS harness_maintenance_legacy_files(
                path TEXT PRIMARY KEY,digest TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','removed')))""")
        self._migrate_legacy()

    def _migrate_legacy(self):
        base = self.root / ".agents/runs"
        lock_path = self.root / ".neurath/local/harness-maintenance-cutover.lock"
        if lock_path.is_symlink():
            raise HarnessMaintenanceError(
                "maintenance cutover lock must not be a symlink")
        descriptor = os.open(
            lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (self.root / ".agents").is_symlink():
                raise HarnessMaintenanceError("legacy maintenance state root uses a symlink")
            if base.exists() and (base.is_symlink() or not base.is_dir()):
                raise HarnessMaintenanceError(
                    "legacy maintenance state root is invalid")
            paths = [] if not base.is_dir() else sorted({
                *base.glob("*/" + LEGACY_LEASE_FILENAME),
                *base.glob("*/" + LEGACY_RECEIPT_DIRECTORY + "/*.json"),
            })
            documents = {}
            for path in paths:
                _check_legacy_maintenance_file(base, path)
                data = path.read_bytes()
                documents[str(path)] = (
                    hashlib.sha256(data).hexdigest(), data)

            with self.database.connection() as db:
                tracked = {
                    row["path"]: row
                    for row in db.execute(
                        "SELECT * FROM harness_maintenance_legacy_files")
                }
                cutover = db.execute(
                    "SELECT 1 FROM runtime_schema "
                    "WHERE component='harness-maintenance-json'"
                ).fetchone() is not None
                for name, (file_digest, data) in documents.items():
                    old = tracked.get(name)
                    if old is not None:
                        if (old["status"] == "removed"
                                or old["digest"] != file_digest):
                            raise HarnessMaintenanceError(
                                "legacy maintenance state reappeared or changed")
                        continue
                    if cutover:
                        raise HarnessMaintenanceError(
                            "legacy maintenance state appeared after SQLite cutover")
                    path = Path(name)
                    try:
                        payload = json.loads(data)
                    except (TypeError, ValueError) as error:
                        raise HarnessMaintenanceError(
                            "legacy maintenance state is invalid") from error
                    expected = (
                        "active"
                        if path.name == LEGACY_LEASE_FILENAME
                        and isinstance(payload, dict) and payload.get("status") == "active"
                        else "closed"
                    )
                    payload = _maintenance_payload(
                        payload, expected, path=path, base=base)
                    encoded = _canonical(payload)
                    if expected == "active":
                        values = (
                            payload["session_id"], payload["lease_id"],
                            payload["actor_id"], encoded,
                        )
                        previous = db.execute(
                            "SELECT payload FROM harness_maintenance_leases "
                            "WHERE session_id=?", (values[0],)
                        ).fetchone()
                        if previous is not None:
                            try:
                                previous_payload = json.loads(previous["payload"])
                            except (TypeError, ValueError) as error:
                                raise HarnessMaintenanceError(
                                    "existing maintenance lease is corrupt") from error
                            _maintenance_payload(previous_payload, "active")
                            if previous["payload"] != encoded:
                                raise HarnessMaintenanceError(
                                    "legacy maintenance lease collides with SQLite")
                        db.execute(
                            "INSERT OR IGNORE INTO harness_maintenance_leases "
                            "VALUES(?,?,?,?)", values)
                    else:
                        values = (
                            payload["lease_id"], payload["session_id"],
                            payload["actor_id"], encoded,
                        )
                        previous = db.execute(
                            "SELECT payload FROM harness_maintenance_receipts "
                            "WHERE lease_id=?", (values[0],)
                        ).fetchone()
                        if previous is not None:
                            try:
                                previous_payload = json.loads(previous["payload"])
                            except (TypeError, ValueError) as error:
                                raise HarnessMaintenanceError(
                                    "existing maintenance receipt is corrupt") from error
                            _maintenance_payload(previous_payload, "closed")
                            if previous["payload"] != encoded:
                                raise HarnessMaintenanceError(
                                    "legacy maintenance receipt collides with SQLite")
                        db.execute(
                            "INSERT OR IGNORE INTO harness_maintenance_receipts "
                            "VALUES(?,?,?,?)", values)
                    db.execute(
                        "INSERT INTO harness_maintenance_legacy_files "
                        "VALUES(?,?,'pending')", (name, file_digest))
                db.execute(
                    "INSERT OR IGNORE INTO runtime_schema "
                    "VALUES('harness-maintenance-json',1)")
                pending = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM harness_maintenance_legacy_files "
                        "WHERE status='pending'")
                ]

            for row in pending:
                path = Path(row["path"])
                _check_legacy_maintenance_file(
                    base, path, may_be_missing=True)
                if path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != row["digest"]:
                        raise HarnessMaintenanceError(
                            "legacy maintenance state changed before removal")
                    path.unlink()

            with self.database.connection() as db:
                db.execute(
                    "UPDATE harness_maintenance_legacy_files "
                    "SET status='removed' WHERE status='pending'")

    @staticmethod
    def _decode(row):
        if row is None:
            raise HarnessMaintenanceError("no active maintenance lease exists")
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError) as error:
            raise HarnessMaintenanceError("maintenance lease is invalid or inactive") from error
        _maintenance_payload(payload, "active")
        if (payload.get("session_id"), payload.get("lease_id"), payload.get("actor_id")) != (
                row["session_id"], row["lease_id"], row["actor_id"]):
            raise HarnessMaintenanceError("maintenance lease identity is corrupt")
        return payload

    def read_active(self, session_id):
        with self.database.connection() as db:
            return self._decode(db.execute(
                "SELECT * FROM harness_maintenance_leases WHERE session_id=?",
                (session_id,)).fetchone())

    def begin(self, payload):
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM harness_maintenance_leases WHERE session_id=?",
                (payload["session_id"],)).fetchone()
            if row is not None:
                existing = self._decode(row)
                if _utc_now() < _parse_time(existing.get("expires_at")):
                    raise HarnessMaintenanceError("an active maintenance lease already exists")
                db.execute("DELETE FROM harness_maintenance_leases WHERE session_id=?",
                           (payload["session_id"],))
            db.execute("INSERT INTO harness_maintenance_leases VALUES(?,?,?,?)", (
                payload["session_id"], payload["lease_id"], payload["actor_id"],
                _canonical(payload)))

    def close(self, expected, closed):
        encoded = _canonical(closed)
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM harness_maintenance_leases WHERE session_id=?",
                (expected["session_id"],)).fetchone()
            current = self._decode(row)
            if current != expected:
                raise HarnessMaintenanceError("maintenance lease changed during close")
            old = db.execute(
                "SELECT payload FROM harness_maintenance_receipts WHERE lease_id=?",
                (expected["lease_id"],)).fetchone()
            if old is not None and old["payload"] != encoded:
                raise HarnessMaintenanceError("maintenance receipt identity collision")
            db.execute("INSERT OR IGNORE INTO harness_maintenance_receipts VALUES(?,?,?,?)", (
                expected["lease_id"], expected["session_id"], expected["actor_id"], encoded))
            db.execute("DELETE FROM harness_maintenance_leases "
                       "WHERE session_id=? AND lease_id=?",
                       (expected["session_id"], expected["lease_id"]))
        return RECEIPT_PREFIX + expected["lease_id"]


class HarnessMaintenanceAuthority:
    """Active exact-actor, exact-target maintenance lease의 우회 권한을 확인합니다."""

    @classmethod
    def authorizes(
        cls,
        *,
        cwd: Path,
        environment: Mapping[str, object],
        hook_runtime: SessionRuntime | None,
        runtime_agent_id: str | None,
        runtime_session_id: str | None,
        tool_name: str,
        targets: Sequence[str | Path],
    ) -> bool:
        """Structured edit가 active maintenance lease 범위 안인지 판정합니다.

        Args:
            cwd: Lease의 repository control root를 찾을 현재 경로입니다.
            environment: Current runtime identity를 증명하는 environment입니다.
            hook_runtime: Vendor wrapper가 고정한 optional runtime입니다.
            runtime_agent_id: Hook payload가 제공한 optional actor identity입니다.
            runtime_session_id: Hook payload가 제공한 optional session identity입니다.
            tool_name: Structured edit 여부를 판정할 normalized tool 이름입니다.
            targets: 이번 invocation이 수정하려는 exact file target입니다.

        Returns:
            Actor, session, TTL과 모든 target이 active lease에 결속하면 참입니다.
        """
        if tool_name not in DIRECT_MUTATION_TOOLS or not targets:
            return False
        try:
            binding = RuntimeEnvironmentResolver().resolve_hook_actor(
                environment,
                runtime_agent_id,
                runtime_session_id,
                hook_runtime=hook_runtime,
            )
            repository = cwd.resolve(strict=True)
            locator = SessionLocator.from_worktree(repository)
            payload = HarnessMaintenanceStore(locator.control_root).read_active(
                str(binding.session_id))
            if not isinstance(payload, dict) or payload.get("status") != "active":
                return False
            if payload.get("session_id") != str(binding.session_id):
                return False
            if payload.get("actor_id") != str(binding.actor_id):
                return False
            if _utc_now() >= _parse_time(payload.get("expires_at")):
                return False
            raw_targets = payload.get("targets")
            if not isinstance(raw_targets, list) or any(
                not isinstance(item, str) for item in raw_targets
            ):
                return False
            leased = {_canonical_target(repository, item) for item in raw_targets}
            requested = {_canonical_target(repository, target) for target in targets}
            return (
                bool(requested)
                and requested <= leased
                and all(_is_harness_target(repository, target) for target in requested)
            )
        except (
            HarnessMaintenanceError,
            OSError,
            sqlite3.Error,
            ValueError,
            RuntimeIdentityConflict,
            RuntimeIdentityUnavailable,
        ):
            return False


class HarnessMaintenanceCli:
    """Current actor를 위한 auditable maintenance lease lifecycle을 소유합니다."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
        cwd: Path,
    ) -> int:
        """Maintenance lease를 열고 조회하거나 digest readback과 함께 닫습니다.

        Args:
            arguments: `begin`, `status`, `end` 중 하나의 exact CLI argv입니다.
            environment: Lease owner session과 actor를 증명하는 runtime environment입니다.
            cwd: Repository control root를 찾고 target을 canonicalize할 경로입니다.

        Returns:
            성공하면 0, invalid scope 또는 authority면 2를 반환합니다.
        """
        parser = argparse.ArgumentParser(prog="harness_maintenance")
        commands = parser.add_subparsers(dest="command", required=True)
        begin = commands.add_parser("begin")
        begin.add_argument("--reason", required=True)
        begin.add_argument("--target", action="append", required=True)
        begin.add_argument("--ttl-seconds", type=int, default=3_600)
        commands.add_parser("status")
        end = commands.add_parser("end")
        end.add_argument("--summary", required=True)
        namespace = parser.parse_args(list(arguments))
        try:
            repository = cwd.resolve(strict=True)
            session_id, actor_id = self._identity(environment)
            locator = SessionLocator.from_worktree(repository)
            store = HarnessMaintenanceStore(locator.control_root)
            if namespace.command == "begin":
                result = self._begin(
                    repository=repository,
                    store=store,
                    session_id=session_id,
                    actor_id=actor_id,
                    reason=str(namespace.reason),
                    raw_targets=tuple(namespace.target),
                    ttl_seconds=int(namespace.ttl_seconds),
                )
            elif namespace.command == "status":
                result = store.read_active(session_id)
            else:
                result = self._end(
                    repository=repository,
                    store=store,
                    session_id=session_id,
                    actor_id=actor_id,
                    summary=str(namespace.summary),
                )
        except (HarnessMaintenanceError, OSError, sqlite3.Error, ValueError) as error:
            print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
        return 0

    def _identity(self, environment: Mapping[str, str]) -> tuple[str, str]:
        overlay_session = environment.get("NEURATH_AGENT_SESSION_ID")
        overlay_actor = environment.get("NEURATH_AGENT_ACTOR_ID")
        overlay_runtime = environment.get("NEURATH_AGENT_RUNTIME")
        if overlay_session and overlay_actor and overlay_runtime:
            return overlay_session, overlay_actor
        codex_session = environment.get("CODEX_THREAD_ID")
        if codex_session:
            return codex_session, f"codex:session:{codex_session}"
        claude_session = environment.get("CLAUDE_CODE_SESSION_ID")
        if claude_session:
            return claude_session, f"claude-code:session:{claude_session}"
        raise HarnessMaintenanceError("maintenance mode requires exact runtime identity")

    def _begin(
        self,
        *,
        repository: Path,
        store: HarnessMaintenanceStore,
        session_id: str,
        actor_id: str,
        reason: str,
        raw_targets: Sequence[str],
        ttl_seconds: int,
    ) -> Mapping[str, object]:
        if not reason.strip():
            raise HarnessMaintenanceError("maintenance reason must be non-empty")
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise HarnessMaintenanceError(
                f"maintenance ttl must be between 1 and {MAX_TTL_SECONDS} seconds"
            )
        targets = tuple(sorted({_canonical_target(repository, target) for target in raw_targets}))
        if not targets or any(not _is_harness_target(repository, target) for target in targets):
            raise HarnessMaintenanceError(
                "maintenance targets must be exact Neurath harness-owned paths"
            )
        if any(target.is_dir() for target in targets):
            raise HarnessMaintenanceError("maintenance targets must be files, not directories")
        now = _utc_now()
        payload: dict[str, object] = {
            "schema_version": 1,
            "lease_id": uuid.uuid4().hex,
            "status": "active",
            "session_id": session_id,
            "actor_id": actor_id,
            "reason": reason.strip(),
            "targets": [str(target) for target in targets],
            "opened_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        store.begin(payload)
        return payload

    def _end(
        self,
        *,
        repository: Path,
        store: HarnessMaintenanceStore,
        session_id: str,
        actor_id: str,
        summary: str,
    ) -> Mapping[str, object]:
        if not summary.strip():
            raise HarnessMaintenanceError("maintenance summary must be non-empty")
        payload = store.read_active(session_id)
        if payload.get("session_id") != session_id or payload.get("actor_id") != actor_id:
            raise HarnessMaintenanceError("only the lease owner may close maintenance mode")
        raw_targets = payload.get("targets")
        if not isinstance(raw_targets, list):
            raise HarnessMaintenanceError("maintenance target list is invalid")
        readback: list[dict[str, object]] = []
        for item in raw_targets:
            if not isinstance(item, str):
                raise HarnessMaintenanceError("maintenance target entry is invalid")
            target = _canonical_target(repository, item)
            if target.is_file():
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                state = "present"
            elif target.exists():
                digest = None
                state = "non-file"
            else:
                digest = None
                state = "missing"
            readback.append({"target": str(target), "state": state, "sha256": digest})
        closed = dict(payload)
        closed.update({
            "status": "closed",
            "closed_at": _utc_now().isoformat(),
            "summary": summary.strip(),
            "readback": readback,
        })
        receipt = store.close(payload, closed)
        return {"lease_id": payload["lease_id"], "receipt": receipt, "readback": readback}


if __name__ == "__main__":
    raise SystemExit(
        HarnessMaintenanceCli().run(sys.argv[1:], environment=dict(os.environ), cwd=Path.cwd())
    )
