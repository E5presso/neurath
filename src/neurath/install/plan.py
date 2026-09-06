"""Private plan files, which may include original credentials and configuration."""

import json
import os
import tempfile
import uuid
from pathlib import Path

from neurath.install.transaction import InstallError, git_dir


def write_plan(root, value, output=None):
    if output is None:
        directory = git_dir(root) / "neurath-plans"
        if directory.is_symlink():
            raise InstallError("plan directory must not be a symlink")
        directory.mkdir(mode=0o700, exist_ok=True)
        output = directory / f"{value['id']}-{uuid.uuid4().hex}.json"
    output = Path(output).absolute()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())
            file.flush()
            os.fsync(file.fileno())
        # Publish only a complete 0600 file, without replacing existing files or links.
        os.link(temporary, output)
    except FileExistsError as error:
        raise InstallError("plan output already exists; choose a new private path") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output
