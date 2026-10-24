"""현재 CLI 안내를 검증하고 소스 식별을 담은 같은 배포 wheel을 만든다."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from neurath.cli_guide import render


def build(output: Path) -> None:
    """오래된 가이드는 실패시키고 원 소스를 바꾸지 않는 staging에서 빌드한다.

    Args:
        output: 후보 wheel 출력 폴더.

    Raises:
        ValueError: 실제 CLI와 가이드가 다른 경우.
    """
    root = Path(__file__).resolve().parents[1]
    if (root / "src/neurath/resources/cli-guide.md").read_text() != render():
        raise ValueError("CLI guide is stale; generate and verify it before release")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--", "src", "pyproject.toml"], cwd=root, text=True
        ).strip()
    )
    digest = hashlib.sha256()
    for path in sorted((root / "src/neurath").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    with tempfile.TemporaryDirectory(prefix="neurath-build-") as directory:
        staging = Path(directory)
        shutil.copytree(root / "src", staging / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(root / "pyproject.toml", staging / "pyproject.toml")
        (staging / "src/neurath/resources/distribution.json").write_text(
            json.dumps(
                {
                    "source_commit": None if dirty else commit,
                    "source_base": commit,
                    "source_modified": dirty,
                    "source_tree_sha256": digest.hexdigest(),
                }
            )
        )
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(output.resolve())],
            cwd=staging,
            check=True,
        )


def main() -> None:
    """명시한 출력 위치에 검증된 후보를 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    build(parser.parse_args().output)


if __name__ == "__main__":
    main()
