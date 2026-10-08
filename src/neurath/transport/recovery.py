"""A recovery switch whose operation never depends on task storage."""

import os
import tempfile
from pathlib import Path


def bypass(root, enabled=None):
    if enabled is not None and type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    root = Path(root).resolve()
    directory = root / ".neurath" / "local"
    marker = directory / "bypass-enabled"
    if any(p.is_symlink() for p in (root / '.neurath', directory, marker)):
        raise ValueError("recovery state must not be a symlink")
    if marker.exists() and not marker.is_file():
        raise ValueError("invalid recovery marker")
    if enabled is True:
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.recovery-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(b'Neurath hook suspension; host permissions unchanged.\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, marker)
        finally:
            Path(temporary).unlink(missing_ok=True)
    elif enabled is False:
        marker.unlink(missing_ok=True)
    return {'enabled': marker.is_file(), 'scope': 'worktree'}
