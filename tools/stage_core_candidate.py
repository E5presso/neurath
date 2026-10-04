"""Stage a disposable new-core-only package without changing the active installation.

This is a pre-cutover validation artifact, not a public release. The final source
removal follows actual-host validation against this isolated candidate.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED_DIRECTORIES = {"agents", "hosts", "runtime"}
RETAINED_PROVIDERS = {"__init__.py", "stdio.py", "contracts.py", "environment.py"}
RETAINED_MEMORY = {"__init__.py", "store.py", "learning.py"}


def retained(relative):
    parts = relative.parts
    if "__pycache__" in parts or relative.suffix == ".pyc":
        return False
    if parts[0] in RETIRED_DIRECTORIES:
        return False
    if parts[0] == "providers" and relative.name not in RETAINED_PROVIDERS:
        return False
    if parts[0] == "memory" and relative.name not in RETAINED_MEMORY:
        return False
    if relative.as_posix() in {"install/cutover.py", "install/mcp_guidance.py"}:
        return False
    if parts[:2] == ("_assets", "scripts"):
        return False
    if parts[:3] == ("_assets", ".agents", "skills"):
        if relative.name == "contracts.json":
            return False
        if "scripts" in parts and parts[3] != "reconnect-host":
            return False
    return True


def stage(destination):
    if destination.exists():
        raise ValueError("Candidate destination must not exist")
    destination.mkdir(parents=True)
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", ".python-version"):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, destination / name)
    source = ROOT / "src/neurath"
    package = destination / "src/neurath"
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not retained(relative):
            continue
        if path.is_symlink():
            raise ValueError("Candidate source must be independent of symlinks")
        if path.is_file():
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    (destination / "tools").mkdir()
    for name in ("build_manifest.py", "core_catalog.py", "versioning.py"):
        shutil.copy2(ROOT / "tools" / name, destination / "tools" / name)
    subprocess.run([sys.executable, str(destination / "tools/build_manifest.py")], check=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(stage(args.output.resolve()))


if __name__ == "__main__":
    main()
