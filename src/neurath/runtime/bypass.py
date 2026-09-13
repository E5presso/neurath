"""One atomic worktree marker, readable even when kernel storage is broken."""
import os
import tempfile
from pathlib import Path


def mode(root, enabled=None):
    root = Path(root).resolve()
    path = root / ".neurath/local/bypass-enabled"
    if enabled is not None and type(enabled) is not bool:
        raise ValueError("enabled must be a boolean or null")
    if any(part.is_symlink() for part in (path, path.parent, path.parent.parent)):
        raise ValueError("bypass state must not be a symlink")
    if path.exists() and not path.is_file():
        raise ValueError("bypass marker must be a regular file")
    if enabled is None:
        return {"enabled": path.is_file(), "scope": "worktree"}
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".bypass-", dir=path.parent)
        os.close(descriptor)
        try:
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    else:
        path.unlink(missing_ok=True)
    return {"enabled": enabled, "scope": "worktree"}
