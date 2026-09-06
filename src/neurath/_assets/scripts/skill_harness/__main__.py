"""main 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

from pathlib import Path

from scripts.skill_harness.checker import SkillHarnessChecker

ROOT = __import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(Path(__file__).resolve().parents[2])


class SkillHarnessApplication:
    """skill harness application 관련 설정과 검증 조건을 함께 표현합니다."""

    def run(self) -> int:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Returns:
            run 처리 결과입니다."""
        violations = SkillHarnessChecker(ROOT).check()
        if violations:
            for violation in violations:
                print(violation.render(ROOT))
            return 1
        return 0


def main() -> None:
    """CLI entrypoint가 인자를 해석하고 process exit code를 반환합니다.

    Raises:
        입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
    raise SystemExit(SkillHarnessApplication().run())


if __name__ == "__main__":
    main()
