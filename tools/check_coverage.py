"""보고서의 미실행 라인과 분기가 모두 0인지 반올림 없이 검사한다."""

import json
import sys
from pathlib import Path


def check_report(path: Path) -> None:
    """Coverage JSON의 누락 개수로 라인·분기 100%를 각각 강제한다.

    Args:
        path: 전체 소스를 측정한 coverage JSON 보고서 경로.

    Raises:
        ValueError: 최상위 객체·totals가 없거나 누락·제외 개수가 비정수 또는 음수인 경우.
        SystemExit: 미실행 라인·분기 또는 제외된 라인이 남아 있는 경우.
    """
    report: object = json.loads(path.read_text())
    if not isinstance(report, dict):
        raise ValueError("Coverage report must be an object")
    totals: object = report.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("Coverage report must contain totals")
    missing_lines: object = totals.get("missing_lines")
    missing_branches: object = totals.get("missing_branches")
    excluded_lines: object = totals.get("excluded_lines")
    if not (
        isinstance(missing_lines, int)
        and isinstance(missing_branches, int)
        and isinstance(excluded_lines, int)
    ):
        raise ValueError("Coverage totals must contain missing line, branch and exclusion counts")
    if missing_lines < 0 or missing_branches < 0 or excluded_lines < 0:
        raise ValueError("Coverage counts cannot be negative")
    if excluded_lines:
        raise SystemExit(f"Coverage exclusions not allowed: {excluded_lines} excluded lines")
    if missing_lines or missing_branches:
        raise SystemExit(
            f"Coverage incomplete: {missing_lines} missing lines, {missing_branches} missing branches"
        )
    print("COVERAGE_CHECK_OK: lines=100%, branches=100%")


def main() -> None:
    """명시한 보고서 또는 필수 검사 보고서의 커버리지 기준을 검증한다."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("coverage-out/coverage.json")
    check_report(path)


if __name__ == "__main__":
    main()
