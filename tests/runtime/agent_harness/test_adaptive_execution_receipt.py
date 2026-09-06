"""Executable adaptive evidence가 current worktree runtime readback을 소유하는지 검증합니다."""

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.adaptive_control import (
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    GapInventory,
    GoalContract,
    OracleOwner,
    RequirementSection,
    approved_requirement_fingerprint,
)
from scripts.agent_harness.adaptive_control_store import AdaptiveControlState
from scripts.agent_harness.adaptive_execution_receipt import (
    AdaptiveExecutionReceiptInvalid,
    AdaptiveExecutionReceiptStore,
)
from scripts.agent_harness.harness_incident import run_regression_commands
from scripts.agent_harness.session_kernel import (
    SessionLocator,
    WorkflowId,
    WorkflowRecord,
    WorkflowStarted,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    StateHandle,
)


class AdaptiveExecutionReceiptStoreTest(TestCase):
    """Self-authored executable JSON이 실행 증명으로 승격하지 못하게 합니다."""

    def setUp(self) -> None:
        """Dirty-byte fingerprint와 실제 pytest node를 가진 격리 Git workflow를 만듭니다."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repository = Path(directory.name)
        subprocess.run(("git", "init", "-q"), cwd=self.repository, check=True)
        subprocess.run(
            ("git", "config", "user.email", "fixture@example.invalid"),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "config", "user.name", "Fixture"),
            cwd=self.repository,
            check=True,
        )
        (self.repository / ".gitignore").write_text(
            ".agents/runs/\n.pytest_cache/\n__pycache__/\n",
            encoding="utf-8",
        )
        tests = self.repository / "tests/test_runtime_evidence.py"
        tests.parent.mkdir(parents=True)
        tests.write_text(
            "def test_passes():\n"
            "    assert True\n\n"
            "def test_fails():\n"
            "    assert False\n\n"
            "def test_skips():\n"
            "    import pytest\n"
            "    pytest.skip('no execution')\n",
            encoding="utf-8",
        )
        subprocess.run(("git", "add", "."), cwd=self.repository, check=True)
        subprocess.run(
            ("git", "commit", "-qm", "runtime fixture"),
            cwd=self.repository,
            check=True,
        )
        binding = RuntimeEnvironmentResolver().resolve({
            "CODEX_THREAD_ID": "adaptive-execution-session"
        })
        self.owner = StateHandle.initialize(SessionLocator(self.repository), binding)
        self.workflow_id = WorkflowId("adaptive-execution-workflow")
        self.contract = self._contract("adaptive runtime evidence를 검증한다")
        self.owner.apply(
            WorkflowStarted(
                session_id=self.owner.session_id,
                workflow_id=self.workflow_id,
                owner_actor_id=self.owner.actor_id,
                kind="evaluate-harness",
                goal=self.contract.goal,
                payload={"skill_state": {}},
                idempotency_key="adaptive-execution:workflow",
            )
        )
        self.store = AdaptiveExecutionReceiptStore(self.owner, self.workflow_id)

    def test_actual_passing_pytest_node_issues_and_replays_current_receipt(self) -> None:
        """Harness가 실행한 exact pytest node만 executable PASS로 발행하고 재실행합니다."""
        issued = self.store.execute_pytest(
            self.contract,
            criterion_id="runtime-proof",
            evidence_kind=EvidenceKind.EXAMPLE_TEST,
            pytest_node="tests/test_runtime_evidence.py::test_passes",
        )

        self.assertEqual(EvidenceAuthority.EXECUTABLE, issued.evidence.authority)
        self.assertEqual("harness:adaptive-execution", issued.evidence.lineage.issuer_id)
        self.assertEqual(
            issued.evidence.reference, f"sha256:{issued.evidence.lineage.receipt_digest}"
        )
        self.store.verify(
            issued.evidence,
            self.contract,
            expected_workflow_revision=0,
        )

    def test_fabricated_or_missing_receipt_cannot_verify(self) -> None:
        """Executable enum과 SHA 모양만 자가 작성한 evidence는 runtime proof가 아닙니다."""
        issued = self.store.execute_pytest(
            self.contract,
            criterion_id="runtime-proof",
            evidence_kind=EvidenceKind.EXAMPLE_TEST,
            pytest_node="tests/test_runtime_evidence.py::test_passes",
        )
        fabricated = issued.evidence.__class__(
            goal_fingerprint=issued.evidence.goal_fingerprint,
            criterion_id=issued.evidence.criterion_id,
            kind=issued.evidence.kind,
            authority=issued.evidence.authority,
            status=issued.evidence.status,
            reference=f"sha256:{'f' * 64}",
            lineage=issued.evidence.lineage.__class__(
                authority=issued.evidence.lineage.authority,
                issuer_id=issued.evidence.lineage.issuer_id,
                subject_id=issued.evidence.lineage.subject_id,
                intent_revision=issued.evidence.lineage.intent_revision,
                source_revision=issued.evidence.lineage.source_revision,
                receipt_digest="f" * 64,
            ),
        )

        with self.assertRaises(AdaptiveExecutionReceiptInvalid):
            self.store.verify(fabricated, self.contract, expected_workflow_revision=0)

    def test_receipt_rejects_wrong_goal_worktree_and_workflow_revision(self) -> None:
        """Goal, dirty current bytes, workflow revision 중 하나라도 달라지면 stale입니다."""
        issued = self.store.execute_pytest(
            self.contract,
            criterion_id="runtime-proof",
            evidence_kind=EvidenceKind.EXAMPLE_TEST,
            pytest_node="tests/test_runtime_evidence.py::test_passes",
        )

        with self.assertRaises(AdaptiveExecutionReceiptInvalid):
            self.store.verify(
                issued.evidence,
                self._contract("다른 adaptive goal"),
                expected_workflow_revision=0,
            )
        with self.assertRaises(AdaptiveExecutionReceiptInvalid):
            self.store.verify(
                issued.evidence,
                self.contract,
                expected_workflow_revision=1,
            )

        (self.repository / "dirty.txt").write_text("current dirty bytes\n", encoding="utf-8")
        with self.assertRaises(AdaptiveExecutionReceiptInvalid):
            self.store.verify(
                issued.evidence,
                self.contract,
                expected_workflow_revision=0,
            )

    def test_contract_check_accepts_current_amended_goal_and_rejects_stale_contract(self) -> None:
        """Executable evidence는 initial anchor가 아닌 current typed contract에 결속됩니다."""
        current = self.owner.inspect().workflows[self.workflow_id]
        amended = self._contract("수정된 adaptive runtime evidence를 검증한다", intent_revision=2)
        amended_state = AdaptiveControlState.empty(
            amended,
            GapInventory(
                intent_revision=amended.intent_revision,
                source_revision="repo:head-2",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )
        amended_workflow = WorkflowRecord(
            workflow_id=current.id,
            owner_actor_id=current.owner_actor_id,
            kind=current.kind,
            goal=current.goal,
            payload={"skill_state": {"adaptive_control": amended_state.to_payload()}},
            revision=current.revision + 1,
            status=current.status,
            last_transition_idempotency_key=current.last_transition_idempotency_key,
        )

        self.store._require_contract(
            amended_workflow,
            amended,
            "runtime-proof",
            EvidenceKind.EXAMPLE_TEST,
        )
        with self.assertRaises(AdaptiveExecutionReceiptInvalid):
            self.store._require_contract(
                amended_workflow,
                self.contract,
                "runtime-proof",
                EvidenceKind.EXAMPLE_TEST,
            )

    def test_failed_or_no_op_pytest_node_cannot_issue_receipt(self) -> None:
        """Nonzero exit과 all-skipped/no-op test는 executable PASS artifact를 만들지 못합니다."""
        for node in (
            "tests/test_runtime_evidence.py::test_fails",
            "tests/test_runtime_evidence.py::test_skips",
        ):
            with (
                self.subTest(node=node),
                self.assertRaises(AdaptiveExecutionReceiptInvalid),
            ):
                self.store.execute_pytest(
                    self.contract,
                    criterion_id="runtime-proof",
                    evidence_kind=EvidenceKind.EXAMPLE_TEST,
                    pytest_node=node,
                )

    def test_verifier_memoizes_only_within_one_readback_instance(self) -> None:
        """One verifier는 exact receipt를 한 번만 replay하지만 새 verifier는 반드시 다시 실행합니다."""
        issued = self.store.execute_pytest(
            self.contract,
            criterion_id="runtime-proof",
            evidence_kind=EvidenceKind.EXAMPLE_TEST,
            pytest_node="tests/test_runtime_evidence.py::test_passes",
        )

        with patch(
            "scripts.agent_harness.adaptive_execution_receipt.run_regression_commands",
            wraps=run_regression_commands,
        ) as replay:
            self.store.verify(
                issued.evidence,
                self.contract,
                expected_workflow_revision=0,
            )
            self.store.verify(
                issued.evidence,
                self.contract,
                expected_workflow_revision=0,
            )
            AdaptiveExecutionReceiptStore(self.owner, self.workflow_id).verify(
                issued.evidence,
                self.contract,
                expected_workflow_revision=0,
            )

        self.assertEqual(2, replay.call_count)

    def _contract(self, goal: str, *, intent_revision: int = 1) -> GoalContract:
        """Executable example-test를 oracle로 갖는 현재 goal contract를 만듭니다."""
        constraints = ("current worktree bytes에 결속한다",)
        non_goals = ("self-authored JSON을 실행으로 간주하지 않는다",)
        source_revision = f"approved-plan:{intent_revision}"
        requirement = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            intent_revision,
            source_revision,
        )
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({"REQ-runtime-proof"}),
            criteria=(
                CriterionSpec(
                    criterion_id="runtime-proof",
                    description="실제 pytest node가 현재 bytes에서 PASS한다",
                    source_requirement_id="REQ-runtime-proof",
                    approved_requirement_fingerprint=requirement,
                    observer="adaptive execution verifier",
                    precondition="tracked pytest node가 있다",
                    stimulus="harness가 exact node를 실행한다",
                    expected_outcome="at least one test passes",
                    oracle_owner=OracleOwner.EXECUTABLE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.EXAMPLE_TEST}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )
