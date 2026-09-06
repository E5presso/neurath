"""Vendor hook input을 exact-session lifecycle과 bounded context output으로 연결합니다."""

import hashlib
import json
import shlex
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from scripts.agent_harness.enclave_store import EnclaveStore
from scripts.agent_harness.runtime_adapter import (
    ClaudeCodeRuntimeAdapter,
    CodexRuntimeAdapter,
    LifecycleCause,
    RuntimeAdapter,
    RuntimeAdapterError,
    RuntimeCapability,
    RuntimeEnvelope,
)
from scripts.agent_harness.runtime_assurance import (
    RuntimeAssurance,
    RuntimeAssuranceError,
    RuntimeAssuranceInventory,
)
from scripts.agent_harness.session_kernel import (
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    ActorStatus,
    EffectAcknowledged,
    EffectId,
    EffectKind,
    EffectPrepared,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnStatus,
    OutboxEffect,
    ResumeId,
    SessionCompacted,
    SessionId,
    SessionKernel,
    SessionKernelError,
    SessionLocator,
    SessionNotFound,
    SessionResumed,
    SessionRuntime,
    SessionStarted,
    SessionStatus,
)
from scripts.agent_harness.session_rehydration import (
    ForkLineage,
    LifecycleConflict,
    RehydrationDecision,
    RehydrationDiagnostic,
    RehydrationStatus,
    SessionLifecycle,
    SessionRehydrator,
)
from scripts.agent_harness.session_retention import SessionRetentionManager
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle

DEFAULT_SESSION_RETENTION_SECONDS = 86_400.0
"""Terminal process state를 exact GC 전에 보존하는 bounded diagnostic window입니다."""


class RuntimeHookDiagnostic(StrEnum):
    """Runtime hook boundary가 요청을 거부한 machine-readable 원인입니다."""

    INVALID_INPUT = "invalid-input"
    """Stdin JSON이 object가 아니거나 JSON 형식 자체가 잘못됐습니다."""

    RUNTIME_UNAVAILABLE = "runtime-unavailable"
    """Payload와 environment 어디에도 vendor runtime 근거가 없습니다."""

    RUNTIME_CONFLICT = "runtime-conflict"
    """Claude Code와 Codex provenance가 한 요청에 동시에 나타났습니다."""

    IDENTITY_CONFLICT = "identity-conflict"
    """Inherited canonical identity가 vendor payload identity와 일치하지 않습니다."""

    STATE_CONFLICT = "state-conflict"
    """Typed lifecycle event가 exact persisted session invariant와 충돌했습니다."""

    OUTPUT_UNAVAILABLE = "output-unavailable"
    """Runtime이 제공한 output file에 canonical identity를 기록할 수 없습니다."""

    LIFECYCLE_UNAVAILABLE = "lifecycle-unavailable"
    """Runtime이 requested fork/end lifecycle의 provenance capability를 제공하지 않습니다."""

    CONTEXT_BUDGET_EXCEEDED = "context-budget-exceeded"
    """Load-bearing assignment, goal 또는 open action이 host context budget보다 큽니다."""


