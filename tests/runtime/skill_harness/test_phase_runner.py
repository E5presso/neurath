"""test phase runner 관련 타입과 실행 흐름을 정의합니다."""

import hashlib
import json
import os
import re
import subprocess
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from typing import Self, cast
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts.agent_harness.adaptive_control import (
    AmbiguityAssessment,
    AuthorityReceipt,
    ClarificationGap,
    ControlAction,
    ControlDecision,
    CriterionEvidence,
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapAuthority,
    GapInventory,
    GapResolution,
    GoalAttainment,
    GoalContract,
    GoalCoverage,
    IterationObservation,
    OracleOwner,
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionTarget,
    adaptive_output_fingerprint,
    approved_requirement_fingerprint,
    user_decision_value_summary_digest,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityStatus,
    AdaptiveControlAuthorityVerification,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlReceipt,
    AdaptiveControlState,
    AdaptiveControlStore,
)
from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.harness_incident import (
    HarnessIncidentApplication,
    HarnessIncidentValidationError,
)
from scripts.agent_harness.repository_readback import RepositoryWorktreeReadback
from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    KernelEvent,
    ProcessState,
    SessionKernel,
    SessionLocator,
    SessionStateStore,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowId,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityBinding,
    StateHandle,
)
from scripts.skill_harness import phase_runner as phase_runner_module
from scripts.skill_harness.phase_runner import (
    AdaptiveControlTransitionReadback,
    PhaseRunner,
    PhaseRunnerApplication,
    PhaseRunStore,
    SkillContractRepository,
)

DEFAULT_NORTH_STAR = "테스트 목표: 최초 지시·완료 기준·비목표"
SATURATED_SOURCE_CAPABILITY_INVENTORY = (
    "source_capability_inventory: "
    f"source_sha={'a' * 40} pass_count=2 new_capability_counts=7|0 "
    "capability_ids=ambiguity|goal-contract|goal-attainment|reflection|"
    "termination|promotion|provenance capability_count=7 source_files=42 "
    "complete=true saturated=true"
)


class TransitionOnlyPhaseFixtureKernel(SessionKernel):
    """Negative readback fixtures가 valid transition만 persist하고 authority는 만들지 않습니다."""

    def apply(
        self,
        event: KernelEvent,
        expected_revision: int | None = None,
    ) -> ProcessState:
        """Production reducer/CAS는 유지하고 aggregate authority admission만 생략합니다."""
        paths = self._session_paths(event.session_id)
        return SessionStateStore(paths.process_state).transact(event, expected_revision)


