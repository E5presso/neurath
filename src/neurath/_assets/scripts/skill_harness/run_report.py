"""run report 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.skill_harness.checker import CONTRACTS_PATH, SkillHarnessChecker
from scripts.skill_harness.violation import Violation

VALID_PHASE_STATUSES = {"completed", "skipped", "blocked", "failed"}


class SkillRunReportValidator:
    """skill run report validator 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(self, root: Path) -> None:
        """SkillRunReportValidator 인스턴스가 skill contract와 phase runner enforcement 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            root: 호출자가 넘긴 root 값입니다."""
        self._root = root.resolve()

    def validate(self, report_path: Path) -> list[Violation]:
        """SkillRunReportValidator의 필드 조합이 skill contract와 phase runner enforcement invariant를 깨는지 검사합니다.

        Args:
            report_path: 호출자가 넘긴 report path 값입니다.

        Returns:
            validate 처리 결과입니다."""
        path = report_path.resolve()
        report = self._read_json_object(path)
        contracts = SkillHarnessChecker(self._root)._contracts(__import__("scripts._neurath_paths", fromlist=["asset_path"]).asset_path(self._root, CONTRACTS_PATH))

        skill = report.get("skill")
        if not isinstance(skill, str) or skill not in contracts:
            return [
                Violation(
                    code="DR001",
                    path=path,
                    message="run report skill must name a contracted skill",
                )
            ]

        contract = contracts[skill]
        violations: list[Violation] = []
        violations.extend(self._check_terminal_state(path, report, contract))
        violations.extend(self._check_phases(path, report, contract))
        return violations

    def _check_terminal_state(
        self,
        path: Path,
        report: dict[str, object],
        contract: dict[str, object],
    ) -> list[Violation]:
        terminal_state = report.get("terminal_state")
        allowed_states = self._string_list(contract.get("terminal_states"))
        if not isinstance(terminal_state, str) or terminal_state not in allowed_states:
            return [
                Violation(
                    code="DR002",
                    path=path,
                    message="run report terminal_state must match the skill contract",
                )
            ]
        return []

    def _check_phases(
        self,
        path: Path,
        report: dict[str, object],
        contract: dict[str, object],
    ) -> list[Violation]:
        report_phases = report.get("phases")
        contract_phases = contract.get("phase_contracts")
        if not isinstance(report_phases, list) or not isinstance(contract_phases, list):
            return [
                Violation(
                    code="DR003",
                    path=path,
                    message="run report phases must match contract phases",
                )
            ]

        violations: list[Violation] = []
        if len(report_phases) != len(contract_phases):
            violations.append(
                Violation(
                    code="DR004",
                    path=path,
                    message="run report must include every contracted phase exactly once",
                )
            )

        for index, contract_phase in enumerate(contract_phases):
            if not isinstance(contract_phase, dict):
                continue
            if index >= len(report_phases) or not isinstance(report_phases[index], dict):
                continue
            report_phase = report_phases[index]
            violations.extend(self._check_phase(path, report_phase, contract_phase))
        return violations

    def _check_phase(
        self,
        path: Path,
        report_phase: dict[str, object],
        contract_phase: dict[str, object],
    ) -> list[Violation]:
        violations: list[Violation] = []
        phase_identity_matches = True
        if report_phase.get("id") != contract_phase.get("id"):
            phase_identity_matches = False
            violations.append(
                Violation(
                    code="DR005",
                    path=path,
                    message="run report phase id is out of order",
                )
            )
        if report_phase.get("name") != contract_phase.get("name"):
            phase_identity_matches = False
            violations.append(
                Violation(
                    code="DR006",
                    path=path,
                    message="run report phase name must match the skill contract",
                )
            )
        if not phase_identity_matches:
            return violations
        status = report_phase.get("status")
        if not isinstance(status, str) or status not in VALID_PHASE_STATUSES:
            violations.append(
                Violation(
                    code="DR007",
                    path=path,
                    message="run report phase status must be a valid terminal phase status",
                )
            )
        if status in {"blocked", "failed"} and not isinstance(report_phase.get("reason"), str):
            violations.append(
                Violation(
                    code="DR008",
                    path=path,
                    message="blocked or failed phases must include a reason",
                )
            )

        evidence = self._string_list(report_phase.get("evidence"))
        min_evidence_count = contract_phase.get("min_evidence_count")
        if isinstance(min_evidence_count, int) and len(evidence) < min_evidence_count:
            violations.append(
                Violation(
                    code="DR009",
                    path=path,
                    message="run report phase does not meet min_evidence_count",
                )
            )
        for required in self._string_list(contract_phase.get("required_evidence")):
            if not any(required in item for item in evidence):
                violations.append(
                    Violation(
                        code="DR010",
                        path=path,
                        message=f"run report phase evidence is missing {required!r}",
                    )
                )
        return violations

    def _read_json_object(self, path: Path) -> dict[str, object]:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError(f"{path} must contain a JSON object")
        return parsed

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]


class SkillRunReportApplication:
    """skill run report application 관련 설정과 검증 조건을 함께 표현합니다."""

    def run(self, raw_args: list[str] | None = None) -> int:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            raw_args: 호출자가 넘긴 raw args 값입니다.

        Returns:
            run 처리 결과입니다."""
        parser = argparse.ArgumentParser(
            description="Validate an Neurath deterministic skill run report."
        )
        parser.add_argument("report", type=Path)
        args = parser.parse_args(raw_args)

        violations = SkillRunReportValidator(__import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(Path(__file__).resolve().parents[2])).validate(
            args.report
        )
        if violations:
            root = __import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(Path(__file__).resolve().parents[2])
            for violation in violations:
                print(violation.render(root))
            return 1
        return 0


def main() -> None:
    """CLI entrypoint가 인자를 해석하고 process exit code를 반환합니다.

    Raises:
        입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
    raise SystemExit(SkillRunReportApplication().run())


if __name__ == "__main__":
    main()
