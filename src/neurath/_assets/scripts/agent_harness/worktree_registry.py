"""Cross-session worktree ownership을 per-resource transaction으로 조정합니다."""

import fcntl
import hashlib
import json
import os
import secrets
import subprocess
from contextlib import ExitStack
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TextIO

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorStatus,
    SessionId,
    SessionKernel,
    SessionKernelError,
    SessionLocator,
    WorktreeId,
)


class WorktreeOperation(StrEnum):
    """Worktree 접근이 state를 변경하는지 구분합니다."""

    READ_ONLY = "read-only"
    """Repository state를 바꾸지 않는 inspection입니다."""
    MUTATE = "mutate"
    """Owner fencing이 필요한 product 또는 repository mutation입니다."""


class WorktreeClaimStatus(StrEnum):
    """Shared claim이 허용하는 current resource lifecycle입니다."""

    ACTIVE = "active"
    """Current owner가 normal mutation 또는 handoff를 수행할 수 있습니다."""

    CLEANUP_RESERVED = "cleanup-reserved"
    """Exact owner의 fenced cleanup만 진행할 수 있고 다른 mutation은 차단됩니다."""


class WorktreeRegistryError(RuntimeError):
    """Shared worktree ownership contract를 만족할 수 없음을 나타냅니다."""


class WorktreeAlreadyClaimed(WorktreeRegistryError):
    """다른 active owner가 이미 worktree를 claim했음을 나타냅니다."""

    def __init__(self, existing_claim: WorktreeClaim) -> None:
        """충돌한 canonical owner를 오류에 보존합니다.

        Args:
            existing_claim: Exclusive transaction에서 확인한 현재 claim입니다.
        """
        self.existing_claim = existing_claim
        super().__init__(
            "worktree "
            f"{existing_claim.worktree_id} is owned by "
            f"{existing_claim.session_id}/{existing_claim.actor_id}"
        )


class WorktreeClaimInvalid(WorktreeRegistryError):
    """Claim identity, actor authority 또는 persisted shape가 잘못되었음을 나타냅니다."""


class WorktreeLeaseConflict(WorktreeRegistryError):
    """Owner, lease epoch 또는 fencing token이 current claim과 다름을 나타냅니다."""

    def __init__(self, current_claim: WorktreeClaim) -> None:
        """Caller가 재조회할 수 있도록 current fenced claim을 보존합니다.

        Args:
            current_claim: Exclusive lock 안에서 읽은 canonical claim입니다.
        """
        self.current_claim = current_claim
        super().__init__(
            "stale worktree lease for "
            f"{current_claim.worktree_id}: epoch {current_claim.lease_epoch}"
        )


class WorktreeCleanupInProgress(WorktreeRegistryError):
    """Fenced cleanup reservation이 다른 owner transition을 차단합니다."""

    def __init__(self, current_claim: WorktreeClaim) -> None:
        """충돌한 cleanup reservation을 diagnostic에 보존합니다.

        Args:
            current_claim: Cleanup-reserved 상태인 current fenced claim입니다.
        """
        self.current_claim = current_claim
        super().__init__(f"worktree cleanup is reserved: {current_claim.worktree_id}")


class WorktreeNotClaimed(WorktreeRegistryError):
    """Canonical registry에 해당 worktree claim이 없음을 나타냅니다."""


class WorktreeIdentityUnavailable(WorktreeRegistryError):
    """입력 path를 active Git worktree로 증명할 수 없을 때 발생합니다."""


class WorktreeIdentityAmbiguous(WorktreeRegistryError):
    """Git identity output이 canonical resource 하나로 수렴하지 않을 때 발생합니다."""


class CanonicalWorktreeIdentity:
    """Git common directory와 top-level에서 결정된 shared resource identity입니다."""

    __slots__ = ("_path", "_repository_control_root", "_worktree_id")

    def __init__(
        self,
        *,
        worktree_id: WorktreeId,
        path: Path,
        repository_control_root: Path,
    ) -> None:
        """Canonical worktree identity와 topology 경계를 함께 고정합니다.

        Args:
            worktree_id: Common-dir와 top-level의 stable digest로 만든 resource identity입니다.
            path: Git이 증명한 canonical worktree top-level입니다.
            repository_control_root: Linked worktree가 공유하는 SessionLocator control root입니다.
        """
        self._worktree_id = worktree_id
        self._path = path
        self._repository_control_root = repository_control_root

    @property
    def worktree_id(self) -> WorktreeId:
        """Shared registry에서 사용할 canonical worktree identity를 반환합니다.

        Returns:
            Filesystem path를 노출하지 않는 stable resource key입니다.
        """
        return self._worktree_id

    @property
    def path(self) -> Path:
        """Git이 증명한 canonical worktree top-level을 반환합니다.

        Returns:
            Nested cwd와 symlink를 정규화한 absolute top-level path입니다.
        """
        return self._path

    @property
    def repository_control_root(self) -> Path:
        """Root와 linked worktree가 공유하는 repository control root를 반환합니다.

        Returns:
            SessionLocator와 shared registry가 사용하는 canonical root입니다.
        """
        return self._repository_control_root


