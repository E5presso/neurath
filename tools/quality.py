"""Shared pre-commit and CI quality gate over every current package module."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Check formatting, lint, strict types, architecture, and guard regression fixtures."""
    root = Path(__file__).resolve().parents[1]
    commands = (
        ["-m", "ruff", "check", "src", "tests", "tools"],
        ["-m", "ruff", "format", "--check", "src", "tests", "tools"],
        ["-m", "pyrefly", "check"],
        ["-m", "pydoclint.main", "src", "tools"],
        ["tools/architecture.py"],
        [
            "-m",
            "pytest",
            "-q",
            "tests/test_architecture.py",
            "tests/test_quality_hook.py",
            "tests/test_domain.py",
            "tests/test_dependency_lifecycle.py",
        ],
    )
    for arguments in commands:
        subprocess.run([sys.executable, *arguments], cwd=root, check=True)
    print("QUALITY_CHECK_OK")


if __name__ == "__main__":
    main()
