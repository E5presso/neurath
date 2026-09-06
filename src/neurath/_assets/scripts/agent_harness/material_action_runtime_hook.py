"""PreTool start CAS와 PostTool readback을 material-action batch에 결속합니다."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from scripts.agent_harness.bounded_process import run_bounded_process
from scripts.agent_harness.harness_maintenance import HarnessMaintenanceAuthority
from scripts.agent_harness.material_action import (
    MaterialActionBatch,
    MaterialActionKind,
    MaterialActionStatus,
    ObservableObservation,
    ToolInvocation,
    ToolReceipt,
    ToolReceiptOutcome,
    material_observable_digest,
)
from scripts.agent_harness.session_kernel import (
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
)
from scripts.agent_harness.skill_state_contract import SessionKernelError
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityConflict,
    RuntimeIdentityUnavailable,
    StateHandle,
    StateHandleAuthorityError,
)
from scripts.agent_harness.tool_action_parser import (
    ToolActionEffect,
    ToolActionParser,
    ToolActionPayloadError,
    ToolActionRequest,
    ToolActionResult,
)


class MaterialActionHookDecisionCode(StrEnum):
    """Runtime adapter와 test가 공유하는 material-action 판정 원인입니다."""

    HARNESS_MAINTENANCE = "harness-maintenance"
    """Active repair lease가 exact actor와 exact harness target을 승인했습니다."""

    HOST_MANAGED = "host-managed"
    """Repository structured-edit harness 밖의 tool은 host authority에 맡깁니다."""

    STARTED = "started"
    """PreTool request를 current batch에 CAS commit한 뒤 allow했습니다."""

    OBSERVED = "observed"
    """PostTool result와 authoritative local readback을 matching invocation에 기록했습니다."""

    IDEMPOTENT = "idempotent"
    """이미 기록된 exact PreTool 또는 PostTool delivery의 안전한 재시도입니다."""

    ACTION_REQUIRED = "action-required"
    """Current actor turn에 open prepared batch가 없습니다."""

    ACTION_CONFLICT = "action-conflict"
    """Batch revision, lifecycle 또는 one-in-flight invariant가 현재 request와 충돌합니다."""

    TARGET_DENIED = "target-denied"
    """Target이 dynamic, unknown, external 또는 prepared boundary 밖입니다."""

    RECEIPT_MISMATCH = "receipt-mismatch"
    """PostTool tool-use identity, request digest 또는 result가 started invocation과 다릅니다."""

    IDENTITY_UNAVAILABLE = "identity-unavailable"
    """Exact runtime session과 actor identity를 StateHandle에 결속하지 못했습니다."""

    INVALID_INPUT = "invalid-input"
    """Hook event 또는 vendor payload를 deterministic request로 해석하지 못했습니다."""


class MaterialActionHookDecision:
    """Material-action allow 또는 deny와 stable 원인을 묶는 immutable value입니다."""

    __slots__ = ("allowed", "code", "reason")

    def __init__(
        self,
        *,
        allowed: bool,
        code: MaterialActionHookDecisionCode,
        reason: str,
    ) -> None:
        """한 hook 판정을 생성 뒤 변경할 수 없게 고정합니다.

        Args:
            allowed: Runtime tool lifecycle을 계속할 수 있으면 참입니다.
            code: Caller와 test가 분기할 machine-readable 원인입니다.
            reason: Agent가 필요한 복구 행동을 이해할 수 있는 설명입니다.
        """
        object.__setattr__(self, "allowed", allowed)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "reason", reason)

    allowed: bool
    """Tool lifecycle을 계속할 수 있는 판정이면 참입니다."""

    code: MaterialActionHookDecisionCode
    """Runtime adapter가 사용하는 stable decision identity입니다."""

    reason: str
    """Deny 원인 또는 성공한 state transition의 짧은 설명입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 decision mutation을 거부합니다.

        Args:
            name: 변경하려 한 decision attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable decision 생성 뒤에는 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class MaterialActionHookResult:
    """Vendor process exit와 내부 typed decision을 함께 반환합니다."""

    __slots__ = ("decision", "exit_code", "stderr")

    def __init__(
        self,
        *,
        exit_code: int,
        stderr: str,
        decision: MaterialActionHookDecision,
    ) -> None:
        """Hook protocol output을 immutable result로 고정합니다.

        Args:
            exit_code: Allow이면 0, fail-closed 판정이면 2입니다.
            stderr: Runtime에 전달할 deny JSON이며 allow에서는 비어 있습니다.
            decision: Application test와 process adapter가 공유하는 typed 판정입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "stderr", stderr)
        object.__setattr__(self, "decision", decision)

    exit_code: int
    """Allow이면 0, invalid 또는 deny이면 2입니다."""

    stderr: str
    """Runtime이 사용자에게 노출할 structured deny 설명입니다."""

    decision: MaterialActionHookDecision
    """State transition 결과의 stable application 판정입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 hook result mutation을 거부합니다.

        Args:
            name: 변경하려 한 result attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable result 생성 뒤에는 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class BoundedValidatorProcess:
    """PostTool validator와 그 descendant를 하나의 bounded process group으로 실행합니다."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        """Positive timeout을 process-group lifecycle에 고정합니다.

        Args:
            timeout_seconds: Validator group 전체가 끝나야 하는 wall-clock 초입니다.

        Raises:
            ValueError: Timeout이 양수가 아니면 발생합니다.
        """
        if timeout_seconds <= 0:
            raise ValueError("validator timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    def run(self, executable: Path, raw_input: bytes) -> tuple[int, bytes]:
        """Validator를 새 process group에서 실행하고 timeout이면 group 전체를 종료합니다.

        Args:
            executable: Exact Python edit validator executable입니다.
            raw_input: Vendor PostTool JSON 원문입니다.

        Returns:
            Exit status와 bounded validator output bytes입니다.

        Raises:
            OSError: Validator가 regular executable file이 아니거나 시작할 수 없으면 발생합니다.
        """
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise OSError("python edit validator must be an executable regular file")
        result = run_bounded_process(
            (str(executable),),
            cwd=executable.parent,
            input_bytes=raw_input,
            merge_stderr=True,
            timeout_seconds=self._timeout_seconds,
        )
        if result.timed_out:
            message = b"python edit validator timed out\n"
            return result.returncode, result.stdout + message
        return result.returncode, result.stdout


class MaterialActionRuntimeHookApplication:
    """Runtime tool lifecycle을 current actor의 prepared material intent에 집행합니다."""

    def __init__(self, hook_runtime: SessionRuntime | None = None) -> None:
        """Payload parser와 optional runtime-specific hook authority를 준비합니다.

        Args:
            hook_runtime: Vendor wrapper가 명시한 exact hook runtime입니다.
        """
        self._parser = ToolActionParser()
        self._runtime_identities = RuntimeEnvironmentResolver()
        self._hook_runtime = hook_runtime

    def run(
        self,
        event: str,
        raw_input: str,
        environment: Mapping[str, object],
        cwd: Path,
    ) -> MaterialActionHookResult:
        """PreTool start, PostTool 또는 permission-denied receipt를 처리합니다.

        Args:
            event: ``pre``, ``post`` 또는 ``permission-denied`` lifecycle 이름입니다.
            raw_input: Vendor runtime이 stdin으로 전달한 hook JSON입니다.
            environment: Runtime-owned session과 actor identity environment입니다.
            cwd: Hook이 실행되는 repository directory입니다.

        Returns:
            State transition을 포함한 deterministic allow 또는 deny 결과입니다.
        """
        try:
            if event == "pre":
                request = self._parser.parse_request(raw_input, cwd)
                parsed_result = None
            elif event == "post":
                parsed_result = self._parser.parse_result(raw_input, cwd)
                if environment.get("NEURATH_POST_VALIDATOR_FAILED") == "1":
                    parsed_result = ToolActionResult(
                        request=parsed_result.request,
                        succeeded=False,
                        output_digest=parsed_result.output_digest,
                        duration_milliseconds=parsed_result.duration_milliseconds,
                    )
                request = parsed_result.request
            elif event == "permission-denied":
                parsed_result = self._parser.parse_result(raw_input, cwd)
                request = parsed_result.request
            else:
                return self._deny(
                    event,
                    MaterialActionHookDecisionCode.INVALID_INPUT,
                    "material-action hook event must be pre, post, or permission-denied",
                )
        except ToolActionPayloadError as error:
            return self._deny(
                event,
                MaterialActionHookDecisionCode.INVALID_INPUT,
                str(error),
            )

        if request.effect is ToolActionEffect.HOST_MANAGED:
            return self._allow(
                MaterialActionHookDecisionCode.HOST_MANAGED,
                "non-edit tool authority belongs to the host runtime",
            )
        if HarnessMaintenanceAuthority.authorizes(
            cwd=cwd,
            environment=environment,
            hook_runtime=self._hook_runtime,
            runtime_agent_id=request.runtime_agent_id,
            runtime_session_id=request.runtime_session_id,
            tool_name=request.name,
            targets=request.targets,
        ):
            return self._allow(
                MaterialActionHookDecisionCode.HARNESS_MAINTENANCE,
                "active exact-target harness maintenance lease bypasses material batching",
            )
        handle = self._attach(environment, cwd, request)
        if handle is None:
            return self._deny(
                event,
                MaterialActionHookDecisionCode.IDENTITY_UNAVAILABLE,
                "material action requires exact runtime session and actor identity",
            )
        if event == "pre":
            return self._start(request, handle)
        if parsed_result is None:
            return self._deny(
                event,
                MaterialActionHookDecisionCode.INVALID_INPUT,
                "PostTool result was not parsed",
            )
        return self._observe(
            parsed_result,
            handle,
            runtime_event=event,
            forced_outcome=(ToolReceiptOutcome.UNKNOWN if event == "permission-denied" else None),
        )

    def _attach(
        self,
        environment: Mapping[str, object],
        cwd: Path,
        request: ToolActionRequest,
    ) -> StateHandle | None:
        try:
            locator = SessionLocator.from_worktree(cwd)
            binding = self._runtime_identities.resolve_hook_actor(
                environment,
                request.runtime_agent_id,
                request.runtime_session_id,
                hook_runtime=self._hook_runtime,
            )
            return StateHandle.attach(locator, binding)
        except (
            OSError,
            subprocess.CalledProcessError,
            RuntimeIdentityUnavailable,
            RuntimeIdentityConflict,
            SessionNotFound,
            StateHandleAuthorityError,
        ):
            return None

    def _start(
        self,
        request: ToolActionRequest,
        handle: StateHandle,
    ) -> MaterialActionHookResult:
        if request.invocation_id is None:
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.INVALID_INPUT,
                "material mutation requires runtime tool-use identity",
            )
        try:
            state = handle.inspect()
        except SessionKernelError, StateHandleAuthorityError:
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.IDENTITY_UNAVAILABLE,
                "material mutation requires current exact-session state",
            )
        batch = state.material_actions.get(handle.actor_id)
        if batch is None or batch.status is not MaterialActionStatus.OPEN:
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.ACTION_REQUIRED,
                "current actor turn has no open prepared material-action batch",
            )
        target_denial = self._target_denial(batch, request)
        if target_denial is not None:
            return target_denial
        turn = state.foreground_turns.get(handle.actor_id)
        if turn is None or (
            batch.turn_generation,
            batch.turn_revision,
        ) != (turn.generation, turn.revision):
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.ACTION_CONFLICT,
                "prepared batch is stale for the current foreground turn",
            )
        try:
            precondition_matches = self._precondition_matches(batch, request)
        except OSError:
            precondition_matches = False
        if not precondition_matches:
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.ACTION_CONFLICT,
                "current target readback differs from the latest persisted digest",
            )
        event = MaterialActionToolStarted(
            session_id=handle.session_id,
            actor_id=handle.actor_id,
            batch_id=batch.batch_id,
            expected_batch_revision=batch.revision,
            invocation_id=request.invocation_id,
            tool_name=request.name,
            request_digest=request.request_digest,
            targets=request.targets,
            idempotency_key=(
                f"material-action:start:{batch.batch_id}:{request.invocation_id}:"
                f"{request.request_digest}"
            ),
        )
        try:
            updated = handle.apply(event, expected_revision=state.revision)
        except SessionKernelError, StateHandleAuthorityError:
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.ACTION_CONFLICT,
                "material-action start lost its exact batch or state revision CAS",
            )
        code = (
            MaterialActionHookDecisionCode.IDEMPOTENT
            if updated.revision == state.revision
            else MaterialActionHookDecisionCode.STARTED
        )
        return self._allow(
            code,
            "tool request is recorded in the current prepared batch before allow",
        )

    def _target_denial(
        self,
        batch: MaterialActionBatch,
        request: ToolActionRequest,
    ) -> MaterialActionHookResult | None:
        if batch.kind is MaterialActionKind.EXTERNAL_MUTATION:
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.TARGET_DENIED,
                "external mutation has no registered typed runtime authority",
            )
        if not request.targets or not set(request.targets).issubset(batch.targets):
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.TARGET_DENIED,
                "tool targets are outside the prepared exact boundary",
            )
        expectation_ids = {item.observable_id for item in batch.expectations}
        if not set(request.targets).issubset(expectation_ids):
            return self._deny(
                "pre",
                MaterialActionHookDecisionCode.TARGET_DENIED,
                "every affected local target requires a prepared observable baseline",
            )
        return None

    def _precondition_matches(
        self,
        batch: MaterialActionBatch,
        request: ToolActionRequest,
    ) -> bool:
        """Affected target의 current digest가 latest persisted observation과 같은지 확인합니다.

        Args:
            batch: Original baseline과 sequential receipt를 소유한 current batch입니다.
            request: 시작하려는 exact mutation target 목록입니다.

        Returns:
            모든 affected observable의 authoritative readback이 latest known digest와 같으면 참입니다.

        Raises:
            OSError: Local observable을 regular file 또는 부재로 판정할 수 없으면 발생합니다.
        """
        known = {
            expectation.observable_id: expectation.baseline_digest
            for expectation in batch.expectations
        }
        for invocation in batch.invocations:
            if invocation.receipt is not None:
                known.update({
                    observation.observable_id: observation.current_digest
                    for observation in invocation.receipt.observations
                })
        return all(self._read_digest(Path(target)) == known[target] for target in request.targets)

    def _observe(
        self,
        result: ToolActionResult,
        handle: StateHandle,
        *,
        runtime_event: str = "post",
        forced_outcome: ToolReceiptOutcome | None = None,
    ) -> MaterialActionHookResult:
        request = result.request
        if request.invocation_id is None:
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.INVALID_INPUT,
                "PostTool material receipt requires runtime tool-use identity",
            )
        try:
            state = handle.inspect()
        except SessionKernelError, StateHandleAuthorityError:
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.IDENTITY_UNAVAILABLE,
                "PostTool receipt requires current exact-session state",
            )
        batch = state.material_actions.get(handle.actor_id)
        if batch is None:
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.ACTION_REQUIRED,
                "PostTool receipt has no prepared material-action batch",
            )
        invocation = self._invocation(batch, request.invocation_id)
        if invocation is None or not self._request_matches(invocation, request):
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.RECEIPT_MISMATCH,
                "PostTool request or tool-use identity does not match a started invocation",
            )
        outcome = forced_outcome or (
            ToolReceiptOutcome.SUCCEEDED if result.succeeded else ToolReceiptOutcome.FAILED
        )
        if invocation.receipt is not None:
            if (
                invocation.receipt.request_digest == request.request_digest
                and invocation.receipt.output_digest == result.output_digest
                and invocation.receipt.outcome is outcome
            ):
                return self._allow(
                    MaterialActionHookDecisionCode.IDEMPOTENT,
                    "exact PostTool delivery is already recorded",
                )
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.RECEIPT_MISMATCH,
                "tool-use identity already has a different PostTool receipt",
            )
        if batch.in_flight is not invocation:
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.RECEIPT_MISMATCH,
                "only the current in-flight invocation accepts a PostTool receipt",
            )
        try:
            observations = self._read_observations(batch)
        except OSError:
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.TARGET_DENIED,
                "prepared local observable could not be read authoritatively",
            )
        receipt = ToolReceipt(
            receipt_id=f"{runtime_event}:{request.invocation_id}",
            request_digest=request.request_digest,
            outcome=outcome,
            output_digest=result.output_digest,
            observations=observations,
            duration_milliseconds=result.duration_milliseconds,
        )
        kernel_event = MaterialActionToolObserved(
            session_id=handle.session_id,
            actor_id=handle.actor_id,
            batch_id=batch.batch_id,
            expected_batch_revision=batch.revision,
            invocation_id=request.invocation_id,
            receipt=receipt,
            idempotency_key=(
                f"material-action:observe:{batch.batch_id}:{request.invocation_id}:"
                f"{result.output_digest}"
            ),
        )
        try:
            handle.apply(kernel_event, expected_revision=state.revision)
        except SessionKernelError, StateHandleAuthorityError:
            return self._deny(
                runtime_event,
                MaterialActionHookDecisionCode.ACTION_CONFLICT,
                "PostTool receipt lost its exact batch or state revision CAS",
            )
        return self._allow(
            MaterialActionHookDecisionCode.OBSERVED,
            "matching PostTool result and current local readback are recorded",
        )

    def _invocation(
        self,
        batch: MaterialActionBatch,
        invocation_id: str,
    ) -> ToolInvocation | None:
        return next(
            (
                invocation
                for invocation in batch.invocations
                if invocation.invocation_id == invocation_id
            ),
            None,
        )

    def _request_matches(
        self,
        invocation: ToolInvocation,
        request: ToolActionRequest,
    ) -> bool:
        return (
            invocation.tool_name,
            invocation.request_digest,
            invocation.targets,
        ) == (
            request.name,
            request.request_digest,
            request.targets,
        )

    def _read_observations(
        self,
        batch: MaterialActionBatch,
    ) -> tuple[ObservableObservation, ...]:
        observations: list[ObservableObservation] = []
        for expectation in batch.expectations:
            if expectation.observable_id not in batch.targets:
                raise OSError("observable is outside prepared local targets")
            target = Path(expectation.observable_id)
            observations.append(
                ObservableObservation(
                    observable_id=expectation.observable_id,
                    current_digest=self._read_digest(target),
                )
            )
        return tuple(observations)

    def _read_digest(self, target: Path) -> str | None:
        """Canonical local observable의 file digest 또는 authoritative 부재를 반환합니다.

        Args:
            target: Prepared batch가 소유한 absolute local observable path입니다.

        Returns:
            Regular file의 streamed SHA-256 또는 path가 없으면 ``None``입니다.

        Raises:
            OSError: 존재하는 target이 regular file이 아니거나 읽을 수 없으면 발생합니다.
        """
        return material_observable_digest(target)

    def _allow(
        self,
        code: MaterialActionHookDecisionCode,
        reason: str,
    ) -> MaterialActionHookResult:
        decision = MaterialActionHookDecision(allowed=True, code=code, reason=reason)
        return MaterialActionHookResult(exit_code=0, stderr="", decision=decision)

    def _deny(
        self,
        event: str,
        code: MaterialActionHookDecisionCode,
        reason: str,
    ) -> MaterialActionHookResult:
        decision = MaterialActionHookDecision(allowed=False, code=code, reason=reason)
        hook_event = "PreToolUse" if event == "pre" else "PostToolUse"
        payload = {
            "hookSpecificOutput": {
                "hookEventName": hook_event,
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Neurath material-action gate [{code.value}]: {reason}"
                ),
            }
        }
        stderr = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        return MaterialActionHookResult(exit_code=2, stderr=stderr, decision=decision)


class MaterialActionRuntimeHookCommand:
    """Process stdin, environment와 cwd를 runtime hook application에 전달합니다."""

    def run(self, arguments: Sequence[str]) -> int:
        """Exact event argument 하나를 받아 hook exit code를 반환합니다.

        Args:
            arguments: ``pre``, ``post`` 또는 ``permission-denied`` command입니다.

        Returns:
            Invalid command이면 2, 아니면 application 판정 exit code입니다.
        """
        parsed = tuple(arguments)
        if len(parsed) == 3 and parsed[0] == "post-composite":
            try:
                runtime = SessionRuntime(parsed[1])
            except ValueError:
                return 2
            return self._run_composite_post(Path(parsed[2]), runtime)
        if len(parsed) != 2 or parsed[0] not in {
            "pre",
            "post",
            "permission-denied",
        }:
            return 2
        try:
            runtime = SessionRuntime(parsed[1])
        except ValueError:
            return 2
        result = MaterialActionRuntimeHookApplication(runtime).run(
            parsed[0],
            sys.stdin.read(),
            os.environ,
            Path.cwd(),
        )
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.exit_code

    def _run_composite_post(self, validator: Path, runtime: SessionRuntime) -> int:
        """Validator group 종료 뒤 같은 process에서 material readback을 기록합니다.

        Args:
            validator: Exact Python edit validator executable입니다.

        Returns:
            Validator, original tool 또는 material receipt 중 하나라도 실패하면 2입니다.
        """
        raw_input = sys.stdin.buffer.read()
        try:
            validator_status, validator_output = BoundedValidatorProcess().run(
                validator,
                raw_input,
            )
        except OSError as error:
            validator_status = 2
            validator_output = f"{error}\n".encode()
        validator_failed = validator_status != 0 or bool(validator_output)
        environment = dict(os.environ)
        environment["NEURATH_POST_VALIDATOR_FAILED"] = "1" if validator_failed else "0"
        decoded = raw_input.decode("utf-8", errors="strict")
        result = MaterialActionRuntimeHookApplication(runtime).run(
            "post",
            decoded,
            environment,
            Path.cwd(),
        )
        try:
            tool_failed = not ToolActionParser().parse_result(decoded, Path.cwd()).succeeded
        except ToolActionPayloadError, UnicodeError:
            tool_failed = True
        if validator_output:
            sys.stdout.buffer.write(validator_output)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return 2 if result.exit_code != 0 or validator_failed or tool_failed else 0


if __name__ == "__main__":
    raise SystemExit(MaterialActionRuntimeHookCommand().run(sys.argv[1:]))
