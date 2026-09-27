"""Resolve shared project storage from the canonical Git common directory."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
import subprocess
from pathlib import Path


_discovery: ContextVar[dict[Path, tuple[tuple, Path]] | None] = ContextVar("neurath_project_discovery", default=None)


@contextmanager
def discovery_scope():
    """Reuse repository paths for one hook; never retain mutable authority state.

    Each entry owns a fresh cache, including nested hooks. Reset also runs on
    failures, so a later event observes repository/worktree changes afresh.
    """
    token = _discovery.set({})
    try:
        yield
    finally:
        _discovery.reset(token)


def control_root(root):
    cache = _discovery.get()
    # Git environment overrides are process mutable and may use relative paths.
    # Let Git resolve those requests rather than reuse filesystem discovery.
    if cache is None or any(
        key in {"GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_CEILING_DIRECTORIES",
                "GIT_DISCOVERY_ACROSS_FILESYSTEM"} or key.startswith("GIT_CONFIG")
        for key in os.environ
    ):
        return _discover_control_root(root)
    path = Path(root).resolve()
    signature = _layout_signature(path)
    previous = cache.get(path)
    if previous is None or previous[0] != signature:
        previous = (signature, _discover_control_root(path))
        cache[path] = previous
    return previous[1]


def _layout_signature(path):
    """Invalidate cached discovery if Git directory or commondir pointers change."""
    def stamp(value):
        try:
            stat = value.lstat()
        except FileNotFoundError:
            return (str(value), None)
        target = None
        if value.is_symlink():
            try:
                followed = value.stat()
            except FileNotFoundError:
                pass
            else:
                target = (followed.st_dev, followed.st_ino, followed.st_mtime_ns,
                          followed.st_ctime_ns, followed.st_size)
        return (str(value), str(value.resolve()), stat.st_dev, stat.st_ino,
                stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, target)

    for directory in (path, *path.parents):
        marker = directory / ".git"
        if not marker.exists() and not marker.is_symlink():
            continue
        metadata = marker
        if marker.is_file():
            content = marker.read_text().strip()
            if content.startswith("gitdir: "):
                metadata = (directory / content.removeprefix("gitdir: ")).resolve()
        return (stamp(marker), stamp(metadata), stamp(metadata / "commondir"))
    # Bare repositories have no .git marker. Their commondir can still change.
    return (stamp(path), stamp(path / "commondir"))


def _discover_control_root(root):
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    common = Path(result.stdout.strip()).resolve()
    return common.parent if common.name == ".git" else common
