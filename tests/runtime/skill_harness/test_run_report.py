"""test run report 관련 타입과 실행 흐름을 정의합니다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from typing import Self
from unittest import TestCase

from scripts.skill_harness.run_report import SkillRunReportValidator


class SkillRunReportValidatorTest(TestCase):
    """skill contract와 phase runner enforcement 회귀 시나리오를 unittest fixture로 고정합니다."""

    def test_accepts_valid_run_report(self) -> None:
        """skill contract와 phase runner enforcement의 accepts valid run report 회귀 조건을 검증합니다."""
        with RunReportFixture() as fixture:
            fixture.write_contracts()
            report = fixture.write_report({
                "skill": "process-ticket",
                "terminal_state": "failed",
                "phases": [
                    {
                        "id": 1,
                        "name": "orientation",
                        "status": "completed",
                        "evidence": ["agents_rules_read", "work_item_source"],
                    },
                    {
                        "id": 2,
                        "name": "verification",
                        "status": "failed",
                        "reason": "pre-commit failed",
                        "evidence": ["pre_commit_result", "focused_test_result"],
                    },
                ],
            })

            violations = SkillRunReportValidator(fixture.root).validate(report)

        self.assertEqual([], violations)

    def test_rejects_out_of_order_phase_report(self) -> None:
        """skill contract와 phase runner enforcement의 rejects out of order phase report 회귀 조건을 검증합니다."""
        with RunReportFixture() as fixture:
            fixture.write_contracts()
            report = fixture.write_report({
                "skill": "process-ticket",
                "terminal_state": "failed",
                "phases": [
                    {
                        "id": 2,
                        "name": "verification",
                        "status": "completed",
                        "evidence": ["pre_commit_result", "focused_test_result"],
                    },
                    {
                        "id": 1,
                        "name": "orientation",
                        "status": "completed",
                        "evidence": ["agents_rules_read", "work_item_source"],
                    },
                ],
            })

            violations = SkillRunReportValidator(fixture.root).validate(report)

        self.assertEqual(["DR005", "DR006", "DR005", "DR006"], [v.code for v in violations])

    def test_rejects_phase_without_required_evidence(self) -> None:
        """skill contract와 phase runner enforcement의 rejects phase without required evidence 회귀 조건을 검증합니다."""
        with RunReportFixture() as fixture:
            fixture.write_contracts()
            report = fixture.write_report({
                "skill": "process-ticket",
                "terminal_state": "failed",
                "phases": [
                    {
                        "id": 1,
                        "name": "orientation",
                        "status": "completed",
                        "evidence": ["agents_rules_read"],
                    },
                    {
                        "id": 2,
                        "name": "verification",
                        "status": "completed",
                        "evidence": ["pre_commit_result", "focused_test_result"],
                    },
                ],
            })

            violations = SkillRunReportValidator(fixture.root).validate(report)

        self.assertEqual(["DR009", "DR010"], [v.code for v in violations])


class RunReportFixture:
    """run report fixture 관련 설정과 검증 조건을 함께 표현합니다."""

    def __enter__(self) -> Self:
        """RunReportFixture resource lifecycle을 열고 닫아 skill contract와 phase runner enforcement 실행 중 누수를 막습니다.

        Returns:
            enter 처리 결과입니다."""
        self._temporary_directory = TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """RunReportFixture resource lifecycle을 열고 닫아 skill contract와 phase runner enforcement 실행 중 누수를 막습니다.

        Args:
            exc_type: 호출자가 넘긴 exc type 값입니다.
            exc_value: 호출자가 넘긴 exc value 값입니다.
            traceback: 호출자가 넘긴 traceback 값입니다."""
        self._temporary_directory.cleanup()

    def write_contracts(self) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "process-ticket": {
                  "terminal_states": ["failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "orientation",
                      "min_evidence_count": 2,
                      "required_evidence": ["agents_rules_read", "work_item_source"]
                    },
                    {
                      "id": 2,
                      "name": "verification",
                      "min_evidence_count": 2,
                      "required_evidence": ["focused_test_result", "pre_commit_result"]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_report(self, report: dict[str, object]) -> Path:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            report: 호출자가 넘긴 report 값입니다.

        Returns:
            write report 처리 결과입니다."""
        path = self.root / "run-report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def write(self, relative_path: str, content: str) -> None:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            relative_path: 호출자가 넘긴 relative path 값입니다.
            content: 호출자가 넘긴 content 값입니다."""
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(content), encoding="utf-8")
