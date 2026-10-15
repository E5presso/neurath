"""Required validation for the candidate package; never installs or publishes it."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run the shared quality gate, all behavior tests, and wheel construction."""
    root = Path(__file__).resolve().parents[1]
    for arguments in (
        ["tools/quality.py"],
        ["-m", "pytest", "-q"],
        ["-m", "build", "--wheel", "--outdir", "dist"],
    ):
        subprocess.run([sys.executable, *arguments], cwd=root, check=True)
    print("NEURATH_CHECK_OK")


if __name__ == "__main__":
    main()
