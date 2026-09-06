"""공개 writer 전체에서 phase와 adaptive 종료 상태의 일관성을 검증합니다."""

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.session_kernel import (
    TransitionRejected,
    WorkflowFinalized,
    WorkflowId,
    WorkflowStatus,
)
from scripts.agent_harness.state_cli import StateCliApplication
from scripts.skill_harness import phase_runner
from scripts.skill_harness.tests.test_phase_runner import PhaseRunnerFixture


class WorkflowTerminalAdmissionTest(TestCase):
    """실패 label로 phase 계약을 우회하지 못하고 정상 실패는 닫히게 합니다."""

    def test_operational_writers_preserve_phase_identity_and_completed_results(self) -> None:
        """공개 advance와 finalize는 단계 삭제·순서 변경·완료 기록 변조를 거부합니다."""
        source = (Path(__file__).resolve().parents[3] / ".agents/skills/contracts.json").read_text()
        for operation in ("advance", "finalize"):
            for mutation in ("delete", "reorder", "rename", "rewrite", "skip-ahead"):
                with (
                    self.subTest(operation=operation, mutation=mutation),
                    PhaseRunnerFixture() as fixture,
                ):
                    fixture.write(".agents/skills/contracts.json", source)
                    initialized = fixture.run("init", "--skill", "commit", "--run-id", "real")
                    self.assertEqual(0, initialized.exit_code, initialized.output)
                    completed = fixture.run(
                        "complete",
                        "--phase-id",
                        "1",
                        "--status",
                        "completed",
                        "--summary",
                        "inspected",
                        "--evidence",
                        "git_status: inspected",
                        "--evidence",
                        "diff_review: inspected",
                    )
                    self.assertEqual(0, completed.exit_code, completed.output)
                    before = fixture._state_handle.inspect()
                    workflow = before.workflows[WorkflowId(fixture.workflow_id)]
                    payload = json.loads(json.dumps(dict(workflow.payload)))
                    phase = payload["phase_run"]
                    if mutation == "delete":
                        phase["phases"] = phase["phases"][:1]
                    elif mutation == "reorder":
                        phase["phases"].reverse()
                    elif mutation == "rename":
                        phase["phases"][1]["name"] = "replacement"
                    elif mutation == "rewrite":
                        phase["phases"][0]["evidence"] = ["fabricated"]
                    else:
                        phase["phases"][2]["status"] = "completed"
                    arguments = [
                        "workflow",
                        operation,
                        "--workflow-id",
                        fixture.workflow_id,
                        "--expected-revision",
                        str(workflow.revision),
                        "--idempotency-key",
                        "phase-preservation",
                    ]
                    if operation == "finalize":
                        phase["current_phase_id"] = None
                        phase["terminal_state"] = "committed"
                        arguments.extend(("--status", "completed"))
                    arguments.extend(("--payload-json", json.dumps(payload)))
                    result = StateCliApplication().run(
                        arguments,
                        fixture.environment,
                        fixture.root,
                    )
                    self.assertNotEqual(0, result.exit_code, result.stdout)
                    self.assertEqual(
                        before.to_payload(), fixture._state_handle.inspect().to_payload()
                    )

    def test_operational_final_phase_still_completes_atomically(self) -> None:
        """정상 단계 순서와 마지막 단계·종료의 원자적 완료를 계속 허용합니다."""
        source = (Path(__file__).resolve().parents[3] / ".agents/skills/contracts.json").read_text()
        with PhaseRunnerFixture() as fixture:
            fixture.write(".agents/skills/contracts.json", source)
            fixture.run("init", "--skill", "commit", "--run-id", "real")
            for phase_id, evidence in (
                (1, ("git_status: inspected", "diff_review: inspected")),
                (2, ("staged_files: scoped",)),
                (3, ("commit_sha: " + "a" * 40,)),
            ):
                arguments = [
                    "complete",
                    "--phase-id",
                    str(phase_id),
                    "--status",
                    "completed",
                    "--summary",
                    "completed",
                ]
                for item in evidence:
                    arguments.extend(("--evidence", item))
                if phase_id == 3:
                    arguments.extend(("--terminal-state", "committed"))
                result = fixture.run(*arguments)
                self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual("committed", result.payload["terminal_state"])

    def test_generic_failed_finalization_cannot_bypass_pending_phase(self) -> None:
        """CLI와 직접 kernel event 모두 미완료 phase를 failed로 숨기지 못합니다."""
        for writer in ("cli", "kernel"):
            with self.subTest(writer=writer), PhaseRunnerFixture() as fixture:
                fixture.write_adaptive_control_contract()
                fixture.run("init", "--skill", "plan-issues", "--run-id", "pending")
                fixture.write_adaptive_control_continue_state()
                before = fixture._state_handle.inspect()
                workflow = before.workflows[WorkflowId(fixture.workflow_id)]
                if writer == "cli":
                    result = StateCliApplication().run(
                        (
                            "workflow",
                            "finalize",
                            "--workflow-id",
                            fixture.workflow_id,
                            "--expected-revision",
                            str(workflow.revision),
                            "--status",
                            "failed",
                            "--payload-json",
                            json.dumps(dict(workflow.payload)),
                            "--idempotency-key",
                            "terminal:pending",
                        ),
                        fixture.environment,
                        fixture.root,
                    )
                    self.assertNotEqual(0, result.exit_code, result.stdout)
                else:
                    with self.assertRaises(TransitionRejected):
                        fixture._state_handle.apply(
                            WorkflowFinalized(
                                session_id=fixture._state_handle.session_id,
                                workflow_id=workflow.id,
                                actor_id=fixture._state_handle.actor_id,
                                expected_workflow_revision=workflow.revision,
                                terminal_status=WorkflowStatus.FAILED,
                                payload=workflow.payload,
                                idempotency_key="terminal:pending",
                            )
                        )
                self.assertEqual(before.to_payload(), fixture._state_handle.inspect().to_payload())

    def test_deleting_phase_projection_cannot_hide_pending_execution(self) -> None:
        """종료 payload에서 phase namespace를 지워도 원래 계약을 탈출하지 못합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "pending")
            fixture.write_adaptive_control_continue_state()
            workflow = fixture._state_handle.inspect().workflows[WorkflowId(fixture.workflow_id)]
            payload = dict(workflow.payload)
            payload.pop("phase_run")
            with self.assertRaises(TransitionRejected):
                fixture._state_handle.apply(
                    WorkflowFinalized(
                        session_id=fixture._state_handle.session_id,
                        workflow_id=workflow.id,
                        actor_id=fixture._state_handle.actor_id,
                        expected_workflow_revision=workflow.revision,
                        terminal_status=WorkflowStatus.FAILED,
                        payload=payload,
                        idempotency_key="terminal:deleted-phase",
                    )
                )

    def test_typed_execution_failure_still_finalizes(self) -> None:
        """실제 typed FAILED와 실패 phase가 일치하면 정식 실패 종료를 허용합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "failed")
            fixture.write_adaptive_control_execution_failed_state()
            completed = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "typed execution failed",
                "--reason",
                "execution failed",
            )
            self.assertEqual(0, completed.exit_code, completed.output)
            finalized = fixture.run("finalize", "--terminal-state", "failed")
            self.assertEqual(0, finalized.exit_code, finalized.output)

    def test_expired_evaluation_watchdog_still_returns_blocked(self) -> None:
        """실제 timeout 예외는 adaptive 성공 증거 없이도 일관된 blocked 종료를 보존합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_single_phase_adaptive_evaluate_harness_contract()
            with patch.object(phase_runner.time, "time", return_value=1_000.0):
                fixture.run("init", "--skill", "evaluate-harness", "--run-id", "watchdog")
            with patch.object(phase_runner.time, "time", return_value=6_401.0):
                completed = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    "blocked",
                    "--summary",
                    "watchdog exceeded",
                    "--reason",
                    "emergency timeout",
                )
                self.assertEqual(0, completed.exit_code, completed.output)
                finalized = fixture.run("finalize", "--terminal-state", "blocked")
                self.assertEqual(0, finalized.exit_code, finalized.output)
