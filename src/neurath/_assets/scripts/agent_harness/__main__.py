"""Agent harness 검사를 CLI로 실행합니다."""

from __future__ import annotations

from pathlib import Path

from scripts.agent_harness.checker import AgentHarnessChecker

ROOT = __import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(Path(__file__).resolve().parents[2])


class AgentHarnessApplication:
    """Agent harness 위반을 stdout에 출력하는 CLI application입니다."""

    def run(self) -> int:
        """Agent harness 검사를 실행하고 shell exit code를 반환합니다.

        Returns:
            위반이 있으면 1, 없으면 0입니다."""
        violations = AgentHarnessChecker(ROOT).check()
        if violations:
            for violation in violations:
                print(violation.render(ROOT))
            return 1
        return 0


def main() -> None:
    """Agent harness CLI를 process exit로 연결합니다.

    Raises:
        SystemExit: 검사 결과 exit code로 process를 종료합니다."""
    raise SystemExit(AgentHarnessApplication().run())


if __name__ == "__main__":
    main()
