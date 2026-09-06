"""Phase runner CLI가 runtime session workflow만 사용하는 cutover 계약입니다."""

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.agent_harness.session_kernel import (
    SessionId,
    SessionKernel,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
from scripts.skill_harness.phase_runner import PhaseRunnerApplication


class SessionPhaseRunnerApplicationTest(unittest.TestCase):
    """Manual state path 없이 phase workflow를 시작하고 재개하는지 검증합니다."""

    def setUp(self) -> None:
        """Minimal contracted skill과 git common root를 준비합니다."""
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        subprocess.run(
            ["git", "init", "--quiet", str(self.root)],
            check=True,
            capture_output=True,
            text=True,
        )
        contracts = self.root / ".agents" / "skills" / "contracts.json"
        contracts.parent.mkdir(parents=True)
        contracts.write_text(
            json.dumps({
                "skills": {
                    "checkpoint": {
                        "terminal_states": ["done", "failed"],
                        "phase_contracts": [
                            {
                                "id": 1,
                                "name": "execute",
                                "min_evidence_count": 0,
                                "required_evidence": [],
                            }
                        ],
                    }
                }
            }),
            encoding="utf-8",
        )
        self.environment = {"CODEX_THREAD_ID": "session-a"}
        self._initialize_session(self.environment)

    def _initialize_session(self, environment: dict[str, str]) -> None:
        """Runtime lifecycle이 operational phase command 전에 exact session을 시작합니다.

        Args:
            environment: Session identity를 소유한 runtime environment입니다.
        """
        locator = SessionLocator.from_worktree(self.root)
        binding = RuntimeEnvironmentResolver().resolve(environment)
        StateHandle.initialize(locator, binding)

    def run_application(self, *arguments: str) -> tuple[int, dict[str, object]]:
        """Captured stdout과 exit code로 PhaseRunnerApplication을 호출합니다.

        Args:
            arguments: State path가 없는 phase runner argument입니다.

        Returns:
            Exit code와 JSON object output입니다.
        """
        output = StringIO()
        with redirect_stdout(output):
            exit_code = PhaseRunnerApplication(self.root).run(
                list(arguments),
                environment=self.environment,
            )
        payload: object = json.loads(output.getvalue())
        self.assertIsInstance(payload, dict)
        return exit_code, dict(payload) if isinstance(payload, dict) else {}

    def test_init_current_complete_finalize_use_one_session_workflow(self) -> None:
        """모든 phase command가 workflow ID로 같은 session aggregate를 갱신합니다."""
        init_code, initialized = self.run_application(
            "init",
            "--workflow-id",
            "workflow-a",
            "--skill",
            "checkpoint",
            "--run-id",
            "run-a",
            "--north-star",
            "세션 A 목표",
        )
        current_code, current = self.run_application(
            "current",
            "--workflow-id",
            "workflow-a",
        )
        complete_code, completed = self.run_application(
            "complete",
            "--workflow-id",
            "workflow-a",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "완료",
        )
        finalize_code, finalized = self.run_application(
            "finalize",
            "--workflow-id",
            "workflow-a",
            "--terminal-state",
            "done",
        )

        self.assertEqual((0, 0, 0, 0), (init_code, current_code, complete_code, finalize_code))
        self.assertEqual("phase_initialized", initialized["event"])
        self.assertEqual("current_phase", current["event"])
        self.assertEqual("phase_completed", completed["event"])
        self.assertEqual("phase_run_finalized", finalized["event"])
        locator = SessionLocator.from_worktree(self.root)
        state = SessionKernel(locator).inspect(SessionId("session-a"))
        workflow = state.workflows[WorkflowId("workflow-a")]
        self.assertEqual("completed", workflow.status.value)
        self.assertEqual("세션 A 목표", workflow.goal)
        self.assertFalse((self.root / ".agents/runs/current-phase-run.json").exists())
        self.assertFalse((self.root / ".agents/runs/active-north-star.json").exists())

    def test_complete_terminal_state_atomically_finishes_operational_workflow(self) -> None:
        """Operational final phase는 complete와 finalize를 한 번의 workflow CAS로 닫습니다."""
        init_code, _ = self.run_application(
            "init",
            "--workflow-id",
            "workflow-atomic",
            "--skill",
            "checkpoint",
            "--run-id",
            "run-atomic",
            "--north-star",
            "한 번의 terminal transition으로 checkpoint를 닫는다",
        )
        complete_code, completed = self.run_application(
            "complete",
            "--workflow-id",
            "workflow-atomic",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "완료",
            "--terminal-state",
            "done",
        )

        locator = SessionLocator.from_worktree(self.root)
        workflow = (
            SessionKernel(locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("workflow-atomic")]
        )

        self.assertEqual((0, 0), (init_code, complete_code))
        self.assertEqual("phase_run_finalized", completed["event"])
        self.assertEqual("done", completed["terminal_state"])
        self.assertIs(True, completed["atomic_completion"])
        completed_phase = completed["completed_phase"]
        evaluation = completed["evaluation"]
        self.assertIsInstance(completed_phase, dict)
        self.assertIsInstance(evaluation, dict)
        if not isinstance(completed_phase, dict) or not isinstance(evaluation, dict):
            self.fail("atomic terminal receipt must contain phase and evaluation objects")
        self.assertEqual("completed", completed_phase["status"])
        self.assertIs(True, evaluation["accepted"])
        self.assertEqual("completed", workflow.status.value)
        self.assertEqual(1, workflow.revision)

    def test_same_workflow_id_isolated_by_runtime_session(self) -> None:
        """동일 workflow ID도 runtime session directory 사이에서 섞이지 않습니다."""
        self.run_application(
            "init",
            "--workflow-id",
            "shared",
            "--skill",
            "checkpoint",
            "--run-id",
            "run-a",
            "--north-star",
            "A 목표",
        )
        self.environment = {"CODEX_THREAD_ID": "session-b"}
        self._initialize_session(self.environment)
        self.run_application(
            "init",
            "--workflow-id",
            "shared",
            "--skill",
            "checkpoint",
            "--run-id",
            "run-b",
            "--north-star",
            "B 목표",
        )
        locator = SessionLocator.from_worktree(self.root)

        state_a = SessionKernel(locator).inspect(SessionId("session-a"))
        state_b = SessionKernel(locator).inspect(SessionId("session-b"))

        self.assertEqual("A 목표", state_a.workflows[WorkflowId("shared")].goal)
        self.assertEqual("B 목표", state_b.workflows[WorkflowId("shared")].goal)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
