"""Material mutation의 PreTool start와 PostTool readback runtime gate를 검증합니다."""

import json
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.material_action import (
    MaterialActionKind,
    ObservableDeltaKind,
    ObservableExpectation,
    ToolInvocationStatus,
    ToolReceiptOutcome,
    canonical_material_target,
    material_observable_digest,
)
from scripts.agent_harness.material_action_runtime_hook import (
    BoundedValidatorProcess,
    MaterialActionHookDecisionCode,
    MaterialActionHookResult,
    MaterialActionRuntimeHookApplication,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    MaterialActionPrepared,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
)


class MaterialActionRuntimeHookApplicationTest(TestCase):
    """Exact actor turn의 prepared batch만 runtime mutation을 시작하고 관찰합니다."""

    def setUp(self) -> None:
        """Git control root, current actor turn과 local observable fixture를 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "repository"
        self.root.mkdir()
        self._git("init", "-q", "-b", "develop")
        self._git(
            "-c",
            "user.name=Neurath Test",
            "-c",
            "user.email=neurath@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        )
        self.source = self.root / "src/example.py"
        self.source.parent.mkdir()
        self.source.write_text("value = 1\n", encoding="utf-8")
        self.locator = SessionLocator.from_worktree(self.root)
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("owner-session")
        self.actor_id = ActorId("codex:session:owner-session")
        self.environment = {"CODEX_THREAD_ID": "owner-session"}
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume:owner-session"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.actor_id,
                idempotency_key="session:start",
            )
        )
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=self.session_id,
                actor_id=self.actor_id,
                idempotency_key="turn:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=self.session_id,
                actor_id=self.actor_id,
                vendor_turn_id="vendor-turn-1",
                idempotency_key="turn:prompt",
            )
        )
        self.application = MaterialActionRuntimeHookApplication()

    def _git(self, *arguments: str) -> None:
        """Fixture repository를 host Git 설정과 격리해 초기화합니다."""
        subprocess.run(
            ("git", "-C", str(self.root), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "1",
                "HOME": str(self.root.parent),
            },
        )

    def _digest(self, path: Path) -> str:
        """Observable fixture의 현재 mode+bytes SHA-256을 반환합니다."""
        digest = material_observable_digest(path)
        assert digest is not None
        return digest

    def _prepare(self, *, target: Path | None = None) -> None:
        """Current foreground turn에 exact local mutation batch를 준비합니다."""
        observable = self.source if target is None else target
        canonical = canonical_material_target(observable)
        baseline = self._digest(canonical) if canonical.exists() or canonical.is_symlink() else None
        state = self.kernel.inspect(self.session_id)
        turn = state.foreground_turns[self.actor_id]
        self.kernel.apply(
            MaterialActionPrepared(
                session_id=self.session_id,
                actor_id=self.actor_id,
                batch_id="batch-1",
                sequence=1,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=(str(canonical),),
                expectations=(
                    ObservableExpectation(
                        observable_id=str(canonical),
                        baseline_digest=baseline,
                        expected_delta=ObservableDeltaKind.CHANGED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=None,
                idempotency_key="action:prepare:batch-1",
            )
        )

    def _payload(
        self,
        invocation_id: str,
        *,
        target: Path | None = None,
        response: object | None = None,
    ) -> str:
        """PreTool과 PostTool이 공유하는 exact Edit request payload를 만듭니다."""
        path = self.source if target is None else target
        payload: dict[str, object] = {
            "tool_name": "Edit",
            "tool_use_id": invocation_id,
            "cwd": str(self.root),
            "tool_input": {
                "file_path": str(path),
                "old_string": "value = 1",
                "new_string": "value = 2",
            },
        }
        if response is not None:
            payload["tool_response"] = response
        return json.dumps(payload)

    def _run(self, event: str, payload: str) -> MaterialActionHookResult:
        """Runtime event를 exact Codex identity와 repository root에서 실행합니다."""
        return self.application.run(event, payload, self.environment, self.root)

    def test_host_managed_fast_path_does_not_require_session_identity(self) -> None:
        """Non-edit tool은 material state를 attach하거나 mutate하지 않고 즉시 허용합니다."""
        payload = json.dumps({
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.source)},
        })

        result = self.application.run("pre", payload, {}, self.root)

        self.assertEqual(0, result.exit_code)
        self.assertEqual(MaterialActionHookDecisionCode.HOST_MANAGED, result.decision.code)

    def test_validator_timeout_reaps_the_entire_process_group_before_post_readback(self) -> None:
        """Timed-out validator의 child까지 종료해 formatter가 terminal receipt 뒤에 남지 않습니다."""
        validator = self.root / "validator-with-child.sh"
        child_pid = self.root / "validator-child.pid"
        validator.write_text(
            "#!/bin/sh\n"
            "python3 -c 'import time; time.sleep(30)' &\n"
            f"printf '%s' \"$!\" > {str(child_pid)!r}\n"
            "wait\n",
            encoding="utf-8",
        )
        validator.chmod(0o755)

        status, output = BoundedValidatorProcess(timeout_seconds=1.0).run(
            validator,
            b"{}",
        )
        deadline = time.monotonic() + 1.0
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_pid.exists())
        pid = int(child_pid.read_text(encoding="utf-8"))
        while self._process_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(124, status)
        self.assertIn(b"validator timed out", output)
        self.assertFalse(self._process_exists(pid))

    def _process_exists(self, pid: int) -> bool:
        """Test child PID가 아직 signal을 받을 수 있는지 확인합니다."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def test_mutation_without_current_prepared_batch_is_denied(self) -> None:
        """Worktree owner라도 current actor turn에 prepared material intent가 없으면 mutate하지 못합니다."""
        before = self.kernel.inspect(self.session_id).revision

        result = self._run("pre", self._payload("tool-1"))

        self.assertEqual(2, result.exit_code)
        self.assertEqual(MaterialActionHookDecisionCode.ACTION_REQUIRED, result.decision.code)
        self.assertEqual(before, self.kernel.inspect(self.session_id).revision)

    def test_pre_tool_records_exact_start_cas_before_allow(self) -> None:
        """Exact actor, turn, target와 tool-use request를 CAS commit한 뒤에만 mutation을 허용합니다."""
        self._prepare()

        result = self._run("pre", self._payload("tool-1"))
        state = self.kernel.inspect(self.session_id)
        invocation = state.material_actions[self.actor_id].in_flight

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual(MaterialActionHookDecisionCode.STARTED, result.decision.code)
        self.assertIsNotNone(invocation)
        assert invocation is not None
        self.assertEqual("tool-1", invocation.invocation_id)
        self.assertEqual((str(self.source.resolve()),), invocation.targets)

    def test_pre_tool_denies_unobserved_drift_from_the_latest_known_digest(self) -> None:
        """Prepare 또는 latest PostTool 이후 외부에서 바뀐 file은 다음 mutation 시작 전에 차단합니다."""
        self._prepare()
        self.source.write_text("foreign = True\n", encoding="utf-8")

        result = self._run("pre", self._payload("tool-1"))

        self.assertEqual(2, result.exit_code)
        self.assertEqual(MaterialActionHookDecisionCode.ACTION_CONFLICT, result.decision.code)
        self.assertIsNone(
            self.kernel.inspect(self.session_id).material_actions[self.actor_id].in_flight
        )

    def test_unknown_target_and_second_in_flight_call_fail_closed(self) -> None:
        """Prepared scope 밖 target과 receipt 전 두 번째 invocation은 batch를 넓히지 못합니다."""
        self._prepare()
        foreign = self.root / "src/foreign.py"
        first = self._run("pre", self._payload("tool-1"))
        concurrent = self._run("pre", self._payload("tool-2"))
        outside = self._run("pre", self._payload("tool-3", target=foreign))

        self.assertEqual(0, first.exit_code)
        self.assertEqual(2, concurrent.exit_code)
        self.assertEqual(MaterialActionHookDecisionCode.ACTION_CONFLICT, concurrent.decision.code)
        self.assertEqual(2, outside.exit_code)
        self.assertEqual(MaterialActionHookDecisionCode.TARGET_DENIED, outside.decision.code)

    def test_post_tool_exact_match_records_readback_and_is_idempotent(self) -> None:
        """Matching PostTool만 current file digest를 기록하고 같은 delivery retry는 no-op입니다."""
        self._prepare()
        pre = self._run("pre", self._payload("tool-1"))
        self.source.write_text("value = 2\n", encoding="utf-8")
        post_payload = self._payload(
            "tool-1",
            response={"filePath": str(self.source), "status": "ok"},
        )

        observed = self._run("post", post_payload)
        revision = self.kernel.inspect(self.session_id).revision
        duplicate = self._run("post", post_payload)
        state = self.kernel.inspect(self.session_id)
        invocation = state.material_actions[self.actor_id].invocations[0]

        self.assertEqual(0, pre.exit_code)
        self.assertEqual(0, observed.exit_code, observed.stderr)
        self.assertEqual(MaterialActionHookDecisionCode.OBSERVED, observed.decision.code)
        self.assertEqual(0, duplicate.exit_code, duplicate.stderr)
        self.assertEqual(MaterialActionHookDecisionCode.IDEMPOTENT, duplicate.decision.code)
        self.assertEqual(revision, state.revision)
        self.assertIs(ToolInvocationStatus.OBSERVED, invocation.status)
        assert invocation.receipt is not None
        self.assertEqual(
            self._digest(self.source), invocation.receipt.observations[0].current_digest
        )
        self.assertNotIn("value = 2", json.dumps(state.to_payload()))

    def test_file_mode_change_is_part_of_the_material_observable_digest(self) -> None:
        """Executable bit 변경을 byte-identical no-op으로 축소하지 않습니다."""
        self.source.chmod(0o644)
        self._prepare()
        payload = self._payload("chmod-1")

        started = self._run("pre", payload)
        self.assertEqual(0, started.exit_code, started.stderr)
        self.source.chmod(0o755)
        observed = self._run(
            "post",
            self._payload("chmod-1", response={"status": "ok"}),
        )

        self.assertEqual(0, observed.exit_code, observed.stderr)
        batch = self.kernel.inspect(self.session_id).material_actions[self.actor_id]
        receipt = batch.invocations[0].receipt
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertNotEqual(
            batch.expectations[0].baseline_digest,
            receipt.observations[0].current_digest,
        )

    def test_post_validator_failure_still_closes_in_flight_with_failed_receipt(self) -> None:
        """Python validator failure도 PostTool readback을 생략하지 않고 failed outcome으로 기록합니다."""
        self._prepare()
        self._run("pre", self._payload("tool-1"))
        self.source.write_text("value = 2\n", encoding="utf-8")
        environment = {**self.environment, "NEURATH_POST_VALIDATOR_FAILED": "1"}

        result = self.application.run(
            "post",
            self._payload("tool-1", response={"status": "ok"}),
            environment,
            self.root,
        )
        receipt = (
            self.kernel
            .inspect(self.session_id)
            .material_actions[self.actor_id]
            .invocations[0]
            .receipt
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIs(ToolReceiptOutcome.FAILED, receipt.outcome)
        self.assertIsNone(receipt.duration_milliseconds)

    def test_claude_post_tool_failure_records_failed_receipt_from_top_level_error(self) -> None:
        """Claude failure event의 top-level error도 in-flight를 terminal receipt로 닫습니다."""
        self._prepare()
        self._run("pre", self._payload("tool-1"))
        payload = json.loads(self._payload("tool-1"))
        payload.update({
            "hook_event_name": "PostToolUseFailure",
            "error": "Edit failed before producing a tool response",
            "is_interrupt": False,
            "duration_ms": 12,
        })

        result = self._run("post", json.dumps(payload))
        receipt = (
            self.kernel
            .inspect(self.session_id)
            .material_actions[self.actor_id]
            .invocations[0]
            .receipt
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIs(ToolReceiptOutcome.FAILED, receipt.outcome)
        self.assertEqual(12, receipt.duration_milliseconds)

    def test_claude_permission_denial_records_unknown_receipt_without_claiming_execution(
        self,
    ) -> None:
        """PreTool 뒤 permission 거부는 unchanged readback과 UNKNOWN receipt로 in-flight를 닫습니다."""
        self._prepare()
        self._run("pre", self._payload("tool-1"))
        payload = json.loads(self._payload("tool-1"))
        payload.update({
            "hook_event_name": "PermissionDenied",
            "reason": "Blocked by auto mode classifier",
        })

        result = self._run("permission-denied", json.dumps(payload))
        batch = self.kernel.inspect(self.session_id).material_actions[self.actor_id]
        receipt = batch.invocations[0].receipt

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIs(ToolReceiptOutcome.UNKNOWN, receipt.outcome)
        self.assertIsNone(batch.in_flight)
        self.assertEqual(self._digest(self.source), receipt.observations[0].current_digest)

    def test_post_tool_rejects_mismatched_tool_use_or_request_digest(self) -> None:
        """다른 tool-use identity와 변경된 request는 current in-flight receipt를 소비하지 못합니다."""
        self._prepare()
        self._run("pre", self._payload("tool-1"))
        wrong_id = self._run("post", self._payload("tool-2", response={"status": "ok"}))
        payload = json.loads(self._payload("tool-1", response={"status": "ok"}))
        tool_input = payload["tool_input"]
        assert isinstance(tool_input, dict)
        tool_input["new_string"] = "value = 3"
        wrong_request = self._run("post", json.dumps(payload))

        self.assertEqual(2, wrong_id.exit_code)
        self.assertEqual(MaterialActionHookDecisionCode.RECEIPT_MISMATCH, wrong_id.decision.code)
        self.assertEqual(2, wrong_request.exit_code)
        self.assertEqual(
            MaterialActionHookDecisionCode.RECEIPT_MISMATCH,
            wrong_request.decision.code,
        )

    def test_observed_receipt_allows_the_next_sequential_call(self) -> None:
        """한 invocation의 PostTool receipt 뒤에는 같은 batch에서 다음 exact call을 시작합니다."""
        self._prepare()
        self._run("pre", self._payload("tool-1"))
        self.source.write_text("value = 2\n", encoding="utf-8")
        self._run("post", self._payload("tool-1", response={"status": "ok"}))

        second = self._run("pre", self._payload("tool-2"))
        state = self.kernel.inspect(self.session_id)

        self.assertEqual(0, second.exit_code, second.stderr)
        self.assertEqual(2, len(state.material_actions[self.actor_id].invocations))
        in_flight = state.material_actions[self.actor_id].in_flight
        self.assertIsNotNone(in_flight)
        assert in_flight is not None
        self.assertEqual("tool-2", in_flight.invocation_id)
