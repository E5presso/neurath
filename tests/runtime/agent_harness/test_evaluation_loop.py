"""평가 루프가 exact workflow state와 수렴 조건을 함께 강제하는지 검증합니다."""

import io
import subprocess
import unittest
from collections.abc import Callable, Mapping
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.agent_harness.evaluation_loop import (
    EvaluationLoop,
    EvaluationLoopApplication,
    EvaluationLoopClock,
    EvaluationLoopError,
    Finding,
)
from scripts.agent_harness.session_kernel import (
    SessionId,
    SessionLocator,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateSnapshot,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle


class SequenceEvaluationClock(EvaluationLoopClock):
    """Test가 timestamp capture 횟수와 값을 관찰할 수 있는 clock입니다."""

    def __init__(self, timestamps: tuple[str, ...]) -> None:
        """호출 순서대로 반환할 timestamp를 고정합니다.

        Args:
            timestamps: `now` 호출마다 하나씩 반환할 ISO timestamp입니다.
        """
        self._timestamps = timestamps
        self._calls = 0

    @property
    def calls(self) -> int:
        """현재까지 timestamp를 요청한 횟수를 반환합니다.

        Returns:
            `now` 호출 횟수입니다.
        """
        return self._calls

    def now(self) -> str:
        """다음 고정 timestamp를 반환합니다.

        Returns:
            호출 순서에 대응하는 timestamp입니다.

        Raises:
            AssertionError: 준비한 timestamp보다 많이 호출하면 발생합니다.
        """
        if self._calls >= len(self._timestamps):
            raise AssertionError("evaluation clock was called more often than expected")
        timestamp = self._timestamps[self._calls]
        self._calls += 1
        return timestamp


type SkillStateCommit = Callable[
    [SkillStateStore, SkillStateSnapshot, Mapping[str, object], str],
    SkillStateSnapshot,
]


class ConflictOnceCommit:
    """첫 skill-state CAS만 충돌시키고 retry candidate를 관찰합니다."""

    def __init__(
        self,
        test_case: EvaluationLoopTest,
        commit: SkillStateCommit,
    ) -> None:
        """실제 commit과 typed assertion owner를 결합합니다.

        Args:
            test_case: Nested candidate shape를 검증할 test instance입니다.
            commit: 첫 conflict 뒤 호출할 original commit operation입니다.
        """
        self._test_case = test_case
        self._commit = commit
        self._attempts = 0
        self._observed_timestamps: list[object] = []

    @property
    def attempts(self) -> int:
        """현재까지 commit을 시도한 횟수를 반환합니다.

        Returns:
            Synthetic conflict를 포함한 commit attempt 수입니다.
        """
        return self._attempts

    @property
    def observed_timestamps(self) -> tuple[object, ...]:
        """각 retry candidate에서 관찰한 opened_at을 반환합니다.

        Returns:
            Attempt 순서대로 보존한 timestamp tuple입니다.
        """
        return tuple(self._observed_timestamps)

    def __call__(
        self,
        store: SkillStateStore,
        snapshot: SkillStateSnapshot,
        candidate: Mapping[str, object],
        operation_id: str,
    ) -> SkillStateSnapshot:
        """첫 attempt에는 conflict를, 다음 attempt에는 실제 commit을 수행합니다.

        Args:
            store: Patch가 전달한 exact SkillStateStore입니다.
            snapshot: 이번 attempt가 읽은 workflow-local CAS 원본입니다.
            candidate: Pure transform이 계산한 replacement skill state입니다.
            operation_id: Retry 전체에서 재사용하는 persisted-하지 않는 event identity입니다.

        Returns:
            두 번째 이후 attempt에서 실제 commit된 snapshot입니다.

        Raises:
            SkillStateConflict: 첫 attempt에서 retry를 강제하기 위해 발생합니다.
        """
        self._attempts += 1
        loops = self._test_case._mapping(candidate["evaluation_loops"], "retry loops")
        loop = self._test_case._mapping(loops["retry-gate"], "retry loop")
        self._observed_timestamps.append(loop["opened_at"])
        if self._attempts == 1:
            raise SkillStateConflict("synthetic workflow conflict")
        return self._commit(store, snapshot, candidate, operation_id)


class EvaluationLoopTest(unittest.TestCase):
    """루프 domain과 workflow-local optimistic persistence 계약을 검증합니다."""

    OPENED_AT = "2026-08-04T01:00:00+00:00"
    ROUND_ONE_AT = "2026-08-04T01:01:00+00:00"
    ROUND_TWO_AT = "2026-08-04T01:02:00+00:00"
    ROUND_THREE_AT = "2026-08-04T01:03:00+00:00"
    CLOSED_AT = "2026-08-04T01:04:00+00:00"

    def run(
        self,
        result: unittest.TestResult | None = None,
    ) -> unittest.TestResult | None:
        """각 unittest 실행 전에 snake-case fixture setup을 적용합니다.

        Args:
            result: Unittest runner가 제공한 optional result collector입니다.

        Returns:
            표준 TestCase 실행 결과입니다.
        """
        self.set_up()
        return super().run(result)

    def set_up(self) -> None:
        """독립 Git repository와 runtime-bound active workflow를 준비합니다."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repository = Path(self.directory.name)
        subprocess.run(
            ("git", "init", "--quiet", str(self.repository)),
            check=True,
            capture_output=True,
            text=True,
        )
        self.environment = {"CODEX_THREAD_ID": "evaluation-session"}
        self.locator = SessionLocator.from_worktree(self.repository)
        binding = RuntimeEnvironmentResolver().resolve(self.environment)
        self.handle = StateHandle.initialize(self.locator, binding)
        self.workflow_id = WorkflowId("workflow-a")
        self._start_workflow(self.workflow_id)
        self.stream = io.StringIO()

    def _start_workflow(self, workflow_id: WorkflowId) -> None:
        """평가 루프를 담을 active workflow를 생성합니다.

        Args:
            workflow_id: 같은 session에 생성할 workflow identity입니다.
        """
        self.handle.apply(
            WorkflowStarted(
                session_id=self.handle.session_id,
                workflow_id=workflow_id,
                owner_actor_id=self.handle.actor_id,
                kind="process-ticket",
                goal="평가 대상 작업을 완료한다",
                payload={
                    "phase_run": {"phase": 3, "status": "active"},
                    "skill_state": {"ticket": 42},
                },
                idempotency_key=f"evaluation-fixture:{workflow_id}",
            )
        )

    def _run(
        self,
        arguments: tuple[str, ...],
        *,
        application: EvaluationLoopApplication | None = None,
        environment: Mapping[str, object] | None = None,
    ) -> int:
        """Evaluation CLI를 fixture runtime과 repository에서 실행합니다.

        Args:
            arguments: Path selector가 없는 CLI arguments입니다.
            application: Clock을 주입한 application override입니다.
            environment: Exact session을 바꿀 runtime environment override입니다.

        Returns:
            CLI exit code입니다.
        """
        runner = EvaluationLoopApplication() if application is None else application
        return runner.run(
            arguments,
            self.environment if environment is None else environment,
            self.repository,
            self.stream,
        )

    def _open_arguments(
        self,
        loop_id: str,
        workflow_id: WorkflowId | None = None,
    ) -> tuple[str, ...]:
        """완료 조건 두 개를 포함한 open command를 만듭니다.

        Args:
            loop_id: 새 evaluation loop identity입니다.
            workflow_id: 기본 fixture와 다른 workflow selector입니다.

        Returns:
            Application에 전달할 argument tuple입니다.
        """
        selected = self.workflow_id if workflow_id is None else workflow_id
        return (
            "--workflow-id",
            str(selected),
            "open",
            "--loop-id",
            loop_id,
            "--goal",
            "발행 가능 판정",
            "--acceptance",
            "추측 없이 착수 가능",
            "--acceptance",
            "실패 test 선행 가능",
        )

    def _mapping(self, value: object, label: str) -> Mapping[str, object]:
        """Persisted JSON value가 string-keyed object인지 검증합니다.

        Args:
            value: 검증할 persisted value입니다.
            label: Assertion failure에 표시할 경로입니다.

        Returns:
            검증된 mapping입니다.
        """
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            self.fail(f"{label} must be a string-keyed object")
        return value

    def open_loop(self) -> EvaluationLoop:
        """완료 조건과 deterministic timestamp를 갖춘 루프를 엽니다.

        Returns:
            새 evaluation loop aggregate입니다.
        """
        return EvaluationLoop.open(
            "backlog-gate",
            "백로그가 발행 가능한지 판정한다",
            ("추측 없이 착수 가능", "실패 test를 먼저 쓸 수 있음"),
            self.OPENED_AT,
        )

    def test_open_requires_acceptance_written_first(self) -> None:
        """완료 조건 없이 루프를 열 수 없습니다."""
        with self.assertRaises(EvaluationLoopError):
            EvaluationLoop.open("gate", "목표", ("하나뿐",), self.OPENED_AT)

    def test_finding_requires_root_cause_and_verdict_reason(self) -> None:
        """지적에는 근본 원인 분류와 판정 사유가 있어야 합니다."""
        with self.assertRaises(EvaluationLoopError):
            Finding.parse("F1:stale-reference:accept")
        with self.assertRaises(EvaluationLoopError):
            Finding.parse("F1:stale-reference:accept:   ")
        with self.assertRaises(EvaluationLoopError):
            Finding.parse("F1:stale-reference:maybe:사유")

    def test_recurring_root_cause_warns_without_blocking_round(self) -> None:
        """같은 근본 원인이 반복되면 경고하되 다음 회차를 막지는 않습니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:stale-reference:accept:번호가 어긋남"),),
            self.ROUND_ONE_AT,
        )
        loop.record_round(
            2,
            (Finding.parse("F2:stale-reference:accept:또 어긋남"),),
            self.ROUND_TWO_AT,
        )

        warnings = loop.record_round(
            3,
            (Finding.parse("F3:other:accept:다른 문제"),),
            self.ROUND_THREE_AT,
        )

        self.assertEqual(3, len(loop.rounds))
        self.assertTrue(any("stale-reference" in warning for warning in warnings))

    def test_recurring_root_cause_can_close_the_finding_ledger_without_goal_claim(self) -> None:
        """반복 판정 뒤에도 ledger는 닫지만 사용자 goal 수렴을 주장하지 않습니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:stale-reference:accept:번호가 어긋남"),),
            self.ROUND_ONE_AT,
        )
        loop.record_round(
            2,
            (Finding.parse("F2:stale-reference:accept:또 어긋남"),),
            self.ROUND_TWO_AT,
        )
        loop.record_round(
            3,
            (Finding.parse("F3:stale-reference:reject:더 볼 것 없음"),),
            self.ROUND_THREE_AT,
        )

        warnings = loop.close("findings-clear", "게이트로 원인을 없앴다", self.CLOSED_AT)

        self.assertEqual(loop.payload["outcome"], "findings-clear")
        self.assertTrue(any("stale-reference" in warning for warning in warnings))

    def test_receipt_records_recurring_root_causes(self) -> None:
        """반복된 근본 원인은 receipt에 남아 판단이 기록으로 보입니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:stale-reference:accept:번호가 어긋남"),),
            self.ROUND_ONE_AT,
        )
        loop.record_round(
            2,
            (Finding.parse("F2:stale-reference:reject:같은 원인 재확인"),),
            self.ROUND_TWO_AT,
        )
        loop.close("approach-change-required", "참조 방식을 바꾼다", self.CLOSED_AT)

        self.assertIn("recurring=", loop.receipt())

    def test_many_rounds_can_close_as_findings_clear(self) -> None:
        """회차 수가 아니라 마지막 회차의 accepted finding으로 ledger 종료를 판정합니다."""
        loop = self.open_loop()
        for number in range(1, 8):
            loop.record_round(
                number,
                (Finding.parse(f"F{number}:a-cause:accept:{number}번째 지적"),),
                f"2026-08-04T01:{number:02d}:00+00:00",
            )
        loop.record_round(
            8,
            (Finding.parse("F8:b-cause:reject:범위 밖"),),
            "2026-08-04T01:08:00+00:00",
        )

        loop.close("findings-clear", "성질 검사가 모두 비었다", self.CLOSED_AT)

        self.assertEqual(loop.payload["outcome"], "findings-clear")
        self.assertEqual(8, len(loop.rounds))

    def test_findings_clear_requires_no_accepted_finding_in_last_round(self) -> None:
        """마지막 회차에 채택된 지적이 남으면 finding ledger를 닫지 않습니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:a-cause:accept:고침"),),
            self.ROUND_ONE_AT,
        )
        with self.assertRaises(EvaluationLoopError):
            loop.close("findings-clear", "끝", self.CLOSED_AT)
        loop.record_round(
            2,
            (Finding.parse("F2:b-cause:reject:발행을 막지 않음"),),
            self.ROUND_TWO_AT,
        )
        loop.close("findings-clear", "남은 지적은 모두 반려", self.CLOSED_AT)
        self.assertEqual(loop.payload["outcome"], "findings-clear")

    def test_finding_ledger_rejects_goal_convergence_claim(self) -> None:
        """Finding 부재만으로 adaptive goal completion을 가장하는 legacy outcome을 거부합니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:a-cause:reject:현재 목표를 깨지 않음"),),
            self.ROUND_ONE_AT,
        )

        with self.assertRaises(EvaluationLoopError):
            loop.close("converged", "사용자 목표까지 달성했다고 주장", self.CLOSED_AT)

    def test_receipt_requires_closed_loop(self) -> None:
        """닫히지 않은 루프는 receipt를 낼 수 없습니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:a-cause:reject:근거 없음"),),
            self.ROUND_ONE_AT,
        )
        with self.assertRaises(EvaluationLoopError):
            loop.receipt()
        loop.close("findings-clear", "지적을 모두 반려", self.CLOSED_AT)
        self.assertIn("outcome=findings-clear", loop.receipt())

    def test_cli_rejects_manual_state_selector_and_requires_workflow_id(self) -> None:
        """CLI는 state path를 받지 않고 exact workflow identity를 필수로 요구합니다."""
        cases = (
            (
                "--workflow-id",
                str(self.workflow_id),
                "--state",
                "/tmp/legacy.json",
                "receipt",
                "--loop-id",
                "backlog-gate",
            ),
            ("receipt", "--loop-id", "backlog-gate"),
        )

        for arguments in cases:
            with (
                self.subTest(arguments=arguments),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                EvaluationLoopApplication().run(
                    arguments,
                    self.environment,
                    self.repository,
                    self.stream,
                )

        self.assertFalse(hasattr(EvaluationLoop, "load"))
        self.assertFalse(hasattr(EvaluationLoop, "save"))

    def test_cli_preserves_multiple_loops_and_sibling_state_in_exact_workflow(self) -> None:
        """한 workflow의 evaluation_loops는 여러 loop와 sibling skill state를 보존합니다."""
        clock = SequenceEvaluationClock((
            self.OPENED_AT,
            "2026-08-04T01:00:30+00:00",
            self.ROUND_ONE_AT,
            self.CLOSED_AT,
            "2026-08-04T01:05:00+00:00",
        ))
        application = EvaluationLoopApplication(clock)

        opened_a = self._run(
            self._open_arguments("backlog-gate"),
            application=application,
        )
        opened_b = self._run(
            self._open_arguments("parallel-gate"),
            application=application,
        )
        rounded = self._run(
            (
                "--workflow-id",
                str(self.workflow_id),
                "round",
                "--loop-id",
                "backlog-gate",
                "--number",
                "1",
                "--finding",
                "F1:scope-creep:reject:현재 목표를 깨지 않음",
            ),
            application=application,
        )
        closed = self._run(
            (
                "--workflow-id",
                str(self.workflow_id),
                "close",
                "--loop-id",
                "backlog-gate",
                "--outcome",
                "findings-clear",
                "--summary",
                "반려",
            ),
            application=application,
        )
        receipt = self._run(
            (
                "--workflow-id",
                str(self.workflow_id),
                "receipt",
                "--loop-id",
                "backlog-gate",
            ),
            application=application,
        )
        duplicate_close = self._run(
            (
                "--workflow-id",
                str(self.workflow_id),
                "close",
                "--loop-id",
                "backlog-gate",
                "--outcome",
                "findings-clear",
                "--summary",
                "또 닫기",
            ),
            application=application,
        )

        self.assertEqual(
            (0, 0, 0, 0, 0, 1),
            (
                opened_a,
                opened_b,
                rounded,
                closed,
                receipt,
                duplicate_close,
            ),
        )
        snapshot = SkillStateStore(self.handle, self.workflow_id).read()
        self.assertEqual(42, snapshot.skill_state["ticket"])
        loops = self._mapping(snapshot.skill_state["evaluation_loops"], "evaluation loops")
        self.assertEqual({"backlog-gate", "parallel-gate"}, set(loops))
        backlog = self._mapping(loops["backlog-gate"], "backlog gate")
        parallel = self._mapping(loops["parallel-gate"], "parallel gate")
        self.assertEqual(self.OPENED_AT, backlog["opened_at"])
        self.assertEqual(self.CLOSED_AT, backlog["closed_at"])
        self.assertEqual("2026-08-04T01:00:30+00:00", parallel["opened_at"])
        self.assertIn("evaluation_loop_receipt:", self.stream.getvalue())

    def test_cli_does_not_fallback_across_workflow_or_session(self) -> None:
        """같은 loop id라도 다른 workflow나 runtime session에서 암묵적으로 찾지 않습니다."""
        second_workflow = WorkflowId("workflow-b")
        self._start_workflow(second_workflow)
        opened = self._run(self._open_arguments("backlog-gate"))

        wrong_workflow = self._run((
            "--workflow-id",
            str(second_workflow),
            "receipt",
            "--loop-id",
            "backlog-gate",
        ))
        wrong_session = self._run(
            (
                "--workflow-id",
                str(self.workflow_id),
                "receipt",
                "--loop-id",
                "backlog-gate",
            ),
            environment={"CODEX_THREAD_ID": "other-session"},
        )

        self.assertEqual(0, opened)
        self.assertEqual(1, wrong_workflow)
        self.assertEqual(1, wrong_session)
        self.assertFalse(self.locator.locate(SessionId("other-session")).process_state.exists())

    def test_optimistic_retry_reuses_one_timestamp_in_pure_transform(self) -> None:
        """Conflict 재시도는 transform 밖에서 한 번 얻은 timestamp를 그대로 재사용합니다."""
        clock = SequenceEvaluationClock((
            self.OPENED_AT,
            "2026-08-04T09:59:59+00:00",
        ))
        application = EvaluationLoopApplication(clock)
        conflict = ConflictOnceCommit(self, SkillStateStore._commit)

        with patch.object(
            SkillStateStore,
            "_commit",
            autospec=True,
            side_effect=conflict,
        ) as commit:
            result = self._run(
                self._open_arguments("retry-gate"),
                application=application,
            )

        self.assertEqual(0, result)
        self.assertEqual(2, commit.call_count)
        self.assertEqual(2, conflict.attempts)
        self.assertEqual(1, clock.calls)
        self.assertEqual(
            (self.OPENED_AT, self.OPENED_AT),
            conflict.observed_timestamps,
        )

    def test_state_records_acceptance_and_verdicts_without_file_round_trip(self) -> None:
        """Aggregate payload에 완료 조건과 판정이 남고 Path persistence API는 없습니다."""
        loop = self.open_loop()
        loop.record_round(
            1,
            (Finding.parse("F1:a-cause:defer:후속 티켓으로 분리"),),
            self.ROUND_ONE_AT,
        )
        loop.close("findings-clear", "채택 없음", self.CLOSED_AT)

        payload = loop.to_payload()
        rounds = payload["rounds"]
        if not isinstance(rounds, list):
            self.fail("rounds must be a list")
        first_round = self._mapping(rounds[0], "first round")
        findings = first_round["findings"]
        if not isinstance(findings, list):
            self.fail("findings must be a list")
        acceptance = payload["acceptance"]
        if not isinstance(acceptance, list):
            self.fail("acceptance must be a list")
        first_finding = self._mapping(findings[0], "first finding")
        self.assertEqual(2, len(acceptance))
        self.assertEqual("defer", first_finding["verdict"])


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
