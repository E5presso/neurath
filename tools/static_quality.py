"""pre-commit과 전체 검증이 공유하는 소스 정적 검사다."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """포맷·린트·타입·문서·아키텍처를 검사하고 실패한 단계에서 중단한다."""
    root = Path(__file__).resolve().parents[1]
    commands = (
        ["-m", "ruff", "check", "src", "tests", "tools"],
        ["-m", "ruff", "format", "--check", "src", "tests", "tools"],
        ["-m", "pyrefly", "check"],
        ["-m", "pydoclint.main", "src", "tools"],
        ["tools/architecture.py"],
        ["tools/docstrings.py"],
    )
    for arguments in commands:
        subprocess.run([sys.executable, *arguments], cwd=root, check=True)
    print("STATIC_QUALITY_CHECK_OK")


if __name__ == "__main__":
    main()
