"""후보 패키지의 필수 검사를 실행하며 설치하거나 공개하지 않는다."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """공유 품질 검사·전체 행동 시험·라인과 분기 100% 검사·휠 생성을 실행한다."""
    root = Path(__file__).resolve().parents[1]
    for arguments in (
        ["tools/quality.py"],
        [
            "-m",
            "pytest",
            "-q",
            "--cov=src/neurath",
            "--cov-branch",
            "--cov-fail-under=100",
            "--cov-report=term-missing",
            "--cov-report=json:coverage-out/coverage.json",
            "--cov-report=xml:coverage-out/coverage.xml",
        ],
        ["tools/check_coverage.py"],
        ["-m", "build", "--wheel", "--outdir", "dist"],
    ):
        subprocess.run([sys.executable, *arguments], cwd=root, check=True)
    print("NEURATH_CHECK_OK")


if __name__ == "__main__":
    main()
