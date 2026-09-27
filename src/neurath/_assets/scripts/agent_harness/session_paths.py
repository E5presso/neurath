"""Resolve exact session persistence paths from a repository control root."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts._neurath_paths import state_path
from scripts.agent_harness.session_model import (
    ImmutableValue,
    InvalidIdentity,
    SessionId,
)


class SessionPaths(ImmutableValue):
    """한 exact session의 canonical persistence path 모음입니다."""

    __slots__ = (
        "artifacts",
        "directory",
        "enclave",
        "enclave_lock",
        "process_state",
        "process_state_lock",
    )

    def __init__(self, directory: Path) -> None:
        """Exact session directory에서 모든 canonical persistence path를 계산합니다.

        Args:
            directory: 단일 session이 소유하는 canonical control-plane directory입니다.
        """
        object.__setattr__(self, "directory", directory)
        object.__setattr__(self, "process_state", directory / ".process-state.json")
        object.__setattr__(self, "process_state_lock", directory / ".process-state.json.lock")
        object.__setattr__(self, "enclave", directory / "enclave.json")
        object.__setattr__(self, "enclave_lock", directory / "enclave.json.lock")
        object.__setattr__(self, "artifacts", directory / "artifacts")

    directory: Path
    """단일 exact session이 소유하는 canonical control-plane directory입니다."""

    process_state: Path
    """Revision과 operational snapshot을 보존하는 canonical JSON file입니다."""

    process_state_lock: Path
    """Process-state compare-and-swap commit 구간을 직렬화하는 lock file입니다."""

    enclave: Path
    """Session-private durable fact를 격리해 보존하는 enclave JSON file입니다."""

    enclave_lock: Path
    """Enclave 최초 생성을 직렬화하는 lock file입니다."""

    artifacts: Path
    """Exact session 실행에서 생성한 artifact를 격리하는 directory입니다."""


class SessionLocator:
    """Validated session identity를 canonical control-plane path로 변환합니다."""

    def __init__(self, control_root: Path) -> None:
        """Repository 공통 control-plane root에 locator를 고정합니다.

        Args:
            control_root: 모든 linked worktree가 공유할 repository control root입니다.
        """
        self._control_root = control_root.absolute()

    @property
    def control_root(self) -> Path:
        """Repository control-plane root를 반환합니다.

        Returns:
            Session directory와 resource registry를 포함하는 absolute root입니다.
        """
        return self._control_root

    @property
    def worktree_registry_root(self) -> Path:
        """Cross-session worktree claim registry path를 반환합니다.

        Returns:
            모든 session이 공유하는 worktree claim directory입니다.
        """
        return state_path(self._control_root, "resources/worktrees")

    @classmethod
    def from_worktree(cls, worktree: Path) -> SessionLocator:
        """Git common directory에서 linked worktree 공통 control root를 결정합니다.

        Args:
            worktree: Repository 또는 linked worktree 안의 경로입니다.

        Returns:
            Git common directory를 기준으로 모든 worktree가 공유하는 locator입니다.

        Raises:
            subprocess.CalledProcessError: 경로가 유효한 Git worktree가 아니면 발생합니다.
        """
        completed = subprocess.run(
            (
                "git",
                "-C",
                str(worktree),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        common_directory = Path(completed.stdout.strip()).resolve()
        if common_directory.name == ".git":
            return cls(common_directory.parent)
        return cls(common_directory)

    def locate(self, session_id: SessionId) -> SessionPaths:
        """Exact session directory를 scan 없이 결정합니다.

        Args:
            session_id: Canonical directory 이름으로 사용할 validated session identity입니다.

        Returns:
            다른 session으로 fallback하지 않는 exact persistence path 모음입니다.

        Raises:
            InvalidIdentity: Session identity가 path traversal을 허용하면 발생합니다.
        """
        self._validate_path_identity(session_id)
        return SessionPaths(state_path(self._control_root, "runs") / str(session_id))

    def _validate_path_identity(self, session_id: SessionId) -> None:
        if session_id in {SessionId("."), SessionId("..")}:
            raise InvalidIdentity(f"unsafe session id: {session_id}")
        if "/" in session_id or "\\" in session_id or "\x00" in session_id:
            raise InvalidIdentity(f"unsafe session id: {session_id}")
