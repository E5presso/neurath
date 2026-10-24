"""후보 패키지의 필수 검사를 실행하며 설치하거나 공개하지 않는다."""

import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path


def main(*, combine_coverage: bool = False) -> None:
    """전체 시험 또는 CI 분할 측정 결과로 동일한 커버리지·정적 검사·빌드를 수행한다.

    Args:
        combine_coverage: 성공한 모든 CI 분할의 측정 파일을 합쳐 검증할지 여부.
    """
    root = Path(__file__).resolve().parents[1]
    measurements = (
        [
            ["-m", "coverage", "combine"],
            ["-m", "coverage", "report"],
            ["-m", "coverage", "json", "-o", "coverage-out/coverage.json"],
            ["-m", "coverage", "xml", "-o", "coverage-out/coverage.xml"],
        ]
        if combine_coverage
        else [
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
        ]
    )
    for arguments in (
        ["tools/static_quality.py"],
        ["tools/generate_cli_guide.py", "--check"],
        *measurements,
        ["tools/check_coverage.py"],
        ["-m", "build", "--wheel", "--outdir", "dist"],
    ):
        subprocess.run([sys.executable, *arguments], cwd=root, check=True)
    print("NEURATH_CHECK_OK")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--combine-coverage", action="store_true")
    main(combine_coverage=parser.parse_args().combine_coverage)
