"""Neurath 하네스 자체를 수리할 때 쓰는 bounded superuser lease를 제공합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.agent_harness.session_kernel import SessionLocator, SessionRuntime
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityConflict,
    RuntimeIdentityUnavailable,
)

LEASE_FILENAME = "harness-maintenance.json"
RECEIPT_DIRECTORY = "harness-maintenance-receipts"
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


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


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
            lease_path = (
                locator.control_root / ".agents" / "runs" / str(binding.session_id) / LEASE_FILENAME
            )
            payload = json.loads(lease_path.read_text(encoding="utf-8"))
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
            json.JSONDecodeError,
            OSError,
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
            lease_path = locator.control_root / ".agents" / "runs" / session_id / LEASE_FILENAME
            if namespace.command == "begin":
                result = self._begin(
                    repository=repository,
                    lease_path=lease_path,
                    session_id=session_id,
                    actor_id=actor_id,
                    reason=str(namespace.reason),
                    raw_targets=tuple(namespace.target),
                    ttl_seconds=int(namespace.ttl_seconds),
                )
            elif namespace.command == "status":
                result = self._read_active(lease_path)
            else:
                result = self._end(
                    repository=repository,
                    lease_path=lease_path,
                    session_id=session_id,
                    actor_id=actor_id,
                    summary=str(namespace.summary),
                )
        except (HarnessMaintenanceError, OSError, json.JSONDecodeError) as error:
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
        lease_path: Path,
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
        if lease_path.exists():
            existing = self._read_active(lease_path)
            if _utc_now() < _parse_time(existing.get("expires_at")):
                raise HarnessMaintenanceError("an active maintenance lease already exists")
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
        _atomic_write(lease_path, payload)
        return payload

    def _read_active(self, lease_path: Path) -> dict[str, object]:
        try:
            payload = json.loads(lease_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise HarnessMaintenanceError("no active maintenance lease exists") from error
        if not isinstance(payload, dict) or payload.get("status") != "active":
            raise HarnessMaintenanceError("maintenance lease is invalid or inactive")
        return {str(key): value for key, value in payload.items()}

    def _end(
        self,
        *,
        repository: Path,
        lease_path: Path,
        session_id: str,
        actor_id: str,
        summary: str,
    ) -> Mapping[str, object]:
        if not summary.strip():
            raise HarnessMaintenanceError("maintenance summary must be non-empty")
        payload = self._read_active(lease_path)
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
        receipt = lease_path.parent / RECEIPT_DIRECTORY / f"{payload['lease_id']}.json"
        _atomic_write(lease_path, closed)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        os.replace(lease_path, receipt)
        return {"lease_id": payload["lease_id"], "receipt": str(receipt), "readback": readback}


if __name__ == "__main__":
    raise SystemExit(
        HarnessMaintenanceCli().run(sys.argv[1:], environment=dict(os.environ), cwd=Path.cwd())
    )
