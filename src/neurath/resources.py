"""Immutable packaged resources, separate from the target repository."""

import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
BUNDLE = PACKAGE / "_assets"


def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text())


def runtime_profile(root):
    path = Path(root) / ".neurath/profile.json"
    return json.loads(path.read_text())["profile"] if path.is_file() else None


def distribution_id():
    digest = hashlib.sha256()
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(PACKAGE).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