class PhaseRunnerApplicationTest(TestCase):
    """skill contract와 phase runner enforcement 회귀 시나리오를 unittest fixture로 고정합니다."""

    def test_semantic_single_phase_contract_initializes_adaptive_policy(self) -> None:
        """Single-phase semantic skill도 phase 수와 무관하게 required policy를 고정합니다."""
        root = Path(__file__).resolve().parents[3]
        repository = SkillContractRepository(root)

        semantic = repository.get("audit-spec")
        operational = repository.get("checkpoint")

        self.assertEqual(1, len(semantic.phases))
        self.assertTrue(semantic.adaptive_control_required)
        self.assertFalse(operational.adaptive_control_required)

    def test_init_writes_state_and_outputs_first_phase(self) -> None:
        """skill contract와 phase runner enforcement의 init writes state and outputs first phase 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()

            result = fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-001",
                "--workflow-id",
                "workflow-explicit",
            )

            state = fixture.read_state("workflow-explicit")

        self.assertEqual(0, result.exit_code)
        self.assertEqual("phase_initialized", result.payload["event"])
        current_phase = result.object_payload("current_phase")
        self.assertEqual(1, current_phase["id"])
        self.assertEqual("orientation", current_phase["name"])
        self.assertEqual("process-ticket", state["skill"])
        self.assertEqual(1, state["current_phase_id"])

    def test_current_outputs_quantitative_requirements(self) -> None:
        """skill contract와 phase runner enforcement의 current outputs quantitative requirements 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run("current")

        self.assertEqual(0, result.exit_code)
        self.assertEqual("current_phase", result.payload["event"])
        self.assertEqual(2, result.payload["min_evidence_count"])
        self.assertEqual(
            ["agents_rules_read", "work_item_source"], result.payload["required_evidence"]
        )

    def test_current_resurfaces_north_star_for_reanchoring(self) -> None:
        """매 phase 조회 때 착수 시 고정한 목표를 다시 노출해 표류를 막는다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-001",
                "--north-star",
                "의도: X 구현. 완료 기준: 테스트 통과. 비목표: Y 건드리지 않기.",
            )

            result = fixture.run("current")

        self.assertEqual(0, result.exit_code)
        self.assertEqual(
            "의도: X 구현. 완료 기준: 테스트 통과. 비목표: Y 건드리지 않기.",
            result.payload["north_star"],
        )

    def test_fresh_transition_receipts_equal_the_current_phase_readback(self) -> None:
        """Fresh init/complete receipt는 별도 current 호출 없이 같은 phase contract를 제공합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            initialized = fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "fresh-receipt-chain",
            )
            current_after_init = fixture.run("current")
            completed = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "orientation complete",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: GitHub issue 1",
            )
            current_after_complete = fixture.run("current")

        self.assertEqual(
            initialized.object_payload("current_phase"),
            current_after_init.object_payload("phase"),
        )
        self.assertEqual(
            completed.object_payload("next_phase"),
            current_after_complete.object_payload("phase"),
        )

    def test_complete_resurfaces_north_star(self) -> None:
        """phase 완료 응답에도 착수 시 고정한 목표를 다시 노출한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-001",
                "--north-star",
                "고정된 목표 문장",
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "done",
                "--evidence",
                "agents_rules_read: yes",
                "--evidence",
                "work_item_source: plan",
            )

        self.assertEqual(0, result.exit_code)
        self.assertEqual("고정된 목표 문장", result.payload["north_star"])

    def test_phase_completion_records_timing(self) -> None:
        """Run 시작과 phase 완료 시각·소요를 기록해 병목을 데이터로 볼 수 있게 한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "done",
                "--evidence",
                "agents_rules_read: yes",
                "--evidence",
                "work_item_source: plan",
            )
            state = fixture.read_state()

        self.assertIsInstance(state["started_at_epoch"], float)
        phases = state["phases"]
        assert isinstance(phases, list)
        phase = phases[0]
        assert isinstance(phase, dict)
        duration = phase["duration_seconds"]
        self.assertIsInstance(phase["completed_at_epoch"], float)
        assert isinstance(duration, float)
        self.assertGreaterEqual(duration, 0.0)
        self.assertEqual(0, result.exit_code)

    def test_evaluate_harness_runtime_budget_returns_control_instead_of_claiming_success(
        self,
    ) -> None:
        """Run wall-clock watchdog 뒤에는 성공을 가장하지 않고 blocked로 종료합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            with patch.object(phase_runner_module.time, "time", return_value=1_000.0):
                fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
            head_sha = "a" * 40
            rows = "A|B"
            row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
            decisions = "A:deny|B:allow"
            row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            worktree_sha = fixture.worktree_sha()
            matrix_id = hashlib.sha256(
                f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
            ).hexdigest()
            evidence = (
                "failure_scenario: scenario=bounded-evaluation",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                (
                    f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} rows={rows} "
                    f"row_specs={row_specs} row_count=2 decisions={decisions} row_nodes={row_nodes}"
                ),
            )
            with patch.object(phase_runner_module.time, "time", return_value=6_401.0):
                over_budget = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    "completed",
                    "--summary",
                    "continue evaluating",
                    *(item for value in evidence for item in ("--evidence", value)),
                )
                returned_control = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    "blocked",
                    "--summary",
                    "evaluation budget exhausted",
                    "--reason",
                    "explicit user approval is required for another generation",
                    *(item for value in evidence for item in ("--evidence", value)),
                )

        self.assertEqual(1, over_budget.exit_code)
        self.assertEqual("EVALUATION_BUDGET_EXHAUSTED", over_budget.payload["code"])
        self.assertEqual(0, returned_control.exit_code, returned_control.output)

    def test_evaluate_harness_allows_saturated_inventory_within_three_pass_budget(
        self,
    ) -> None:
        """Source delta loop가 포화되면 30분을 넘었어도 총 90분 안에서 matrix를 freeze합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            with patch.object(phase_runner_module.time, "time", return_value=1_000.0):
                fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
            head_sha = "a" * 40
            rows = "A|B"
            row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
            decisions = "A:deny|B:allow"
            row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            worktree_sha = fixture.worktree_sha()
            matrix_id = hashlib.sha256(
                f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
            ).hexdigest()
            with patch.object(phase_runner_module.time, "time", return_value=4_600.0):
                result = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    "completed",
                    "--summary",
                    "source inventory saturated",
                    "--evidence",
                    "failure_scenario: scenario=bounded-source-study",
                    "--evidence",
                    SATURATED_SOURCE_CAPABILITY_INVENTORY,
                    "--evidence",
                    (
                        f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                        f"head_sha={head_sha} worktree_sha={worktree_sha} rows={rows} "
                        f"row_specs={row_specs} row_count=2 decisions={decisions} row_nodes={row_nodes}"
                    ),
                )

        self.assertEqual(0, result.exit_code, result.output)

    def test_evaluate_harness_requires_saturated_source_inventory_without_pass_cap(self) -> None:
        """Source inventory는 두 번 이상 실행하되 신규 capability가 0이 될 때까지 계속할 수 있습니다."""
        rows = (
            (
                "source_capability_inventory: sources=label-only",
                "source_capability_inventory.source_sha",
            ),
            (
                "source_capability_inventory: "
                f"source_sha={'a' * 40} pass_count=1 new_capability_counts=7 "
                "capability_ids=a|b|c|d|e|f|g capability_count=7 source_files=42 "
                "complete=true saturated=true",
                "source_capability_inventory.pass_count",
            ),
            (
                "source_capability_inventory: "
                f"source_sha={'a' * 40} pass_count=3 new_capability_counts=7|1|1 "
                "capability_ids=a|b|c|d|e|f|g|h|i capability_count=9 source_files=42 "
                "complete=true saturated=true",
                "source_capability_inventory.saturation",
            ),
            (
                "source_capability_inventory: "
                f"source_sha={'a' * 40} pass_count=4 new_capability_counts=7|1|1|0 "
                "capability_ids=a|b|c|d|e|f|g|h|i capability_count=9 source_files=42 "
                "complete=true saturated=true",
                None,
            ),
        )
        for inventory, expected_failure in rows:
            with self.subTest(expected_failure=expected_failure):
                with PhaseRunnerFixture() as fixture:
                    fixture.write_structured_evaluate_harness_contract()
                    fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
                    head_sha = "a" * 40
                    matrix_rows = "A|B"
                    row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
                    decisions = "A:deny|B:allow"
                    row_nodes = (
                        "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
                    )
                    worktree_sha = fixture.worktree_sha()
                    matrix_id = hashlib.sha256(
                        (
                            f"{head_sha}|{worktree_sha}|{matrix_rows}|{row_specs}|{decisions}|{row_nodes}"
                        ).encode()
                    ).hexdigest()
                    result = fixture.run(
                        "complete",
                        "--phase-id",
                        "1",
                        "--status",
                        "completed",
                        "--summary",
                        "freeze source inventory",
                        "--evidence",
                        "failure_scenario: scenario=bounded-source-study",
                        "--evidence",
                        inventory,
                        "--evidence",
                        (
                            f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                            f"head_sha={head_sha} worktree_sha={worktree_sha} "
                            f"rows={matrix_rows} row_specs={row_specs} "
                            f"row_count=2 decisions={decisions} row_nodes={row_nodes}"
                        ),
                    )

                if expected_failure is None:
                    self.assertEqual(0, result.exit_code, result.output)
                else:
                    self.assertEqual(1, result.exit_code)
                    self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
                    self.assertIn(expected_failure, str(result.payload["message"]))

    def test_finalize_reports_phase_timing_summary(self) -> None:
        """Finalize 응답은 단계별 소요와 전체 소요 요약을 함께 낸다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "cannot inspect work item",
                "--reason",
                "GitHub issue is unavailable",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: unavailable",
            )
            result = fixture.run("finalize", "--terminal-state", "failed")

        self.assertEqual(0, result.exit_code)
        timings = result.payload["phase_timings"]
        assert isinstance(timings, list)
        measured = [
            row for row in timings if isinstance(row, dict) and row["duration_seconds"] is not None
        ]
        self.assertEqual(1, len(measured))
        total = result.payload["total_duration_seconds"]
        assert isinstance(total, float)
        self.assertGreaterEqual(total, 0.0)

    def test_init_rejects_empty_north_star(self) -> None:
        """빈 목표로는 착수할 수 없다. 앵커 없는 계약 작업이 생기지 않게 한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()

            result = fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-001",
                "--north-star",
                "   ",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("NORTH_STAR_REQUIRED", result.payload["code"])

    def test_phase_runner_has_no_global_pointer_or_legacy_path_store(self) -> None:
        """Phase runner production surface에는 global pointer와 path store가 존재하지 않습니다."""
        self.assertFalse(hasattr(phase_runner_module, "ActiveNorthStarPointer"))
        self.assertFalse(hasattr(phase_runner_module, "PhaseStateStore"))

    def test_multiple_workflows_coexist_in_one_exact_session(self) -> None:
        """같은 session의 두 phase workflow는 북극성과 current state를 서로 덮지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run(
                "init",
                "--workflow-id",
                "workflow-a",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-a",
                "--north-star",
                "run-a 목표: 티켓 A 완주",
            )
            fixture.run(
                "init",
                "--workflow-id",
                "workflow-b",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-b",
                "--north-star",
                "run-b 목표: 티켓 B 완주",
            )

            current_a = fixture.run("current", "--workflow-id", "workflow-a")
            current_b = fixture.run("current", "--workflow-id", "workflow-b")

        self.assertEqual("run-a 목표: 티켓 A 완주", current_a.payload["north_star"])
        self.assertEqual("run-b 목표: 티켓 B 완주", current_b.payload["north_star"])

    def test_existing_workflow_rejects_different_init_without_overwrite(self) -> None:
        """이미 사용 중인 workflow identity는 다른 run으로 재초기화되지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            first = fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-a",
            )

            conflicting = fixture.run(
                "init",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-b",
            )
            current = fixture.read_state()

        self.assertEqual(0, first.exit_code)
        self.assertEqual(1, conflicting.exit_code)
        self.assertEqual("STATE_INVALID", conflicting.payload["code"])
        self.assertEqual("run-a", current["run_id"])

    def test_current_missing_workflow_does_not_fallback_to_another_workflow(self) -> None:
        """Explicit workflow가 없으면 같은 session의 다른 active workflow를 scan하지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-a")

            result = fixture.run("current", "--workflow-id", "missing-workflow")

        self.assertEqual(1, result.exit_code)
        self.assertEqual("STATE_MISSING", result.payload["code"])

    def test_finalize_one_workflow_preserves_other_workflow(self) -> None:
        """한 workflow terminal transition은 같은 session의 다른 workflow를 제거하지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            for workflow_id, run_id in (("workflow-a", "run-a"), ("workflow-b", "run-b")):
                fixture.run(
                    "init",
                    "--workflow-id",
                    workflow_id,
                    "--skill",
                    "process-ticket",
                    "--run-id",
                    run_id,
                )
            fixture.run(
                "complete",
                "--workflow-id",
                "workflow-a",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "cannot inspect work item",
                "--reason",
                "GitHub issue is unavailable",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: unavailable",
            )
            finalized = fixture.run(
                "finalize",
                "--workflow-id",
                "workflow-a",
                "--terminal-state",
                "failed",
            )
            current_b = fixture.run("current", "--workflow-id", "workflow-b")

        self.assertEqual(0, finalized.exit_code)
        self.assertEqual("current_phase", current_b.payload["event"])
        self.assertEqual("run-b", current_b.payload["run_id"])

    def test_public_cli_rejects_state_path_and_reinject_command(self) -> None:
        """Manual state selector와 global reinjection command는 parser surface에서 제거됩니다."""
        application = PhaseRunnerApplication(Path.cwd())

        with self.assertRaises(SystemExit):
            application.run([
                "init",
                "--workflow-id",
                "workflow-a",
                "--skill",
                "process-ticket",
                "--run-id",
                "run-a",
                "--north-star",
                "목표",
                "--state",
                "/tmp/legacy.json",
            ])
        with self.assertRaises(SystemExit):
            application.run(["reinject", "--workflow-id", "workflow-a"])
        with self.assertRaises(SystemExit):
            application.run(["current"])

    def test_complete_rejects_wrong_phase_id(self) -> None:
        """skill contract와 phase runner enforcement의 complete rejects wrong phase id 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "2",
                "--status",
                "completed",
                "--summary",
                "done",
                "--evidence",
                "agents_rules_read: yes",
                "--evidence",
                "work_item_source: plan",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("PHASE_ID_MISMATCH", result.payload["code"])

    def test_complete_rejects_missing_required_evidence(self) -> None:
        """skill contract와 phase runner enforcement의 complete rejects missing required evidence 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "done",
                "--evidence",
                "agents_rules_read: yes",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("INSUFFICIENT_EVIDENCE", result.payload["code"])

    def test_terminal_non_success_does_not_require_unavailable_success_evidence(self) -> None:
        """Blocked/failed 종료는 만들 수 없는 성공 receipt 때문에 active 상태에 갇히지 않습니다."""
        for status in ("blocked", "failed"):
            with self.subTest(status=status), PhaseRunnerFixture() as fixture:
                fixture.write_contracts_with_evidence_pattern()
                fixture.run("init", "--skill", "automate-qa", "--run-id", "run-001")

                terminal = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    status,
                    "--summary",
                    "required external authority is unavailable",
                    "--reason",
                    "the host cannot issue the required receipt",
                )
                finalized = fixture.run("finalize", "--terminal-state", status)

            self.assertEqual(0, terminal.exit_code)
            completed_phase = cast(dict[str, object], terminal.payload["completed_phase"])
            evaluation = cast(dict[str, object], terminal.payload["evaluation"])
            self.assertEqual([], completed_phase["evidence"])
            self.assertEqual(0, evaluation["min_evidence_count"])
            self.assertEqual([], evaluation["required_evidence"])
            self.assertEqual([], evaluation["pattern_checked_evidence"])
            self.assertEqual(0, finalized.exit_code)
            self.assertEqual(status, finalized.payload["terminal_state"])

    def test_adaptive_missing_evaluator_cannot_terminalize_the_current_phase_as_blocked(
        self,
    ) -> None:
        """평가 evidence 부재는 blocker가 아니며 current phase를 재개 가능하게 유지합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "evaluator-pending")
            receipt = fixture.write_adaptive_control_continue_state()
            before = fixture.read_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "blocked",
                "--summary",
                "formal evaluator is unavailable",
                "--reason",
                "independent evaluator report has not been admitted",
            )
            after = fixture.read_state()

        self.assertIs(ControlAction.CONTINUE, receipt.decision.action)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("adaptive_control_terminal", str(result.payload["message"]))
        self.assertEqual(before, after)

    def test_adaptive_missing_evaluator_cannot_relabel_pending_as_failed(self) -> None:
        """평가 pending은 failed label로도 current phase를 terminalize할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "evaluator-pending")
            receipt = fixture.write_adaptive_control_continue_state()
            before = fixture.read_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "formal evaluator is unavailable",
                "--reason",
                "independent evaluator report has not been admitted",
            )
            after = fixture.read_state()

        self.assertIs(ControlAction.CONTINUE, receipt.decision.action)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("adaptive_control_terminal", str(result.payload["message"]))
        self.assertEqual(before, after)

    def test_adaptive_incomplete_inventory_cannot_masquerade_as_terminal_blocker(self) -> None:
        """조사 미완료의 BLOCKED action은 external blocker receipt가 아닙니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "inventory-pending")
            receipt = fixture.write_adaptive_control_ambiguity_state(ControlAction.BLOCKED)
            before = fixture.read_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "blocked",
                "--summary",
                "inventory is incomplete",
                "--reason",
                "one requirement section has not been assessed",
            )
            after = fixture.read_state()

        self.assertIs(ControlAction.BLOCKED, receipt.decision.action)
        self.assertIsNone(receipt.ambiguity.selected_gap_id)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("adaptive_control_terminal", str(result.payload["message"]))
        self.assertEqual(before, after)

    def test_generic_finalization_cannot_create_its_own_adaptive_phase_result(self) -> None:
        """Typed execution failure만으로 generic final event가 pending phase 결과를 만들지 못합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "forged-terminal")
            fixture.write_adaptive_control_execution_failed_state()
            before = fixture._state_handle.inspect()
            workflow = before.workflows[WorkflowId(fixture.workflow_id)]
            state = phase_runner_module.PhaseRunState.from_payload(fixture.read_state())
            contract = SkillContractRepository(fixture.root).get("plan-issues")
            candidate = state.with_completed_phase(
                contract,
                1,
                "failed",
                (),
                "owner-supplied result",
                "execution failed",
            ).with_terminal_state("failed")
            with self.assertRaises(TransitionRejected):
                fixture._state_handle.apply(
                    WorkflowFinalized(
                        session_id=fixture._state_handle.session_id,
                        workflow_id=workflow.id,
                        actor_id=fixture._state_handle.actor_id,
                        expected_workflow_revision=workflow.revision,
                        terminal_status=WorkflowStatus.FAILED,
                        payload={**workflow.payload, "phase_run": candidate.as_payload()},
                        idempotency_key="generic:forged-terminal",
                    )
                )
            self.assertEqual(before.to_payload(), fixture._state_handle.inspect().to_payload())

    def test_adaptive_authoritative_repository_blocker_can_terminalize_the_phase(self) -> None:
        """Current repository blocker는 평가 pending과 달리 blocked terminal을 허용합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "repository-blocker")
            receipt = fixture.write_adaptive_control_repository_blocker_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "blocked",
                "--summary",
                "repository source proves a terminal blocker",
                "--reason",
                "the current tracked blocker source denies further work",
            )
            finalized = fixture.run("finalize", "--terminal-state", "blocked")
            self.assertEqual(0, finalized.exit_code, finalized.output)

        self.assertIs(ControlAction.BLOCKED, receipt.decision.action)
        self.assertEqual("repository-blocker", receipt.ambiguity.selected_gap_id)
        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual("blocked", result.payload["terminal_candidate"])

    def test_adaptive_typed_execution_failure_can_terminalize_the_phase(self) -> None:
        """Typed FAILED execution은 pending label과 달리 failed terminal을 허용합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "execution-failed")
            fixture.write_adaptive_control_execution_failed_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "typed execution failed",
                "--reason",
                "the adaptive execution lifecycle recorded FAILED",
            )

        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual("failed", result.payload["terminal_candidate"])

    def test_adaptive_repairable_criterion_failure_cannot_relabel_as_terminal_failed(
        self,
    ) -> None:
        """Repairable criterion FAIL은 typed execution failure로 승격되지 않습니다."""
        goal_fingerprint = "a" * 64
        workflow_id = WorkflowId("repairable-failure")
        receipt = AdaptiveControlReceipt(
            workflow_id=workflow_id,
            workflow_revision=3,
            goal_fingerprint=goal_fingerprint,
            ambiguity=AmbiguityAssessment(
                score=0.0,
                ready=True,
                action=ControlAction.CONTINUE,
                selected_gap_id=None,
                unresolved_gap_ids=(),
                stale_gap_ids=(),
                assessment_complete=True,
            ),
            progress=0.0,
            attainment=GoalAttainment(
                goal_fingerprint=goal_fingerprint,
                achieved=False,
                progress=0.0,
                action=ControlAction.CONTINUE,
                failed=("repairable-criterion",),
                pending=("goal-coverage",),
                stale=(),
                settled=(),
            ),
            decision=ControlDecision(
                action=ControlAction.CONTINUE,
                achieved=False,
                reason="repair the current criterion",
            ),
        )
        authority = AdaptiveControlAuthorityVerification(
            status=AdaptiveControlAuthorityStatus.VERIFIED,
            workflow_id=workflow_id,
            workflow_revision=3,
            goal_fingerprint=goal_fingerprint,
            verified_delegation_ids=(),
            pending_claims=(),
            reason="all external claims verified",
            user_prompt_receipt=None,
        )
        store = cast(PhaseRunStore, Mock())
        store.read_adaptive_control_transition.return_value = AdaptiveControlTransitionReadback(
            receipt=receipt,
            authority=authority,
            contract_goal="repairable goal",
            criteria=(),
            blocker_gap_ids=(),
            execution_status=ExecutionStatus.COMPLETED,
        )

        failures = PhaseRunner(
            SkillContractRepository(Path.cwd())
        )._adaptive_terminal_transition_failures("failed", store)

        self.assertIn("adaptive_control_terminal.failure", failures)

    def test_adaptive_evaluate_harness_watchdog_can_return_blocked_control(self) -> None:
        """Emergency watchdog은 evaluator pending과 달리 bounded control return을 허용합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_single_phase_adaptive_evaluate_harness_contract()
            with patch.object(phase_runner_module.time, "time", return_value=1_000.0):
                fixture.run("init", "--skill", "evaluate-harness", "--run-id", "watchdog")
            with patch.object(phase_runner_module.time, "time", return_value=6_401.0):
                result = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    "blocked",
                    "--summary",
                    "watchdog returned control",
                    "--reason",
                    "the emergency wall-clock boundary was exceeded",
                )

        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual("blocked", result.payload["terminal_candidate"])

    def test_adaptive_control_receipt_rejects_label_only_and_forged_claims(self) -> None:
        """A37: label 문자열과 current receipt를 가장한 goal fingerprint를 거부합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-label")
            fixture.write_adaptive_control_complete_state()
            label_only = fixture.complete_adaptive_control_phase(
                "adaptive_control_receipt: complete"
            )

        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-forged")
            receipt = fixture.write_adaptive_control_complete_state()
            forged = fixture.adaptive_control_receipt_evidence(receipt).replace(
                receipt.goal_fingerprint,
                "f" * 64,
            )
            forged_result = fixture.complete_adaptive_control_phase(forged)

        self.assertEqual(1, label_only.exit_code)
        self.assertEqual(1, forged_result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", label_only.payload["code"])
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", forged_result.payload["code"])

    def test_adaptive_control_receipt_rejects_stale_workflow_revision(self) -> None:
        """A38: 제출 전 sibling state commit이 생기면 이전 revision receipt를 거부합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-stale")
            receipt = fixture.write_adaptive_control_complete_state()
            stale_evidence = fixture.adaptive_control_receipt_evidence(receipt)
            fixture.write_skill_state({"post_receipt_mutation": True})

            result = fixture.complete_adaptive_control_phase(stale_evidence)

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("adaptive_control_receipt", str(result.payload["message"]))

    def test_adaptive_control_receipt_accepts_complete_and_rejects_await_user(self) -> None:
        """A39: exact COMPLETE만 완료로 인정하고 exact AWAIT_USER도 비완료로 둡니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-complete")
            complete_receipt = fixture.write_adaptive_control_complete_state()
            complete_result = fixture.complete_adaptive_control_phase(
                fixture.adaptive_control_receipt_evidence(complete_receipt)
            )
            fixture.refresh_adaptive_control_completion_authority()
            finalize_result = fixture.run("finalize", "--terminal-state", "planned")

        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-await")
            await_receipt = fixture.write_adaptive_control_await_user_state()
            await_result = fixture.complete_adaptive_control_phase(
                fixture.adaptive_control_receipt_evidence(await_receipt)
            )

        self.assertIs(ControlAction.COMPLETE, complete_receipt.decision.action)
        self.assertEqual(0, complete_result.exit_code, complete_result.output)
        self.assertEqual(0, finalize_result.exit_code, finalize_result.output)
        self.assertIs(ControlAction.AWAIT_USER, await_receipt.decision.action)
        self.assertEqual(1, await_result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", await_result.payload["code"])

    def test_finalize_rechecks_current_adaptive_completion_after_phase_receipt(self) -> None:
        """Phase 승인 뒤 goal authority가 바뀌면 stale 성공 evidence로 finalize할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-reopen")
            complete_receipt = fixture.write_adaptive_control_complete_state()
            completed = fixture.complete_adaptive_control_phase(
                fixture.adaptive_control_receipt_evidence(complete_receipt)
            )
            fixture.override_adaptive_control_goal(EvidenceKind.USER_ACCEPTANCE)

            finalized = fixture.run("finalize", "--terminal-state", "planned")

        self.assertEqual(0, completed.exit_code, completed.output)
        self.assertEqual(1, finalized.exit_code)
        self.assertEqual("STATE_INVALID", finalized.payload["code"])

    def test_adaptive_policy_adds_first_and_final_gates_for_new_runs_only(self) -> None:
        """Skill 분기 없이 persisted policy가 init/receipt를 합성하고 legacy state는 보존합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_two_phase_adaptive_contract()
            initialized = fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "adaptive-policy",
            )
            missing_initial = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "phase one",
                "--evidence",
                "phase_one_evidence: yes",
            )
            initial_receipt = fixture.write_adaptive_control_await_user_state()
            phase_one = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "phase one",
                "--evidence",
                "phase_one_evidence: yes",
                "--evidence",
                fixture.adaptive_control_initialized_evidence(initial_receipt),
            )
            current = fixture.run("current")
            missing_final = fixture.run(
                "complete",
                "--phase-id",
                "2",
                "--status",
                "completed",
                "--summary",
                "phase two",
                "--evidence",
                "phase_two_evidence: yes",
            )

        current_phase = current.object_payload("phase")
        initialized_phase = initialized.object_payload("current_phase")
        initialized_required = initialized_phase["required_evidence"]
        current_required = current_phase["required_evidence"]
        if not isinstance(initialized_required, list) or not all(
            isinstance(item, str) for item in initialized_required
        ):
            raise TypeError("initial required_evidence must be a string list")
        if not isinstance(current_required, list) or not all(
            isinstance(item, str) for item in current_required
        ):
            raise TypeError("current required_evidence must be a string list")
        self.assertIn(
            "adaptive_control_initialized",
            initialized_required,
        )
        self.assertEqual("INSUFFICIENT_EVIDENCE", missing_initial.payload["code"])
        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertIn("adaptive_control_receipt", current_required)
        self.assertEqual("INSUFFICIENT_EVIDENCE", missing_final.payload["code"])

    def test_complete_next_phase_payload_uses_effective_adaptive_requirements(self) -> None:
        """Complete receipt의 next phase도 합성된 adaptive evidence contract를 반환합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_two_phase_adaptive_contract()
            fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "adaptive-next-phase",
            )
            receipt = fixture.write_adaptive_control_await_user_state()

            completed = fixture.complete_adaptive_initial_phase(receipt)

        self.assertEqual(0, completed.exit_code, completed.output)
        next_phase = completed.object_payload("next_phase")
        self.assertEqual(
            ["phase_two_evidence", "adaptive_control_receipt"],
            next_phase["required_evidence"],
        )
        self.assertEqual(2, next_phase["min_evidence_count"])

    def test_adaptive_initialization_rejects_unresolved_ambiguity_actions(self) -> None:
        """ASK_USER, RESEARCH, BLOCKED intent는 질문/조사 전에 구현 phase로 넘어가지 않습니다."""
        for action in (
            ControlAction.ASK_USER,
            ControlAction.RESEARCH,
            ControlAction.BLOCKED,
        ):
            with self.subTest(action=action), PhaseRunnerFixture() as fixture:
                fixture.write_two_phase_adaptive_contract()
                fixture.run(
                    "init",
                    "--skill",
                    "plan-issues",
                    "--run-id",
                    f"adaptive-{action.value}",
                )
                receipt = fixture.write_adaptive_control_ambiguity_state(action)

                result = fixture.run(
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    "completed",
                    "--summary",
                    "phase one",
                    "--evidence",
                    "phase_one_evidence: yes",
                    "--evidence",
                    fixture.adaptive_control_initialized_evidence(receipt),
                )

                self.assertIs(action, receipt.ambiguity.action)
                self.assertEqual(1, result.exit_code)
                self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
                self.assertIn(
                    "adaptive_control_initialized",
                    str(result.payload["message"]),
                )

    def test_adaptive_readback_binds_goal_to_current_phase_north_star(self) -> None:
        """Fresh adaptive state는 immutable initial north star와 다른 goal로 시작하지 못합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_two_phase_adaptive_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "goal-mismatch-init")
            before = fixture._state_handle.inspect()

            with self.assertRaises(TransitionRejected):
                fixture.write_adaptive_control_await_user_state(
                    goal="축소된 초기 goal",
                )

            after = fixture._state_handle.inspect()

        self.assertEqual(before.revision, after.revision)
        self.assertEqual(
            DEFAULT_NORTH_STAR,
            after.workflows[WorkflowId(fixture.workflow_id)].goal,
        )

    def test_typed_goal_amendment_completes_against_current_contract(self) -> None:
        """Typed amendment 뒤 phase와 finalization은 current goal authority로 완료됩니다."""
        amended_goal = "사용자가 수정한 current adaptive goal"
        with PhaseRunnerFixture() as fixture:
            fixture.write_two_phase_adaptive_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "goal-amendment-final")
            initial = fixture.write_adaptive_control_await_user_state()
            phase_one = fixture.complete_adaptive_initial_phase(initial)
            amended = fixture.override_adaptive_control_goal(
                EvidenceKind.INDEPENDENT_SEMANTIC,
                goal=amended_goal,
            )
            completion = fixture.write_current_adaptive_control_complete_state()
            phase_two = fixture.run(
                "complete",
                "--phase-id",
                "2",
                "--status",
                "completed",
                "--summary",
                "phase two",
                "--evidence",
                "phase_two_evidence: yes",
                "--evidence",
                fixture.adaptive_control_receipt_evidence(completion),
            )
            refreshed = fixture.refresh_adaptive_control_completion_authority()
            phase_state = fixture.read_state()
            workflow = fixture._state_handle.inspect().workflows[WorkflowId(fixture.workflow_id)]
            current_goal = fixture._adaptive_control_store().read().state.contract.goal
            finalized = fixture.run("finalize", "--terminal-state", "planned")

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertNotEqual(initial.goal_fingerprint, amended.goal_fingerprint)
        self.assertEqual(amended.goal_fingerprint, completion.goal_fingerprint)
        self.assertEqual(completion.goal_fingerprint, refreshed.goal_fingerprint)
        self.assertEqual(DEFAULT_NORTH_STAR, phase_state["north_star"])
        self.assertEqual(DEFAULT_NORTH_STAR, workflow.goal)
        self.assertEqual(amended_goal, current_goal)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(0, finalized.exit_code, finalized.output)

    def test_every_adaptive_phase_transition_rechecks_current_intent_readiness(self) -> None:
        """Phase 1 후 재개된 ASK_USER/RESEARCH는 중간 phase advance를 fail-closed합니다."""
        for action in (ControlAction.ASK_USER, ControlAction.RESEARCH):
            with self.subTest(action=action), PhaseRunnerFixture() as fixture:
                fixture.write_three_phase_adaptive_contract()
                fixture.run(
                    "init",
                    "--skill",
                    "plan-issues",
                    "--run-id",
                    f"reactive-{action.value}",
                )
                initial = fixture.write_adaptive_control_await_user_state()
                phase_one = fixture.complete_adaptive_initial_phase(initial)
                fixture.write_adaptive_control_ambiguity_state(action)

                phase_two = fixture.run(
                    "complete",
                    "--phase-id",
                    "2",
                    "--status",
                    "completed",
                    "--summary",
                    "phase two",
                    "--evidence",
                    "phase_two_evidence: yes",
                )

                self.assertEqual(0, phase_one.exit_code, phase_one.output)
                self.assertEqual(1, phase_two.exit_code)
                self.assertEqual("EVIDENCE_PATTERN_MISMATCH", phase_two.payload["code"])
                self.assertIn("adaptive_control_transition", str(phase_two.payload["message"]))

        with PhaseRunnerFixture() as fixture:
            fixture.write_three_phase_adaptive_contract()
            fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "reactive-ready",
            )
            initial = fixture.write_adaptive_control_await_user_state()
            phase_one = fixture.complete_adaptive_initial_phase(initial)
            phase_two = fixture.run(
                "complete",
                "--phase-id",
                "2",
                "--status",
                "completed",
                "--summary",
                "phase two",
                "--evidence",
                "phase_two_evidence: yes",
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)

    def test_adaptive_phase_transition_rejects_ready_user_gap_without_runtime_authority(
        self,
    ) -> None:
        """Ready ambiguity score가 self-authored USER_FACT를 phase authority로 세탁하지 못합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_three_phase_adaptive_contract()
            fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "authority-user-gap",
            )
            initial = fixture.write_adaptive_control_continue_state()
            phase_one = fixture.complete_adaptive_initial_phase(initial)
            ready = fixture.write_adaptive_control_user_gap_without_runtime_authority()

            phase_two = fixture.complete_adaptive_middle_phase()

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertTrue(ready.ambiguity.ready)
        self.assertIs(ControlAction.CONTINUE, ready.decision.action)
        self.assertEqual(1, phase_two.exit_code)
        self.assertIn("adaptive_control_transition.authority", str(phase_two.payload["message"]))

    def test_adaptive_phase_transition_rejects_recovery_decisions(self) -> None:
        """Reflection recovery와 exhaustion action은 phase advance 전에 소비해야 합니다."""
        for action in (
            ControlAction.CHANGE_APPROACH,
            ControlAction.ENUMERATE_INVARIANT,
            ControlAction.PROMOTE_HARNESS,
        ):
            with self.subTest(action=action), PhaseRunnerFixture() as fixture:
                fixture.write_three_phase_adaptive_contract()
                fixture.run(
                    "init",
                    "--skill",
                    "plan-issues",
                    "--run-id",
                    f"recovery-{action.value}",
                )
                initial = fixture.write_adaptive_control_continue_state()
                phase_one = fixture.complete_adaptive_initial_phase(initial)
                recovery = fixture.write_adaptive_control_decision(action)

                phase_two = fixture.complete_adaptive_middle_phase()

                self.assertEqual(0, phase_one.exit_code, phase_one.output)
                self.assertIs(action, recovery.decision.action)
                self.assertEqual(1, phase_two.exit_code)
                self.assertIn(
                    "adaptive_control_transition.decision",
                    str(phase_two.payload["message"]),
                )

    def test_adaptive_phase_transition_allows_continue_with_verified_authority(self) -> None:
        """Ready CONTINUE decision은 exact external authority가 검증됐을 때만 진행합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_three_phase_adaptive_contract()
            fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "authority-continue",
            )
            receipt = fixture.write_adaptive_control_continue_state()

            phase_one = fixture.complete_adaptive_initial_phase(receipt)

        self.assertIs(ControlAction.CONTINUE, receipt.decision.action)
        self.assertEqual(0, phase_one.exit_code, phase_one.output)

    def test_adaptive_phase_transition_bounds_await_user_to_user_acceptance(self) -> None:
        """AWAIT_USER는 current USER_ACCEPTANCE, coverage, execution gap만 허용합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_three_phase_adaptive_contract()
            fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "await-user-only",
            )
            user_only = fixture.write_adaptive_control_await_user_state()
            allowed = fixture.complete_adaptive_initial_phase(user_only)

        with PhaseRunnerFixture() as fixture:
            fixture.write_three_phase_adaptive_contract()
            fixture.run(
                "init",
                "--skill",
                "plan-issues",
                "--run-id",
                "await-user-independent",
            )
            mixed = fixture.write_adaptive_control_await_user_state(
                include_independent_criterion=True,
            )
            denied = fixture.complete_adaptive_initial_phase(mixed)

        self.assertIs(ControlAction.AWAIT_USER, user_only.decision.action)
        self.assertEqual(0, allowed.exit_code, allowed.output)
        self.assertIs(ControlAction.AWAIT_USER, mixed.decision.action)
        self.assertEqual(1, denied.exit_code)
        self.assertIn("adaptive_control_transition.await_user", str(denied.payload["message"]))

    def test_review_code_rejects_self_attested_receipt_without_delegation_evidence(self) -> None:
        """형식이 그럴듯해도 consumed delegation이 없으면 review를 완료하지 못합니다."""
        head_sha = "a" * 40
        outcome_ref = f"sha256:{'b' * 64}"
        with PhaseRunnerFixture() as fixture:
            fixture.write_review_code_contract()
            fixture.run("init", "--skill", "review-code", "--run-id", "review-001")

            result = fixture.complete_review_code(head_sha, outcome_ref=outcome_ref)

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("delegation_evidence", str(result.payload["message"]))

    def test_review_code_rejects_skipped_execution(self) -> None:
        """Review execute는 skipped로 우회할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_review_code_contract()
            fixture.run("init", "--skill", "review-code", "--run-id", "review-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "skipped",
                "--summary",
                "review skipped",
                *fixture.review_evidence("a" * 40, f"sha256:{'b' * 64}"),
            )

        self.assertEqual(1, result.exit_code)
        self.assertIn("skip_forbidden", str(result.payload["message"]))

    def test_review_code_rejects_ambiguous_or_duplicate_evidence_labels(self) -> None:
        """한 mega-string이나 중복 label로 여러 receipt를 가장할 수 없습니다."""
        head_sha = "a" * 40
        outcome_ref = f"sha256:{'b' * 64}"
        with PhaseRunnerFixture() as fixture:
            fixture.write_review_code_contract()
            fixture.run("init", "--skill", "review-code", "--run-id", "review-001")
            fixture.write_review_completion(head_sha)
            evidence = list(fixture.review_evidence(head_sha, outcome_ref))
            evidence.extend(("--evidence", evidence[-3]))

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "review complete",
                *evidence,
            )

        self.assertEqual(1, result.exit_code)
        self.assertIn("review_report_readback.label", str(result.payload["message"]))

    def test_review_code_accepts_consumed_delegation_artifact(self) -> None:
        """Consumed delegation과 canonical artifact가 일치할 때만 review를 완료합니다."""
        head_sha = "a" * 40
        with PhaseRunnerFixture() as fixture:
            fixture.write_review_code_contract()
            fixture.run("init", "--skill", "review-code", "--run-id", "review-001")
            outcome_ref = fixture.write_review_completion(head_sha)

            result = fixture.complete_review_code(head_sha, outcome_ref=outcome_ref)

        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual("phase_completed", result.payload["event"])

    def test_review_code_rejects_tampered_consumed_artifact(self) -> None:
        """Consume 뒤 artifact 본문을 바꾸면 digest-verified read-back이 실패합니다."""
        head_sha = "a" * 40
        with PhaseRunnerFixture() as fixture:
            fixture.write_review_code_contract()
            fixture.run("init", "--skill", "review-code", "--run-id", "review-001")
            outcome_ref = fixture.write_review_completion(head_sha)
            fixture.corrupt_artifact(outcome_ref)

            result = fixture.complete_review_code(head_sha, outcome_ref=outcome_ref)

        self.assertEqual(1, result.exit_code)
        self.assertIn("delegation_evidence.readback", str(result.payload["message"]))

    def test_complete_advances_to_next_phase(self) -> None:
        """skill contract와 phase runner enforcement의 complete advances to next phase 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.write_skill_state({"monitor_event_ack": {"event_id": "event-123"}})

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "orientation complete",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: GitHub issue 1",
            )
            state = fixture.read_state()
            skill_state = fixture.read_skill_state()

        self.assertEqual(0, result.exit_code)
        self.assertEqual("phase_completed", result.payload["event"])
        next_phase = result.object_payload("next_phase")
        self.assertEqual(2, next_phase["id"])
        self.assertEqual(2, state["current_phase_id"])
        acknowledgement = skill_state["monitor_event_ack"]
        self.assertIsInstance(acknowledgement, dict)
        assert isinstance(acknowledgement, dict)
        self.assertEqual("event-123", acknowledgement["event_id"])

    def test_atomic_terminal_complete_rejects_nonfinal_phase_without_mutation(self) -> None:
        """Atomic terminal 요청이 이르면 phase evidence도 부분 저장하지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            before = fixture.read_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "orientation complete",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: GitHub issue 1",
                "--terminal-state",
                "merged",
            )
            after = fixture.read_state()

        self.assertEqual(1, result.exit_code)
        self.assertEqual("INCOMPLETE_PHASES", result.payload["code"])
        self.assertEqual(before, after)

    def test_atomic_terminal_complete_rejects_adaptive_workflow_without_mutation(self) -> None:
        """Adaptive workflow는 final authority refresh를 위해 기존 two-command 경로를 유지합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_adaptive_control_contract()
            fixture.run("init", "--skill", "plan-issues", "--run-id", "adaptive-atomic")
            before = fixture.read_state()

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "adaptive goal complete",
                "--terminal-state",
                "planned",
            )
            after = fixture.read_state()

        self.assertEqual(1, result.exit_code)
        self.assertEqual("ATOMIC_FINALIZE_UNSUPPORTED", result.payload["code"])
        self.assertEqual(before, after)

    def test_atomic_terminal_complete_reuses_terminal_validation_without_mutation(self) -> None:
        """Invalid terminal과 terminal phase mismatch는 completion을 부분 저장하지 않습니다."""
        cases = (
            ("completed", "unknown", "TERMINAL_STATE_INVALID"),
            ("failed", "blocked", "TERMINAL_PHASE_REQUIRED"),
        )
        for status, terminal_state, expected_code in cases:
            with (
                self.subTest(status=status, terminal_state=terminal_state),
                PhaseRunnerFixture() as fixture,
            ):
                fixture.write_contracts()
                fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
                before = fixture.read_state()
                arguments = [
                    "complete",
                    "--phase-id",
                    "1",
                    "--status",
                    status,
                    "--summary",
                    "terminal validation",
                    "--terminal-state",
                    terminal_state,
                ]
                if status == "completed":
                    arguments.extend((
                        "--evidence",
                        "agents_rules_read: AGENTS.md and charter",
                        "--evidence",
                        "work_item_source: GitHub issue 1",
                    ))
                else:
                    arguments.extend(("--reason", "the terminal states do not match"))

                result = fixture.run(*arguments)
                after = fixture.read_state()

            self.assertEqual(1, result.exit_code)
            self.assertEqual(expected_code, result.payload["code"])
            self.assertEqual(before, after)

    def test_finalize_rejects_incomplete_success_state(self) -> None:
        """skill contract와 phase runner enforcement의 finalize rejects incomplete success state 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run("finalize", "--terminal-state", "merged")

        self.assertEqual(1, result.exit_code)
        self.assertEqual("INCOMPLETE_PHASES", result.payload["code"])

    def test_failed_phase_can_finalize_failed_state(self) -> None:
        """skill contract와 phase runner enforcement의 failed phase can finalize failed state 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "cannot inspect work item",
                "--reason",
                "GitHub issue is unavailable",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: unavailable",
            )
            result = fixture.run("finalize", "--terminal-state", "failed")
            state = fixture.read_state()

        self.assertEqual(0, result.exit_code)
        self.assertEqual("phase_run_finalized", result.payload["event"])
        self.assertEqual("failed", state["terminal_state"])

    def test_process_ticket_finalize_rejects_open_harness_incident(self) -> None:
        """Direct phase finalize도 open incident를 우회할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "monitor loop stopped",
                "--reason",
                "delivery timeout",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: issue 128",
            )
            fixture.record_harness_incident(
                "monitor-loop-stopped",
                "approval 전에 monitor loop가 중단됨",
            )

            result = fixture.run("finalize", "--terminal-state", "failed")

        self.assertEqual(1, result.exit_code)
        self.assertEqual("HARNESS_INCIDENT_UNRESOLVED", result.payload["code"])

    def test_process_ticket_finalize_accepts_escalated_harness_incident(self) -> None:
        """이관된 incident는 수정 소유권이 loop owner에게 넘어갔으므로 finalize를 막지 않는다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "harness gap blocks the ticket",
                "--reason",
                "typed helper denied",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: issue 128",
            )
            incident_id = fixture.record_harness_incident(
                "typed-helper-denied",
                "공식 helper 호출이 게이트에 거부됨",
            )
            fixture.escalate_harness_incident(
                incident_id,
                "helper 인식이 실행 위치에 묶여 있어 loop owner의 develop 수정이 필요함",
                ["uv run python -m scripts.agent_harness.harness_incident validate"],
            )

            result = fixture.run("finalize", "--terminal-state", "failed")

        self.assertEqual(0, result.exit_code, result.output)

    def test_incident_application_rejects_incomplete_escalation_before_finalize(self) -> None:
        """Typed application은 불완전한 escalation을 canonical state에 만들지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "harness gap blocks the ticket",
                "--reason",
                "typed helper denied",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: issue 128",
            )
            incident_id = fixture.record_harness_incident(
                "typed-helper-denied",
                "공식 helper 호출이 게이트에 거부됨",
            )

            with self.assertRaisesRegex(HarnessIncidentValidationError, "summary"):
                fixture.escalate_harness_incident(incident_id, "", [])

            result = fixture.run("finalize", "--terminal-state", "failed")

        self.assertEqual(1, result.exit_code)
        self.assertEqual("HARNESS_INCIDENT_UNRESOLVED", result.payload["code"])

    def test_process_ticket_finalize_accepts_empty_typed_incident_ledger(self) -> None:
        """Canonical process state의 빈 typed incident ledger는 terminal complete입니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "failed",
                "--summary",
                "monitor loop stopped",
                "--reason",
                "delivery timeout",
                "--evidence",
                "agents_rules_read: AGENTS.md and charter",
                "--evidence",
                "work_item_source: issue 128",
            )

            result = fixture.run("finalize", "--terminal-state", "failed")

        self.assertEqual(0, result.exit_code, result.output)

    def test_complete_rejects_evidence_that_does_not_match_required_pattern(self) -> None:
        """skill contract와 phase runner enforcement의 complete rejects evidence that does not match required pattern 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts_with_evidence_pattern()
            fixture.run("init", "--skill", "automate-qa", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "qa evidence collected",
                "--evidence",
                "client_surface_evidence: looked okay",
                "--evidence",
                "network_or_api_evidence: response status 200",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_complete_accepts_evidence_that_matches_required_pattern(self) -> None:
        """skill contract와 phase runner enforcement의 complete accepts evidence that matches required pattern 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_contracts_with_evidence_pattern()
            fixture.run("init", "--skill", "automate-qa", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "qa evidence collected",
                "--evidence",
                "client_surface_evidence: screenshot=/tmp/home.png",
                "--evidence",
                "network_or_api_evidence: response status 200",
            )

        self.assertEqual(0, result.exit_code)
        evaluation = result.object_payload("evaluation")
        self.assertEqual(["client_surface_evidence"], evaluation["pattern_checked_evidence"])

    def test_process_ticket_monitoring_rejects_terminal_state_without_monitor_event(
        self,
    ) -> None:
        """process-ticket monitoring은 monitor terminal event 없는 증거를 거부해야 한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_monitoring_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                "pr_review_status: HUMAN_REVIEW was posted",
                "--evidence",
                "ai_review_head_sha: abc123",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
                "--evidence",
                (
                    "monitor_event_source: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "poll_interval_seconds=30 resume_adapter=command"
                ),
                "--evidence",
                "monitor_started: local monitor armed",
                "--evidence",
                (
                    "monitor_terminal_state: review-blocked by inference; "
                    "no monitor_event terminal arrived"
                ),
                "--evidence",
                "process_state_resume_check: branch matches upstream",
                "--evidence",
                (
                    "route_resume_contract: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "resume_adapter=command"
                ),
                "--evidence",
                "monitor_event_readback: monitor_event=event source=local-pr-monitor resume_status=invoked-fallback",
                "--evidence",
                (
                    "live_terminal_readback: reason=mergeable-clean state=OPEN "
                    "mergeState=CLEAN reviewDecision=APPROVED "
                    "failedChecks=0 pendingChecks=0 headRefOid=abc123 "
                    "unresolvedReviewThreads=0"
                ),
                "--evidence",
                "pending_human_comments: TOTAL=0",
                "--evidence",
                "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_monitoring_rejects_unconfigured_monitor_resume(self) -> None:
        """문자열만 꾸민 monitor evidence는 resume adapter 없이 통과하면 안 된다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_monitoring_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                "pr_review_status: AUTO_APPROVE was posted",
                "--evidence",
                "ai_review_head_sha: abc123",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
                "--evidence",
                (
                    "monitor_event_source: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "poll_interval_seconds=30 resume_adapter=unconfigured"
                ),
                "--evidence",
                "monitor_started: local monitor armed",
                "--evidence",
                (
                    "monitor_terminal_state: monitor_event=terminal "
                    "reason=mergeable-clean source=local-pr-monitor "
                    "resume_status=queued-no-adapter"
                ),
                "--evidence",
                "process_state_resume_check: branch matches upstream",
                "--evidence",
                (
                    "route_resume_contract: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "resume_adapter=unconfigured"
                ),
                "--evidence",
                "monitor_event_readback: monitor_event=terminal source=local-pr-monitor resume_status=queued-no-adapter",
                "--evidence",
                (
                    "live_terminal_readback: reason=mergeable-clean state=OPEN "
                    "mergeState=CLEAN reviewDecision=APPROVED "
                    "failedChecks=0 pendingChecks=0 headRefOid=abc123 "
                    "unresolvedReviewThreads=0"
                ),
                "--evidence",
                "pending_human_comments: TOTAL=0",
                "--evidence",
                "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_monitoring_rejects_unresolved_review_threads(self) -> None:
        """미해결 review thread가 남으면 comments TOTAL=0이어도 mergeable-clean이 아니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_monitoring_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                "pr_review_status: AUTO_APPROVE was posted",
                "--evidence",
                "ai_review_head_sha: abc123",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
                "--evidence",
                (
                    "monitor_event_source: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "poll_interval_seconds=30 resume_adapter=command"
                ),
                "--evidence",
                "monitor_started: local monitor armed",
                "--evidence",
                (
                    "monitor_terminal_state: monitor_event=terminal "
                    "reason=mergeable-clean source=local-pr-monitor "
                    "resume_status=invoked"
                ),
                "--evidence",
                "process_state_resume_check: branch matches upstream",
                "--evidence",
                (
                    "route_resume_contract: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "resume_adapter=command"
                ),
                "--evidence",
                (
                    "monitor_event_readback: monitor_event=terminal "
                    "source=local-pr-monitor resume_status=invoked"
                ),
                "--evidence",
                (
                    "live_terminal_readback: reason=mergeable-clean state=OPEN "
                    "mergeState=CLEAN reviewDecision=APPROVED "
                    "failedChecks=0 pendingChecks=0 headRefOid=abc123 "
                    "unresolvedReviewThreads=0"
                ),
                "--evidence",
                "pending_human_comments: TOTAL=0",
                "--evidence",
                "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=1",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_monitoring_accepts_local_pr_monitor_terminal_state(self) -> None:
        """process-ticket monitoring은 local monitor terminal event를 근거로 수락한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_monitoring_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.write_skill_state({
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "repo": "octo/neurath",
                    "pr_number": 131,
                    "session_id": "session-1",
                    "workflow_id": "process-ticket-131",
                    "runtime_id": "monitor-runtime-1",
                    "worktree_id": "worktree-1",
                    "observation_resource": {
                        "kind": "monitor-observation-cache",
                        "worktree_id": "worktree-1",
                    },
                    "poll_interval_seconds": 30,
                    "resume_adapter": "command",
                    "last_seen": {"snapshot": {}},
                    "pid": 1234,
                    "heartbeat_at_epoch": 1.0,
                },
            })

            result = fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                "pr_review_status: HUMAN_REVIEW was posted",
                "--evidence",
                "ai_review_head_sha: abc123",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=autopilot "
                    "terminal_sink=autopilot merge_policy=auto"
                ),
                "--evidence",
                (
                    "monitor_event_source: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "poll_interval_seconds=30 resume_adapter=command"
                ),
                "--evidence",
                "monitor_started: local monitor armed",
                "--evidence",
                (
                    "monitor_terminal_state: monitor_event=terminal "
                    "reason=mergeable-clean source=local-pr-monitor "
                    "resume_status=invoked"
                ),
                "--evidence",
                "process_state_resume_check: branch matches upstream",
                "--evidence",
                (
                    "route_resume_contract: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "resume_adapter=command"
                ),
                "--evidence",
                (
                    "monitor_event_readback: monitor_event=terminal "
                    "source=local-pr-monitor resume_status=invoked"
                ),
                "--evidence",
                (
                    "live_terminal_readback: reason=mergeable-clean state=OPEN "
                    "mergeState=CLEAN reviewDecision=APPROVED "
                    "failedChecks=0 pendingChecks=0 headRefOid=abc123 "
                    "unresolvedReviewThreads=0"
                ),
                "--evidence",
                "pending_human_comments: TOTAL=0",
                "--evidence",
                "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0",
            )

        self.assertEqual(0, result.exit_code)
        evaluation = result.object_payload("evaluation")
        self.assertEqual(
            [
                "agent_session_context",
                "live_terminal_readback",
                "monitor_event_readback",
                "monitor_event_source",
                "monitor_terminal_state",
                "pending_human_comments",
                "route_resume_contract",
                "unresolved_review_threads",
            ],
            evaluation["pattern_checked_evidence"],
        )

    def test_process_ticket_work_event_requires_both_completion_acks(self) -> None:
        """작업 event read-back은 delivery와 두 completion ACK를 모두 요구합니다."""
        root = Path(__file__).resolve().parents[3]
        contracts = json.loads((root / ".agents/skills/contracts.json").read_text(encoding="utf-8"))
        phases = contracts["skills"]["process-ticket"]["phase_contracts"]
        monitoring = next(phase for phase in phases if phase["name"] == "monitoring")
        pattern = monitoring["evidence_patterns"]["monitor_event_readback"]
        work_event = "monitor_event=event source=local-pr-monitor resume_status=invoked"

        self.assertIsNone(re.search(pattern, work_event))
        self.assertIsNone(re.search(pattern, f"{work_event} turn_completion.status=completed"))
        self.assertIsNone(re.search(pattern, f"{work_event} turn.status=completed"))
        self.assertIsNotNone(
            re.search(
                pattern,
                f"{work_event} turn_completion.status=completed turn.status=completed",
            )
        )

    def test_monitoring_semantics_reject_live_terminal_head_mismatch(self) -> None:
        """live terminal snapshot은 ai-review가 검증한 current head와 일치해야 합니다."""
        evidence = self._monitoring_semantic_evidence(live_head="def456")

        runner = PhaseRunner(SkillContractRepository(Path.cwd()))

        failures = runner._monitoring_semantic_failures(evidence, {})

        self.assertIn("live_terminal_readback.head_sha_mismatch", failures)

    def test_monitoring_rejects_local_review_remote_head_mismatch(self) -> None:
        """Local independent review receipt는 live remote terminal head와 일치해야 합니다."""
        evidence = self._monitoring_semantic_evidence(local_review_head="b" * 40)

        runner = PhaseRunner(SkillContractRepository(Path.cwd()))
        failures = runner._monitoring_semantic_failures(evidence, {})

        self.assertIn("local_review_head_sha.remote_head_mismatch", failures)

    def test_publication_rejects_local_review_head_mismatch(self) -> None:
        """Publication은 local review, commit, pushed head의 exact SHA mismatch를 거부합니다."""
        reviewed_head = "a" * 40
        evidence = (
            (
                "local_review_head_sha: "
                f"head_sha={reviewed_head} kind=final-local-review outcome=result-applied"
            ),
            f"commit_sha: head_sha={'b' * 40}",
            f"push_head_match: head_sha={reviewed_head}",
        )

        runner = PhaseRunner(SkillContractRepository(Path.cwd()))
        failures = runner._publication_semantic_failures(evidence)

        self.assertIn("commit_sha.local_review_mismatch", failures)

    def test_publication_rejects_missing_verified_review_matrix_receipt(self) -> None:
        """Exact-head review라도 frozen 14-row verification receipt 없이는 publish하지 않습니다."""
        reviewed_head = "a" * 40
        evidence = (
            (
                "local_review_head_sha: "
                f"head_sha={reviewed_head} kind=final-local-review outcome=result-applied"
            ),
            f"commit_sha: head_sha={reviewed_head}",
            f"push_head_match: head_sha={reviewed_head}",
        )

        runner = PhaseRunner(SkillContractRepository(Path.cwd()))
        failures = runner._publication_semantic_failures(evidence)

        self.assertIn("local_review_matrix_receipt.missing", failures)

    def test_publication_accepts_exact_verified_review_matrix_receipt(self) -> None:
        """Canonical 14-row pass receipt가 local/commit/push exact head와 일치하면 수락합니다."""
        reviewed_head = "a" * 40
        evidence = (
            (
                "local_review_head_sha: "
                f"head_sha={reviewed_head} kind=final-local-review outcome=result-applied"
            ),
            (
                "local_review_matrix_receipt: "
                f"matrix_id={'b' * 64} frozen=true head_sha={reviewed_head} "
                "row_count=14 verified_rows=14 blocking_findings=0 verdict=pass "
                "harness_audit=true audit_evidence=3 kind=final-local-review "
                "outcome=result-applied"
            ),
            f"commit_sha: head_sha={reviewed_head}",
            f"push_head_match: head_sha={reviewed_head}",
        )

        with TemporaryDirectory() as temporary_directory:
            runner = PhaseRunner(SkillContractRepository(Path(temporary_directory)))
            failures = runner._publication_semantic_failures(evidence)

        self.assertEqual([], failures)

    def test_publication_rejects_commit_head_that_is_not_repository_head(self) -> None:
        """Publication commit evidence는 실제 repository HEAD와 일치해야 합니다."""
        with TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._initialize_git_repository(repository)
            fabricated_head = "a" * 40
            evidence = self._publication_evidence(fabricated_head)

            runner = PhaseRunner(SkillContractRepository(repository))
            failures = runner._publication_semantic_failures(evidence)

        self.assertIn("commit_sha.current_head", failures)

    def test_publication_rejects_push_evidence_without_upstream(self) -> None:
        """Upstream read-back 없이 push evidence를 수락하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            head = self._initialize_git_repository(repository)
            evidence = self._publication_evidence(head)

            runner = PhaseRunner(SkillContractRepository(repository))
            failures = runner._publication_semantic_failures(evidence)

        self.assertIn("push_head_match.upstream_readback", failures)

    def test_publication_accepts_pushed_head_with_upstream_read_back(self) -> None:
        """실제 HEAD와 upstream read-back이 일치하는 publication evidence만 수락합니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repo"
            repository.mkdir()
            head = self._initialize_git_repository(repository, upstream_root=root / "origin.git")
            evidence = self._publication_evidence(head)

            runner = PhaseRunner(SkillContractRepository(repository))
            failures = runner._publication_semantic_failures(evidence)

        self.assertEqual([], failures)

    def test_publication_rejects_upstream_head_behind_local_commit(self) -> None:
        """Push evidence는 upstream ref가 실제 HEAD와 같을 때만 수락됩니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repo"
            repository.mkdir()
            self._initialize_git_repository(repository, upstream_root=root / "origin.git")
            (repository / "unpushed.txt").write_text("unpushed", encoding="utf-8")
            self._git(repository, "add", "unpushed.txt")
            self._git(repository, "commit", "--no-verify", "-m", "unpushed change")
            head = self._git_head(repository)
            evidence = self._publication_evidence(head)

            runner = PhaseRunner(SkillContractRepository(repository))
            failures = runner._publication_semantic_failures(evidence)

        self.assertIn("push_head_match.upstream_mismatch", failures)

    def test_monitoring_rejects_missing_subscription_read_back(self) -> None:
        """Monitoring evidence는 durable monitor_event_subscription read-back을 요구합니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            evidence = self._monitoring_semantic_evidence()

            runner = PhaseRunner(SkillContractRepository(root))
            failures = runner._monitoring_semantic_failures(evidence, {})

        self.assertIn("monitor_event_source.subscription_readback", failures)

    def test_monitoring_rejects_subscription_identity_mismatch(self) -> None:
        """Monitoring evidence identity는 등록된 subscription과 정확히 일치해야 합니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_state = self._monitoring_skill_state(runtime_id="other-runtime")
            evidence = self._monitoring_semantic_evidence()

            runner = PhaseRunner(SkillContractRepository(root))
            failures = runner._monitoring_semantic_failures(evidence, skill_state)

        self.assertIn("monitor_event_source.runtime_id_mismatch", failures)
        self.assertIn("route_resume_contract.runtime_id_mismatch", failures)

    def test_monitoring_accepts_subscription_bound_evidence(self) -> None:
        """등록된 subscription과 일치하는 monitoring evidence는 추가 실패가 없습니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_state = self._monitoring_skill_state()
            evidence = self._monitoring_semantic_evidence()

            runner = PhaseRunner(SkillContractRepository(root))
            failures = runner._monitoring_semantic_failures(evidence, skill_state)

        self.assertEqual(
            [],
            [failure for failure in failures if "subscription" in failure or "mismatch" in failure],
        )

    def test_merge_cleanup_rejects_unverified_process_state_merged(self) -> None:
        """process_state_merged evidence는 검증된 merge receipt 형태여야 합니다."""
        evidence = self._merge_cleanup_readback_evidence(
            "process_state_merged: merged recorded",
        )

        runner = PhaseRunner(SkillContractRepository(Path.cwd()))
        failures = runner._completed_merge_cleanup_failures(evidence)

        self.assertIn("process_state_merged.receipt", failures)

    def test_merge_cleanup_rejects_merge_commit_missing_from_history(self) -> None:
        """Merge receipt의 merge commit은 fetched local history에 존재해야 합니다."""
        with TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._initialize_git_repository(repository)
            evidence = self._merge_cleanup_readback_evidence(
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'c' * 40}",
            )

            runner = PhaseRunner(SkillContractRepository(repository))
            failures = runner._completed_merge_cleanup_failures(evidence)

        self.assertIn("process_state_merged.merge_commit_readback", failures)

    def test_merge_cleanup_accepts_merge_commit_present_in_history(self) -> None:
        """실제 존재하는 merge commit receipt는 read-back 실패가 없습니다."""
        with TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            head = self._initialize_git_repository(repository)
            evidence = self._merge_cleanup_readback_evidence(
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={head}",
            )

            runner = PhaseRunner(SkillContractRepository(repository))
            failures = runner._completed_merge_cleanup_failures(evidence)

        self.assertEqual([], failures)

    def _publication_evidence(self, head: str) -> tuple[str, ...]:
        """Exact head로 상호 일치하는 publication evidence를 만듭니다."""
        return (
            (
                "local_review_head_sha: "
                f"head_sha={head} kind=final-local-review outcome=result-applied"
            ),
            (
                "local_review_matrix_receipt: "
                f"matrix_id={'b' * 64} frozen=true head_sha={head} "
                "row_count=14 verified_rows=14 blocking_findings=0 verdict=pass "
                "harness_audit=true audit_evidence=3 kind=final-local-review "
                "outcome=result-applied"
            ),
            f"commit_sha: head_sha={head}",
            f"push_head_match: head_sha={head}",
        )

    def _merge_cleanup_readback_evidence(self, merged_receipt: str) -> tuple[str, ...]:
        """다른 cleanup read-back은 통과하는 merge cleanup evidence를 만듭니다."""
        return (
            "merge_command: gh pr merge --squash --delete-branch",
            "github_merge_readback: state=MERGED head_sha=" + "d" * 40,
            "issue_status_readback: issue_status=Done",
            "parent_issue_completion_readback: parent_issue=none",
            "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
            "worktree_cleanup_readback: worktree_removed=true",
            merged_receipt,
        )

    def _monitoring_skill_state(
        self,
        *,
        runtime_id: str = "monitor-runtime-1",
    ) -> dict[str, object]:
        """Monitoring evidence와 대조할 workflow skill-state를 만듭니다."""
        return {
            "monitor_event_subscription": {
                "provider": "local-pr-monitor",
                "repo": "octo/neurath",
                "pr_number": 131,
                "session_id": "session-1",
                "workflow_id": "process-ticket-131",
                "runtime_id": runtime_id,
                "worktree_id": "worktree-1",
                "observation_resource": {
                    "kind": "monitor-observation-cache",
                    "worktree_id": "worktree-1",
                },
                "poll_interval_seconds": 30,
                "resume_adapter": "command",
                "last_seen": {"snapshot": {}},
                "pid": 1234,
                "heartbeat_at_epoch": 1.0,
            },
        }

    def _initialize_git_repository(
        self,
        repository: Path,
        *,
        upstream_root: Path | None = None,
    ) -> str:
        """커밋 하나를 가진 git repository를 만들고 HEAD SHA를 반환합니다."""
        self._git(repository, "init", "-b", "develop")
        (repository / "seed.txt").write_text("seed", encoding="utf-8")
        self._git(repository, "add", "seed.txt")
        self._git(repository, "commit", "--no-verify", "-m", "seed")
        if upstream_root is not None:
            self._git(repository, "init", "--bare", str(upstream_root))
            self._git(repository, "remote", "add", "origin", str(upstream_root))
            self._git(repository, "push", "-u", "origin", "develop")
        return self._git_head(repository)

    def _git_head(self, repository: Path) -> str:
        """Fixture repository의 exact HEAD SHA를 읽습니다."""
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env=self._git_environment(),
        )
        return completed.stdout.strip()

    def _git(self, repository: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repository), *args],
            capture_output=True,
            text=True,
            check=True,
            env=self._git_environment(),
        )

    def _git_environment(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": "/tmp",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Neurath Test",
            "GIT_AUTHOR_EMAIL": "neurath@example.invalid",
            "GIT_COMMITTER_NAME": "Neurath Test",
            "GIT_COMMITTER_EMAIL": "neurath@example.invalid",
        }

    def test_monitoring_semantics_reject_malformed_ai_review_head(self) -> None:
        """malformed ai-review head evidence는 예외 대신 semantic failure를 반환합니다."""
        evidence = self._monitoring_semantic_evidence(ai_review_head="")

        runner = PhaseRunner(SkillContractRepository(Path.cwd()))

        failures = runner._monitoring_semantic_failures(evidence, {})

        self.assertIn("ai_review_head_sha.current_head", failures)

    def test_monitoring_semantics_accept_terminal_reason_states(self) -> None:
        """merged와 closed terminal은 각 GitHub state read-back을 수락합니다."""
        terminal_states = (("merged", "MERGED"), ("closed-without-merge", "CLOSED"))
        runner = PhaseRunner(SkillContractRepository(Path.cwd()))

        for terminal_reason, live_state in terminal_states:
            with self.subTest(terminal_reason=terminal_reason):
                evidence = self._monitoring_semantic_evidence(
                    terminal_reason=terminal_reason,
                    live_state=live_state,
                )

                failures = runner._monitoring_semantic_failures(evidence, {})

                self.assertNotIn("live_terminal_readback.reason", failures)
                self.assertNotIn("live_terminal_readback.state", failures)

    def test_monitoring_semantics_reject_terminal_reason_state_mismatches(self) -> None:
        """terminal reason과 live GitHub state mismatch를 거부합니다."""
        invalid_states = (("merged", "CLOSED"), ("closed-without-merge", "MERGED"))
        runner = PhaseRunner(SkillContractRepository(Path.cwd()))

        for terminal_reason, live_state in invalid_states:
            with self.subTest(terminal_reason=terminal_reason, live_state=live_state):
                evidence = self._monitoring_semantic_evidence(
                    terminal_reason=terminal_reason,
                    live_state=live_state,
                )

                failures = runner._monitoring_semantic_failures(evidence, {})

                self.assertIn("live_terminal_readback.state", failures)

        reason_mismatch = self._monitoring_semantic_evidence(
            terminal_reason="merged",
            live_reason="closed-without-merge",
            live_state="MERGED",
        )
        failures = runner._monitoring_semantic_failures(reason_mismatch, {})
        self.assertIn("live_terminal_readback.reason", failures)

    @staticmethod
    def _monitoring_semantic_evidence(
        *,
        terminal_reason: str = "mergeable-clean",
        live_reason: str | None = None,
        live_state: str = "OPEN",
        ai_review_head: str = "head_sha=" + "a" * 40,
        live_head: str = "a" * 40,
        local_review_head: str = "a" * 40,
    ) -> tuple[str, ...]:
        resolved_live_reason = live_reason or terminal_reason
        live_details = ""
        if terminal_reason == "mergeable-clean":
            live_details = (
                "mergeState=CLEAN reviewDecision=APPROVED failedChecks=0 pendingChecks=0 "
            )
        return (
            f"ai_review_head_sha: {ai_review_head}",
            (
                "local_review_head_sha: "
                f"head_sha={local_review_head} kind=final-local-review outcome=result-applied"
            ),
            (
                "local_review_matrix_receipt: "
                f"matrix_id={'b' * 64} frozen=true head_sha={local_review_head} "
                "row_count=14 verified_rows=14 blocking_findings=0 verdict=pass "
                "harness_audit=true audit_evidence=3 kind=final-local-review "
                "outcome=result-applied"
            ),
            (
                "monitor_event_source: provider=local-pr-monitor "
                "repo=octo/neurath pr_number=131 session_id=session-1 "
                "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                "worktree_id=worktree-1 "
                "observation_resource=monitor-observation-cache:worktree-1 "
                "poll_interval_seconds=30 resume_adapter=command"
            ),
            (
                f"monitor_terminal_state: monitor_event=terminal reason={terminal_reason} "
                "source=local-pr-monitor resume_status=invoked"
            ),
            (
                "route_resume_contract: provider=local-pr-monitor "
                "repo=octo/neurath pr_number=131 session_id=session-1 "
                "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                "worktree_id=worktree-1 "
                "observation_resource=monitor-observation-cache:worktree-1 "
                "resume_adapter=command"
            ),
            (
                "monitor_event_readback: monitor_event=terminal "
                "source=local-pr-monitor resume_status=invoked"
            ),
            (
                f"live_terminal_readback: reason={resolved_live_reason} state={live_state} "
                f"{live_details}headRefOid={live_head} "
                "unresolvedReviewThreads=0"
            ),
            "pending_human_comments: TOTAL=0",
            "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0",
        )

    def test_process_ticket_merge_cleanup_rejects_manual_policy_without_user_approval(
        self,
    ) -> None:
        """normal mode는 사용자 승인 evidence 없이 merge_cleanup에 진입할 수 없다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                "merge_approval: merge_policy=manual monitor reached mergeable-clean",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_merge_cleanup_skips_manual_policy_without_user_approval(
        self,
    ) -> None:
        """normal mode는 승인 전 merge cleanup을 skip하고 mergeable-clean으로 종료할 수 있다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            skip_result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "skipped",
                "--reason",
                "manual merge approval was not provided",
                "--summary",
                "merge cleanup skipped",
                "--evidence",
                "merge_command: skipped",
                "--evidence",
                "merge_approval: merge_policy=manual explicit_user_approval=false",
                "--evidence",
                "github_merge_readback: state=OPEN head_sha=abc123",
                "--evidence",
                "issue_status_readback: state=OPEN",
                "--evidence",
                "parent_issue_completion_readback: skipped parent_issue=not_applicable",
                "--evidence",
                "branch_cleanup_readback: skipped remote_branch_deleted=false local_branch_removed=false",
                "--evidence",
                "worktree_cleanup_readback: skipped worktree_removed=false",
                "--evidence",
                "process_state_merged: merged=null",
                "--evidence",
                "terminal_report: status: mergeable-clean",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )
            fixture.write_adaptive_control_complete_state()
            finalize_result = fixture.run("finalize", "--terminal-state", "mergeable-clean")

        self.assertEqual(0, skip_result.exit_code)
        self.assertEqual(0, finalize_result.exit_code)

    def test_process_ticket_merge_cleanup_accepts_manual_policy_with_user_approval(self) -> None:
        """normal mode도 explicit user approval evidence가 있으면 merge_cleanup을 허용한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                "merge_approval: merge_policy=manual explicit_user_approval=true approved_by=user",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(0, result.exit_code)

    def _skipped_merge_cleanup_evidence(self) -> tuple[str, ...]:
        """merge_cleanup phase를 skip시키되 label·min-count를 만족하는 junk evidence입니다."""
        labels = (
            "merge_command",
            "merge_approval",
            "github_merge_readback",
            "issue_status_readback",
            "parent_issue_completion_readback",
            "branch_cleanup_readback",
            "worktree_cleanup_readback",
            "process_state_merged",
            "terminal_report",
            "gap_dispatch_check",
        )
        arguments: list[str] = []
        for label in labels:
            arguments.extend(("--evidence", f"{label}: skipped-no-merge-happened"))
        return tuple(arguments)

    def _complete_monitor_route(self, fixture: PhaseRunnerFixture) -> None:
        """merge_cleanup finalize 테스트용 phase 8을 완료합니다."""
        fixture.run(
            "complete",
            "--phase-id",
            "8",
            "--status",
            "completed",
            "--summary",
            "monitoring finished",
            "--evidence",
            (
                "agent_session_context: agent_session.kind=worktree_owner "
                "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                "terminal_sink=user merge_policy=manual"
            ),
        )

    def test_finalize_merged_requires_completed_merge_cleanup(self) -> None:
        """merge_cleanup을 skip한 채 merged terminal로 종료할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            self._complete_monitor_route(fixture)
            fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "skipped",
                "--summary",
                "skipping merge cleanup",
                *self._skipped_merge_cleanup_evidence(),
            )

            result = fixture.run("finalize", "--terminal-state", "merged")

        self.assertEqual(1, result.exit_code)
        self.assertEqual("MERGE_CLEANUP_REQUIRED", result.payload["code"])

    def test_finalize_mergeable_clean_still_allows_skipped_merge_cleanup(self) -> None:
        """merged가 아닌 mergeable-clean terminal은 merge_cleanup skip을 허용합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            self._complete_monitor_route(fixture)
            fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "skipped",
                "--summary",
                "not merged yet",
                *self._skipped_merge_cleanup_evidence(),
            )

            fixture.write_adaptive_control_complete_state()
            result = fixture.run("finalize", "--terminal-state", "mergeable-clean")

        self.assertEqual(0, result.exit_code, result.output)

    def test_process_ticket_merge_cleanup_accepts_parent_with_remaining_children(self) -> None:
        """남은 child issue가 있으면 parent issue를 아직 Done으로 만들지 않는다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                "merge_approval: merge_policy=manual explicit_user_approval=true approved_by=user",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                (
                    "parent_issue_completion_readback: parent_issue=#112 "
                    "all_child_issues_done=false parent_completion_action=not_ready "
                    "remaining_child_issues=#116 parent_issue_status=InProgress"
                ),
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(0, result.exit_code)

    def test_process_ticket_merge_cleanup_requires_done_parent_when_all_children_done(self) -> None:
        """모든 child issue가 Done이면 parent issue Done read-back도 필요하다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                "merge_approval: merge_policy=manual explicit_user_approval=true approved_by=user",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                (
                    "parent_issue_completion_readback: parent_issue=#112 "
                    "all_child_issues_done=true parent_completion_action=not_ready "
                    "parent_issue_status=InProgress"
                ),
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        message = str(result.payload["message"])
        self.assertIn("parent_issue_completion_readback.parent_completion_action", message)
        self.assertIn("parent_issue_completion_readback.done", message)

    def test_process_ticket_merge_cleanup_rejects_incomplete_terminal_cleanup(self) -> None:
        """completed merge cleanup은 issue Done, branch 삭제, worktree 삭제 read-back이 필요하다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash",
                "--evidence",
                "merge_approval: merge_policy=manual explicit_user_approval=true approved_by=user",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=false local_branch_removed=false",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=false",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        message = str(result.payload["message"])
        self.assertIn("merge_command.delete_branch", message)
        self.assertIn("issue_status_readback.done", message)
        self.assertIn("branch_cleanup_readback.remote_branch_deleted", message)
        self.assertIn("branch_cleanup_readback.local_branch_removed", message)
        self.assertIn("worktree_cleanup_readback.worktree_removed", message)

    def test_process_ticket_merge_cleanup_accepts_auto_policy_with_auto_merge_invocation(
        self,
    ) -> None:
        """auto mode는 최초 invocation을 merge approval로 고정한 evidence가 필요하다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=autopilot "
                    "terminal_sink=autopilot merge_policy=auto"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                "merge_approval: merge_policy=auto auto_merge_invocation=true",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(0, result.exit_code)

    def test_process_ticket_merge_cleanup_rejects_auto_policy_without_invocation(
        self,
    ) -> None:
        """auto mode도 auto-merge invocation evidence 없이 병합할 수 없다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=autopilot "
                    "terminal_sink=autopilot merge_policy=auto"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                "merge_approval: merge_policy=auto",
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_merge_cleanup_accepts_pr_author_merge_comment(self) -> None:
        """PR 작성자와 같은 사용자의 명시적 PR comment 병합 요청은 승인으로 본다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                (
                    "merge_approval: merge_policy=manual explicit_user_approval=true "
                    "approved_by=user source=github_pr_comment comment_id=123 "
                    "author=E5presso pr_author=E5presso head_sha=abc123 "
                    "approved_at=2026-07-01T03:10:00Z merge_intent=true"
                ),
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(0, result.exit_code)

    def test_process_ticket_merge_cleanup_rejects_comment_from_non_pr_author(self) -> None:
        """GitHub PR comment 승인은 작성자가 PR 작성자와 같아야 한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                (
                    "merge_approval: merge_policy=manual explicit_user_approval=true "
                    "approved_by=user source=github_pr_comment comment_id=123 "
                    "author=reviewer pr_author=E5presso head_sha=abc123 "
                    "approved_at=2026-07-01T03:10:00Z merge_intent=true"
                ),
                "--evidence",
                "github_merge_readback: state=MERGED head_sha=abc123",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_merge_cleanup_rejects_comment_without_head_readback(self) -> None:
        """GitHub PR comment 승인은 대상 head SHA를 고정해야 한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_merge_cleanup_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")
            fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "9",
                "--status",
                "completed",
                "--summary",
                "merge cleanup finished",
                "--evidence",
                "merge_command: gh pr merge --squash --delete-branch",
                "--evidence",
                (
                    "merge_approval: merge_policy=manual explicit_user_approval=true "
                    "approved_by=user source=github_pr_comment comment_id=123 "
                    "author=E5presso pr_author=E5presso approved_at=2026-07-01T03:10:00Z "
                    "merge_intent=true"
                ),
                "--evidence",
                "github_merge_readback: state=MERGED",
                "--evidence",
                "issue_status_readback: issue_status=Done state=CLOSED",
                "--evidence",
                "parent_issue_completion_readback: parent_issue=none",
                "--evidence",
                "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
                "--evidence",
                "worktree_cleanup_readback: worktree_removed=true",
                "--evidence",
                f"process_state_merged: state=MERGED pr_number=131 merge_commit_oid={'e' * 40}",
                "--evidence",
                "terminal_report: status: merged",
                "--evidence",
                "gap_dispatch_check: gaps_detected=none gaps_dispatched=none spawned=none",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_monitoring_rejects_detached_fallback_resume(self) -> None:
        """same-thread resume 실패를 detached fallback으로 소비하면 monitoring evidence가 아니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_monitoring_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "8",
                "--status",
                "completed",
                "--summary",
                "monitoring finished",
                "--evidence",
                "pr_review_status: AUTO_APPROVE posted",
                "--evidence",
                "ai_review_head_sha: abc123",
                "--evidence",
                (
                    "agent_session_context: agent_session.kind=worktree_owner "
                    "agent_session.owned_worktree=/tmp/worktree route_owner=process-ticket "
                    "terminal_sink=user merge_policy=manual"
                ),
                "--evidence",
                (
                    "monitor_event_source: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "poll_interval_seconds=30 resume_adapter=command"
                ),
                "--evidence",
                "monitor_started: local monitor armed",
                "--evidence",
                (
                    "monitor_terminal_state: monitor_event=terminal "
                    "reason=mergeable-clean source=local-pr-monitor "
                    "resume_status=invoked-fallback"
                ),
                "--evidence",
                "process_state_resume_check: branch matches upstream",
                "--evidence",
                (
                    "route_resume_contract: provider=local-pr-monitor "
                    "repo=octo/neurath pr_number=131 session_id=session-1 "
                    "workflow_id=process-ticket-131 runtime_id=monitor-runtime-1 "
                    "worktree_id=worktree-1 "
                    "observation_resource=monitor-observation-cache:worktree-1 "
                    "resume_adapter=command"
                ),
                "--evidence",
                (
                    "monitor_event_readback: monitor_event=terminal "
                    "source=local-pr-monitor resume_status=invoked-fallback"
                ),
                "--evidence",
                (
                    "live_terminal_readback: reason=mergeable-clean state=OPEN "
                    "mergeState=CLEAN reviewDecision=APPROVED "
                    "failedChecks=0 pendingChecks=0 headRefOid=abc123 "
                    "unresolvedReviewThreads=0"
                ),
                "--evidence",
                "pending_human_comments: TOTAL=0",
                "--evidence",
                "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_publication_rejects_english_github_metadata(self) -> None:
        """process-ticket publication은 영어 PR body/readback evidence를 거부한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_publication_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "7",
                "--status",
                "completed",
                "--summary",
                "publication finished",
                "--evidence",
                "commit_sha: abc123",
                "--evidence",
                "push_head_match: yes",
                "--evidence",
                "pr_readback_metadata: PR body has Summary and Verification sections",
                "--evidence",
                "acceptance_handoff_result: PASS",
                "--evidence",
                "pr_review_status: success",
                "--evidence",
                "merge_gate: clean",
                "--evidence",
                "github_metadata_language: korean=false forbidden_english_headings=2",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_process_ticket_publication_accepts_korean_github_metadata(self) -> None:
        """GitHub title/body 한국어 audit evidence가 있어야 publication을 완료한다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_publication_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "7",
                "--status",
                "completed",
                "--summary",
                "publication finished",
                "--evidence",
                "commit_sha: abc123",
                "--evidence",
                "push_head_match: yes",
                "--evidence",
                "pr_readback_metadata: 목적 구현 요약 인수 기준 검증 위험",
                "--evidence",
                "acceptance_handoff_result: PASS",
                "--evidence",
                "pr_review_status: success",
                "--evidence",
                "merge_gate: clean",
                "--evidence",
                (
                    "github_metadata_language: "
                    "validator=scripts.skill_harness.github_metadata_language "
                    "policy_passed=true korean=true title_korean=true body_korean=true "
                    "forbidden_english_headings=0 title_issue_prefix=true "
                    "title_issue_number_matches=true "
                    "commit_subject_issue_prefix=true "
                    "commit_subject_issue_number_matches=true"
                ),
            )

        self.assertEqual(0, result.exit_code)

    def test_process_ticket_publication_rejects_pr_title_without_issue_prefix(self) -> None:
        """process-ticket publication은 PR title issue prefix가 없으면 완료하지 않는다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_process_ticket_publication_contract()
            fixture.run("init", "--skill", "process-ticket", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "7",
                "--status",
                "completed",
                "--summary",
                "publication finished",
                "--evidence",
                "commit_sha: abc123",
                "--evidence",
                "push_head_match: yes",
                "--evidence",
                "pr_readback_metadata: 목적 구현 요약 인수 기준 검증 위험",
                "--evidence",
                "acceptance_handoff_result: PASS",
                "--evidence",
                "pr_review_status: success",
                "--evidence",
                "merge_gate: clean",
                "--evidence",
                (
                    "github_metadata_language: "
                    "validator=scripts.skill_harness.github_metadata_language "
                    "policy_passed=true korean=true title_korean=true body_korean=true "
                    "forbidden_english_headings=0 title_issue_prefix=false"
                ),
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_harness_improvement_accepts_prose_only_gap_closure(self) -> None:
        """ADR-0023에 따라 산문만으로 gap을 닫는 harness 개선을 차단하지 않습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "gap closed",
                "--evidence",
                "weak_or_failed_gaps: monitor drift",
                "--evidence",
                "patch_recommendation: 규칙 문구를 일반 원칙으로 정리",
                "--evidence",
                "deterministic_enforcement_gate: 없음 - 산문 정리만으로 원인이 사라짐",
                "--evidence",
                "rules_skills_guidance_only: 규칙 문서는 유도용이고 강제는 기존 게이트가 유지",
                "--evidence",
                "verification_result: reviewed text",
            )

        self.assertEqual(0, result.exit_code)

    def test_harness_improvement_rejects_untested_executable_gate_claim(self) -> None:
        """executable gate를 주장하면 그 주장에 test 근거가 있어야 합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "gap closed",
                "--evidence",
                "weak_or_failed_gaps: monitor drift",
                "--evidence",
                "patch_recommendation: add checker",
                "--evidence",
                "deterministic_enforcement_gate: scripts/new_checker.py added",
                "--evidence",
                "rules_skills_guidance_only: guidance",
                "--evidence",
                "verification_result: reviewed text",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])

    def test_harness_improvement_accepts_executable_gate_evidence(self) -> None:
        """skill contract와 phase runner enforcement의 harness improvement accepts executable gate evidence 회귀 조건을 검증합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "gap closed",
                "--evidence",
                "weak_or_failed_gaps: monitor drift",
                "--evidence",
                "patch_recommendation: add scripts/skill_harness checker and tests",
                "--evidence",
                (
                    "deterministic_enforcement_gate: scripts/skill_harness/checker.py "
                    "and scripts/skill_harness/tests/test_checker.py unittest passed"
                ),
                "--evidence",
                "rules_skills_guidance_only: rules/skills are guidance and not enforcement",
                "--evidence",
                "verification_result: uv run python -m unittest scripts.skill_harness.tests.test_checker passed",
            )

        self.assertEqual(0, result.exit_code)

    def test_evaluate_harness_rejects_label_only_acceptance_matrix(self) -> None:
        """Matrix label만 있는 self-assertion은 frozen row contract가 아닙니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "fake matrix",
                "--evidence",
                "failure_scenario=fake",
                "--evidence",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                "--evidence",
                "acceptance_matrix=fake",
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("acceptance_matrix", str(result.payload["message"]))

    def test_evaluate_harness_rejects_opaque_rows_without_role_context_capability(self) -> None:
        """Row identity는 role/context/capability tuple 없이 opaque label로 대체할 수 없습니다."""
        head_sha = "c" * 40
        rows = "opaque-a|opaque-b"
        row_specs = "opaque-a|opaque-b"
        decisions = "opaque-a:allow|opaque-b:deny"
        row_nodes = "opaque-a@scripts/evolution_cases.py::test_a|opaque-b@scripts/evolution_cases.py::test_b"
        matrix_id = hashlib.sha256(
            f"{head_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
        ).hexdigest()
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")

            result = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "opaque matrix",
                "--evidence",
                "failure_scenario: scenario=opaque-matrix",
                "--evidence",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                "--evidence",
                (
                    f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                    f"head_sha={head_sha} rows={rows} row_specs={row_specs} "
                    f"row_count=2 decisions={decisions} row_nodes={row_nodes}"
                ),
            )

        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("acceptance_matrix.row_specs", str(result.payload["message"]))

    def test_evaluate_harness_rejects_count_only_finding_and_unmapped_dedup(self) -> None:
        """Finding reproduction과 stable-rule dedup은 frozen matrix identity에 결속됩니다."""
        head_sha = "a" * 40
        rows = "A|B"
        row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
        decisions = "A:deny|B:allow"
        row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
            worktree_sha = fixture.worktree_sha()
            matrix_id = hashlib.sha256(
                f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
            ).hexdigest()
            phase_one = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "matrix frozen",
                "--evidence",
                "failure_scenario: scenario=state-fence",
                "--evidence",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                "--evidence",
                (
                    f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} "
                    f"rows={rows} row_specs={row_specs} "
                    f"row_count=2 decisions={decisions} row_nodes={row_nodes}"
                ),
            )
            result = fixture.run(
                "complete",
                "--phase-id",
                "2",
                "--status",
                "completed",
                "--summary",
                "count-only findings",
                "--evidence",
                f"project_mapping: matrix_id={matrix_id} mapped_rows={rows}",
                "--evidence",
                (
                    "independent_evaluator_report: delegation_id=missing outcome_ref=sha256:missing "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} blocking_findings=1"
                ),
                "--evidence",
                (
                    f"finding_reproduction: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} "
                    "finding_ids=F1 reproduced=true commands=1 expected_actual_pairs=1"
                ),
                "--evidence",
                (
                    f"root_cause_deduplication: matrix_id={matrix_id} "
                    "finding_ids=F1 stable_rule_ids=R1 mapped=true"
                ),
                "--evidence",
                (
                    f"enforcement_classification: matrix_id={matrix_id} "
                    f"classified_rows={rows} strong_rows=B weak_rows=none failed_rows=A"
                ),
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("finding_reproduction", str(result.payload["message"]))
        self.assertIn("root_cause_deduplication", str(result.payload["message"]))

    def test_evaluate_harness_rejects_label_without_consumed_direct_child_report(self) -> None:
        """그럴듯한 evaluator label로 direct-child delegation readback을 대신할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n",
            )
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
            head_sha = "a" * 40
            rows = "A|B"
            row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
            decisions = "A:deny|B:allow"
            row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            worktree_sha = fixture.worktree_sha()
            matrix_id = hashlib.sha256(
                f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
            ).hexdigest()
            phase_one = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "matrix frozen",
                "--evidence",
                "failure_scenario: scenario=delegation-readback",
                "--evidence",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                "--evidence",
                f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                f"head_sha={head_sha} worktree_sha={worktree_sha} rows={rows} "
                f"row_specs={row_specs} row_count=2 decisions={decisions} row_nodes={row_nodes}",
            )
            result = fixture.complete_structured_harness_evaluation(
                matrix_id=matrix_id,
                head_sha=head_sha,
                worktree_sha=worktree_sha,
                rows=rows,
                record_evaluator=False,
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(1, result.exit_code)
        self.assertIn(
            "independent_evaluator_report.delegation_readback",
            str(result.payload["message"]),
        )

    def test_evaluate_harness_rejects_label_only_fixed_matrix_result(self) -> None:
        """완료는 exact-head 전체 row의 zero-blocker verification receipt를 요구합니다."""
        head_sha = "b" * 40
        rows = "A|B"
        row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
        decisions = "A:deny|B:allow"
        row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert False\n\ndef test_b():\n    assert True\n",
            )
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
            worktree_sha = fixture.worktree_sha()
            matrix_id = hashlib.sha256(
                f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
            ).hexdigest()
            phase_one = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "matrix frozen",
                "--evidence",
                "failure_scenario: scenario=state-fence",
                "--evidence",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                "--evidence",
                (
                    f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} "
                    f"rows={rows} row_specs={row_specs} "
                    f"row_count=2 decisions={decisions} row_nodes={row_nodes}"
                ),
            )
            evaluator_ref = fixture.record_evaluate_harness_evaluator(
                matrix_id=matrix_id,
                head_sha=head_sha,
                worktree_sha=worktree_sha,
                blocking_findings=("F1",),
            )
            phase_two = fixture.run(
                "complete",
                "--phase-id",
                "2",
                "--status",
                "completed",
                "--summary",
                "finding reproduced",
                "--evidence",
                f"project_mapping: matrix_id={matrix_id} mapped_rows={rows}",
                "--evidence",
                (
                    "independent_evaluator_report: "
                    f"delegation_id=evaluate-harness-reviewer-1 outcome_ref={evaluator_ref} "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} blocking_findings=1"
                ),
                "--evidence",
                (
                    f"finding_reproduction: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} "
                    f"finding_ids=F1 reproduced=true commands=1 expected_actual_pairs=1 "
                    f"reproduction_specs=F1:A:deny:allow:{'d' * 64} "
                    "reproduction_nodes=F1@scripts/evolution_cases.py::test_a"
                ),
                "--evidence",
                (
                    f"root_cause_deduplication: matrix_id={matrix_id} "
                    "finding_ids=F1 stable_rule_ids=R1 mapped=true dedup_specs=F1:R1"
                ),
                "--evidence",
                (
                    f"enforcement_classification: matrix_id={matrix_id} "
                    f"classified_rows={rows} strong_rows=B weak_rows=none failed_rows=A"
                ),
            )
            result = fixture.run(
                "complete",
                "--phase-id",
                "3",
                "--status",
                "completed",
                "--summary",
                "fake verification",
                "--evidence",
                "weak_or_failed_gaps: rows=A",
                "--evidence",
                "patch_recommendation: scripts/skill_harness/phase_runner.py tests",
                "--evidence",
                "deterministic_enforcement_gate: scripts/skill_harness/phase_runner.py unittest",
                "--evidence",
                "rules_skills_guidance_only: guidance, not enforcement",
                "--evidence",
                (
                    f"verification_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} result=approach_change_required "
                    "row_count=2 blocking_findings=1"
                ),
                "--evidence",
                "fixed_matrix_verification_result=fake",
                "--evidence",
                (
                    f"harness_evolution_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} "
                    "action=approach_change_required finding_ids=F1 "
                    "harness_paths=none regression_nodes=none"
                ),
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("fixed_matrix_verification_result", str(result.payload["message"]))

    def test_evaluate_harness_rejects_self_attested_noop_verification(self) -> None:
        """Agent가 적은 command/exit_code 문자열은 matrix 실행 receipt가 아닙니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n",
            )
            matrix_id, head_sha, worktree_sha, phase_one, phase_two = (
                fixture.complete_structured_harness_discovery()
            )

            result = fixture.run(
                "complete",
                "--phase-id",
                "3",
                "--status",
                "completed",
                "--summary",
                "self-attested pass",
                "--evidence",
                "weak_or_failed_gaps: rows=A",
                "--evidence",
                "patch_recommendation: change gate",
                "--evidence",
                "deterministic_enforcement_gate: scripts/evolution_cases.py tested_by=tests",
                "--evidence",
                "rules_skills_guidance_only: true",
                "--evidence",
                (
                    f"verification_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} command=false exit_code=0"
                ),
                "--evidence",
                (
                    f"fixed_matrix_verification_result: matrix_id={matrix_id} "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} rows=A|B "
                    "row_count=2 result=pass blocking_findings=0 "
                    "exit_code=0 command=false"
                ),
                "--evidence",
                (
                    f"harness_evolution_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} action=promote finding_ids=F1 "
                    "harness_paths=scripts/evolution_cases.py "
                    "regression_nodes=scripts/evolution_cases.py::test_a"
                ),
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("fixed_matrix_verification_result", str(result.payload["message"]))

    def test_evaluate_harness_invalidates_stale_fixed_worktree_receipt(self) -> None:
        """Patch 뒤 fixed/evolution receipt도 제출 순간의 exact dirty bytes여야 합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n",
            )
            matrix_id, head_sha, _baseline_sha, phase_one, phase_two = (
                fixture.complete_structured_harness_discovery()
            )
            stale_worktree_sha = fixture.worktree_sha()
            fixture.write("scripts/changed_before_fixed.py", "CHANGED = True\n")
            row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            result = fixture.run(
                "complete",
                "--phase-id",
                "3",
                "--status",
                "completed",
                "--summary",
                "stale fixed receipt",
                "--evidence",
                "weak_or_failed_gaps: rows=A",
                "--evidence",
                "patch_recommendation: change gate",
                "--evidence",
                "deterministic_enforcement_gate: executable tests",
                "--evidence",
                "rules_skills_guidance_only: true",
                "--evidence",
                (
                    f"verification_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={stale_worktree_sha} result=pass row_count=2 "
                    "blocking_findings=0"
                ),
                "--evidence",
                (
                    f"fixed_matrix_verification_result: matrix_id={matrix_id} "
                    f"head_sha={head_sha} worktree_sha={stale_worktree_sha} rows=A|B "
                    f"row_count=2 result=pass blocking_findings=0 row_nodes={row_nodes}"
                ),
                "--evidence",
                (
                    f"harness_evolution_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={stale_worktree_sha} action=promote finding_ids=F1 "
                    "harness_paths=scripts/evolution_cases.py "
                    "regression_nodes=scripts/evolution_cases.py::test_a"
                ),
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("fixed_matrix_verification_result.matrix", str(result.payload["message"]))

    def test_evaluate_harness_invalidates_matrix_when_dirty_worktree_changes(self) -> None:
        """같은 HEAD에서도 source/test byte가 바뀌면 evaluator receipt는 stale입니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
            head_sha = "a" * 40
            rows = "A|B"
            row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
            decisions = "A:deny|B:allow"
            row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            worktree_sha = fixture.worktree_sha()
            matrix_id = hashlib.sha256(
                f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
            ).hexdigest()
            phase_one = fixture.run(
                "complete",
                "--phase-id",
                "1",
                "--status",
                "completed",
                "--summary",
                "matrix frozen",
                "--evidence",
                "failure_scenario: scenario=dirty-worktree",
                "--evidence",
                SATURATED_SOURCE_CAPABILITY_INVENTORY,
                "--evidence",
                (
                    f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} rows={rows} "
                    f"row_specs={row_specs} row_count=2 decisions={decisions} row_nodes={row_nodes}"
                ),
            )
            fixture.write("scripts/changed_after_freeze.py", "CHANGED = True\n")
            result = fixture.complete_structured_harness_evaluation(
                matrix_id=matrix_id,
                head_sha=head_sha,
                worktree_sha=worktree_sha,
                rows=rows,
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(1, result.exit_code)
        self.assertEqual("EVIDENCE_PATTERN_MISMATCH", result.payload["code"])
        self.assertIn("worktree", str(result.payload["message"]))

    def test_evaluate_harness_worktree_digest_excludes_ignored_runtime_artifacts(self) -> None:
        """Digest는 ignored/generated bytes를 빼고 relevant untracked source는 포함합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write(".gitignore", ".agents/runs/\ngenerated/\n")
            runner = PhaseRunner(SkillContractRepository(fixture.root))
            baseline = runner._repository_worktree_sha()

            fixture.write("generated/cache.json", '{"ephemeral": true}\n')
            ignored_artifact = runner._repository_worktree_sha()
            fixture.write("scripts/relevant_untracked.py", "VALUE = 1\n")
            relevant_source = runner._repository_worktree_sha()

        self.assertRegex(baseline, r"^[0-9a-f]{64}$")
        self.assertEqual(baseline, ignored_artifact)
        self.assertNotEqual(ignored_artifact, relevant_source)

    def test_evaluate_harness_regression_execution_preserves_worktree_without_parent_policy(
        self,
    ) -> None:
        """Regression pytest는 parent bytecode policy 없이도 repository bytes를 보존합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write(
                "scripts/tests/test_regression.py",
                "def test_regression():\n    assert True\n",
            )
            runner = PhaseRunner(SkillContractRepository(fixture.root))
            before = runner._repository_worktree_sha()

            with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": ""}):
                returncode = runner._run_python_regression_node(
                    "scripts/tests/test_regression.py::test_regression"
                )
            after = runner._repository_worktree_sha()

        self.assertEqual(0, returncode)
        self.assertEqual(before, after)

    def test_evaluate_harness_accepts_reverified_approach_change_required(self) -> None:
        """반증된 접근은 same-matrix 실행 실패를 숨기지 않고 terminalize할 수 있습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert False\n\ndef test_b():\n    assert True\n",
            )
            matrix_id, head_sha, worktree_sha, phase_one, phase_two = (
                fixture.complete_structured_harness_discovery()
            )
            row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            phase_three = fixture.run(
                "complete",
                "--phase-id",
                "3",
                "--status",
                "completed",
                "--summary",
                "approach disproved by frozen matrix",
                "--evidence",
                "weak_or_failed_gaps: rows=A",
                "--evidence",
                "patch_recommendation: redesign boundary",
                "--evidence",
                "deterministic_enforcement_gate: existing row tests",
                "--evidence",
                "rules_skills_guidance_only: true",
                "--evidence",
                (
                    f"verification_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} result=approach_change_required "
                    "row_count=2 blocking_findings=1"
                ),
                "--evidence",
                (
                    f"fixed_matrix_verification_result: matrix_id={matrix_id} "
                    f"head_sha={head_sha} worktree_sha={worktree_sha} rows=A|B "
                    "row_count=2 result=approach_change_required blocking_findings=1 "
                    f"row_nodes={row_nodes}"
                ),
                "--evidence",
                (
                    f"harness_evolution_result: matrix_id={matrix_id} head_sha={head_sha} "
                    f"worktree_sha={worktree_sha} action=approach_change_required "
                    "finding_ids=F1 harness_paths=none regression_nodes=none"
                ),
            )
            fixture.write_adaptive_control_complete_state()
            finalized = fixture.run("finalize", "--terminal-state", "evaluated")

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(0, phase_three.exit_code, phase_three.output)
        self.assertEqual(0, finalized.exit_code, finalized.output)

    def test_evaluate_harness_rejects_promoted_finding_without_harness_and_regression_paths(
        self,
    ) -> None:
        """자기개선은 prose 제안이 아니라 실제 harness와 regression node를 남겨야 합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n",
            )
            fixture.write(
                "scripts/tests/test_harness_gate.py",
                "def test_gate():\n    assert True\n",
            )
            matrix_id, head_sha, _worktree_sha, phase_one, phase_two = (
                fixture.complete_structured_harness_discovery(
                    reproduction_node="scripts/tests/test_harness_gate.py::test_gate"
                )
            )
            baseline_row_nodes = (
                "A@scripts/tests/test_harness_gate.py::test_gate|"
                "B@scripts/evolution_cases.py::test_b"
            )
            result = fixture.complete_structured_harness_promotion(
                matrix_id=matrix_id,
                head_sha=head_sha,
                harness_paths="none",
                regression_nodes="none",
                row_nodes=baseline_row_nodes,
            )
            fixture.write("scripts/harness_gate.py", "ENFORCED = True\n")
            fixture.write("scripts/tests/test_harness_gate.py", "VALUE = True\n")
            missing_node = fixture.complete_structured_harness_promotion(
                matrix_id=matrix_id,
                head_sha=head_sha,
                harness_paths="scripts/harness_gate.py",
                regression_nodes="scripts/tests/test_harness_gate.py::test_gate",
                row_nodes=baseline_row_nodes,
            )
            fixture.write(
                "scripts/tests/test_harness_gate.py",
                "def test_gate():\n    assert True\n",
            )
            accepted = fixture.complete_structured_harness_promotion(
                matrix_id=matrix_id,
                head_sha=head_sha,
                harness_paths="scripts/harness_gate.py",
                regression_nodes="scripts/tests/test_harness_gate.py::test_gate",
                row_nodes=(
                    "A@scripts/tests/test_harness_gate.py::test_gate|"
                    "B@scripts/evolution_cases.py::test_b"
                ),
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(1, result.exit_code)
        self.assertIn("harness_evolution_result", str(result.payload["message"]))
        self.assertEqual(1, missing_node.exit_code)
        self.assertIn("previous_acceptance_matrix.row_nodes", str(missing_node.payload["message"]))
        self.assertEqual(0, accepted.exit_code, accepted.output)

    def test_evaluate_harness_rejects_unrelated_passing_node_as_promoted_finding_regression(
        self,
    ) -> None:
        """Promotion은 finding을 최초 재현한 node identity를 무관한 통과 test로 바꿀 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                (
                    "def test_a():\n    assert True\n\n"
                    "def test_b():\n    assert True\n\n"
                    "def test_unrelated():\n    assert True\n"
                ),
            )
            matrix_id, head_sha, _worktree_sha, phase_one, phase_two = (
                fixture.complete_structured_harness_discovery()
            )
            fixture.write("scripts/harness_gate.py", "ENFORCED = True\n")
            result = fixture.complete_structured_harness_promotion(
                matrix_id=matrix_id,
                head_sha=head_sha,
                harness_paths="scripts/harness_gate.py",
                regression_nodes="scripts/evolution_cases.py::test_unrelated",
                row_nodes=(
                    "A@scripts/evolution_cases.py::test_unrelated|"
                    "B@scripts/evolution_cases.py::test_b"
                ),
            )

        self.assertEqual(0, phase_one.exit_code, phase_one.output)
        self.assertEqual(0, phase_two.exit_code, phase_two.output)
        self.assertEqual(1, result.exit_code)
        self.assertIn("harness_evolution_result", str(result.payload["message"]))


class PhaseRunnerResult:
    """phase runner result 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(self, exit_code: int, output: str) -> None:
        """PhaseRunnerResult 인스턴스가 skill contract와 phase runner enforcement 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            exit_code: 호출자가 넘긴 exit code 값입니다.
            output: 호출자가 넘긴 output 값입니다."""
        self.exit_code = exit_code
        self.output = output

    @property
    def payload(self) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Returns:
            payload 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        parsed = json.loads(self.output)
        if not isinstance(parsed, dict):
            raise TypeError("phase runner output must be a JSON object")
        return parsed

    def object_payload(self, key: str) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            key: 호출자가 넘긴 key 값입니다.

        Returns:
            object payload 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        value = self.payload[key]
        if not isinstance(value, dict):
            raise TypeError(f"{key} must be a JSON object")
        return value


class PhaseRunnerFixture:
    """phase runner fixture 관련 설정과 검증 조건을 함께 표현합니다."""

    def __enter__(self) -> Self:
        """PhaseRunnerFixture resource lifecycle을 열고 닫아 skill contract와 phase runner enforcement 실행 중 누수를 막습니다.

        Returns:
            enter 처리 결과입니다."""
        self._temporary_directory = TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        subprocess.run(
            ("git", "-C", str(self.root), "init", "-q"),
            check=True,
            capture_output=True,
            text=True,
        )
        self.session_id = "phase-runner-session"
        (self.root / ".gitignore").write_text(".neurath/local/\n", encoding="utf-8")
        self.workflow_id = "phase-runner-workflow"
        self.environment = {"CODEX_THREAD_ID": self.session_id}
        self.locator = SessionLocator.from_worktree(self.root)
        binding = RuntimeEnvironmentResolver().resolve(self.environment)
        self._state_handle = StateHandle.initialize(self.locator, binding)
        self._state_handle.apply(
            ActorStarted(
                session_id=self._state_handle.session_id,
                actor_id=ActorId("codex:admission-fixture-evaluator"),
                parent_actor_id=self._state_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
                idempotency_key="phase-fixture:admission-evaluator",
            )
        )
        self.process_state_path = (
            self.root / ".agents" / "runs" / self.session_id / ".process-state.json"
        )
        self._mutation_index = 0
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """PhaseRunnerFixture resource lifecycle을 열고 닫아 skill contract와 phase runner enforcement 실행 중 누수를 막습니다.

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
                  "terminal_states": ["merged", "failed", "blocked"],
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

    def write_adaptive_control_contract(self) -> None:
        """Adaptive read-back receipt 하나만 요구하는 phase contract를 작성합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "plan-issues": {
                  "adaptive_control": "required",
                  "terminal_states": ["planned", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "report_result",
                      "min_evidence_count": 1,
                      "required_evidence": ["adaptive_control_receipt"]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_single_phase_adaptive_evaluate_harness_contract(self) -> None:
        """Watchdog terminal boundary만 검증하는 adaptive evaluate-harness contract입니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "evaluate-harness": {
                  "adaptive_control": "required",
                  "terminal_states": ["evaluated", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "evaluate",
                      "min_evidence_count": 1,
                      "required_evidence": ["verification_result"]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_two_phase_adaptive_contract(self) -> None:
        """Cross-skill adaptive policy를 사용하는 두 phase fixture를 작성합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "plan-issues": {
                  "adaptive_control": "required",
                  "terminal_states": ["planned", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "prepare",
                      "min_evidence_count": 1,
                      "required_evidence": ["phase_one_evidence"]
                    },
                    {
                      "id": 2,
                      "name": "report",
                      "min_evidence_count": 1,
                      "required_evidence": ["phase_two_evidence"]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_three_phase_adaptive_contract(self) -> None:
        """Reactive internal gate를 중간 transition에서 검증할 contract를 작성합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "plan-issues": {
                  "adaptive_control": "required",
                  "terminal_states": ["planned", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "prepare",
                      "min_evidence_count": 1,
                      "required_evidence": ["phase_one_evidence"]
                    },
                    {
                      "id": 2,
                      "name": "implement",
                      "min_evidence_count": 1,
                      "required_evidence": ["phase_two_evidence"]
                    },
                    {
                      "id": 3,
                      "name": "report",
                      "min_evidence_count": 1,
                      "required_evidence": ["phase_three_evidence"]
                    }
                  ]
                }
              }
            }
            """,
        )

    def _adaptive_control_contract(
        self,
        evidence_kind: EvidenceKind,
        *,
        goal: str = DEFAULT_NORTH_STAR,
        include_independent_criterion: bool = False,
        intent_revision: int = 1,
        source_revision: str | None = None,
    ) -> GoalContract:
        """Phase completion용 single-criterion goal contract를 반환합니다."""
        constraints = ("exact workflow state만 신뢰한다",)
        non_goals = ("evidence label을 completion authority로 쓰지 않는다",)
        resolved_source_revision = source_revision or f"test-phase-runner:{intent_revision}"
        requirement_ids = {"REQ-phase-complete"}
        oracle_owner = (
            OracleOwner.USER
            if evidence_kind is EvidenceKind.USER_ACCEPTANCE
            else OracleOwner.INDEPENDENT_EVALUATOR
            if evidence_kind is EvidenceKind.INDEPENDENT_SEMANTIC
            else OracleOwner.EXECUTABLE
        )
        criteria = [
            CriterionSpec(
                criterion_id="phase-complete",
                description="현재 phase completion authority가 존재한다",
                source_requirement_id="REQ-phase-complete",
                approved_requirement_fingerprint=approved_requirement_fingerprint(
                    goal,
                    constraints,
                    non_goals,
                    intent_revision,
                    resolved_source_revision,
                ),
                observer="phase runner evaluator",
                precondition="current workflow와 approved goal revision이 일치한다",
                stimulus="phase completion을 제출한다",
                expected_outcome="authoritative read-back으로 completion을 판정한다",
                oracle_owner=oracle_owner,
                hard=True,
                required_evidence=frozenset({evidence_kind}),
            )
        ]
        if include_independent_criterion:
            requirement_ids.add("REQ-independent-interpretation")
            criteria.append(
                CriterionSpec(
                    criterion_id="independent-interpretation",
                    description="독립 해석 authority가 현재 goal을 판정한다",
                    source_requirement_id="REQ-independent-interpretation",
                    approved_requirement_fingerprint=approved_requirement_fingerprint(
                        goal,
                        constraints,
                        non_goals,
                        intent_revision,
                        resolved_source_revision,
                    ),
                    observer="independent evaluator",
                    precondition="current goal contract가 고정되어 있다",
                    stimulus="goal meaning을 독립 평가한다",
                    expected_outcome="independent semantic claim이 존재한다",
                    oracle_owner=OracleOwner.INDEPENDENT_EVALUATOR,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.INDEPENDENT_SEMANTIC}),
                )
            )
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset(requirement_ids),
            criteria=tuple(criteria),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=resolved_source_revision,
        )

    def _adaptive_inventory(self, contract: GoalContract) -> GapInventory:
        """모든 clarification section을 current goal basis에서 평가한 inventory입니다."""
        return GapInventory(
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            assessed_sections=frozenset(RequirementSection),
            gaps=(),
        )

    def write_adaptive_control_ambiguity_state(
        self,
        action: ControlAction,
    ) -> AdaptiveControlReceipt:
        """First-phase gate 검증용 unresolved ambiguity snapshot을 저장합니다."""
        default_contract = self._adaptive_control_contract(EvidenceKind.EXAMPLE_TEST)

        def reopen_ambiguity(
            current: AdaptiveControlState | None,
        ) -> AdaptiveControlState:
            """요청한 ambiguity action을 파생하는 replacement state를 생성합니다.

            Args:
                current: Exact workflow에 이미 저장된 optional adaptive state입니다.

            Returns:
                Requested unresolved action을 갖는 adaptive state입니다.

            Raises:
                ValueError: Action이 지원되지 않거나 BLOCKED를 기존 state에 쓰면 발생합니다.
            """
            contract = current.contract if current is not None else default_contract
            if action is ControlAction.BLOCKED:
                if current is not None:
                    raise ValueError("BLOCKED fixture requires a fresh adaptive snapshot")
                inventory = GapInventory(
                    intent_revision=contract.intent_revision,
                    source_revision=contract.source_revision,
                    assessed_sections=frozenset(
                        section
                        for section in RequirementSection
                        if section is not RequirementSection.SCOPE
                    ),
                    gaps=(),
                )
            else:
                authority = {
                    ControlAction.ASK_USER: GapAuthority.USER,
                    ControlAction.RESEARCH: GapAuthority.REPOSITORY,
                }.get(action)
                if authority is None:
                    raise ValueError(f"unsupported ambiguity action: {action}")
                inventory = GapInventory(
                    intent_revision=contract.intent_revision,
                    source_revision=contract.source_revision,
                    assessed_sections=frozenset(RequirementSection),
                    gaps=(
                        ClarificationGap(
                            gap_id=f"initial-{action.value}",
                            section=RequirementSection.SCOPE,
                            authority=authority,
                            dependency_rank=0,
                            weight=1.0,
                            blocking=True,
                            reversible=False,
                            scope_local=False,
                            context="현재 구현 경계를 결정할 사실이 필요하다",
                            question="구현 경계를 어떻게 확정할까?",
                            consequence="확정 전에 구현하면 스코프가 바뀐다",
                            recommendation="upstream authority로 한 가지 사실만 확정한다",
                            recommendation_rationale=(
                                "가장 상위의 미확정 사실 하나만 닫아야 후속 결정을 다시 만들지 않는다"
                            ),
                            intent_revision=contract.intent_revision,
                            resolution=GapResolution.OPEN,
                        ),
                    ),
                )
            if current is None:
                return AdaptiveControlState.empty(contract, inventory)
            return AdaptiveControlState(
                contract=contract,
                inventory=inventory,
                evidence=current.evidence,
                coverage=current.coverage,
                execution_status=current.execution_status,
                observations=current.observations,
            )

        snapshot = self._adaptive_control_store().update(reopen_ambiguity)
        receipt = snapshot.receipt()
        if receipt.ambiguity.action is not action:
            raise AssertionError(f"expected {action.value}, got {receipt.ambiguity.action.value}")
        return receipt

    def _adaptive_control_store(self) -> AdaptiveControlStore:
        """Fixture의 exact workflow에 결속된 adaptive store를 반환합니다."""
        return AdaptiveControlStore(
            SkillStateStore(self._state_handle, WorkflowId(self.workflow_id))
        )

    def override_adaptive_control_goal(
        self,
        evidence_kind: EvidenceKind,
        *,
        goal: str = DEFAULT_NORTH_STAR,
    ) -> AdaptiveControlReceipt:
        """명시적 goal override로 이전 authority와 history를 폐기합니다."""
        transition_handle = StateHandle(
            TransitionOnlyPhaseFixtureKernel(self.locator),
            RuntimeIdentityBinding(
                runtime=self._state_handle.runtime,
                session_id=self._state_handle.session_id,
                actor_id=self._state_handle.actor_id,
                root_actor_id=self._state_handle.actor_id,
            ),
        )
        store = AdaptiveControlStore(
            SkillStateStore(transition_handle, WorkflowId(self.workflow_id))
        )
        current = store.read()
        previous_contract = current.state.contract
        contract = self._adaptive_control_contract(
            evidence_kind,
            goal=goal,
            intent_revision=previous_contract.intent_revision + 1,
        )
        target_id = previous_contract.criteria[0].criterion_id
        disposition = UserDecisionDisposition.ACCEPTED
        decision = UserDecision(
            claim=UserDecisionClaim(
                workflow_id=self.workflow_id,
                question_workflow_revision=current.workflow_revision,
                source_goal_fingerprint=previous_contract.fingerprint,
                source_intent_revision=previous_contract.intent_revision,
                source_revision=previous_contract.source_revision,
                question_digest=hashlib.sha256(b"goal override question").hexdigest(),
                question_generation=1,
                question_turn_revision=1,
                prompt_digest=hashlib.sha256(b"goal override response").hexdigest(),
                prompt_reference="user-prompt:goal-override",
                prompt_generation=2,
                prompt_turn_revision=2,
                target_kind=UserDecisionTarget.CRITERION,
                target_id=target_id,
                disposition=disposition,
                value_summary_digest=user_decision_value_summary_digest(
                    UserDecisionTarget.CRITERION,
                    target_id,
                    disposition,
                    contract.fingerprint,
                    contract.intent_revision,
                    contract.source_revision,
                ),
                result_goal_fingerprint=contract.fingerprint,
                result_intent_revision=contract.intent_revision,
                result_source_revision=contract.source_revision,
            ),
            interpretation_lineage=AuthorityReceipt(
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                issuer_id="codex:goal-override-evaluator",
                subject_id=str(self._state_handle.actor_id),
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                receipt_digest="d" * 64,
                delegation_id="goal-override-evaluation",
            ),
        )
        return store.override_goal(
            current.workflow_revision,
            contract,
            inventory=self._adaptive_inventory(contract),
            user_decisions=(decision,),
        ).receipt()

    def write_adaptive_control_continue_state(self) -> AdaptiveControlReceipt:
        """Authority claim이 아직 없고 next action이 CONTINUE인 ready snapshot을 기록합니다."""
        contract = self._adaptive_control_contract(EvidenceKind.EXAMPLE_TEST)
        state = AdaptiveControlState.empty(contract, self._adaptive_inventory(contract))
        return self._adaptive_control_store().update(lambda _current: state).receipt()

    def write_adaptive_control_execution_failed_state(self) -> AdaptiveControlReceipt:
        """Current adaptive execution lifecycle을 typed FAILED로 전이합니다."""
        contract = self._adaptive_control_contract(EvidenceKind.EXAMPLE_TEST)
        store = self._adaptive_control_store()
        store.update(
            lambda _current: AdaptiveControlState.empty(
                contract,
                self._adaptive_inventory(contract),
            )
        )
        return store.update(
            lambda current: replace(
                cast(AdaptiveControlState, current),
                execution_status=ExecutionStatus.FAILED,
            )
        ).receipt()

    def write_adaptive_control_repository_blocker_state(self) -> AdaptiveControlReceipt:
        """Current tracked source가 입증하는 repository-owned terminal blocker를 기록합니다."""
        subprocess.run(
            (
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Neurath Test",
                "-c",
                "user.email=neurath@example.invalid",
                "commit",
                "--allow-empty",
                "--no-verify",
                "-m",
                "seed",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        reference = "docs/repository-blocker.txt"
        self.write(reference, "current repository state denies this goal\n")
        subprocess.run(
            ("git", "-C", str(self.root), "add", "--", reference),
            check=True,
            capture_output=True,
            text=True,
        )
        readback = RepositoryWorktreeReadback(self.root).read_tracked_file(reference)
        contract = self._adaptive_control_contract(
            EvidenceKind.EXAMPLE_TEST,
            source_revision=readback.worktree_fingerprint,
        )
        open_gap = ClarificationGap(
            gap_id="repository-blocker",
            section=RequirementSection.SCOPE,
            authority=GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=1.0,
            blocking=True,
            reversible=False,
            scope_local=False,
            context="Current repository source denies further work",
            question="Can this goal proceed against the current source?",
            consequence="Ignoring the source would produce an invalid result",
            recommendation="Return blocked control with the tracked source receipt",
            recommendation_rationale="Repository authority owns this prerequisite",
            intent_revision=contract.intent_revision,
        )
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.PRIMARY_SOURCE,
            issuer_id="repository",
            subject_id=str(self._state_handle.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=readback.worktree_fingerprint,
            receipt_digest=readback.content_digest,
        )
        open_inventory = GapInventory(
            intent_revision=contract.intent_revision,
            source_revision=readback.worktree_fingerprint,
            assessed_sections=frozenset(RequirementSection),
            gaps=(open_gap,),
        )
        store = self._adaptive_control_store()
        store.update(lambda _current: AdaptiveControlState.empty(contract, open_inventory))
        blocker = open_gap.mark_blocked(reference, lineage)
        return store.update(
            lambda current: replace(
                cast(AdaptiveControlState, current),
                inventory=replace(
                    cast(AdaptiveControlState, current).inventory,
                    gaps=(blocker,),
                ),
            )
        ).receipt()

    def write_adaptive_control_user_gap_without_runtime_authority(
        self,
    ) -> AdaptiveControlReceipt:
        """Current prompt provenance 없이 self-authored USER_FACT를 저장합니다."""
        store = self._adaptive_control_store()
        current = store.read()
        contract = current.state.contract
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.USER,
            issuer_id="user",
            subject_id=str(self._state_handle.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest="a" * 64,
            delegation_id="prompt:unverified",
        )
        gap = ClarificationGap(
            gap_id="self-authored-user-fact",
            section=RequirementSection.SCOPE,
            authority=GapAuthority.USER,
            dependency_rank=0,
            weight=1.0,
            blocking=True,
            reversible=False,
            scope_local=False,
            context="사용자가 정해야 하는 작업 경계가 있다",
            question="이 작업 경계를 승인할까요?",
            consequence="agent 추정으로 닫으면 사용자 권한을 가장한다",
            recommendation="current user prompt에서 경계를 확인한다",
            recommendation_rationale="USER_FACT는 runtime prompt provenance가 필요하다",
            intent_revision=contract.intent_revision,
            resolution=GapResolution.USER_FACT,
            evidence_reference="prompt:unverified",
            resolution_lineage=lineage,
        )
        inventory = GapInventory(
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            assessed_sections=frozenset(RequirementSection),
            gaps=(gap,),
        )
        candidate = AdaptiveControlState(
            contract=contract,
            inventory=inventory,
            evidence=current.state.evidence,
            coverage=current.state.coverage,
            execution_status=current.state.execution_status,
            observations=current.state.observations,
        )
        return store.update(lambda _current: candidate).receipt()

    def write_adaptive_control_decision(
        self,
        action: ControlAction,
    ) -> AdaptiveControlReceipt:
        """Canonical observations로 requested recovery decision을 파생합니다."""
        observation_shape = {
            ControlAction.CHANGE_APPROACH: (2, ("introduced-loop",), False),
            ControlAction.ENUMERATE_INVARIANT: (2, ("preexisting-family",), False),
            ControlAction.PROMOTE_HARNESS: (1, (), True),
        }.get(action)
        if observation_shape is None:
            raise ValueError(f"unsupported recovery action: {action}")
        count, root_causes, reproducible_harness_gap = observation_shape
        store = self._adaptive_control_store()
        for generation in range(1, count + 1):
            current = store.read().state
            fingerprint = adaptive_output_fingerprint(
                current.contract,
                current.inventory,
                current.evidence,
                current.coverage,
                current.execution_status,
            )
            observation = IterationObservation(
                goal_fingerprint=current.contract.fingerprint,
                generation=generation,
                output_fingerprint=fingerprint,
                active_criteria=tuple(
                    criterion.criterion_id for criterion in current.contract.criteria
                ),
                root_causes=root_causes,
                progress=0.0,
                material_change=generation == 1,
                reproducible_harness_gap=(reproducible_harness_gap and generation == count),
            )
            candidate = AdaptiveControlState(
                contract=current.contract,
                inventory=current.inventory,
                evidence=current.evidence,
                coverage=current.coverage,
                execution_status=current.execution_status,
                observations=(*current.observations, observation),
            )
            store.update(lambda _current, replacement=candidate: replacement)
        receipt = store.read().receipt()
        if receipt.decision.action is not action:
            raise AssertionError(f"expected {action.value}, got {receipt.decision.action.value}")
        return receipt

    def write_adaptive_control_complete_state(
        self,
        *,
        goal: str = DEFAULT_NORTH_STAR,
    ) -> AdaptiveControlReceipt:
        """Consumed external evaluation까지 충족된 COMPLETE snapshot을 기록합니다."""
        return self._write_adaptive_control_complete_state(goal=goal, refresh=False)

    def write_current_adaptive_control_complete_state(self) -> AdaptiveControlReceipt:
        """Typed amendment가 고정한 current contract에 새 completion authority를 기록합니다."""
        return self._write_adaptive_control_complete_state(goal=None, refresh=False)

    def refresh_adaptive_control_completion_authority(self) -> AdaptiveControlReceipt:
        """Sibling phase mutation 뒤 current revision에 새 독립 평가 authority를 발행합니다."""
        current = self._adaptive_control_store().read().state
        return self._write_adaptive_control_complete_state(
            goal=current.contract.goal,
            refresh=True,
        )

    def _write_adaptive_control_complete_state(
        self,
        *,
        goal: str | None,
        refresh: bool,
    ) -> AdaptiveControlReceipt:
        """Initial 또는 refreshed independent completion을 current workflow에 결속합니다."""
        store = self._adaptive_control_store()
        if refresh:
            current = store.read().state
            contract = current.contract
            inventory = current.inventory
            prior_evidence = current.evidence
            evaluation_revision = max(item.evaluation_revision for item in current.evidence) + 1
            if current.coverage is None:
                raise AssertionError("completion refresh requires existing coverage")
            coverage_revision = current.coverage.evaluation_revision + 1
            identity_suffix = "-refresh"
            user_decisions = current.user_decisions
        elif goal is None:
            current = store.read().state
            contract = current.contract
            inventory = current.inventory
            prior_evidence = current.evidence
            evaluation_revision = (
                max(
                    (item.evaluation_revision for item in current.evidence),
                    default=0,
                )
                + 1
            )
            coverage_revision = (
                1 if current.coverage is None else current.coverage.evaluation_revision + 1
            )
            identity_suffix = "-current"
            user_decisions = current.user_decisions
        else:
            contract = self._adaptive_control_contract(
                EvidenceKind.INDEPENDENT_SEMANTIC,
                goal=goal,
            )
            inventory = self._adaptive_inventory(contract)
            prior_evidence = ()
            evaluation_revision = 1
            coverage_revision = 1
            identity_suffix = ""
            user_decisions = ()
        criterion_id = contract.criteria[0].criterion_id
        evaluator_id = ActorId(f"codex:phase-adaptive-evaluator{identity_suffix}")
        delegation_id = DelegationId(f"delegation-phase-evaluator{identity_suffix}")
        self._state_handle.apply(
            ActorStarted(
                session_id=self._state_handle.session_id,
                actor_id=evaluator_id,
                parent_actor_id=self._state_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"phase-adaptive:evaluator{identity_suffix}",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        criterion_claim = {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "criterion-evidence",
            "criterion_id": criterion_id,
            "evaluation_revision": evaluation_revision,
            "goal_fingerprint": contract.fingerprint,
            "kind": EvidenceKind.INDEPENDENT_SEMANTIC.value,
            "reference": f"independent:phase-complete{identity_suffix}",
            "status": EvidenceStatus.PASS.value,
        }
        coverage_claim = {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "goal-coverage",
            "criterion_ids": [criterion_id],
            "evaluation_revision": coverage_revision,
            "goal_alignment": 1.0,
            "goal_fingerprint": contract.fingerprint,
            "reference": f"independent:phase-coverage{identity_suffix}",
            "reward_hacking_risk": 0.0,
            "semantic_drift": 0.0,
            "status": EvidenceStatus.PASS.value,
            "uncertainty": 0.0,
        }
        completion_claim = {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "execution-completion",
            "goal_fingerprint": contract.fingerprint,
            "status": ExecutionStatus.COMPLETED.value,
        }
        trajectory_digest = AdaptiveEvaluationCandidateStore(
            self._state_handle,
            WorkflowId(self.workflow_id),
        ).current_trajectory_digest()
        report = {
            "blocking_findings": [],
            "claims": sorted(
                (criterion_claim, coverage_claim, completion_claim),
                key=lambda claim: json.dumps(
                    claim,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ),
            "goal_fingerprint": contract.fingerprint,
            "intent_revision": contract.intent_revision,
            "kind": "adaptive-goal-evaluation",
            "source_revision": contract.source_revision,
            "summary": "adaptive goal evaluation passed",
            "trajectory_assessment": {
                "blocking_findings": [],
                "trajectory_digest": trajectory_digest,
                "verdict": "pass",
            },
            "verdict": "pass",
            "workflow_id": self.workflow_id,
        }
        evaluator_handle = StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=self._state_handle.runtime,
                session_id=self._state_handle.session_id,
                actor_id=evaluator_id,
                root_actor_id=self._state_handle.actor_id,
            ),
        )
        outcome_ref = (
            SessionArtifactStore(evaluator_handle)
            .put_json({
                "delegation_id": str(delegation_id),
                "report": report,
                "schema": "neurath.delegation-result.v1",
                "target_agent_id": str(evaluator_id),
            })
            .reference
        )
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            issuer_id=str(evaluator_id),
            subject_id=str(self._state_handle.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=outcome_ref.removeprefix("sha256:"),
            delegation_id=str(delegation_id),
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=inventory,
            evidence=(
                *prior_evidence,
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id=criterion_id,
                    kind=EvidenceKind.INDEPENDENT_SEMANTIC,
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    status=EvidenceStatus.PASS,
                    reference=f"independent:phase-complete{identity_suffix}",
                    lineage=lineage,
                    evaluation_revision=evaluation_revision,
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({criterion_id}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference=f"independent:phase-coverage{identity_suffix}",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=lineage,
                evaluation_revision=coverage_revision,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
            user_decisions=user_decisions,
        )
        prepared = AdaptiveEvaluationCandidateStore(
            self._state_handle,
            WorkflowId(self.workflow_id),
        ).prepare(state)
        self._state_handle.apply(
            DelegationAssigned(
                session_id=self._state_handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=self._state_handle.actor_id,
                target_actor_id=evaluator_id,
                assignment=prepared.assignment_json,
                idempotency_key=f"phase-adaptive:assign{identity_suffix}",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        evaluator_handle.apply(
            DelegationReported(
                session_id=evaluator_handle.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=evaluator_id,
                result=DelegationResult(
                    verdict="pass",
                    summary=json.dumps(
                        {
                            "candidate_ref": prepared.candidate_ref,
                            "summary": "adaptive goal evaluation passed",
                            "trajectory_digest": trajectory_digest,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    outcome_ref=outcome_ref,
                    blocking_findings=(),
                ),
                idempotency_key=f"phase-adaptive:report{identity_suffix}",
            )
        )
        self._state_handle.apply(
            DelegationConsumed(
                session_id=self._state_handle.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=self._state_handle.actor_id,
                idempotency_key=f"phase-adaptive:consume{identity_suffix}",
            )
        )
        return store.update(lambda _current: state).receipt()

    def write_adaptive_control_await_user_state(
        self,
        *,
        goal: str = DEFAULT_NORTH_STAR,
        include_independent_criterion: bool = False,
    ) -> AdaptiveControlReceipt:
        """User acceptance가 남아 있는 exact AWAIT_USER snapshot을 기록합니다."""
        contract = self._adaptive_control_contract(
            EvidenceKind.USER_ACCEPTANCE,
            goal=goal,
            include_independent_criterion=include_independent_criterion,
        )
        state = AdaptiveControlState.empty(contract, self._adaptive_inventory(contract))
        return self._adaptive_control_store().update(lambda _current: state).receipt()

    def adaptive_control_receipt_evidence(self, receipt: AdaptiveControlReceipt) -> str:
        """Typed receipt identity와 완료 판정을 phase evidence wire 형식으로 직렬화합니다."""
        return "adaptive_control_receipt: " + json.dumps(
            receipt.to_evidence(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def adaptive_control_initialized_evidence(
        self,
        receipt: AdaptiveControlReceipt,
    ) -> str:
        """Current nonterminal receipt를 initialization read-back evidence로 직렬화합니다."""
        return "adaptive_control_initialized: " + json.dumps(
            receipt.to_evidence(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def complete_adaptive_initial_phase(
        self,
        receipt: AdaptiveControlReceipt,
    ) -> PhaseRunnerResult:
        """Current ready receipt로 adaptive-required first phase를 완료합니다."""
        return self.run(
            "complete",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "phase one",
            "--evidence",
            "phase_one_evidence: yes",
            "--evidence",
            self.adaptive_control_initialized_evidence(receipt),
        )

    def complete_adaptive_middle_phase(self) -> PhaseRunnerResult:
        """Current adaptive transition read-back만으로 middle phase를 완료합니다."""
        return self.run(
            "complete",
            "--phase-id",
            "2",
            "--status",
            "completed",
            "--summary",
            "phase two",
            "--evidence",
            "phase_two_evidence: yes",
        )

    def complete_adaptive_control_phase(self, receipt_evidence: str) -> PhaseRunnerResult:
        """Adaptive receipt를 유일한 evidence로 report phase 완료에 제출합니다."""
        return self.run(
            "complete",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "adaptive goal complete",
            "--evidence",
            receipt_evidence,
        )

    def write_contracts_with_evidence_pattern(self) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "automate-qa": {
                  "terminal_states": ["qa-complete", "failed", "blocked"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "deployed_surface_evidence",
                      "min_evidence_count": 2,
                      "required_evidence": [
                        "client_surface_evidence",
                        "network_or_api_evidence"
                      ],
                      "evidence_patterns": {
                        "client_surface_evidence": "screenshot|video|accessibility"
                      }
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_review_code_contract(self) -> None:
        """Durable delegate completion read-back을 요구하는 review-code 계약을 작성합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "review-code": {
                  "terminal_states": ["completed", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "execute",
                      "min_evidence_count": 7,
                      "required_evidence": [
                        "subagent_dispatch",
                        "diff_marker",
                        "persona_readback",
                        "review_categories",
                        "delegate_transition_receipt",
                        "review_report_readback",
                        "turn_harness_audit"
                      ]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_review_completion(self, head_sha: str) -> str:
        """Typed delegation lifecycle과 digest artifact로 canonical review를 씁니다."""
        matrix_rows = [
            {"category": category, "row_id": row_id, "severity": severity}
            for row_id, category, severity in (
                ("C01", "architecture-boundary", "critical"),
                ("C02", "type-discipline", "warning"),
                ("C03", "yagni", "warning"),
                ("C04", "domain-boundary", "critical"),
                ("C05", "naming", "warning"),
                ("C06", "test-gate", "critical"),
                ("C07", "readability", "warning"),
                ("C08", "api-contract", "warning"),
                ("C09", "persistence", "warning"),
                ("C10", "transaction-integrity", "critical"),
                ("C11", "pattern-consistency", "warning"),
                ("C12", "defensive-helper", "warning"),
                ("C13", "operations-consistency", "warning"),
                ("C14", "spec-completeness", "critical"),
            )
        ]
        rows = [row["row_id"] for row in matrix_rows]
        matrix_identity = json.dumps(
            {"head_sha": head_sha, "rows": matrix_rows},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        matrix_id = hashlib.sha256(matrix_identity.encode()).hexdigest()
        matrix = {
            "frozen": True,
            "head_sha": head_sha,
            "matrix_id": matrix_id,
            "row_count": 14,
            "rows": matrix_rows,
        }
        reviewer_id = ActorId("codex:reviewer-1")
        delegation_id = DelegationId("review-1")
        self._state_handle.apply(
            ActorStarted(
                session_id=self._state_handle.session_id,
                actor_id=reviewer_id,
                parent_actor_id=self._state_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="phase-fixture:reviewer-started",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        assignment = json.dumps(
            {
                "kind": "review-code",
                "review_acceptance_matrix": matrix,
                "reviewed_head_sha": head_sha,
                "scope": "exact-head complete review",
                "started_at": "2026-08-04T00:00:00+00:00",
                "target": "reviewer",
                "workflow_id": self.workflow_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._state_handle.apply(
            DelegationAssigned(
                session_id=self._state_handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=self._state_handle.actor_id,
                target_actor_id=reviewer_id,
                assignment=assignment,
                idempotency_key="phase-fixture:review-assigned",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        review_report = {
            "blocking_findings": [],
            "harness_audit": {
                "checked": True,
                "evidence": [
                    "git_diff:sha256:" + "1" * 64,
                    "process_state:sha256:" + "2" * 64,
                    "execution_trajectory:sha256:" + "3" * 64,
                ],
            },
            "matrix_id": matrix_id,
            "matrix_head_sha": head_sha,
            "review_findings": [],
            "review_notes": [
                {
                    "stable_key": "C02-REBUTTED-TYPE-RISK",
                    "row_id": "C02",
                    "summary": "타입 위험 반박이 재검증됐습니다.",
                    "severity": "resolved",
                    "impact": "해당 호출 경로는 정규화된 입력만 받습니다.",
                    "root_cause_key": "type-risk",
                    "disposition": "rebutted",
                    "evidence_command": "uv run python -m unittest tests.test_type_contract",
                    "expected": "exit=0",
                    "actual": "exit=0",
                }
            ],
            "summary": "14개 행과 반박 근거를 모두 재검증했습니다.",
            "verified_review_rows": rows,
            "verdict": "pass",
        }
        reviewer_binding = RuntimeIdentityBinding(
            runtime=self._state_handle.runtime,
            session_id=self._state_handle.session_id,
            actor_id=reviewer_id,
            root_actor_id=self._state_handle.actor_id,
        )
        reviewer_handle = StateHandle.attach(self.locator, reviewer_binding)
        artifact = SessionArtifactStore(reviewer_handle).put_json({
            "delegation_id": str(delegation_id),
            "report": review_report,
            "schema": "neurath.delegation-result.v1",
            "target_agent_id": str(reviewer_id),
        })
        reviewer_handle.apply(
            DelegationReported(
                session_id=reviewer_handle.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=reviewer_id,
                result=DelegationResult(
                    verdict="pass",
                    summary=review_report["summary"],
                    outcome_ref=artifact.reference,
                    blocking_findings=(),
                ),
                idempotency_key="phase-fixture:review-reported",
            )
        )
        self._state_handle.apply(
            DelegationConsumed(
                session_id=self._state_handle.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=self._state_handle.actor_id,
                idempotency_key="phase-fixture:review-consumed",
            )
        )
        return artifact.reference

    def review_evidence(self, head_sha: str, outcome_ref: str) -> tuple[str, ...]:
        """Review completion command에 전달할 exact-label evidence 인자를 반환합니다."""
        return (
            "--evidence",
            "subagent_dispatch: agent_id=codex:reviewer-1 delegation_id=review-1 outcome=result-applied",
            "--evidence",
            f"diff_marker: head_sha={head_sha}",
            "--evidence",
            "persona_readback: policy_id=constructive-skeptic-v1 categories=14",
            "--evidence",
            "review_categories: verified=14",
            "--evidence",
            (
                "delegate_transition_receipt: delegation_id=review-1 "
                f"target_agent_id=codex:reviewer-1 outcome_ref={outcome_ref}"
            ),
            "--evidence",
            (
                f"review_report_readback: outcome_ref={outcome_ref} note_count=1 "
                "blocker_count=0 verdict=pass"
            ),
            "--evidence",
            "turn_harness_audit: checked=true evidence_count=3 violations=0",
        )

    def complete_review_code(self, head_sha: str, *, outcome_ref: str) -> PhaseRunnerResult:
        """Canonical review evidence로 execute phase 완료를 시도합니다."""
        return self.run(
            "complete",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "review complete",
            *self.review_evidence(head_sha, outcome_ref),
        )

    def write_process_ticket_monitoring_contract(self) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "process-ticket": {
                  "terminal_states": ["merged", "mergeable-clean", "blocked"],
                  "phase_contracts": [
                    {
                      "id": 8,
                      "name": "monitoring",
                      "min_evidence_count": 12,
                      "required_evidence": [
                        "pr_review_status",
                        "ai_review_head_sha",
                        "agent_session_context",
                        "monitor_event_source",
                        "monitor_started",
                        "monitor_terminal_state",
                        "process_state_resume_check",
                        "route_resume_contract",
                        "monitor_event_readback",
                        "live_terminal_readback",
                        "pending_human_comments",
                        "unresolved_review_threads"
                      ],
                      "evidence_patterns": {
                        "agent_session_context": "agent_session\\\\.kind=worktree_owner.*agent_session\\\\.owned_worktree=.*route_owner=(process-ticket|autopilot).*terminal_sink=(user|autopilot).*merge_policy=(manual|auto)",
                        "monitor_event_source": "provider=local-pr-monitor.*repo=.*pr_number=.*session_id=.*workflow_id=.*runtime_id=.*worktree_id=.*observation_resource=monitor-observation-cache:.*poll_interval_seconds=30.*resume_adapter=(command|app-server)",
                        "monitor_terminal_state": "monitor_event=terminal.*reason=(merged|mergeable-clean|closed-without-merge).*source=local-pr-monitor.*resume_status=invoked",
                        "route_resume_contract": "provider=local-pr-monitor.*repo=.*pr_number=.*session_id=.*workflow_id=.*runtime_id=.*worktree_id=.*observation_resource=monitor-observation-cache:.*resume_adapter=(command|app-server)",
                        "monitor_event_readback": "monitor_event=(terminal.*source=local-pr-monitor.*resume_status=invoked|event.*source=local-pr-monitor.*resume_status=invoked.*turn_completion.status=completed.*turn.status=completed)",
                        "live_terminal_readback": "reason=(mergeable-clean.*state=OPEN.*mergeState=CLEAN.*reviewDecision=APPROVED.*failedChecks=0.*pendingChecks=0.*headRefOid=.*unresolvedReviewThreads=0|merged.*state=MERGED.*headRefOid=.*unresolvedReviewThreads=0|closed-without-merge.*state=CLOSED.*headRefOid=.*unresolvedReviewThreads=0)",
                        "pending_human_comments": "TOTAL=0",
                        "unresolved_review_threads": "UNRESOLVED_THREADS_COUNT=0"
                      }
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_process_ticket_publication_contract(self) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "process-ticket": {
                  "terminal_states": ["merged", "mergeable-clean", "blocked"],
                  "phase_contracts": [
                    {
                      "id": 7,
                      "name": "publication",
                      "min_evidence_count": 7,
                      "required_evidence": [
                        "commit_sha",
                        "push_head_match",
                        "pr_readback_metadata",
                        "acceptance_handoff_result",
                        "pr_review_status",
                        "merge_gate",
                        "github_metadata_language"
                      ],
                      "evidence_patterns": {
                        "github_metadata_language": "validator=scripts\\\\.skill_harness\\\\.github_metadata_language.*korean=true.*title_korean=true.*body_korean=true.*forbidden_english_headings=0.*title_issue_prefix=true.*title_issue_number_matches=true.*commit_subject_issue_prefix=true.*commit_subject_issue_number_matches=true"
                      }
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_process_ticket_merge_cleanup_contract(self) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "process-ticket": {
                  "terminal_states": ["merged", "mergeable-clean", "blocked"],
                  "phase_contracts": [
                    {
                      "id": 8,
                      "name": "monitor_route",
                      "min_evidence_count": 1,
                      "required_evidence": ["agent_session_context"]
                    },
                    {
                      "id": 9,
                      "name": "merge_cleanup",
                      "min_evidence_count": 10,
                      "required_evidence": [
                        "merge_command",
                        "merge_approval",
                        "github_merge_readback",
                        "issue_status_readback",
                        "parent_issue_completion_readback",
                        "branch_cleanup_readback",
                        "worktree_cleanup_readback",
                        "process_state_merged",
                        "terminal_report",
                        "gap_dispatch_check"
                      ]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_evaluate_harness_contract(self) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다."""
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "evaluate-harness": {
                  "terminal_states": ["evaluated", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "gap_and_verification",
                      "min_evidence_count": 5,
                      "required_evidence": [
                        "weak_or_failed_gaps",
                        "patch_recommendation",
                        "deterministic_enforcement_gate",
                        "rules_skills_guidance_only",
                        "verification_result"
                      ]
                    }
                  ]
                }
              }
            }
            """,
        )

    def write_structured_evaluate_harness_contract(self) -> None:
        """Frozen matrix와 exact-head result를 요구하는 실제 3-phase 계약을 작성합니다."""
        self.write(
            "scripts/evolution_cases.py",
            "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n",
        )
        self.write(
            ".agents/skills/contracts.json",
            """
            {
              "skills": {
                "evaluate-harness": {
                  "terminal_states": ["evaluated", "blocked", "failed"],
                  "phase_contracts": [
                    {
                      "id": 1,
                      "name": "define_failure_scenario",
                      "min_evidence_count": 3,
                      "required_evidence": [
                        "failure_scenario",
                        "source_capability_inventory",
                        "acceptance_matrix"
                      ]
                    },
                    {
                      "id": 2,
                      "name": "independent_evaluation",
                      "min_evidence_count": 5,
                      "required_evidence": [
                        "project_mapping",
                        "independent_evaluator_report",
                        "finding_reproduction",
                        "root_cause_deduplication",
                        "enforcement_classification"
                      ]
                    },
                    {
                      "id": 3,
                      "name": "gap_and_verification",
                      "min_evidence_count": 6,
                      "required_evidence": [
                        "weak_or_failed_gaps",
                        "patch_recommendation",
                        "deterministic_enforcement_gate",
                        "rules_skills_guidance_only",
                        "verification_result",
                        "fixed_matrix_verification_result",
                        "harness_evolution_result"
                      ]
                    }
                  ]
                }
              }
            }
            """,
        )

    def worktree_sha(self) -> str:
        """HEAD와 tracked/untracked current bytes의 독립 test fingerprint를 계산합니다."""
        head_result = subprocess.run(
            ("git", "-C", str(self.root), "rev-parse", "HEAD"),
            check=False,
            capture_output=True,
        )
        head = head_result.stdout.strip() if head_result.returncode == 0 else b""
        files_result = subprocess.run(
            (
                "git",
                "-C",
                str(self.root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ),
            check=True,
            capture_output=True,
        )
        relative_paths = sorted(
            value.decode("utf-8", errors="surrogateescape")
            for value in files_result.stdout.split(b"\0")
            if value and not value.startswith((b".agents/runs/", b".neurath/local/"))
        )
        digest = hashlib.sha256()
        digest.update(b"head\0" + head + b"\0")
        for relative_path in relative_paths:
            path = self.root / relative_path
            digest.update(relative_path.encode("utf-8", errors="surrogateescape") + b"\0")
            if path.is_symlink():
                digest.update(b"symlink\0" + str(path.readlink()).encode() + b"\0")
            elif path.is_file():
                executable = b"x" if path.stat().st_mode & 0o111 else b"-"
                digest.update(b"file\0" + executable + b"\0" + path.read_bytes() + b"\0")
            elif path.exists():
                digest.update(b"directory\0")
            else:
                digest.update(b"missing\0")
        return digest.hexdigest()

    def complete_structured_harness_discovery(
        self,
        *,
        reproduction_node: str = "scripts/evolution_cases.py::test_a",
    ) -> tuple[str, str, str, PhaseRunnerResult, PhaseRunnerResult]:
        """Structured evaluate-harness의 frozen matrix와 reproduced finding을 완료합니다."""
        node_path, _, node_name = reproduction_node.partition("::")
        baseline_path = self.root / node_path
        original_source = baseline_path.read_text(encoding="utf-8")
        baseline_source = original_source.replace(
            f"def {node_name}():\n    assert True", f"def {node_name}():\n    assert False", 1
        )
        baseline_path.write_text(baseline_source, encoding="utf-8")
        self.run("init", "--skill", "evaluate-harness", "--run-id", "run-001")
        head_sha = "a" * 40
        rows = "A|B"
        row_specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
        decisions = "A:deny|B:allow"
        row_nodes = f"A@{reproduction_node}|B@scripts/evolution_cases.py::test_b"
        worktree_sha = self.worktree_sha()
        matrix_id = hashlib.sha256(
            f"{head_sha}|{worktree_sha}|{rows}|{row_specs}|{decisions}|{row_nodes}".encode()
        ).hexdigest()
        phase_one = self.run(
            "complete",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "matrix frozen",
            "--evidence",
            "failure_scenario: scenario=state-fence",
            "--evidence",
            SATURATED_SOURCE_CAPABILITY_INVENTORY,
            "--evidence",
            (
                f"acceptance_matrix: matrix_id={matrix_id} frozen=true "
                f"head_sha={head_sha} worktree_sha={worktree_sha} rows={rows} "
                f"row_specs={row_specs} row_count=2 decisions={decisions} row_nodes={row_nodes}"
            ),
        )
        phase_two = self.complete_structured_harness_evaluation(
            matrix_id=matrix_id,
            head_sha=head_sha,
            worktree_sha=worktree_sha,
            rows=rows,
            reproduction_node=reproduction_node,
        )
        baseline_path.write_text(original_source, encoding="utf-8")
        return matrix_id, head_sha, worktree_sha, phase_one, phase_two

    def complete_structured_harness_evaluation(
        self,
        *,
        matrix_id: str,
        head_sha: str,
        worktree_sha: str,
        rows: str,
        reproduction_node: str = "scripts/evolution_cases.py::test_a",
        record_evaluator: bool = True,
    ) -> PhaseRunnerResult:
        """Frozen worktree identity에 결속한 evaluator finding을 제출합니다."""
        evaluator_ref = "sha256:missing"
        if record_evaluator:
            evaluator_ref = self.record_evaluate_harness_evaluator(
                matrix_id=matrix_id,
                head_sha=head_sha,
                worktree_sha=worktree_sha,
                blocking_findings=("F1",),
            )
        return self.run(
            "complete",
            "--phase-id",
            "2",
            "--status",
            "completed",
            "--summary",
            "finding reproduced",
            "--evidence",
            f"project_mapping: matrix_id={matrix_id} mapped_rows={rows}",
            "--evidence",
            (
                "independent_evaluator_report: "
                f"delegation_id=evaluate-harness-reviewer-1 outcome_ref={evaluator_ref} "
                f"head_sha={head_sha} worktree_sha={worktree_sha} blocking_findings=1"
            ),
            "--evidence",
            (
                f"finding_reproduction: matrix_id={matrix_id} head_sha={head_sha} "
                f"worktree_sha={worktree_sha} finding_ids=F1 reproduced=true "
                "commands=1 expected_actual_pairs=1 "
                f"reproduction_specs=F1:A:deny:allow:{'d' * 64} "
                f"reproduction_nodes=F1@{reproduction_node}"
            ),
            "--evidence",
            (
                f"root_cause_deduplication: matrix_id={matrix_id} "
                "finding_ids=F1 stable_rule_ids=R1 mapped=true dedup_specs=F1:R1"
            ),
            "--evidence",
            (
                f"enforcement_classification: matrix_id={matrix_id} "
                f"classified_rows={rows} strong_rows=B weak_rows=none failed_rows=A"
            ),
        )

    def record_evaluate_harness_evaluator(
        self,
        *,
        matrix_id: str,
        head_sha: str,
        worktree_sha: str,
        blocking_findings: tuple[str, ...],
    ) -> str:
        """Direct-child evaluator의 typed result와 digest artifact를 consume합니다."""
        evaluator_id = ActorId("codex:reviewer-1")
        delegation_id = DelegationId("evaluate-harness-reviewer-1")
        self._state_handle.apply(
            ActorStarted(
                session_id=self._state_handle.session_id,
                actor_id=evaluator_id,
                parent_actor_id=self._state_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="phase-fixture:evaluate-harness-evaluator-started",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        assignment = json.dumps(
            {
                "kind": "evaluate-harness-independent-evaluator",
                "reviewed_head_sha": head_sha,
                "scope": "frozen evaluate-harness matrix",
                "started_at": "2026-08-10T00:00:00+00:00",
                "target": "independent evaluator",
                "workflow_id": self.workflow_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._state_handle.apply(
            DelegationAssigned(
                session_id=self._state_handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=self._state_handle.actor_id,
                target_actor_id=evaluator_id,
                assignment=assignment,
                idempotency_key="phase-fixture:evaluate-harness-evaluator-assigned",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        report = {
            "blocking_findings": list(blocking_findings),
            "head_sha": head_sha,
            "matrix_id": matrix_id,
            "summary": "frozen matrix independently evaluated",
            "verdict": "fail" if blocking_findings else "pass",
            "worktree_sha": worktree_sha,
        }
        evaluator_binding = RuntimeIdentityBinding(
            runtime=self._state_handle.runtime,
            session_id=self._state_handle.session_id,
            actor_id=evaluator_id,
            root_actor_id=self._state_handle.actor_id,
        )
        evaluator_handle = StateHandle.attach(self.locator, evaluator_binding)
        artifact = SessionArtifactStore(evaluator_handle).put_json({
            "delegation_id": str(delegation_id),
            "report": report,
            "schema": "neurath.delegation-result.v1",
            "target_agent_id": str(evaluator_id),
        })
        evaluator_handle.apply(
            DelegationReported(
                session_id=evaluator_handle.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=evaluator_id,
                result=DelegationResult(
                    verdict=report["verdict"],
                    summary=report["summary"],
                    outcome_ref=artifact.reference,
                    blocking_findings=blocking_findings,
                ),
                idempotency_key="phase-fixture:evaluate-harness-evaluator-reported",
            )
        )
        self._state_handle.apply(
            DelegationConsumed(
                session_id=self._state_handle.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=self._state_handle.actor_id,
                idempotency_key="phase-fixture:evaluate-harness-evaluator-consumed",
            )
        )
        return artifact.reference

    def complete_structured_harness_promotion(
        self,
        *,
        matrix_id: str,
        head_sha: str,
        harness_paths: str,
        regression_nodes: str,
        row_nodes: str,
    ) -> PhaseRunnerResult:
        """Current worktree에서 matrix row를 실행하는 promotion receipt를 제출합니다."""
        worktree_sha = self.worktree_sha()
        return self.run(
            "complete",
            "--phase-id",
            "3",
            "--status",
            "completed",
            "--summary",
            "finding promotion evaluated",
            "--evidence",
            "weak_or_failed_gaps: rows=A",
            "--evidence",
            "patch_recommendation: add ownership fence",
            "--evidence",
            "deterministic_enforcement_gate: executable tests",
            "--evidence",
            "rules_skills_guidance_only: true",
            "--evidence",
            (
                f"verification_result: matrix_id={matrix_id} head_sha={head_sha} "
                f"worktree_sha={worktree_sha} result=pass row_count=2 "
                "blocking_findings=0"
            ),
            "--evidence",
            (
                f"fixed_matrix_verification_result: matrix_id={matrix_id} "
                f"head_sha={head_sha} worktree_sha={worktree_sha} rows=A|B "
                f"row_count=2 result=pass blocking_findings=0 row_nodes={row_nodes}"
            ),
            "--evidence",
            (
                f"harness_evolution_result: matrix_id={matrix_id} head_sha={head_sha} "
                f"worktree_sha={worktree_sha} action=promote finding_ids=F1 "
                f"harness_paths={harness_paths} regression_nodes={regression_nodes}"
            ),
        )

    def corrupt_artifact(self, reference: str) -> None:
        """Canonical SQLite payload를 digest 갱신 없이 변조합니다."""
        digest = reference.removeprefix("sha256:")
        with RuntimeDatabase(self.root).connection() as db:
            changed = db.execute(
                "UPDATE runtime_records SET payload=? "
                "WHERE namespace=? AND key=?",
                (
                    b'{"tampered":true}',
                    f"artifact:{self._state_handle.session_id}",
                    digest,
                ),
            )
            if changed.rowcount != 1:
                raise AssertionError("phase fixture artifact is not stored in SQLite")

    def record_harness_incident(self, rule_id: str, symptom: str) -> str:
        """Canonical incident application으로 open occurrence를 기록합니다.

        Args:
            rule_id: 근본 harness invariant identity입니다.
            symptom: 재현 가능한 observed failure입니다.

        Returns:
            후속 transition이 선택할 typed incident identity입니다.
        """
        incident = HarnessIncidentApplication(self._state_handle, self.root).record(
            rule_id,
            symptom,
        )
        return str(incident.id)

    def escalate_harness_incident(
        self,
        incident_id: str,
        summary: str,
        reproduction_commands: list[str],
    ) -> None:
        """Canonical incident application으로 loop-owner handoff를 기록합니다.

        Args:
            incident_id: Escalate할 exact open occurrence입니다.
            summary: Loop owner가 이어갈 bounded handoff입니다.
            reproduction_commands: 결함을 재현할 command 목록입니다.
        """
        HarnessIncidentApplication(self._state_handle, self.root).escalate(
            incident_id,
            summary,
            reproduction_commands,
        )

    def source_manifest_evidence(self, evidence: str) -> str:
        """Fixture source bytes를 manifest에 고정하고 선언된 inventory에 pointer를 붙입니다."""
        capability_text = re.search(r"capability_ids=([^ ]+)", evidence)
        if capability_text is None:
            return evidence
        listed = subprocess.run(
            (
                "git",
                "-C",
                str(self.root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ),
            check=True,
            capture_output=True,
        )
        records = []
        from scripts.skill_harness.harness_source_inventory import HarnessSourceInventory
        inventory = HarnessSourceInventory(self.root)
        for raw_path in sorted(set(listed.stdout.split(b"\0"))):
            if not raw_path or raw_path.startswith((b".agents/runs/", b".neurath/local/")):
                continue
            relative_path = os.fsdecode(raw_path)
            if not inventory._in_scope(relative_path):
                continue
            path = self.root / relative_path
            records.append({
                "path": relative_path,
                "kind": "file",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executable": bool(path.stat().st_mode & 0o111),
            })
        source_path = records[0]["path"]
        manifest = {
            "schema": "neurath.harness-source-inventory.v1",
            "head_sha": None,
            "files": records,
            "capabilities": [
                {
                    "id": capability_id,
                    "source_paths": [source_path],
                    "gate_paths": [],
                    "regression_nodes": [],
                }
                for capability_id in capability_text.group(1).split("|")
            ],
        }
        reference = ".agents/runs/source-capability-manifest.json"
        content = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
        (self.root / reference).write_bytes(content)
        normalized = re.sub(r"source_files=[0-9]+", f"source_files={len(records)}", evidence)
        return (
            f"{normalized} manifest={reference} manifest_sha={hashlib.sha256(content).hexdigest()}"
        )

    def run(self, *args: str) -> PhaseRunnerResult:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            args: 호출자가 넘긴 args 값입니다.

        Returns:
            run 처리 결과입니다."""
        full_args = [
            self.source_manifest_evidence(value)
            if value.startswith("source_capability_inventory:") and " manifest=" not in value
            else value
            for value in args
        ]
        if "--workflow-id" not in full_args:
            full_args.extend(["--workflow-id", self.workflow_id])
        if full_args and full_args[0] == "init" and "--north-star" not in full_args:
            full_args.extend(["--north-star", DEFAULT_NORTH_STAR])
        output = StringIO()
        with redirect_stdout(output):
            exit_code = PhaseRunnerApplication(self.root).run(
                full_args,
                environment=self.environment,
            )
        return PhaseRunnerResult(exit_code, output.getvalue())

    def read_state(self, workflow_id: str | None = None) -> dict[str, object]:
        """Canonical process state의 exact workflow에서 phase_run projection을 읽습니다.

        Args:
            workflow_id: 기본 workflow 대신 읽을 exact aggregate identity입니다.

        Returns:
            Workflow payload의 phase_run object입니다.

        Raises:
            TypeError: Canonical process/workflow/phase payload shape가 잘못되면 발생합니다.
        """
        parsed = self._state_handle.inspect().to_payload()
        if not isinstance(parsed, dict):
            raise TypeError("canonical process state must be a JSON object")
        workflows = parsed.get("workflows")
        if not isinstance(workflows, dict):
            raise TypeError("canonical process state must contain workflows")
        selected_workflow_id = self.workflow_id if workflow_id is None else workflow_id
        workflow = workflows.get(selected_workflow_id)
        if not isinstance(workflow, dict):
            raise TypeError("exact phase workflow must be a JSON object")
        payload = workflow.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("workflow payload must be a JSON object")
        phase_state = payload.get("phase_run")
        if not isinstance(phase_state, dict):
            raise TypeError("workflow payload must contain phase_run")
        return {str(key): value for key, value in phase_state.items()}

    def read_skill_state(self, workflow_id: str | None = None) -> dict[str, object]:
        """Exact workflow의 skill_state namespace를 읽습니다.

        Args:
            workflow_id: 기본 workflow 대신 읽을 exact aggregate identity입니다.

        Returns:
            Skill-specific operational state의 독립 복사본입니다.

        Raises:
            TypeError: Skill state namespace가 JSON object가 아니면 발생합니다.
        """
        selected_workflow_id = self.workflow_id if workflow_id is None else workflow_id
        workflow = self._state_handle.inspect().workflows.get(WorkflowId(selected_workflow_id))
        if workflow is None:
            raise TypeError("exact phase workflow is missing")
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, dict):
            raise TypeError("workflow payload must contain skill_state")
        return {str(key): value for key, value in skill_state.items()}

    def write_skill_state(
        self,
        state: dict[str, object],
        *,
        replace: bool = False,
        workflow_id: str | None = None,
    ) -> None:
        """Typed WorkflowAdvanced로 exact workflow의 skill_state를 갱신합니다.

        Args:
            state: Merge 또는 replacement로 기록할 skill-specific object입니다.
            replace: 기존 namespace를 버리고 전달된 object만 기록할지 여부입니다.
            workflow_id: 기본 workflow 대신 갱신할 exact aggregate identity입니다.

        Raises:
            TypeError: Workflow 또는 기존 skill_state가 없거나 object가 아니면 발생합니다.
        """
        selected_workflow_id = self.workflow_id if workflow_id is None else workflow_id
        typed_workflow_id = WorkflowId(selected_workflow_id)
        workflow = self._state_handle.inspect().workflows.get(typed_workflow_id)
        if workflow is None:
            raise TypeError("exact phase workflow is missing")
        current_skill_state = workflow.payload.get("skill_state")
        if not isinstance(current_skill_state, dict):
            raise TypeError("workflow payload must contain skill_state")
        next_skill_state = {} if replace else dict(current_skill_state)
        next_skill_state.update(state)
        payload = dict(workflow.payload)
        payload["skill_state"] = next_skill_state
        self._mutation_index += 1
        self._state_handle.apply(
            WorkflowAdvanced(
                session_id=self._state_handle.session_id,
                workflow_id=typed_workflow_id,
                actor_id=self._state_handle.actor_id,
                expected_workflow_revision=workflow.revision,
                payload=payload,
                idempotency_key=f"phase-fixture:skill-state:{self._mutation_index}",
            )
        )

    def write(self, relative_path: str, content: str) -> None:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            relative_path: 호출자가 넘긴 relative path 값입니다.
            content: 호출자가 넘긴 content 값입니다."""
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(content), encoding="utf-8")


class HarnessEvidenceIntegrityTest(TestCase):
    """정상 무변경 감사와 독립 finding·실제 실행·source bytes의 결속을 검증합니다."""

    def test_reproduction_must_use_the_frozen_row_test(self) -> None:
        """같이 실패하는 다른 테스트도 처음 확정한 행의 재현 테스트를 대신하지 못합니다."""
        with PhaseRunnerFixture() as fixture:
            identities = self._begin(
                fixture,
                "assert False",
                extra_source="\n\ndef test_other():\n    assert False\n",
            )
            result = self._evaluate(
                fixture,
                *identities,
                ("F1",),
                reproduction_node="scripts/evolution_cases.py::test_other",
            )
        self.assertEqual(1, result.exit_code, result.output)
        self.assertIn("finding_reproduction.row_node_identity", result.output)

    def test_acceptance_matrix_freezes_a_valid_test_for_every_row(self) -> None:
        """초기 검사표는 모든 행의 실제 테스트를 중복 없이 고정하고 digest에 포함합니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            runner = PhaseRunner(SkillContractRepository(fixture.root))
            head = "a" * 40
            worktree = fixture.worktree_sha()
            basis = f"{head}|{worktree}|A|B|A:owner:owned:write|B:child:owned:read|A:deny|B:allow"
            valid = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
            for mapping in (
                valid,
                "none",
                "A@scripts/evolution_cases.py::test_a",
                valid + "|C@scripts/evolution_cases.py::test_c",
                valid + "|A@scripts/evolution_cases.py::test_a",
                valid.replace("::test_b", "::test_a"),
                valid.replace("::test_b", "::test_missing"),
            ):
                with self.subTest(mapping=mapping):
                    digest = hashlib.sha256(f"{basis}|{mapping}".encode()).hexdigest()
                    matrix = (
                        f"matrix_id={digest} frozen=true head_sha={head} worktree_sha={worktree} "
                        "rows=A|B row_specs=A:owner:owned:write|B:child:owned:read "
                        f"row_count=2 decisions=A:deny|B:allow row_nodes={mapping}"
                    )
                    failures = runner._acceptance_matrix_failures(matrix)
                    if mapping == valid:
                        self.assertEqual([], failures)
                        self.assertIn(
                            "acceptance_matrix.matrix_id",
                            runner._acceptance_matrix_failures(
                                matrix.replace("::test_b", "::test_a")
                            ),
                        )
                    else:
                        self.assertIn("acceptance_matrix.row_nodes", failures)

    def test_fixed_matrix_rejects_nonfinding_row_node_substitution(self) -> None:
        """결함 없는 행의 원래 검사가 실패해도 무관한 통과 검사로 바꿔 완료할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            fixture.write_structured_evaluate_harness_contract()
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert True\n\n"
                "def test_b():\n    assert True\n\n"
                "def test_unrelated():\n    assert True\n",
            )
            matrix_id, head, _, first, second = fixture.complete_structured_harness_discovery()
            self.assertEqual(0, first.exit_code, first.output)
            self.assertEqual(0, second.exit_code, second.output)
            fixture.write(
                "scripts/evolution_cases.py",
                "def test_a():\n    assert True\n\n"
                "def test_b():\n    assert False\n\n"
                "def test_unrelated():\n    assert True\n",
            )
            fixture.write("scripts/harness_gate.py", "ENFORCED = True\n")
            result = fixture.complete_structured_harness_promotion(
                matrix_id=matrix_id,
                head_sha=head,
                harness_paths="scripts/harness_gate.py",
                regression_nodes="scripts/evolution_cases.py::test_a",
                row_nodes="A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_unrelated",
            )
        self.assertEqual(1, result.exit_code, result.output)
        self.assertIn("fixed_matrix_verification_result.row_node_identity", result.output)

    def test_documented_source_inventory_order_matches_the_contract(self) -> None:
        """스킬의 원본 형식을 그대로 채운 정상 증거는 계약의 순서 검사도 통과합니다."""
        root = Path(__file__).resolve().parents[3]
        document = (root / ".agents/skills/evaluate-harness/SKILL.md").read_text()
        template = document.split("- `source_capability_inventory`: `", 1)[1].split("` 형식", 1)[0]
        replacements = {
            "<40-hex>": "a" * 40,
            "<64-hex>": "b" * 64,
            "<.agents/runs/<run-id>/source-inventory.json>": ".agents/runs/probe/source-inventory.json",
            "<integer >= 2>": "2",
            "<n|...|0>": "1|0",
            "<id|...>": "probe",
            "<n>": "1",
        }
        for token, value in replacements.items():
            template = template.replace(token, value)
        repository = SkillContractRepository(root)
        failures = PhaseRunner(repository)._pattern_failures(
            repository.get("evaluate-harness").phases[0],
            ("source_capability_inventory: " + " ".join(template.split()),),
        )
        self.assertEqual([], failures)

    def test_zero_findings_reaches_no_change_after_full_matrix_execution(self) -> None:
        """발견 0건은 가짜 finding 없이 전체 검사표를 실행하고 no_change에 도달합니다."""
        with PhaseRunnerFixture() as fixture:
            matrix_id, head, worktree, rows = self._begin(
                fixture,
                "assert True",
                extra_source="\n\ndef test_unrelated():\n    assert True\n",
            )
            evaluated = self._evaluate(fixture, matrix_id, head, worktree, rows, (), empty=True)
            self.assertEqual(0, evaluated.exit_code, evaluated.output)
            arguments = (
                "complete",
                "--phase-id",
                "3",
                "--status",
                "completed",
                "--summary",
                "no changes needed",
                "--evidence",
                "weak_or_failed_gaps: none",
                "--evidence",
                "patch_recommendation: no_change",
                "--evidence",
                "deterministic_enforcement_gate: existing nodes",
                "--evidence",
                "rules_skills_guidance_only: true",
                "--evidence",
                f"verification_result: matrix_id={matrix_id} head_sha={head} worktree_sha={worktree} result=pass row_count=2 blocking_findings=0",
                "--evidence",
                f"fixed_matrix_verification_result: matrix_id={matrix_id} head_sha={head} worktree_sha={worktree} rows={rows} row_count=2 result=pass blocking_findings=0 row_nodes=A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b",
                "--evidence",
                f"harness_evolution_result: matrix_id={matrix_id} head_sha={head} worktree_sha={worktree} action=no_change finding_ids=none harness_paths=none regression_nodes=none",
            )
            rejected = fixture.run(
                *(
                    value.replace(
                        "B@scripts/evolution_cases.py::test_b",
                        "B@scripts/evolution_cases.py::test_unrelated",
                    )
                    for value in arguments
                )
            )
            self.assertEqual(1, rejected.exit_code, rejected.output)
            self.assertIn("fixed_matrix_verification_result.row_node_identity", rejected.output)
            finalized = fixture.run(*arguments)
        self.assertEqual(0, finalized.exit_code, finalized.output)

    def test_consumed_blocker_identity_cannot_be_substituted(self) -> None:
        """같은 blocker 개수라도 evaluator가 지적하지 않은 finding으로 바꿀 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            identities = self._begin(fixture, "assert False")
            result = self._evaluate(fixture, *identities, ("OTHER-BLOCKER",))
        self.assertEqual(1, result.exit_code)
        self.assertIn("independent_evaluator_report.finding_ids", result.output)

    def test_reproduction_requires_the_claimed_test_outcome(self) -> None:
        """실제 통과한 test로 gate failure가 재현됐다고 주장할 수 없습니다."""
        with PhaseRunnerFixture() as fixture:
            identities = self._begin(fixture, "assert True")
            result = self._evaluate(fixture, *identities, ("F1",))
        self.assertEqual(1, result.exit_code)
        self.assertIn("finding_reproduction.execution", result.output)

    def test_reproduction_accepts_real_regression_failure_and_nonblocking_pass(self) -> None:
        """실패 재현과 정상 row 재확인은 서로 맞는 pytest 결과일 때 모두 허용합니다."""
        for body, actual, blockers in (
            ("assert False", "allow", ("F1",)),
            ("assert True", "deny", ()),
        ):
            with self.subTest(actual=actual):
                with PhaseRunnerFixture() as fixture:
                    identities = self._begin(fixture, body)
                    result = self._evaluate(fixture, *identities, blockers, actual=actual)
                self.assertEqual(0, result.exit_code, result.output)

    def test_reproduction_rejects_collection_error_and_changed_worktree(self) -> None:
        """수집 오류나 검사 중 source 변경은 gate 실패의 재현 증거가 아닙니다."""
        rows = (
            ("raise KeyboardInterrupt", "finding_reproduction.execution"),
            (
                "from pathlib import Path; Path('changed.py').write_text('changed'); assert False",
                "finding_reproduction.current_worktree",
            ),
        )
        for body, failure in rows:
            with self.subTest(body=body):
                with PhaseRunnerFixture() as fixture:
                    identities = self._begin(fixture, body)
                    result = self._evaluate(fixture, *identities, ("F1",))
                self.assertEqual(1, result.exit_code)
                self.assertIn(failure, result.output)

    def test_reproduction_rejects_setup_errors_and_skipped_tests(self) -> None:
        """Test-call 실패와 정상 실행만 증거이며 setup 오류와 skip은 증거가 아닙니다."""
        for body, parameters, actual, blockers in (
            ("assert False", "missing_fixture", "allow", ("F1",)),
            ("import pytest; pytest.skip('not exercised')", "", "deny", ()),
        ):
            with self.subTest(parameters=parameters):
                with PhaseRunnerFixture() as fixture:
                    identities = self._begin(fixture, body, parameters=parameters)
                    result = self._evaluate(fixture, *identities, blockers, actual=actual)
                self.assertEqual(1, result.exit_code)
                self.assertIn("finding_reproduction.execution", result.output)

    def test_source_inventory_requires_current_manifest_bytes_and_references(self) -> None:
        """파일 누락·새 파일·stale bytes·가짜 참조를 source inventory label로 감출 수 없습니다."""
        cases = (
            "valid",
            "valid-gate",
            "missing",
            "digest",
            "omitted-file",
            "bytes",
            "added-file",
            "capability",
            "source",
            "gate",
            "node",
            "head",
        )
        for case in cases:
            with self.subTest(case=case):
                with PhaseRunnerFixture() as fixture:
                    fixture.write_structured_evaluate_harness_contract()
                    fixture.write(
                        "scripts/evolution_cases.py",
                        "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n",
                    )
                    evidence = fixture.source_manifest_evidence(
                        SATURATED_SOURCE_CAPABILITY_INVENTORY
                    )
                    reference = ".agents/runs/source-capability-manifest.json"
                    path = fixture.root / reference
                    manifest = json.loads(path.read_text())
                    if case == "valid-gate":
                        manifest["capabilities"][0]["gate_paths"] = ["scripts/evolution_cases.py"]
                        manifest["capabilities"][0]["regression_nodes"] = [
                            "scripts/evolution_cases.py::test_a"
                        ]
                    elif case == "missing":
                        evidence = SATURATED_SOURCE_CAPABILITY_INVENTORY
                    elif case == "digest":
                        evidence = re.sub(
                            r"manifest_sha=[0-9a-f]+", "manifest_sha=" + "0" * 64, evidence
                        )
                    elif case == "omitted-file":
                        manifest["files"].pop()
                    elif case == "bytes":
                        fixture.write(
                            "scripts/evolution_cases.py",
                            "def test_a():\n    assert False\n\ndef test_b():\n    assert True\n",
                        )
                    elif case == "added-file":
                        fixture.write("scripts/added.py", "VALUE = True\n")
                    elif case == "capability":
                        manifest["capabilities"][0]["id"] = "substituted"
                    elif case == "source":
                        manifest["capabilities"][0]["source_paths"] = ["../outside.py"]
                    elif case == "gate":
                        manifest["capabilities"][0]["gate_paths"] = ["scripts/missing.py"]
                    elif case == "node":
                        manifest["capabilities"][0]["gate_paths"] = ["scripts/evolution_cases.py"]
                        manifest["capabilities"][0]["regression_nodes"] = [
                            "scripts/evolution_cases.py::test_missing"
                        ]
                    elif case == "head":
                        manifest["head_sha"] = "0" * 40
                    if case not in {"valid", "missing", "digest", "bytes", "added-file"}:
                        content = json.dumps(manifest, sort_keys=True).encode()
                        path.write_bytes(content)
                        evidence = re.sub(
                            r"manifest_sha=[0-9a-f]+",
                            "manifest_sha=" + hashlib.sha256(content).hexdigest(),
                            evidence,
                        )
                    failures = PhaseRunner(
                        SkillContractRepository(fixture.root)
                    )._source_capability_inventory_failures(evidence)
                if case in {"valid", "valid-gate"}:
                    self.assertEqual([], failures)
                else:
                    self.assertIn("source_capability_inventory.manifest", failures)

    def _begin(
        self,
        fixture: PhaseRunnerFixture,
        body: str,
        *,
        parameters: str = "",
        extra_source: str = "",
    ) -> tuple[str, str, str, str]:
        """두 row의 실제 source를 먼저 쓰고 변경 전 matrix를 freeze합니다."""
        fixture.write_structured_evaluate_harness_contract()
        fixture.write(
            "scripts/evolution_cases.py",
            f"def test_a({parameters}):\n    {body}\n\ndef test_b():\n    assert True\n{extra_source}",
        )
        fixture.run("init", "--skill", "evaluate-harness", "--run-id", "evidence-integrity")
        head = "a" * 40
        worktree = fixture.worktree_sha()
        rows = "A|B"
        specs = "A:owner:owned:write_state|B:delegate:owned:read_state"
        decisions = "A:deny|B:allow"
        row_nodes = "A@scripts/evolution_cases.py::test_a|B@scripts/evolution_cases.py::test_b"
        matrix_id = hashlib.sha256(
            f"{head}|{worktree}|{rows}|{specs}|{decisions}|{row_nodes}".encode()
        ).hexdigest()
        initialized = fixture.run(
            "complete",
            "--phase-id",
            "1",
            "--status",
            "completed",
            "--summary",
            "freeze",
            "--evidence",
            "failure_scenario: scenario=real-source-and-execution",
            "--evidence",
            SATURATED_SOURCE_CAPABILITY_INVENTORY,
            "--evidence",
            f"acceptance_matrix: matrix_id={matrix_id} frozen=true head_sha={head} worktree_sha={worktree} rows={rows} row_specs={specs} row_count=2 decisions={decisions} row_nodes={row_nodes}",
        )
        self.assertEqual(0, initialized.exit_code, initialized.output)
        return matrix_id, head, worktree, rows

    def _evaluate(
        self,
        fixture: PhaseRunnerFixture,
        matrix_id: str,
        head: str,
        worktree: str,
        rows: str,
        blockers: tuple[str, ...],
        *,
        empty: bool = False,
        actual: str = "allow",
        reproduction_node: str = "scripts/evolution_cases.py::test_a",
    ) -> PhaseRunnerResult:
        """Consumed report와 owner reproduction을 독립적으로 고정해 phase 2를 실행합니다."""
        outcome = fixture.record_evaluate_harness_evaluator(
            matrix_id=matrix_id, head_sha=head, worktree_sha=worktree, blocking_findings=blockers
        )
        reproduction = (
            "finding_ids=none reproduced=true commands=0 expected_actual_pairs=0 reproduction_specs=none reproduction_nodes=none"
            if empty
            else f"finding_ids=F1 reproduced=true commands=1 expected_actual_pairs=1 reproduction_specs=F1:A:deny:{actual}:{'d' * 64} reproduction_nodes=F1@{reproduction_node}"
        )
        dedup = (
            "finding_ids=none stable_rule_ids=none mapped=true dedup_specs=none"
            if empty
            else "finding_ids=F1 stable_rule_ids=R1 mapped=true dedup_specs=F1:R1"
        )
        classification = (
            "strong_rows=A|B weak_rows=none failed_rows=none"
            if empty or actual == "deny"
            else "strong_rows=B weak_rows=none failed_rows=A"
        )
        return fixture.run(
            "complete",
            "--phase-id",
            "2",
            "--status",
            "completed",
            "--summary",
            "check evidence",
            "--evidence",
            f"project_mapping: matrix_id={matrix_id} mapped_rows={rows}",
            "--evidence",
            f"independent_evaluator_report: delegation_id=evaluate-harness-reviewer-1 outcome_ref={outcome} head_sha={head} worktree_sha={worktree} blocking_findings={len(blockers)}",
            "--evidence",
            f"finding_reproduction: matrix_id={matrix_id} head_sha={head} worktree_sha={worktree} {reproduction}",
            "--evidence",
            f"root_cause_deduplication: matrix_id={matrix_id} {dedup}",
            "--evidence",
            f"enforcement_classification: matrix_id={matrix_id} classified_rows={rows} {classification}",
        )
