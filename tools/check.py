"""후보 패키지의 필수 검사를 실행하며 설치하거나 공개하지 않는다."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """공유 정적 검사 뒤 전체 시험을 한 번 실행해 라인·분기 100%와 휠을 검증한다."""
    root = Path(__file__).resolve().parents[1]
    for arguments in (
        ["tools/static_quality.py"],
        ["tools/generate_cli_guide.py", "--check"],
        [
            "-m",
            "pytest",
            "-q",
            "-n",
            "auto",
            "--maxprocesses=4",
            "--dist=worksteal",
            "--cov=src/neurath",
            "--cov-branch",
            "--durations=20",
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