class WorktreeIdentityResolver:
    """Current filesystem path를 scan 없이 canonical Git worktree identity로 변환합니다."""

    SCHEMA = "neurath.coding-agent-worktree-identity.v1"

    def resolve(self, path: Path) -> CanonicalWorktreeIdentity:
        """Git common-dir와 top-level에서 deterministic worktree identity를 계산합니다.

        Ambient `GIT_*` environment는 제거하므로 caller가 준 path 이외의 repository로
        identity가 재결속되지 않습니다. Registry file을 조회하거나 existing claim을
        scan하지 않습니다.

        Args:
            path: Worktree top-level 또는 그 안의 현재 working directory입니다.

        Returns:
            Canonical resource ID, top-level, shared repository control root입니다.

        Raises:
            WorktreeIdentityUnavailable: Path가 directory가 아니거나 active Git worktree로
                증명되지 않으면 발생합니다.
            WorktreeIdentityAmbiguous: Git output이나 canonical path 관계가 하나의
                worktree identity로 수렴하지 않으면 발생합니다.
        """
        candidate = self._canonical_candidate(path)
        common_directory, top_level = self._git_identity(candidate)
        if candidate != top_level and not candidate.is_relative_to(top_level):
            raise WorktreeIdentityAmbiguous(
                "current path is outside the canonical Git worktree top-level"
            )
        control_root = (
            common_directory.parent if common_directory.name == ".git" else common_directory
        )
        if not control_root.is_dir():
            raise WorktreeIdentityAmbiguous("repository control root is not a directory")
        worktree_id = self._worktree_id(common_directory, top_level)
        return CanonicalWorktreeIdentity(
            worktree_id=worktree_id,
            path=top_level,
            repository_control_root=control_root,
        )

    def _canonical_candidate(self, path: Path) -> Path:
        try:
            candidate = path.resolve(strict=True)
        except OSError as error:
            raise WorktreeIdentityUnavailable(f"worktree path is unavailable: {path}") from error
        if not candidate.is_dir():
            raise WorktreeIdentityUnavailable(f"worktree path is not a directory: {candidate}")
        return candidate

    def _git_identity(self, candidate: Path) -> tuple[Path, Path]:
        try:
            completed = subprocess.run(
                (
                    "git",
                    "-C",
                    str(candidate),
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                    "--show-toplevel",
                    "--is-inside-work-tree",
                ),
                check=True,
                capture_output=True,
                text=True,
                env=self._git_environment(),
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise WorktreeIdentityUnavailable(
                f"path is not an active Git worktree: {candidate}"
            ) from error
        lines = completed.stdout.splitlines()
        if len(lines) != 3:
            raise WorktreeIdentityAmbiguous("Git worktree identity output is incomplete")
        common_directory_text, top_level_text, inside_worktree = lines
        if inside_worktree != "true":
            raise WorktreeIdentityUnavailable(f"path is not inside a Git worktree: {candidate}")
        common_directory = self._canonical_git_directory(
            common_directory_text,
            "common directory",
        )
        top_level = self._canonical_git_directory(top_level_text, "top-level")
        return common_directory, top_level

    def _canonical_git_directory(self, value: str, label: str) -> Path:
        git_path = Path(value)
        if not git_path.is_absolute():
            raise WorktreeIdentityAmbiguous(f"Git {label} is not absolute")
        try:
            canonical = git_path.resolve(strict=True)
        except OSError as error:
            raise WorktreeIdentityAmbiguous(f"Git {label} is unavailable") from error
        if not canonical.is_dir():
            raise WorktreeIdentityAmbiguous(f"Git {label} is not a directory")
        return canonical

    def _git_environment(self) -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        return environment

    def _worktree_id(self, common_directory: Path, top_level: Path) -> WorktreeId:
        identity = json.dumps(
            {
                "common_directory": str(common_directory),
                "schema": self.SCHEMA,
                "top_level": str(top_level),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return WorktreeId(f"git-worktree-{digest}")


class WorktreeClaim:
    """Shared worktree 하나의 current exclusive owner를 표현합니다."""

    SCHEMA = "neurath.coding-agent-worktree-claim.v3"
    LEGACY_SCHEMA = "neurath.coding-agent-worktree-claim.v2"

    __slots__ = (
        "_actor_id",
        "_fencing_token",
        "_lease_epoch",
        "_path",
        "_session_id",
        "_status",
        "_transition_id",
        "_worktree_id",
    )

    def __init__(
        self,
        *,
        worktree_id: WorktreeId,
        path: Path,
        session_id: SessionId,
        actor_id: ActorId,
        lease_epoch: int = 0,
        fencing_token: str = "",
        status: WorktreeClaimStatus = WorktreeClaimStatus.ACTIVE,
        transition_id: str | None = None,
    ) -> None:
        """Worktree resource identity와 owner identity를 결합합니다.

        Args:
            worktree_id: Shared registry에서 안정적인 resource identity입니다.
            path: Claim 대상 worktree의 canonical filesystem path입니다.
            session_id: Owner actor가 속한 session입니다.
            actor_id: Product mutation authority를 받을 actor입니다.
            lease_epoch: Current claim generation입니다. 새 claim 요청은 0입니다.
            fencing_token: Current generation의 opaque writer token입니다.
            status: Normal ownership 또는 fenced cleanup reservation lifecycle입니다.
            transition_id: Current generation을 만든 exact handoff provenance입니다.

        Raises:
            WorktreeClaimInvalid: Lease epoch가 음수이면 발생합니다.
        """
        if lease_epoch < 0:
            raise WorktreeClaimInvalid("worktree lease_epoch must not be negative")
        if not isinstance(status, WorktreeClaimStatus):
            raise WorktreeClaimInvalid("worktree claim status is invalid")
        if transition_id is not None and (
            not isinstance(transition_id, str) or not transition_id.strip()
        ):
            raise WorktreeClaimInvalid("worktree transition_id must not be empty")
        self._worktree_id = worktree_id
        self._path = path.resolve()
        self._session_id = session_id
        self._actor_id = actor_id
        self._lease_epoch = lease_epoch
        self._fencing_token = fencing_token
        self._status = status
        self._transition_id = None if transition_id is None else transition_id.strip()

    @property
    def worktree_id(self) -> WorktreeId:
        """Claim 대상 worktree identity를 반환합니다.

        Returns:
            Shared registry의 stable worktree identity입니다.
        """
        return self._worktree_id

    @property
    def path(self) -> Path:
        """Claim 대상 canonical filesystem path를 반환합니다.

        Returns:
            Resolve된 worktree directory path입니다.
        """
        return self._path

    @property
    def session_id(self) -> SessionId:
        """Owner actor가 속한 session identity를 반환합니다.

        Returns:
            Current owner actor의 canonical session identity입니다.
        """
        return self._session_id

    @property
    def actor_id(self) -> ActorId:
        """현재 mutation owner actor identity를 반환합니다.

        Returns:
            Current worktree mutation owner actor identity입니다.
        """
        return self._actor_id

    @property
    def lease_epoch(self) -> int:
        """Current ownership generation을 반환합니다.

        Returns:
            Claim 또는 handoff 때 단조 증가하는 lease epoch입니다.
        """
        return self._lease_epoch

    @property
    def fencing_token(self) -> str:
        """Stale writer를 차단하는 current opaque token을 반환합니다.

        Returns:
            Current lease generation에만 유효한 opaque fencing token입니다.
        """
        return self._fencing_token

    @property
    def status(self) -> WorktreeClaimStatus:
        """Current claim lifecycle을 반환합니다.

        Returns:
            Active ownership 또는 cleanup reservation 상태입니다.
        """
        return self._status

    @property
    def transition_id(self) -> str | None:
        """Current generation을 만든 exact handoff provenance를 반환합니다.

        Returns:
            Direct claim/handoff는 None, proof-bound handoff는 stable transition ID입니다.
        """
        return self._transition_id

    def to_payload(self) -> dict[str, object]:
        """Shared registry에 저장할 bounded claim payload를 반환합니다.

        Returns:
            Resource와 fenced owner identity만 포함한 JSON object입니다.
        """
        return {
            "schema": self.SCHEMA,
            "worktree_id": str(self._worktree_id),
            "path": str(self._path),
            "session_id": str(self._session_id),
            "actor_id": str(self._actor_id),
            "lease_epoch": self._lease_epoch,
            "fencing_token": self._fencing_token,
            "status": self._status.value,
            "transition_id": self._transition_id,
        }


class WorktreeAccess:
    """Actor가 요청한 worktree operation을 표현합니다."""

    __slots__ = ("_actor_id", "_operation", "_session_id", "_worktree_id")

    def __init__(
        self,
        *,
        worktree_id: WorktreeId,
        session_id: SessionId,
        actor_id: ActorId,
        operation: WorktreeOperation,
    ) -> None:
        """Resource, actor, operation identity를 하나의 authorization input으로 묶습니다.

        Args:
            worktree_id: 접근 대상 worktree identity입니다.
            session_id: 요청 actor가 속한 session입니다.
            actor_id: 접근을 요청한 actor입니다.
            operation: Read-only inspection 또는 product mutation입니다.
        """
        self._worktree_id = worktree_id
        self._session_id = session_id
        self._actor_id = actor_id
        self._operation = operation

    @property
    def worktree_id(self) -> WorktreeId:
        """접근 대상 worktree identity를 반환합니다.

        Returns:
            Authorization 대상 shared resource identity입니다.
        """
        return self._worktree_id

    @property
    def session_id(self) -> SessionId:
        """요청 actor가 속한 session identity를 반환합니다.

        Returns:
            접근을 요청한 actor의 canonical session identity입니다.
        """
        return self._session_id

    @property
    def actor_id(self) -> ActorId:
        """접근을 요청한 actor identity를 반환합니다.

        Returns:
            Worktree operation을 요청한 actor identity입니다.
        """
        return self._actor_id

    @property
    def operation(self) -> WorktreeOperation:
        """Authorization 대상 operation을 반환합니다.

        Returns:
            Read-only inspection 또는 fenced mutation 구분입니다.
        """
        return self._operation


class WorktreeAccessDecision:
    """Worktree authorization의 deterministic allow/deny 결과입니다."""

    __slots__ = ("_allowed", "_reason")

    def __init__(self, *, allowed: bool, reason: str) -> None:
        """Decision 결과와 machine-readable reason을 고정합니다.

        Args:
            allowed: 요청을 허용하면 참입니다.
            reason: Allow/deny 원인을 나타내는 안정적인 문자열입니다.
        """
        self._allowed = allowed
        self._reason = reason

    @property
    def allowed(self) -> bool:
        """요청을 허용하는지 반환합니다.

        Returns:
            Harness가 해당 operation을 허용하면 참입니다.
        """
        return self._allowed

    @property
    def reason(self) -> str:
        """Allow/deny 원인의 안정적인 문자열을 반환합니다.

        Returns:
            Runtime-neutral authorization reason code입니다.
        """
        return self._reason


class WorktreeRegistry:
    """Worktree별 lock file로 cross-session exclusive claim을 직렬화합니다."""

    def __init__(self, locator: SessionLocator) -> None:
        """Canonical repository control root에서 shared resource registry를 엽니다.

        Args:
            locator: Session과 shared resource가 속한 repository locator입니다.
        """
        self._locator = locator
        self._kernel = SessionKernel(locator)
        self._registry_root = locator.worktree_registry_root

    def claim(self, claim: WorktreeClaim) -> WorktreeClaim:
        """Worktree를 active actor 한 명에게 원자적으로 claim합니다.

        동일 owner의 retry는 idempotent하며 다른 owner 또는 다른 path의 claim은
        canonical state를 바꾸지 않고 거부합니다.

        Args:
            claim: Worktree resource와 desired owner identity입니다.

        Returns:
            Commit되었거나 이미 동일했던 canonical claim입니다.

        Raises:
            WorktreeAlreadyClaimed: 다른 owner 또는 path의 claim이 존재하면 발생합니다.
            WorktreeClaimInvalid: Session에 actor가 없거나 path/identity가 잘못되면 발생합니다.
        """
        self._validate_claim_shape(claim)
        claim_path = self._claim_path(claim.worktree_id)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        active_claim = self._activate(claim, lease_epoch=1)
        serialized = self._serialize_claim(active_claim)
        session_lock = self._open_session_lock(claim.session_id)
        with session_lock:
            fcntl.flock(session_lock.fileno(), fcntl.LOCK_EX)
            try:
                self._validate_claim_authority(claim)
                with self._open_lock(claim_path) as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        if claim_path.exists():
                            current = self._read_claim(claim_path, claim.worktree_id)
                            if current.status is WorktreeClaimStatus.CLEANUP_RESERVED:
                                raise WorktreeCleanupInProgress(current)
                            if not self._same_owner(current, claim):
                                raise WorktreeAlreadyClaimed(current)
                            return current
                        self._write_locked(claim_path, serialized)
                        return active_claim
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(session_lock.fileno(), fcntl.LOCK_UN)

    def get(self, worktree_id: WorktreeId) -> WorktreeClaim:
        """Exact worktree의 current claim을 읽습니다.

        Args:
            worktree_id: 조회할 shared resource identity입니다.

        Returns:
            Current exclusive owner claim입니다.

        Raises:
            WorktreeNotClaimed: Claim file이 없으면 발생합니다.
            WorktreeClaimInvalid: Persisted shape가 잘못되면 발생합니다.
        """
        claim_path = self._claim_path(worktree_id)
        return self._read_claim(claim_path, worktree_id)

    def authorize(self, access: WorktreeAccess) -> WorktreeAccessDecision:
        """Read-only는 즉시 허용하고 mutation은 coherent owner authority를 판정합니다.

        Args:
            access: Resource, actor, operation을 포함한 authorization input입니다.

        Returns:
            Deterministic allow/deny decision입니다.
        """
        if access.operation is WorktreeOperation.READ_ONLY:
            return WorktreeAccessDecision(allowed=True, reason="read-only")
        claim_path = self._claim_path(access.worktree_id)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        session_lock = self._open_session_lock(access.session_id)
        with session_lock:
            fcntl.flock(session_lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._open_lock(claim_path) as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        try:
                            claim = self._read_claim(claim_path, access.worktree_id)
                        except WorktreeNotClaimed:
                            return WorktreeAccessDecision(allowed=False, reason="unclaimed")
                        if claim.status is WorktreeClaimStatus.CLEANUP_RESERVED:
                            return WorktreeAccessDecision(
                                allowed=False,
                                reason="cleanup-reserved",
                            )
                        owner_matches = (
                            claim.session_id == access.session_id
                            and claim.actor_id == access.actor_id
                        )
                        if not owner_matches:
                            return WorktreeAccessDecision(
                                allowed=False,
                                reason="non-owner",
                            )
                        try:
                            self._validate_claim_authority(claim)
                        except WorktreeClaimInvalid:
                            return WorktreeAccessDecision(
                                allowed=False,
                                reason="inactive-owner",
                            )
                        return WorktreeAccessDecision(allowed=True, reason="owner")
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(session_lock.fileno(), fcntl.LOCK_UN)

    def release(self, expected_claim: WorktreeClaim) -> None:
        """Exact owner, epoch, token이 일치하는 current claim을 제거합니다.

        Args:
            expected_claim: 직전에 read한 fenced current claim입니다.

        Raises:
            WorktreeNotClaimed: Current claim이 없으면 발생합니다.
            WorktreeLeaseConflict: Owner, path, epoch 또는 token이 stale하면 발생합니다.
        """
        claim_path = self._claim_path(expected_claim.worktree_id)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        session_lock = self._open_session_lock(expected_claim.session_id)
        with session_lock:
            fcntl.flock(session_lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._open_lock(claim_path) as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        if not claim_path.exists():
                            raise WorktreeNotClaimed(
                                f"worktree {expected_claim.worktree_id} is not claimed"
                            )
                        current = self._read_claim(claim_path, expected_claim.worktree_id)
                        self._require_current_lease(current, expected_claim)
                        self._require_active_claim(current)
                        self._validate_claim_authority(current)
                        claim_path.unlink()
                        self._fsync_directory(claim_path.parent)
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(session_lock.fileno(), fcntl.LOCK_UN)

    def handoff(
        self,
        expected_claim: WorktreeClaim,
        *,
        next_session_id: SessionId,
        next_actor_id: ActorId,
        transition_id: str | None = None,
    ) -> WorktreeClaim:
        """Exact fenced owner에서 다음 active actor로 ownership을 원자적으로 넘깁니다.

        Args:
            expected_claim: 직전에 read한 fenced current claim입니다.
            next_session_id: 새 owner actor가 속한 session입니다.
            next_actor_id: 새 mutation owner actor입니다.
            transition_id: Lifecycle retry를 exact proof에 결속하는 optional provenance입니다.

        Returns:
            Epoch이 증가하고 새 fencing token을 가진 current claim입니다.

        Raises:
            WorktreeNotClaimed: Current claim이 없으면 발생합니다.
            WorktreeLeaseConflict: Expected owner, epoch 또는 token이 stale하면 발생합니다.
            WorktreeClaimInvalid: 새 owner가 active session actor가 아니면 발생합니다.
        """
        desired = WorktreeClaim(
            worktree_id=expected_claim.worktree_id,
            path=expected_claim.path,
            session_id=next_session_id,
            actor_id=next_actor_id,
            transition_id=transition_id,
        )
        self._validate_claim_shape(desired)
        next_claim = self._activate(
            desired,
            lease_epoch=expected_claim.lease_epoch + 1,
        )
        serialized = self._serialize_claim(next_claim)
        claim_path = self._claim_path(expected_claim.worktree_id)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        authority_session_ids = tuple(
            sorted(
                {expected_claim.session_id, next_session_id},
                key=str,
            )
        )
        with ExitStack() as stack:
            session_locks = tuple(
                stack.enter_context(self._open_session_lock(session_id))
                for session_id in authority_session_ids
            )
            for session_lock in session_locks:
                fcntl.flock(session_lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._open_lock(claim_path) as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        if not claim_path.exists():
                            raise WorktreeNotClaimed(
                                f"worktree {expected_claim.worktree_id} is not claimed"
                            )
                        current = self._read_claim(claim_path, expected_claim.worktree_id)
                        self._require_current_lease(current, expected_claim)
                        self._require_active_claim(current)
                        self._validate_claim_authority(current)
                        self._validate_claim_authority(desired)
                        self._write_locked(claim_path, serialized)
                        return next_claim
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                for session_lock in reversed(session_locks):
                    fcntl.flock(session_lock.fileno(), fcntl.LOCK_UN)

    def reserve_cleanup(
        self,
        expected_claim: WorktreeClaim,
        *,
        planned_fencing_token: str | None = None,
    ) -> WorktreeClaim:
        """Destructive Git cleanup 전에 exact active lease를 durable reservation으로 바꿉니다.

        Candidate와 serialization은 lock 밖에서 준비하고, short session/worktree mutex
        구간에서는 owner authority와 expected lease를 다시 비교한 뒤 atomic replace만
        수행합니다. Reservation 이후 normal mutation, release, handoff는 거부됩니다.

        Args:
            expected_claim: Cleanup command가 직전에 읽은 active fenced claim입니다.
            planned_fencing_token: Durable intent가 미리 고정한 optional next token입니다.

        Returns:
            Epoch과 token이 회전한 cleanup-reserved claim입니다.

        Raises:
            WorktreeNotClaimed: Current claim이 사라졌으면 발생합니다.
            WorktreeLeaseConflict: Expected lease가 stale하면 발생합니다.
            WorktreeCleanupInProgress: Current claim이 이미 cleanup-reserved이면 발생합니다.
            WorktreeClaimInvalid: Owner actor가 더는 active가 아니면 발생합니다.
        """
        self._validate_claim_shape(expected_claim)
        if planned_fencing_token is not None and (
            not isinstance(planned_fencing_token, str) or not planned_fencing_token.strip()
        ):
            raise WorktreeClaimInvalid("planned cleanup fencing token must not be empty")
        if planned_fencing_token == expected_claim.fencing_token:
            raise WorktreeClaimInvalid("planned cleanup fencing token must rotate the active token")
        reservation = self._activate(
            expected_claim,
            lease_epoch=expected_claim.lease_epoch + 1,
            status=WorktreeClaimStatus.CLEANUP_RESERVED,
            fencing_token=planned_fencing_token,
        )
        serialized = self._serialize_claim(reservation)
        claim_path = self._claim_path(expected_claim.worktree_id)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        session_lock = self._open_session_lock(expected_claim.session_id)
        with session_lock:
            fcntl.flock(session_lock.fileno(), fcntl.LOCK_EX)
            try:
                self._validate_claim_authority(expected_claim)
                with self._open_lock(claim_path) as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        if not claim_path.exists():
                            raise WorktreeNotClaimed(
                                f"worktree {expected_claim.worktree_id} is not claimed"
                            )
                        current = self._read_claim(claim_path, expected_claim.worktree_id)
                        self._require_current_lease(current, expected_claim)
                        self._require_active_claim(current)
                        self._write_locked(claim_path, serialized)
                        return reservation
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(session_lock.fileno(), fcntl.LOCK_UN)

    def complete_cleanup(self, expected_reservation: WorktreeClaim) -> None:
        """External cleanup 성공 뒤 exact reservation만 제거합니다.

        Args:
            expected_reservation: Cleanup effect를 승인했던 exact reservation lease입니다.

        Raises:
            WorktreeNotClaimed: Reservation이 사라졌으면 발생합니다.
            WorktreeLeaseConflict: Reservation generation이 달라졌으면 발생합니다.
            WorktreeCleanupInProgress: Expected/current claim이 cleanup reservation이 아니면
                발생합니다.
            WorktreeClaimInvalid: Reservation owner authority가 더는 active가 아니면
                발생합니다.
        """
        claim_path = self._claim_path(expected_reservation.worktree_id)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        session_lock = self._open_session_lock(expected_reservation.session_id)
        with session_lock:
            fcntl.flock(session_lock.fileno(), fcntl.LOCK_EX)
            try:
                self._validate_claim_authority(expected_reservation)
                with self._open_lock(claim_path) as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        if not claim_path.exists():
                            raise WorktreeNotClaimed(
                                f"worktree {expected_reservation.worktree_id} is not claimed"
                            )
                        current = self._read_claim(
                            claim_path,
                            expected_reservation.worktree_id,
                        )
                        self._require_current_lease(current, expected_reservation)
                        if current.status is not WorktreeClaimStatus.CLEANUP_RESERVED:
                            raise WorktreeCleanupInProgress(current)
                        claim_path.unlink()
                        self._fsync_directory(claim_path.parent)
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(session_lock.fileno(), fcntl.LOCK_UN)

    def _validate_claim_shape(self, claim: WorktreeClaim) -> None:
        if not claim.path.is_dir():
            raise WorktreeClaimInvalid(f"worktree path is not a directory: {claim.path}")

    def _validate_claim_authority(self, claim: WorktreeClaim) -> None:
        """Held process-state mutex 아래 exact actor authority를 다시 확인합니다.

        Args:
            claim: Commit하려는 owner session과 actor identity입니다.

        Raises:
            WorktreeClaimInvalid: Session이 terminal이거나 actor가 active가 아니면 발생합니다.
        """
        try:
            state = self._kernel.inspect(claim.session_id)
        except SessionKernelError as error:
            raise WorktreeClaimInvalid(
                f"session {claim.session_id} cannot prove active actor authority"
            ) from error
        actor = state.actors.get(claim.actor_id)
        if (
            state.session.status.value != "active"
            or actor is None
            or actor.status is not ActorStatus.ACTIVE
        ):
            raise WorktreeClaimInvalid(
                f"actor {claim.actor_id} is not active in session {claim.session_id}"
            )

    def _claim_path(self, worktree_id: WorktreeId) -> Path:
        value = str(worktree_id)
        if not value or Path(value).name != value or value in {".", ".."}:
            raise WorktreeClaimInvalid("worktree_id must be one non-blank path segment")
        return self._registry_root / f"{value}.json"

    def _open_lock(self, claim_path: Path) -> TextIO:
        return claim_path.with_name(f"{claim_path.name}.lock").open(
            "a+",
            encoding="utf-8",
        )

    def _open_session_lock(self, session_id: SessionId) -> TextIO:
        paths = self._locator.locate(session_id)
        paths.process_state_lock.parent.mkdir(parents=True, exist_ok=True)
        return paths.process_state_lock.open("a+", encoding="utf-8")

    def _read_claim(self, claim_path: Path, worktree_id: WorktreeId) -> WorktreeClaim:
        try:
            raw_payload: object = json.loads(claim_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise WorktreeNotClaimed(f"worktree {worktree_id} is not claimed") from None
        except (json.JSONDecodeError, OSError) as exc:
            raise WorktreeClaimInvalid(
                f"canonical worktree claim is invalid: {claim_path}"
            ) from exc
        if not isinstance(raw_payload, dict):
            raise WorktreeClaimInvalid("canonical worktree claim root must be an object")
        schema = raw_payload.get("schema")
        legacy_fields = {
            "schema",
            "worktree_id",
            "path",
            "session_id",
            "actor_id",
            "lease_epoch",
            "fencing_token",
            "status",
        }
        current_fields = {*legacy_fields, "transition_id"}
        if schema == WorktreeClaim.SCHEMA:
            expected_fields = current_fields
        elif schema == WorktreeClaim.LEGACY_SCHEMA:
            expected_fields = legacy_fields
        else:
            raise WorktreeClaimInvalid("canonical worktree claim schema is unsupported")
        if set(raw_payload) != expected_fields:
            raise WorktreeClaimInvalid("canonical worktree claim fields are invalid")
        persisted_worktree_id = raw_payload.get("worktree_id")
        path = raw_payload.get("path")
        session_id = raw_payload.get("session_id")
        actor_id = raw_payload.get("actor_id")
        lease_epoch = raw_payload.get("lease_epoch")
        fencing_token = raw_payload.get("fencing_token")
        status = raw_payload.get("status")
        transition_id = raw_payload.get("transition_id") if schema == WorktreeClaim.SCHEMA else None
        if persisted_worktree_id != str(worktree_id):
            raise WorktreeClaimInvalid("canonical worktree identity mismatch")
        if (
            not isinstance(path, str)
            or not isinstance(session_id, str)
            or not isinstance(actor_id, str)
            or not isinstance(lease_epoch, int)
            or isinstance(lease_epoch, bool)
            or not isinstance(fencing_token, str)
            or not isinstance(status, str)
            or (transition_id is not None and not isinstance(transition_id, str))
        ):
            raise WorktreeClaimInvalid("canonical worktree claim identity is invalid")
        if lease_epoch < 1 or not fencing_token:
            raise WorktreeClaimInvalid("canonical worktree fencing lease is invalid")
        return WorktreeClaim(
            worktree_id=worktree_id,
            path=Path(path),
            session_id=SessionId(session_id),
            actor_id=ActorId(actor_id),
            lease_epoch=lease_epoch,
            fencing_token=fencing_token,
            status=self._claim_status(status),
            transition_id=transition_id,
        )

    def _same_owner(self, current: WorktreeClaim, desired: WorktreeClaim) -> bool:
        return (
            current.worktree_id == desired.worktree_id
            and current.path == desired.path
            and current.session_id == desired.session_id
            and current.actor_id == desired.actor_id
        )

    def _activate(
        self,
        claim: WorktreeClaim,
        *,
        lease_epoch: int,
        status: WorktreeClaimStatus = WorktreeClaimStatus.ACTIVE,
        fencing_token: str | None = None,
    ) -> WorktreeClaim:
        return WorktreeClaim(
            worktree_id=claim.worktree_id,
            path=claim.path,
            session_id=claim.session_id,
            actor_id=claim.actor_id,
            lease_epoch=lease_epoch,
            fencing_token=secrets.token_hex(32) if fencing_token is None else fencing_token,
            status=status,
            transition_id=claim.transition_id,
        )

    def _require_current_lease(
        self,
        current: WorktreeClaim,
        expected: WorktreeClaim,
    ) -> None:
        if (
            not self._same_owner(current, expected)
            or current.lease_epoch != expected.lease_epoch
            or current.fencing_token != expected.fencing_token
            or current.status is not expected.status
            or current.transition_id != expected.transition_id
        ):
            raise WorktreeLeaseConflict(current)

    def _require_active_claim(self, claim: WorktreeClaim) -> None:
        if claim.status is not WorktreeClaimStatus.ACTIVE:
            raise WorktreeCleanupInProgress(claim)

    def _claim_status(self, value: str) -> WorktreeClaimStatus:
        try:
            return WorktreeClaimStatus(value)
        except ValueError as error:
            raise WorktreeClaimInvalid("canonical worktree claim status is invalid") from error

    def _serialize_claim(self, claim: WorktreeClaim) -> bytes:
        """Candidate claim을 commit mutex 밖에서 canonical bytes로 준비합니다.

        Args:
            claim: Authority validation을 통과한 immutable candidate입니다.

        Returns:
            Atomic replace에 바로 사용할 deterministic UTF-8 JSON입니다.
        """
        return (
            json.dumps(
                claim.to_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def _write_locked(self, claim_path: Path, serialized: bytes) -> None:
        """Prepared claim bytes를 짧은 commit mutex 안에서 atomic replace합니다.

        Args:
            claim_path: Per-resource mutex가 보호하는 canonical claim path입니다.
            serialized: Lock 밖에서 직렬화와 검증을 끝낸 complete bytes입니다.
        """
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                "wb",
                dir=claim_path.parent,
                prefix=f".{claim_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, claim_path)
            self._fsync_directory(claim_path.parent)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    def _fsync_directory(self, directory: Path) -> None:
        """Replace 또는 unlink directory entry를 crash-safe하게 durable flush합니다.

        Args:
            directory: Claim file entry를 소유하는 registry directory입니다.
        """
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
