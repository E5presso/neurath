"""Run new-core contracts from a disposable test directory against the package.

The project-owned suite lives outside distributed assets. No retired script
engine or source-project settings are loaded into the fixture.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_fixture(target, selected_tests=(), *, workers=0):
    target = Path(target)
    shutil.copytree(ROOT / "tests/core", target / "tests/core", ignore=shutil.ignore_patterns("__pycache__"))
    (target / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts="--import-mode=importlib"\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_", "PYTHONPATH"))}
    print(f"Independent core contracts: {target}", flush=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", str(workers), "--dist", "load", *selected_tests],
        cwd=target, env=env, check=False,
    ).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    if args.workers < 0:
        parser.error("workers must be zero or positive")
    if args.target:
        return run_fixture(args.target, args.tests, workers=args.workers)
    with tempfile.TemporaryDirectory(prefix="neurath-core-") as temporary:
        return run_fixture(Path(temporary), args.tests, workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