class ImmutableHookValue:
    """Hook boundary value를 생성 이후 immutable하게 유지합니다."""

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 hook value의 attribute 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Hook value를 생성 후 변경하려 하면 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class RuntimeHookResult(ImmutableHookValue):
    """Process exit, JSON stdout과 typed diagnostic을 하나의 결과로 묶습니다."""

    __slots__ = ("diagnostic", "exit_code", "pending_effect", "stdout")

    def __init__(
        self,
        *,
        exit_code: int,
        stdout: str,
        diagnostic: RuntimeHookDiagnostic | RehydrationDiagnostic | None,
        pending_effect: OutboxEffect | None = None,
    ) -> None:
        """Hook 호출자가 그대로 전달할 process 결과를 고정합니다.

        Args:
            exit_code: Vendor hook process가 반환할 성공 또는 실패 code입니다.
            stdout: Vendor가 읽을 단일 JSON object입니다.
            diagnostic: Context를 생략하거나 요청을 거부한 typed 원인입니다.
            pending_effect: Stdout delivery 뒤 ACK할 exact durable effect입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "stdout", stdout)
        object.__setattr__(self, "diagnostic", diagnostic)
        object.__setattr__(self, "pending_effect", pending_effect)

    exit_code: int
    """Vendor hook process가 반환할 성공 또는 실패 code입니다."""

    stdout: str
    """Hook protocol에 맞춘 단일 JSON object입니다."""

    diagnostic: RuntimeHookDiagnostic | RehydrationDiagnostic | None
    """Context 미주입 또는 boundary 거부를 설명하는 typed code입니다."""

    pending_effect: OutboxEffect | None
    """Hook protocol output이 durable하게 기록된 뒤 ACK할 pending effect입니다."""


class RuntimeHookConfigurationError(RuntimeError):
    """Hook application의 고정 byte budget이 유효하지 않을 때 발생합니다."""


class RuntimeHookFailure(RuntimeError):
    """State mutation 전에 발견한 hook boundary 위반을 typed code와 결합합니다."""

    def __init__(self, diagnostic: RuntimeHookDiagnostic, message: str) -> None:
        """Fail-closed result에 필요한 code와 내부 설명을 보존합니다.

        Args:
            diagnostic: Caller가 분기할 stable failure code입니다.
            message: Debugging에 사용할 구체적인 boundary 위반 설명입니다.
        """
        self.diagnostic = diagnostic
        super().__init__(message)


class RuntimeHookApplication:
    """Runtime provenance를 검증하고 exact-session hook lifecycle을 실행합니다."""

    _CLAUDE_PAYLOAD_FIELDS = frozenset({
        "parent_agent_id",
    })
    _CODEX_PAYLOAD_FIELDS = frozenset({
        "actor_id",
        "capabilities",
        "fork_provenance_id",
        "parent_thread_id",
        "resume_id",
        "source_session_id",
        "thread_id",
    })
    _CLAUDE_ENVIRONMENT_FIELDS = frozenset({
        "CLAUDE_CODE_SESSION_ID",
    })
    _CODEX_ENVIRONMENT_FIELDS = frozenset({"CODEX_THREAD_ID"})
    _RUNTIME_HINT_FIELD = "NEURATH_HOOK_RUNTIME"
    _IDENTITY_FIELDS = (
        "NEURATH_AGENT_SESSION_ID",
        "NEURATH_AGENT_ACTOR_ID",
        "NEURATH_AGENT_RUNTIME",
    )
    _TRUNCATION_MARKER = "\n[neurath-context-truncated]"

    def __init__(
        self,
        locator: SessionLocator,
        *,
        enclave_max_bytes: int,
        additional_context_max_bytes: int,
    ) -> None:
        """Canonical state services와 output byte budget을 결합합니다.

        Args:
            locator: Exact session을 repository control root에 고정하는 resolver입니다.
            enclave_max_bytes: Rehydration source enclave의 serialized byte 상한입니다.
            additional_context_max_bytes: Hook additionalContext UTF-8 byte 상한입니다.

        Raises:
            RuntimeHookConfigurationError: Additional context byte 상한이 양수가 아니면
                발생합니다.
        """
        if additional_context_max_bytes <= 0:
            raise RuntimeHookConfigurationError("additional_context_max_bytes must be positive")
        enclaves = EnclaveStore(locator, max_bytes=enclave_max_bytes)
        self._locator = locator
        self._kernel = SessionKernel(locator)
        self._lifecycle = SessionLifecycle(locator, enclaves)
        self._rehydrator = SessionRehydrator(locator, enclaves)
        self._retention = SessionRetentionManager(
            locator,
            retention_seconds=DEFAULT_SESSION_RETENTION_SECONDS,
        )
        self._runtime_assurances = RuntimeAssuranceInventory(locator.control_root)
        self._additional_context_max_bytes = additional_context_max_bytes
        self._claude_adapter = ClaudeCodeRuntimeAdapter()
        self._codex_adapter = CodexRuntimeAdapter()

    def run(
        self,
        raw_input: str,
        environment: Mapping[str, str],
    ) -> RuntimeHookResult:
        """한 vendor hook JSON을 lifecycle mutation과 protocol output으로 처리합니다.

        Identity와 runtime provenance를 state mutation 전에 검증합니다. Startup만 새
        session을 만들며 resume, compact와 subagent start는 exact existing session에만
        결속됩니다.

        Args:
            raw_input: Vendor가 stdin으로 전달한 JSON object 원문입니다.
            environment: Vendor runtime signal과 선택적 canonical identity export입니다.

        Returns:
            Process exit code, JSON stdout과 optional typed diagnostic입니다.
        """
        try:
            payload = self._parse_payload(raw_input)
            adapter = self._detect_adapter(payload, environment)
            envelope = adapter.normalize(payload)
            envelope, child_attestation_revision = self._resolve_codex_turn_lineage(envelope)
            self._validate_inherited_identity(envelope, environment)
            decision, context, pending_effect = self._apply_lifecycle(
                envelope,
                child_attestation_revision=child_attestation_revision,
            )
            if decision.status is not RehydrationStatus.BLOCKED:
                self._export_claude_session_identity(envelope, environment)
            return RuntimeHookResult(
                exit_code=0,
                stdout=self._encode_output(decision.hook_event_name, context),
                diagnostic=decision.diagnostic,
                pending_effect=pending_effect,
            )
        except RuntimeHookFailure as error:
            return self._failure_result(error.diagnostic)
        except RuntimeAdapterError:
            return self._failure_result(RuntimeHookDiagnostic.INVALID_INPUT)
        except SessionKernelError:
            return self._failure_result(RuntimeHookDiagnostic.STATE_CONFLICT)
        except OSError:
            return self._failure_result(RuntimeHookDiagnostic.OUTPUT_UNAVAILABLE)

    def _parse_payload(self, raw_input: str) -> dict[str, object]:
        try:
            decoded: object = json.loads(raw_input)
        except json.JSONDecodeError as error:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.INVALID_INPUT,
                "runtime hook stdin must be valid JSON",
            ) from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.INVALID_INPUT,
                "runtime hook stdin must be a string-keyed object",
            )
        return {str(key): value for key, value in decoded.items()}

    def _detect_adapter(
        self,
        payload: Mapping[str, object],
        environment: Mapping[str, str],
    ) -> RuntimeAdapter:
        claude_payload = bool(self._CLAUDE_PAYLOAD_FIELDS.intersection(payload))
        codex_payload = bool(self._CODEX_PAYLOAD_FIELDS.intersection(payload))
        if claude_payload and codex_payload:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.RUNTIME_CONFLICT,
                "runtime payload mixes Claude Code and Codex provenance",
            )
        runtime_hint = environment.get(self._RUNTIME_HINT_FIELD)
        if runtime_hint is not None:
            hinted_adapter = self._hinted_adapter(runtime_hint)
            if (
                hinted_adapter is self._claude_adapter
                and codex_payload
                or hinted_adapter is self._codex_adapter
                and claude_payload
            ):
                raise RuntimeHookFailure(
                    RuntimeHookDiagnostic.RUNTIME_CONFLICT,
                    "runtime wiring hint conflicts with vendor-specific payload",
                )
            return hinted_adapter
        if claude_payload:
            return self._claude_adapter
        if codex_payload:
            return self._codex_adapter

        claude_environment = any(environment.get(key) for key in self._CLAUDE_ENVIRONMENT_FIELDS)
        codex_environment = any(environment.get(key) for key in self._CODEX_ENVIRONMENT_FIELDS)
        if claude_environment and codex_environment:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.RUNTIME_CONFLICT,
                "runtime environment is ambiguous",
            )
        if claude_environment:
            return self._claude_adapter
        if codex_environment:
            return self._codex_adapter
        weak_claude = bool(environment.get("CLAUDE_PROJECT_DIR"))
        weak_codex = bool(environment.get("CODEX_HOME"))
        if weak_claude == weak_codex:
            diagnostic = (
                RuntimeHookDiagnostic.RUNTIME_CONFLICT
                if weak_claude
                else RuntimeHookDiagnostic.RUNTIME_UNAVAILABLE
            )
            raise RuntimeHookFailure(diagnostic, "runtime environment is ambiguous")
        return self._claude_adapter if weak_claude else self._codex_adapter

    def _hinted_adapter(self, runtime_hint: str) -> RuntimeAdapter:
        normalized = runtime_hint.strip()
        if normalized == SessionRuntime.CLAUDE_CODE.value:
            return self._claude_adapter
        if normalized == SessionRuntime.CODEX.value:
            return self._codex_adapter
        raise RuntimeHookFailure(
            RuntimeHookDiagnostic.RUNTIME_CONFLICT,
            f"unsupported runtime wiring hint: {runtime_hint}",
        )

    def _validate_inherited_identity(
        self,
        envelope: RuntimeEnvelope,
        environment: Mapping[str, str],
    ) -> None:
        inherited = tuple(environment.get(key) for key in self._IDENTITY_FIELDS)
        if all(value is None for value in inherited):
            return
        if any(value is None or not value.strip() for value in inherited):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.IDENTITY_CONFLICT,
                "canonical runtime identity must be complete",
            )
        inherited_session_id, inherited_actor_id, inherited_runtime = inherited
        if inherited_session_id is None or inherited_actor_id is None or inherited_runtime is None:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.IDENTITY_CONFLICT,
                "canonical runtime identity must be complete",
            )
        if self._is_valid_fork_source_identity(
            envelope,
            inherited_session_id,
            inherited_actor_id,
            inherited_runtime,
        ):
            return
        if (
            inherited_session_id != str(envelope.session_id)
            or inherited_runtime != envelope.runtime.value
        ):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.IDENTITY_CONFLICT,
                "canonical session or runtime conflicts with vendor payload",
            )
        allowed_actor_ids = {str(envelope.actor_id)}
        if envelope.cause is LifecycleCause.SUBAGENT_START:
            if envelope.parent_actor_id is not None:
                allowed_actor_ids.add(str(envelope.parent_actor_id))
            else:
                allowed_actor_ids.add(f"{envelope.runtime.value}:session:{envelope.session_id}")
        if inherited_actor_id not in allowed_actor_ids:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.IDENTITY_CONFLICT,
                "canonical actor conflicts with vendor payload lineage",
            )

    def _is_valid_fork_source_identity(
        self,
        envelope: RuntimeEnvelope,
        inherited_session_id: str,
        inherited_actor_id: str,
        inherited_runtime: str,
    ) -> bool:
        """Capability-proven fork가 inherited source overlay를 target으로 넘길 수 있게 합니다.

        Args:
            envelope: Target identity와 verified source lineage를 가진 runtime event입니다.
            inherited_session_id: Parent process가 export한 source session입니다.
            inherited_actor_id: Parent process가 export한 source actor입니다.
            inherited_runtime: Parent process runtime kind입니다.

        Returns:
            Exact source root overlay이고 target fork capability가 있으면 참입니다.
        """
        source_session_id = envelope.fork_source_session_id
        if (
            envelope.cause is not LifecycleCause.FORK
            or RuntimeCapability.SESSION_FORK_LINEAGE not in envelope.capabilities
            or source_session_id is None
            or inherited_session_id != str(source_session_id)
            or inherited_runtime != envelope.runtime.value
        ):
            return False
        return inherited_actor_id == (f"{envelope.runtime.value}:session:{source_session_id}")

    def _apply_lifecycle(
        self,
        envelope: RuntimeEnvelope,
        *,
        child_attestation_revision: int | None = None,
    ) -> tuple[RehydrationDecision, str | None, OutboxEffect | None]:
        if envelope.cause is LifecycleCause.FORK:
            self._apply_fork(envelope)
            decision = self._rehydrator.rehydrate(envelope)
            context, effect = self._render_delivery(envelope, decision)
            if effect is not None:
                self._validate_fork_pending_delivery(envelope, effect)
                self._kernel.apply(
                    EffectPrepared(
                        session_id=envelope.session_id,
                        actor_id=envelope.actor_id,
                        effect=effect,
                        idempotency_key=f"runtime-hook:fork:{effect.delivery_key}",
                    )
                )
            return decision, context, effect
        if envelope.cause is LifecycleCause.END:
            self._apply_end(envelope)
            return self._rehydrator.rehydrate(envelope), None, None
        if envelope.cause is LifecycleCause.STARTUP:
            initial = self._rehydrator.initial_context(envelope)
            initial_context, initial_effect = self._render_delivery(envelope, initial)
            if initial_effect is None:
                raise RuntimeHookFailure(
                    RuntimeHookDiagnostic.STATE_CONFLICT,
                    "startup context did not produce a durable delivery",
                )
            started = self._kernel.apply(
                SessionStarted(
                    session_id=envelope.session_id,
                    resume_id=envelope.resume_id or ResumeId(str(envelope.session_id)),
                    runtime=envelope.runtime,
                    root_actor_id=envelope.actor_id,
                    idempotency_key=(
                        f"runtime-hook:start:{envelope.runtime.value}:{envelope.session_id}"
                    ),
                    effect=initial_effect,
                )
            )
            self._kernel.apply(
                ForegroundTurnProvisioned(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    idempotency_key=(
                        f"runtime-hook:provisional-turn:{envelope.runtime.value}:"
                        f"{envelope.session_id}:{envelope.actor_id}"
                    ),
                )
            )
            self._verify_startup_ready(
                envelope,
                require_provisional=envelope.actor_id not in started.foreground_turns,
            )
            if initial_effect.id in started.outbox:
                return initial, initial_context, initial_effect
        decision = self._rehydrator.rehydrate(envelope)
        context, effect = self._render_delivery(envelope, decision)
        if decision.status is not RehydrationStatus.READY:
            return decision, context, None
        child_lineage_assurance = (
            self._lineage_assurance(
                envelope,
                turn_attested=child_attestation_revision is not None,
            )
            if envelope.cause is LifecycleCause.SUBAGENT_START
            else None
        )
        if (
            envelope.cause is LifecycleCause.SUBAGENT_START
            and child_lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
        ):
            return decision, context, None
        if effect is None:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "ready rehydration did not produce a durable delivery",
            )
        if envelope.cause is LifecycleCause.STARTUP:
            self._kernel.apply(
                EffectPrepared(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    effect=effect,
                    idempotency_key=f"runtime-hook:startup-retry:{effect.delivery_key}",
                )
            )
        if envelope.cause is LifecycleCause.RESUME:
            current = self._kernel.inspect(envelope.session_id)
            self._kernel.apply(
                SessionResumed(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    resume_id=(
                        envelope.resume_id
                        or current.session.resume_id
                        or ResumeId(str(envelope.session_id))
                    ),
                    lifecycle_provenance_id=effect.delivery_key,
                    idempotency_key=f"runtime-hook:resume:{effect.delivery_key}",
                    effect=effect,
                )
            )
        if envelope.cause is LifecycleCause.COMPACT:
            self._kernel.apply(
                SessionCompacted(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    lifecycle_provenance_id=effect.delivery_key,
                    idempotency_key=f"runtime-hook:compact:{effect.delivery_key}",
                    effect=effect,
                )
            )
        if envelope.cause is LifecycleCause.SUBAGENT_START:
            started = self._kernel.apply(
                ActorStarted(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    parent_actor_id=envelope.parent_actor_id,
                    kind=ActorKind.SUBAGENT,
                    lineage_assurance=(child_lineage_assurance or ActorLineageAssurance.UNATTESTED),
                    idempotency_key=(
                        f"runtime-hook:actor:{envelope.runtime.value}:"
                        f"{envelope.session_id}:{envelope.actor_id}"
                    ),
                    effect=effect,
                ),
                expected_revision=child_attestation_revision,
            )
            if effect.id not in started.outbox:
                self._kernel.apply(
                    EffectPrepared(
                        session_id=envelope.session_id,
                        actor_id=envelope.actor_id,
                        effect=effect,
                        idempotency_key=f"runtime-hook:subagent-retry:{effect.delivery_key}",
                    )
                )
            self._kernel.apply(
                ForegroundTurnProvisioned(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    idempotency_key=(
                        f"runtime-hook:subagent-provisional-turn:{envelope.runtime.value}:"
                        f"{envelope.session_id}:{envelope.actor_id}"
                    ),
                )
            )
            self._kernel.apply(
                ForegroundTurnPrompted(
                    session_id=envelope.session_id,
                    actor_id=envelope.actor_id,
                    vendor_turn_id=envelope.provenance.raw_actor_id,
                    idempotency_key=(
                        f"runtime-hook:subagent-turn:{envelope.runtime.value}:"
                        f"{envelope.session_id}:{envelope.actor_id}"
                    ),
                )
            )
        return decision, context, effect

    def _lineage_assurance(
        self,
        envelope: RuntimeEnvelope,
        *,
        turn_attested: bool = False,
    ) -> ActorLineageAssurance:
        """Runtime profile로 exact parent pointer의 persisted authority를 제한합니다.

        Args:
            envelope: Host parent provenance를 포함한 child lifecycle envelope입니다.

        Returns:
            Host-only immediate-parent assurance가 AVAILABLE인 경우에만
            HOST_ATTESTED이고, config 누락·불일치를 포함한 나머지는
            UNATTESTED입니다.
        """
        if turn_attested:
            return ActorLineageAssurance.HOST_ATTESTED
        if envelope.parent_actor_id is None or envelope.provenance.raw_parent_actor_id is None:
            return ActorLineageAssurance.UNATTESTED
        try:
            profile = self._runtime_assurances.profile(envelope.runtime)
            available = profile.is_admissible(RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE)
        except RuntimeAssuranceError:
            available = False
        return (
            ActorLineageAssurance.HOST_ATTESTED if available else ActorLineageAssurance.UNATTESTED
        )

    def _resolve_codex_turn_lineage(
        self,
        envelope: RuntimeEnvelope,
    ) -> tuple[RuntimeEnvelope, int | None]:
        """Official Codex turn provenance로 exact root direct-child만 증명합니다.

        `SubagentStart`의 host-owned `turn_id`가 동일 Codex session의 active root
        foreground turn과 정확히 일치할 때만 parent를 materialize합니다. Missing,
        spoofed, ambiguous 또는 nested child turn은 state-free 경로를 유지합니다.

        Args:
            envelope: Adapter가 정규화한 immutable lifecycle input입니다.

        Returns:
            Optional root parent가 결속된 envelope와 attestation 당시 process revision입니다.
        """
        turn_id = envelope.provenance.raw_turn_id
        if (
            envelope.runtime is not SessionRuntime.CODEX
            or envelope.cause is not LifecycleCause.SUBAGENT_START
            or envelope.parent_actor_id is not None
            or turn_id is None
        ):
            return envelope, None
        try:
            state = self._kernel.inspect(envelope.session_id)
        except SessionNotFound:
            return envelope, None
        if (
            state.session.runtime is not SessionRuntime.CODEX
            or state.session.status is not SessionStatus.ACTIVE
        ):
            return envelope, None
        matching_actors = tuple(
            actor_id
            for actor_id, turn in state.foreground_turns.items()
            if turn.status is ForegroundTurnStatus.ACTIVE
            and turn.vendor_turn_id == turn_id
            and (actor := state.actors.get(actor_id)) is not None
            and actor.status is ActorStatus.ACTIVE
        )
        if matching_actors != (state.session.root_actor_id,):
            return envelope, None
        return (
            RuntimeEnvelope(
                runtime=envelope.runtime,
                session_id=envelope.session_id,
                resume_id=envelope.resume_id,
                actor_id=envelope.actor_id,
                parent_actor_id=state.session.root_actor_id,
                cause=envelope.cause,
                capabilities=envelope.capabilities,
                provenance=envelope.provenance,
                fork_source_session_id=envelope.fork_source_session_id,
                fork_provenance_id=envelope.fork_provenance_id,
            ),
            state.revision,
        )

    def _verify_startup_ready(
        self,
        envelope: RuntimeEnvelope,
        *,
        require_provisional: bool,
    ) -> None:
        """SessionStart 성공 전에 session, root actor와 작업 가능한 turn을 read-back합니다.

        Args:
            envelope: Fresh startup의 exact session과 root actor identity입니다.
            require_provisional: 이번 startup이 turn을 새로 만들었으면 참입니다.

        Raises:
            RuntimeHookFailure: 세 aggregate 중 하나라도 startup contract와 다르면 발생합니다.
        """
        state = self._kernel.inspect(envelope.session_id)
        actor = state.actors.get(envelope.actor_id)
        turn = state.foreground_turns.get(envelope.actor_id)
        if (
            state.session.status is not SessionStatus.ACTIVE
            or state.session.root_actor_id != envelope.actor_id
            or actor is None
            or actor.status is not ActorStatus.ACTIVE
            or turn is None
            or turn.status is not ForegroundTurnStatus.ACTIVE
            or require_provisional
            and (turn.vendor_turn_id is not None or turn.user_prompt_receipt is not None)
        ):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "startup readback is missing its active session, root actor, or foreground turn",
            )

    def _validate_fork_pending_delivery(
        self,
        envelope: RuntimeEnvelope,
        effect: OutboxEffect,
    ) -> None:
        """Retry target의 pending delivery를 새로 계산한 exact context와 대조합니다.

        Args:
            envelope: Exact fork target session과 root actor identity입니다.
            effect: 최종 bounded output bytes에서 새로 계산한 content-addressed effect입니다.

        Raises:
            RuntimeHookFailure: 기존 outbox가 다른 delivery 또는 context를 포함합니다.
        """
        current = self._kernel.inspect(envelope.session_id)
        if not current.outbox:
            return
        existing = current.outbox.get(effect.id)
        if len(current.outbox) != 1 or existing is None or not existing.same_snapshot(effect):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "runtime fork pending delivery conflicts with exact emitted context",
            )

    def _render_delivery(
        self,
        envelope: RuntimeEnvelope,
        decision: RehydrationDecision,
    ) -> tuple[str | None, OutboxEffect | None]:
        """Decision을 최종 host bytes로 만든 뒤 그 exact delivery를 content-address합니다.

        Args:
            envelope: Vendor lifecycle과 exact actor/session identity입니다.
            decision: Structural optional boundary를 포함한 rehydration 결과입니다.

        Returns:
            실제 출력할 bounded context와 동일 byte를 가리키는 optional effect입니다.
        """
        if decision.status is not RehydrationStatus.READY:
            return None, None
        context = self._render_context(
            envelope,
            decision.additional_context,
            decision.optional_context_start_bytes,
        )
        return context, self._lifecycle_effect(envelope, additional_context=context)

    def _apply_fork(self, envelope: RuntimeEnvelope) -> None:
        """Capability-proven lineage만 independent target session으로 materialize합니다.

        Args:
            envelope: Runtime adapter가 source, target과 provenance를 검증한 fork event입니다.

        Raises:
            RuntimeHookFailure: Runtime lineage가 불충분하거나 persisted target과 충돌합니다.
        """
        source_session_id = envelope.fork_source_session_id
        provenance_id = envelope.fork_provenance_id
        if (
            RuntimeCapability.SESSION_FORK_LINEAGE not in envelope.capabilities
            or source_session_id is None
            or provenance_id is None
        ):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.LIFECYCLE_UNAVAILABLE,
                "runtime fork does not provide verified source lineage",
            )
        try:
            self._lifecycle.fork(
                ForkLineage(
                    runtime=envelope.runtime,
                    source_session_id=source_session_id,
                    target_session_id=envelope.session_id,
                    target_resume_id=(envelope.resume_id or ResumeId(str(envelope.session_id))),
                    provenance_id=provenance_id,
                )
            )
        except LifecycleConflict as error:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "runtime fork conflicts with canonical session lineage",
            ) from error

    def _apply_end(self, envelope: RuntimeEnvelope) -> None:
        """Native SessionEnd capability를 root-authorized terminal retention으로 연결합니다.

        Args:
            envelope: Exact root session end event입니다.

        Raises:
            RuntimeHookFailure: Runtime end capability가 없거나 actor가 root가 아닙니다.
        """
        if RuntimeCapability.SESSION_END not in envelope.capabilities:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.LIFECYCLE_UNAVAILABLE,
                "runtime does not expose a stable SessionEnd lifecycle event",
            )
        current = self._kernel.inspect(envelope.session_id)
        handle = StateHandle.attach(
            self._locator,
            RuntimeIdentityBinding(
                runtime=envelope.runtime,
                session_id=envelope.session_id,
                actor_id=envelope.actor_id,
                root_actor_id=current.session.root_actor_id,
            ),
        )
        self._retention.end(
            handle,
            idempotency_key=(f"runtime-hook:end:{envelope.runtime.value}:{envelope.session_id}"),
        )

    def acknowledge(self, result: RuntimeHookResult) -> None:
        """Hook protocol output write 뒤 exact pending effect를 ACK합니다.

        Args:
            result: 이 application이 생성한 successful hook result입니다.

        Raises:
            RuntimeHookFailure: Pending effect에 exact session identity가 없으면 발생합니다.
        """
        effect = result.pending_effect
        if result.exit_code != 0 or effect is None:
            return
        payload = effect.payload
        raw_session_id = payload.get("session_id")
        if not isinstance(raw_session_id, str):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "pending effect is missing its exact session identity",
            )
        self._kernel.apply(
            EffectAcknowledged(
                session_id=SessionId(raw_session_id),
                actor_id=effect.actor_id,
                effect_id=effect.id,
                idempotency_key=f"runtime-hook:ack:{effect.delivery_key}",
            )
        )

    def _lifecycle_effect(
        self,
        envelope: RuntimeEnvelope,
        *,
        additional_context: str | None,
    ) -> OutboxEffect:
        """Lifecycle provenance와 전달할 context snapshot을 content-address합니다.

        Args:
            envelope: Vendor event에서 정규화한 exact runtime identity입니다.
            additional_context: 이번 delivery가 출력할 exact enclave/assignment context입니다.

        Returns:
            동일 logical delivery retry만 같은 identity를 갖는 durable outbox effect입니다.
        """
        provenance = {
            "actor_id": str(envelope.actor_id),
            "cause": envelope.cause.value,
            "context_present": additional_context is not None,
            "context_sha256": hashlib.sha256(
                (additional_context or "").encode("utf-8")
            ).hexdigest(),
            "event_name": envelope.provenance.event_name,
            "raw_actor_id": envelope.provenance.raw_actor_id,
            "raw_parent_actor_id": envelope.provenance.raw_parent_actor_id,
            "raw_resume_id": envelope.provenance.raw_resume_id,
            "raw_session_id": envelope.provenance.raw_session_id,
            "raw_turn_id": envelope.provenance.raw_turn_id,
            "runtime": envelope.runtime.value,
            "session_id": str(envelope.session_id),
        }
        canonical = json.dumps(
            provenance,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return OutboxEffect(
            effect_id=EffectId(f"runtime-{digest}"),
            actor_id=envelope.actor_id,
            kind=EffectKind.CONTEXT_INJECTION,
            delivery_key=f"runtime-hook:{digest}",
            payload=provenance,
        )

    def _render_context(
        self,
        envelope: RuntimeEnvelope,
        enclave_context: str | None,
        optional_context_start_bytes: int | None,
    ) -> str | None:
        if enclave_context is None:
            return None
        context = enclave_context
        optional_start = optional_context_start_bytes
        if optional_start is None:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "ready context is missing its structural optional boundary",
            )
        if envelope.cause is LifecycleCause.SUBAGENT_START:
            binding = json.dumps(
                {
                    "actor_id": str(envelope.actor_id),
                    "runtime": envelope.runtime.value,
                    "session_id": str(envelope.session_id),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            prefix = f"<neurath-runtime-binding>{binding}</neurath-runtime-binding>\n"
            context = f"{prefix}{enclave_context}"
            optional_start += len(prefix.encode("utf-8"))
        return self._bound_context(
            context,
            optional_context_start_bytes=optional_start,
        )

    def _bound_context(
        self,
        context: str,
        *,
        optional_context_start_bytes: int,
    ) -> str:
        encoded = context.encode("utf-8")
        if len(encoded) <= self._additional_context_max_bytes:
            return context
        marker = self._TRUNCATION_MARKER.encode("utf-8")
        if not 0 <= optional_context_start_bytes <= len(encoded):
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.STATE_CONFLICT,
                "structural context boundary is outside the rendered bytes",
            )
        critical_bytes = encoded[:optional_context_start_bytes].rstrip(b"\n")
        if len(critical_bytes) + len(marker) > self._additional_context_max_bytes:
            raise RuntimeHookFailure(
                RuntimeHookDiagnostic.CONTEXT_BUDGET_EXCEEDED,
                "load-bearing runtime context exceeds the configured host byte budget",
            )
        prefix_budget = self._additional_context_max_bytes - len(marker)
        prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore")
        return f"{prefix}{self._TRUNCATION_MARKER}"

    def _export_claude_session_identity(
        self,
        envelope: RuntimeEnvelope,
        environment: Mapping[str, str],
    ) -> None:
        if (
            envelope.runtime is not SessionRuntime.CLAUDE_CODE
            or envelope.provenance.event_name != "SessionStart"
        ):
            return
        raw_path = environment.get("CLAUDE_ENV_FILE")
        if raw_path is None or not raw_path.strip():
            return
        exports = (
            self._export_line("NEURATH_AGENT_SESSION_ID", str(envelope.session_id)),
            self._export_line("NEURATH_AGENT_ACTOR_ID", str(envelope.actor_id)),
            self._export_line("NEURATH_AGENT_RUNTIME", envelope.runtime.value),
        )
        path = Path(raw_path)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = tuple(line for line in exports if line not in existing.splitlines())
        if not missing:
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{separator}{'\n'.join(missing)}\n")

    def _export_line(self, name: str, value: str) -> str:
        return f"export {name}={shlex.quote(value)}"

    def _encode_output(self, hook_event_name: str, context: str | None) -> str:
        if hook_event_name == "SessionEnd":
            return "{}"
        specific: dict[str, object] = {"hookEventName": hook_event_name}
        if context is not None:
            specific["additionalContext"] = context
        return json.dumps(
            {"hookSpecificOutput": specific},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _failure_result(self, diagnostic: RuntimeHookDiagnostic) -> RuntimeHookResult:
        return RuntimeHookResult(
            exit_code=1,
            stdout="{}",
            diagnostic=diagnostic,
        )
