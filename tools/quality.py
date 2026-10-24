"""커밋 전에 정적 검사와 구조·계약 회귀 시험을 실행한다."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """포맷·린트·엄격한 타입·구조와 검사 도구의 회귀 fixture를 확인한다."""
    root = Path(__file__).resolve().parents[1]
    commands = (
        ["tools/static_quality.py"],
        [
            "-m",
            "pytest",
            "-q",
            "tests/test_architecture.py",
            "tests/test_docstrings.py",
            "tests/test_quality_hook.py",
            "tests/test_domain.py",
            "tests/test_dependency_lifecycle.py",
            "tests/test_core_boundaries.py",
            "tests/test_coverage_gate.py",
            "tests/test_task_domain.py",
            "tests/test_workflow_domain.py",
            "tests/test_runtime.py",
            "tests/test_cli.py",
            "tests/test_checkpoint_graph.py",
            "tests/test_collaboration.py",
            "tests/test_newsroom.py",
            "tests/test_monitoring.py",
            "tests/test_provider.py",
            "tests/test_review_contracts.py",
            "tests/test_uuid_migrations.py",
            "tests/test_framework_execution.py",
        ],
    )
    for arguments in commands:
        subprocess.run([sys.executable, *arguments], cwd=root, check=True)
    print("QUALITY_CHECK_OK")


if __name__ == "__main__":
    main()
