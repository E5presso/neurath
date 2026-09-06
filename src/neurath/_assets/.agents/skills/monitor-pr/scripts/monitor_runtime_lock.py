"""Monitor runtime directory의 짧은 file-effect commit 경계를 공유합니다."""

import fcntl
import glob
from pathlib import Path
from typing import Self, TextIO


class MonitorRuntimeCommitConflict(RuntimeError):
    """Prepared handoff가 exact runtime file path를 claim한 동안 발생합니다."""


class MonitorRuntimeCommitLock:
    """Cooperating monitor file writer끼리 짧은 commit 구간만 직렬화합니다."""

    __slots__ = ("_lock", "_path")

    def __init__(self, state_dir: Path) -> None:
        """Canonical runtime directory에 stable advisory lock path를 고정합니다.

        Args:
            state_dir: Monitor file resources를 소유하는 worktree-local directory입니다.
        """
        self._path = state_dir / ".monitor-handoff.commit.lock"
        self._lock: TextIO | None = None

    def __enter__(self) -> Self:
        """Exclusive advisory lock을 획득하고 context manager를 반환합니다.

        Returns:
            Lock descriptor를 소유한 current context manager입니다.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._path.open("a+", encoding="utf-8")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        self._lock = lock
        return self

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        """Advisory lock을 해제하고 descriptor를 닫습니다.

        Args:
            exception_type: Context body exception type입니다.
            exception: Context body exception instance입니다.
            traceback: Context body traceback입니다.
        """
        del exception_type, exception, traceback
        lock = self._lock
        if lock is None:
            return
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
        self._lock = None


def monitor_runtime_claim_path(
    state_dir: Path,
    *,
    handoff_id: str,
    target_name: str,
) -> Path:
    """Prepared handoff와 exact basename에서 deterministic claim path를 만듭니다.

    Args:
        state_dir: Claimed target이 속한 canonical runtime directory입니다.
        handoff_id: Durable prepared plan의 lowercase hexadecimal identity입니다.
        target_name: Same-directory original file basename입니다.

    Returns:
        Crash 뒤 같은 prepared plan이 다시 찾을 hidden claim path입니다.

    Raises:
        ValueError: Handoff identity 또는 target basename이 unsafe하면 발생합니다.
    """
    if (
        len(handoff_id) != 32
        or any(character not in "0123456789abcdef" for character in handoff_id)
        or not target_name
        or Path(target_name).name != target_name
    ):
        raise ValueError("monitor runtime claim identity is invalid")
    return state_dir / f".monitor-handoff.{handoff_id}.{target_name}.claimed"


def monitor_runtime_target_is_claimed(state_dir: Path, target_name: str) -> bool:
    """Any prepared handoff가 exact basename을 claim 중인지 read-back합니다.

    Args:
        state_dir: Target과 claim이 함께 속한 canonical runtime directory입니다.
        target_name: Launch writer가 교체하려는 exact output basename입니다.

    Returns:
        하나 이상의 durable claim marker가 존재하면 True입니다.
    """
    return any(state_dir.glob(f".monitor-handoff.*.{glob.escape(target_name)}.claimed"))
