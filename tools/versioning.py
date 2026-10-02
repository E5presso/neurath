"""Prepare one patch version per runtime change; checks never mutate source."""
import argparse
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = {
    "src/neurath/manifest.json",
    "src/neurath/_assets/.agents/HARNESS_INDEX.md",
    "src/neurath/_assets/.agents/HARNESS_AUDIT.md",
}


def _number(value):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("package version must be MAJOR.MINOR.PATCH")
    return tuple(map(int, value.split(".")))


def _metadata(root):
    project = root / "pyproject.toml"
    init = root / "src/neurath/__init__.py"
    lock = root / "uv.lock"
    current = tomllib.loads(project.read_text())["project"]["version"]
    _number(current)
    runtime = re.search(r'^__version__ = "([^"]+)"$', init.read_text(), re.M)
    packages = [p for p in tomllib.loads(lock.read_text())["package"] if p["name"] == "neurath"]
    if not runtime or runtime[1] != current or len(packages) != 1 or packages[0]["version"] != current:
        raise ValueError("inconsistent package, runtime or lockfile version")
    return current


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def _baseline(root):
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode or Path(top.stdout.decode().strip()).resolve() != root.resolve():
        return None, False  # Archive or a nested fixture, not this source checkout.
    previous = _git(root, "show", "HEAD:pyproject.toml")
    if previous.returncode:
        raise ValueError("source checkout needs a committed package version baseline")
    baseline = tomllib.loads(previous.stdout.decode())["project"]["version"]
    _number(baseline)
    changed = _git(root, "diff", "--name-only", "-z", "HEAD", "--", "src/neurath")
    new = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", "src/neurath")
    if changed.returncode or new.returncode:
        raise ValueError("cannot verify runtime changes for package version")
    paths = (changed.stdout + new.stdout).decode().split("\0")
    runtime_changed = any(p and p not in GENERATED and "__pycache__" not in Path(p).parts
                          and not p.endswith(".pyc") for p in paths)
    return baseline, runtime_changed


def check_version(root=ROOT):
    current = _metadata(root)
    baseline, changed = _baseline(root)
    if baseline and (_number(current) < _number(baseline)
                     or changed and _number(current) == _number(baseline)):
        raise ValueError("runtime changed without a newer package version; run tools/build_manifest.py")
    return current


def prepare_version(root=ROOT):
    current = _metadata(root)
    baseline, changed = _baseline(root)
    if baseline and _number(current) < _number(baseline):
        raise ValueError("package version cannot decrease")
    if not changed or baseline is None or _number(current) > _number(baseline):
        return current
    major, minor, patch = _number(current)
    target = f"{major}.{minor}.{patch + 1}"
    # Validate all edits before writing; preserve unrelated dependencies and versions.
    replacements = []
    for path, pattern, replacement in (
        (root / "pyproject.toml", r'(?m)^(version = ")' + re.escape(current) + r'("\s*)$',
         rf'\g<1>{target}\g<2>'),
        (root / "src/neurath/__init__.py", r'(?m)^(__version__ = ")' + re.escape(current) + r'("\s*)$',
         rf'\g<1>{target}\g<2>'),
        (root / "uv.lock", r'(\[\[package\]\]\nname = "neurath"\nversion = ")'
         + re.escape(current) + r'(")', rf'\g<1>{target}\g<2>'),
    ):
        value, count = re.subn(pattern, replacement, path.read_text())
        if count != 1:
            raise ValueError(f"cannot update exact package version in {path.name}")
        replacements.append((path, value))
    for path, value in replacements:
        path.write_text(value)
    print(f"Prepared package version {current} -> {target}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(check_version() if args.check else prepare_version())


if __name__ == "__main__":
    main()
