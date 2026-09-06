"""Repository primary source를 current Git worktree bytes에서 read-back합니다."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class RepositoryReadbackError(RuntimeError):
    """Repository source를 deterministic하게 읽을 수 없음을 나타냅니다."""


class RepositoryReadbackInvalid(RepositoryReadbackError):
    """Reference 또는 대상이 canonical tracked regular file이 아닙니다."""


class RepositoryReadbackConflict(RepositoryReadbackError):
    """Readback 도중 current worktree bytes가 바뀌었습니다."""


@dataclass(frozen=True, slots=True)
class RepositoryFileReadback:
    """한 tracked file을 current worktree fingerprint와 content digest에 결속합니다."""

    relative_path: str
    """Repository root에서 대상 tracked file까지의 canonical 상대 경로입니다."""

    worktree_fingerprint: str
    """File을 읽은 stable current worktree 전체의 SHA-256 identity입니다."""

    content_digest: str
    """Readback한 exact file bytes의 SHA-256 digest입니다."""


class RepositoryWorktreeReadback:
    """Git이 추적하는 current regular file만 primary source로 제공합니다."""

    _RUNTIME_PREFIX = (b".agents/runs/", b".neurath/local/")

    def __init__(self, repository_root: Path) -> None:
        """Canonical Git worktree root를 고정합니다.

        Args:
            repository_root: Readback이 절대 벗어나지 않을 repository root입니다.

        Raises:
            RepositoryReadbackInvalid: 경로가 directory가 아니거나 Git root가 아니면
                발생합니다.
        """
        root = repository_root.resolve()
        if not root.is_dir():
            raise RepositoryReadbackInvalid("repository root must be an existing directory")
        top_level = self._git(root, ("rev-parse", "--show-toplevel"), allow_failure=True)
        if not top_level:
            raise RepositoryReadbackInvalid("repository root must be a Git worktree")
        decoded_top_level = Path(os.fsdecode(top_level.strip())).resolve()
        if decoded_top_level != root:
            raise RepositoryReadbackInvalid("repository root must be the Git worktree top level")
        self._root = root

    def worktree_fingerprint(self) -> str:
        """HEAD와 ignored runtime을 뺀 tracked/untracked current bytes를 digest합니다.

        Returns:
            Current worktree identity를 나타내는 SHA-256 hex digest입니다.

        Raises:
            RepositoryReadbackInvalid: Git inventory 또는 file bytes를 읽지 못하면 발생합니다.
        """
        head = __import__("scripts._neurath_paths", fromlist=["repository_head"]).repository_head(self._root, self._git)
        index = self._git(
            self._root,
            ("ls-files", "-z", "--stage"),
            allow_failure=False,
        )
        inventory = self._git(
            self._root,
            (
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ),
            allow_failure=False,
        )
        relative_paths = sorted(
            value
            for value in inventory.split(b"\0")
            if value and not value.startswith(self._RUNTIME_PREFIX)
        )
        digest = hashlib.sha256()
        digest.update(b"head\0" + head + b"\0")
        digest.update(b"index\0" + index + b"\0")
        try:
            for encoded_path in relative_paths:
                relative_path = os.fsdecode(encoded_path)
                candidate = self._root / relative_path
                digest.update(encoded_path + b"\0")
                if candidate.is_symlink():
                    digest.update(b"symlink\0" + os.fsencode(candidate.readlink()) + b"\0")
                elif candidate.is_file():
                    executable = b"x" if candidate.stat().st_mode & 0o111 else b"-"
                    digest.update(b"file\0" + executable + b"\0" + candidate.read_bytes() + b"\0")
                elif candidate.exists():
                    digest.update(b"directory\0")
                else:
                    digest.update(b"missing\0")
        except OSError as error:
            raise RepositoryReadbackInvalid("cannot read current worktree bytes") from error
        return digest.hexdigest()

    def read_tracked_file(self, reference: str) -> RepositoryFileReadback:
        """Canonical tracked regular file을 stable current snapshot에서 읽습니다.

        Args:
            reference: Repository root 기준 canonical POSIX relative file path입니다.

        Returns:
            같은 stable worktree에서 계산한 path, worktree, content digest입니다.

        Raises:
            RepositoryReadbackInvalid: Traversal, symlink, missing, ignored/untracked file이면
                발생합니다.
            RepositoryReadbackConflict: Readback 전후 worktree bytes가 달라지면 발생합니다.
        """
        relative_path = self._canonical_reference(reference)
        self._require_tracked(relative_path)
        candidate = self._regular_file(relative_path)
        before = self.worktree_fingerprint()
        try:
            content = candidate.read_bytes()
        except OSError as error:
            raise RepositoryReadbackInvalid(
                f"cannot read repository source: {relative_path}"
            ) from error
        after = self.worktree_fingerprint()
        if before != after:
            raise RepositoryReadbackConflict(
                f"worktree changed during repository readback: {relative_path}"
            )
        return RepositoryFileReadback(
            relative_path=relative_path,
            worktree_fingerprint=after,
            content_digest=hashlib.sha256(content).hexdigest(),
        )

    def _canonical_reference(self, reference: str) -> str:
        if (
            not isinstance(reference, str)
            or not reference
            or "\\" in reference
            or "\0" in reference
        ):
            raise RepositoryReadbackInvalid(
                "repository source reference must be a canonical relative POSIX path"
            )
        parsed = PurePosixPath(reference)
        if (
            parsed.is_absolute()
            or str(parsed) != reference
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise RepositoryReadbackInvalid(
                "repository source reference must be a canonical relative POSIX path"
            )
        return reference

    def _require_tracked(self, relative_path: str) -> None:
        tracked = self._git(
            self._root,
            ("ls-files", "--error-unmatch", "--", relative_path),
            allow_failure=True,
        )
        tracked_paths = tuple(os.fsdecode(value) for value in tracked.splitlines() if value)
        if tracked_paths != (relative_path,):
            raise RepositoryReadbackInvalid(
                f"repository source must be an exact tracked file: {relative_path}"
            )

    def _regular_file(self, relative_path: str) -> Path:
        candidate = self._root
        for part in PurePosixPath(relative_path).parts:
            candidate /= part
            if candidate.is_symlink():
                raise RepositoryReadbackInvalid(
                    f"repository source cannot traverse a symlink: {relative_path}"
                )
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._root) or not candidate.is_file():
            raise RepositoryReadbackInvalid(
                f"repository source must be an existing regular file: {relative_path}"
            )
        return candidate

    def _git(
        self,
        root: Path,
        arguments: tuple[str, ...],
        *,
        allow_failure: bool,
    ) -> bytes:
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        result = subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=False,
            capture_output=True,
            env=environment,
        )
        if result.returncode != 0:
            if allow_failure:
                return b""
            detail = os.fsdecode(result.stderr).strip() or "Git readback failed"
            raise RepositoryReadbackInvalid(detail)
        return result.stdout
