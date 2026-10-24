"""실제 Typer 정의에서 설치 가이드를 생성·검증한다."""

import argparse
from pathlib import Path

from neurath.cli_guide import render


def main() -> None:
    """생성 본문을 저장하거나 배포 가이드가 현재 정의와 같은지 검사한다.

    Raises:
        SystemExit: 검증 모드에서 가이드가 없거나 오래된 경우.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "src/neurath/resources/cli-guide.md"
    content = render()
    if arguments.check:
        if not path.exists() or path.read_text() != content:
            raise SystemExit("CLI guide is stale; run tools/generate_cli_guide.py")
        print("CLI_GUIDE_CHECK_OK")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(path)


if __name__ == "__main__":
    main()
