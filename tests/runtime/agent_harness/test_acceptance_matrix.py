"""Frozen session harness acceptance matrix runner를 검증합니다."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.acceptance_matrix import (
    ACCEPTANCE_MATRIX,
    AcceptanceId,
    AcceptanceMatrixRunner,
    CommandResult,
    _selected_cases,
)


class RecordingCommandRunner:
    """Subprocess 없이 exact pytest command를 기록하는 deterministic fake입니다."""

    def __init__(self, failures: frozenset[str] = frozenset()) -> None:
        """실패시킬 node set을 고정합니다.

        Args:
            failures: Command arguments에 포함되면 nonzero를 반환할 node입니다.
        """
        self._failures = failures
        self.commands: list[tuple[str, ...]] = []

    def run(self, arguments: object, *, cwd: Path) -> CommandResult:
        """Command를 기록하고 설정된 deterministic result를 반환합니다.

        Args:
            arguments: Runner가 만든 command argument sequence입니다.
            cwd: Runner가 고정한 repository root입니다.

        Returns:
            Failure node 포함 여부로 결정된 result입니다.
        """
        del cwd
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        self.commands.append(command)
        failed = any(node in command for node in self._failures)
        return CommandResult(1 if failed else 0, "failed" if failed else "passed", "")


class AcceptanceMatrixTest(TestCase):
    """A01-A27 coverage와 row별 executable evidence를 고정합니다."""

    def setUp(self) -> None:
        """Repository-independent runner fixture를 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = Path(self.temporary_directory.name)

    def test_matrix_contains_every_frozen_row_exactly_once(self) -> None:
        """Frozen spec의 A01-A27이 누락과 중복 없이 executable node를 가집니다."""
        rows = tuple(case.row for case in ACCEPTANCE_MATRIX)

        self.assertEqual(tuple(AcceptanceId), rows)
        self.assertEqual(27, len(rows))
        self.assertTrue(all(case.nodes for case in ACCEPTANCE_MATRIX))
        self.assertTrue(
            all(
                node.startswith("scripts/") and "::test_" in node
                for case in ACCEPTANCE_MATRIX
                for node in case.nodes
            )
        )

    def test_runner_executes_each_row_as_exact_pytest_nodes(self) -> None:
        """Receipt는 label count가 아니라 각 row의 실제 pytest command를 증명합니다."""
        command_runner = RecordingCommandRunner()
        selected = _selected_cases(("A01", "A22", "A01"))

        receipt = AcceptanceMatrixRunner(self.repository, command_runner).execute(
            selected,
            fail_fast=False,
        )

        self.assertTrue(receipt["passed"])
        self.assertEqual(["A01", "A22"], receipt["executed_rows"])
        self.assertEqual(2, len(command_runner.commands))
        self.assertTrue(
            all(command[1:4] == ("-m", "pytest", "-q") for command in command_runner.commands)
        )
        self.assertEqual(
            "neurath.session-harness-acceptance-receipt.v1",
            receipt["schema"],
        )
        self.assertNotIn("matrix_digest", receipt)
        results = receipt["results"]
        self.assertIsInstance(results, list)
        assert isinstance(results, list)
        self.assertTrue(all("evidence_surfaces" not in result for result in results))

    def test_failure_is_attributed_to_row_and_fail_fast_is_bounded(self) -> None:
        """첫 failing node의 row evidence를 보존하고 후속 row는 실행하지 않습니다."""
        failing_node = ACCEPTANCE_MATRIX[1].nodes[0]
        command_runner = RecordingCommandRunner(frozenset((failing_node,)))

        receipt = AcceptanceMatrixRunner(self.repository, command_runner).execute(
            ACCEPTANCE_MATRIX[:3],
            fail_fast=True,
        )

        self.assertFalse(receipt["passed"])
        self.assertEqual(["A01", "A02"], receipt["executed_rows"])
        results = receipt["results"]
        self.assertIsInstance(results, list)
        assert isinstance(results, list)
        self.assertFalse(results[-1]["passed"])
