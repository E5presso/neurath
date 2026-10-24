"""개발 checkout을 고정 wheel로 빌드한 뒤 같은 배포본의 기존 설치기를 연결한다."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from neurath.infrastructure.database import user_database_path
from tools.build_release import build


def main() -> None:
    """요청한 호스트 범위에 내용별 별도 실행 환경을 적용한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("codex", "claude"), required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--data-home", default=str(user_database_path().parent.parent))
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="neurath-candidate-") as output:
        build(Path(output))
        prepared = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "neurath.entrypoint",
                "distribution",
                "prepare",
                "--wheel",
                str(next(Path(output).glob("*.whl"))),
                "--store",
                str(Path(arguments.data_home) / "neurath/distributions"),
            ],
            text=True,
        )
        candidate = json.loads(prepared)["candidate"]
    subprocess.run(
        [
            sys.executable,
            "-m",
            "neurath.entrypoint",
            "distribution",
            "apply",
            "--candidate",
            candidate,
            "--provider",
            arguments.provider,
            "--directory",
            arguments.directory,
            "--data-home",
            arguments.data_home,
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
