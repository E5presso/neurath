"""Conservative filesystem observations shared by installation and diagnostics.

These helpers do not load installation state or commit changes. Snapshot values
retain exact bytes, mode and symlink identity for planning and rollback.
"""

import base64
import os
import subprocess
from pathlib import Path, PurePosixPath

from neurath.serialization import canonical as canonical

class InstallError(RuntimeError):
    """A conflict or invalid plan prevented mutation."""
def git_dir(root):
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise InstallError("target must be a Git repository")
    return Path(process.stdout.strip())

def repository(root):
    root = Path(root).resolve()
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode or Path(process.stdout.strip()).resolve() != root:
        raise InstallError("target must be the Git worktree root")
    return root

def safe_path(root, relative):
    path = PurePosixPath(relative)
    if (
        not isinstance(relative, str)
        or not relative
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or str(path) != relative
    ):
        raise InstallError(f"unsafe path: {relative}")
    target = root / relative
    for ancestor in target.parents:
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise InstallError(f"symlink ancestor / path escape: {relative}")
        if ancestor.exists() and not ancestor.is_dir():
            raise InstallError(f"parent conflict: {relative}")
    return target

def snapshot(root, relative):
    path = safe_path(root, relative)
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if not path.exists():
        return None
    if path.is_dir():
        return {"kind": "directory"}
    if not path.is_file():
        raise InstallError(f"unsupported file: {relative}")
    return file_value(path.read_bytes(), path.stat().st_mode & 0o777)

def file_value(data, mode=0o644):
    return {"kind": "file", "data": base64.b64encode(data).decode(), "mode": mode}

def bytes_of(value):
    if value is None:
        return b""
    if value.get("kind") != "file":
        raise InstallError("conflict: expected a regular file")
    return base64.b64decode(value["data"], validate=True)
