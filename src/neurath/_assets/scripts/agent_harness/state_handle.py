"""Runtime-owned identity를 exact session state authority로 연결합니다."""

from collections.abc import Mapping
from pathlib import Path

from scripts.agent_harness.material_action import MaterialActionKind
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    ActorStopped,
    DelegationAssigned,
    DelegationCancelled,
    DelegationConsumed,
    DelegationReported,
    EffectAcknowledged,
    EffectPrepared,
    ForegroundTurnClosed,
    ForegroundTurnInvalidated,
    ForegroundTurnReplaced,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnToolObserved,
    ForegroundTurnYielded,
    HarnessIncidentEscalated,
    HarnessIncidentEvidenceSuperseded,
    HarnessIncidentRecorded,
    HarnessIncidentResolved,
    HarnessIncidentsRefreshed,
    KernelEvent,
    MaterialActionAbandoned,
    MaterialActionPrepared,
    MaterialActionResolved,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    ProcessState,
    ResumeId,
    SessionCompacted,
    SessionEnded,
    SessionId,
    SessionKernel,
    SessionKernelError,
    SessionLocator,
    SessionNotFound,
    SessionResumed,
    SessionRuntime,
    SessionStarted,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowStarted,
)


class RuntimeIdentityError(ValueError):
    """Runtime environment가 canonical identity를 증명하지 못했을 때의 base error입니다."""


class RuntimeIdentityUnavailable(RuntimeIdentityError):
    """지원 runtime이 소유한 root session identity가 없을 때 발생합니다."""


class RuntimeIdentityConflict(RuntimeIdentityError):
    """Runtime identity source가 모호하거나 Neurath overlay와 충돌할 때 발생합니다."""


class StateHandleAuthorityError(SessionKernelError):
    """Bound session 또는 actor의 권한 밖 event를 제출할 때 발생합니다."""


class RuntimeIdentityBinding:
    """검증된 vendor root identity와 현재 actor authority를 함께 고정합니다."""

    __slots__ = ("actor_id", "root_actor_id", "runtime", "session_id")

    def __init__(
        self,
        *,
        runtime: SessionRuntime,
        session_id: SessionId,
        actor_id: ActorId,
        root_actor_id: ActorId,
    ) -> None:
        """Runtime identity resolver가 검증한 immutable binding을 생성합니다.

        Args:
            runtime: Root session identity를 발급한 coding-agent runtime입니다.
            session_id: Repository 안 canonical state를 고르는 exact session identity입니다.
            actor_id: 현재 process가 mutation authority를 가진 actor identity입니다.
            root_actor_id: Vendor root identity에서 결정적으로 파생된 root actor입니다.
        """
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "root_actor_id", root_actor_id)

    runtime: SessionRuntime
    """Root session identity를 발급한 coding-agent runtime입니다."""

    session_id: SessionId
    """Repository 안 canonical state를 고르는 exact session identity입니다."""

    actor_id: ActorId
    """현재 process가 mutation authority를 가진 actor identity입니다."""

    root_actor_id: ActorId
    """Vendor root identity에서 결정적으로 파생된 root actor identity입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 authority binding의 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Runtime identity binding은 생성 뒤 항상 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")

    @property
    def is_root(self) -> bool:
        """현재 actor가 vendor root actor인지 반환합니다.

        Returns:
            현재 mutation authority가 root actor이면 `True`입니다.
        """
        return self.actor_id == self.root_actor_id


class RuntimeEnvironmentResolver:
    """Runtime-owned environment를 fail-closed canonical binding으로 검증합니다."""

    _NEURATH_ACTOR_KEY = "NEURATH_AGENT_ACTOR_ID"
    _NEURATH_RUNTIME_KEY = "NEURATH_AGENT_RUNTIME"
    _NEURATH_SESSION_KEY = "NEURATH_AGENT_SESSION_ID"
    _CLAUDE_SESSION_KEY = "CLAUDE_CODE_SESSION_ID"
    _CODEX_SESSION_KEY = "CODEX_THREAD_ID"

    def resolve(self, environment: Mapping[str, object]) -> RuntimeIdentityBinding:
        """Vendor root identity와 optional Neurath actor overlay를 검증합니다.

        Args:
            environment: Runtime과 Neurath hook이 소유한 process environment mapping입니다.

        Returns:
            Exact session, runtime, current actor가 검증된 immutable binding입니다.

        Raises:
            RuntimeIdentityUnavailable: 지원 runtime의 root identity가 존재하지 않으면
                발생합니다.
            RuntimeIdentityConflict: Vendor identity가 모호하거나 Neurath overlay가
                불완전하거나 vendor authority와 충돌하면 발생합니다.
        """
        return self._resolve(environment, process=True)

    def _resolve(self, environment: Mapping[str, object], *, process: bool) -> RuntimeIdentityBinding:
        """Native hooks have their own payload authority; shell calls require process proof."""
        if "NEURATH_TOOL_BINDING" in environment:
            try:
                return __import__("neurath.hosts.identity", fromlist=["resolve_binding"]).resolve_binding(environment)
            except (ValueError, OSError, KeyError) as error:
                raise RuntimeIdentityConflict(str(error)) from error
        if "CODEX_THREAD_ID" in environment and __import__("os").environ.get("NEURATH_TARGET_ROOT"):
            try:
                native_binding = __import__("neurath.hosts.identity", fromlist=["resolve_native_codex"]).resolve_native_codex(environment)
                if native_binding is not None:
                    return native_binding
            except (ValueError, OSError, KeyError) as error:
                raise RuntimeIdentityConflict(str(error)) from error
        try:
            if process:
                __import__("neurath.hosts.identity", fromlist=["require_process_receipt"]).require_process_receipt(environment)
        except (ValueError, OSError, KeyError) as error:
            raise RuntimeIdentityConflict(str(error)) from error
        runtime, session_id, root_actor_id = self._resolve_vendor_identity(environment)
        overlay_keys = (
            self._NEURATH_SESSION_KEY,
            self._NEURATH_ACTOR_KEY,
            self._NEURATH_RUNTIME_KEY,
        )
        overlay_presence = tuple(key in environment for key in overlay_keys)
        if not any(overlay_presence):
            return RuntimeIdentityBinding(
                runtime=runtime,
                session_id=session_id,
                actor_id=root_actor_id,
                root_actor_id=root_actor_id,
            )
        if not all(overlay_presence):
            raise RuntimeIdentityConflict("Neurath runtime identity overlay must be all-or-none")

        overlay_session = SessionId(self._required_identity(environment, self._NEURATH_SESSION_KEY))
        overlay_actor = ActorId(self._required_identity(environment, self._NEURATH_ACTOR_KEY))
        overlay_runtime_value = self._required_identity(environment, self._NEURATH_RUNTIME_KEY)
        try:
            overlay_runtime = SessionRuntime(overlay_runtime_value)
        except ValueError as error:
            raise RuntimeIdentityConflict(
                "Neurath runtime identity overlay is unsupported"
            ) from error

        if overlay_session != session_id or overlay_runtime is not runtime:
            raise RuntimeIdentityConflict(
                "Neurath runtime identity overlay conflicts with vendor root"
            )
        actor_namespace = f"{runtime.value}:"
        actor_suffix = str(overlay_actor).removeprefix(actor_namespace)
        if not str(overlay_actor).startswith(actor_namespace) or not actor_suffix.strip():
            raise RuntimeIdentityConflict("Neurath actor identity conflicts with vendor runtime")
        return RuntimeIdentityBinding(
            runtime=runtime,
            session_id=session_id,
            actor_id=overlay_actor,
            root_actor_id=root_actor_id,
        )

    def resolve_hook_actor(
        self,
        environment: Mapping[str, object],
        runtime_agent_id: object | None,
        runtime_session_id: object | None = None,
        *,
        hook_runtime: SessionRuntime | None = None,
    ) -> RuntimeIdentityBinding:
        """Official hook payload를 runtime-specific adapter authority에 결속합니다.

        Vendor environment identity가 있으면 payload와 exact 대조합니다. Codex처럼 hook
        process에 vendor identity environment를 보장하지 않는 runtime은 adapter가
        ``hook_runtime``을 명시한 경우에만 필수 payload ``session_id``를 root authority로
        사용합니다. Generic caller는 payload만 보고 vendor runtime을 추측할 수 없습니다.

        Args:
            environment: Vendor session과 optional inherited Neurath overlay입니다.
            runtime_agent_id: Hook payload의 optional ``agent_id`` field입니다.
            runtime_session_id: Hook payload가 제공한 optional exact root session입니다.
            hook_runtime: Runtime-specific hook wiring이 증명한 vendor runtime입니다.

        Returns:
            Root hook이면 root binding, child hook이면 exact child binding입니다.

        Raises:
            RuntimeIdentityConflict: Runtime/session mismatch, malformed identity 또는 다른
                child overlay와 충돌하면 발생합니다.
        """
        try:
            binding = self._resolve(environment, process=False)
        except RuntimeIdentityUnavailable:
            if hook_runtime is None:
                raise
            if any(
                key in environment
                for key in (
                    self._NEURATH_SESSION_KEY,
                    self._NEURATH_ACTOR_KEY,
                    self._NEURATH_RUNTIME_KEY,
                )
            ):
                raise RuntimeIdentityConflict(
                    "Neurath actor overlay cannot replace missing vendor hook identity"
                ) from None
            session_value = self._hook_identity(runtime_session_id, "session_id")
            session_id = SessionId(session_value)
            root_actor_id = ActorId(f"{hook_runtime.value}:session:{session_value}")
            binding = RuntimeIdentityBinding(
                runtime=hook_runtime,
                session_id=session_id,
                actor_id=root_actor_id,
                root_actor_id=root_actor_id,
            )
        if hook_runtime is not None and binding.runtime is not hook_runtime:
            raise RuntimeIdentityConflict("hook runtime conflicts with vendor root")
        if runtime_session_id is not None and (
            not isinstance(runtime_session_id, str) or runtime_session_id != str(binding.session_id)
        ):
            raise RuntimeIdentityConflict("hook session conflicts with vendor root")
        if runtime_agent_id is None:
            return binding
        if runtime_session_id is None:
            raise RuntimeIdentityConflict("subagent hook requires exact session_id")
        agent_value = self._hook_identity(runtime_agent_id, "agent_id")
        actor_id = ActorId(f"{binding.runtime.value}:{agent_value}")
        if actor_id == binding.root_actor_id:
            raise RuntimeIdentityConflict("subagent hook cannot claim the root actor")
        if binding.actor_id not in {binding.root_actor_id, actor_id}:
            raise RuntimeIdentityConflict("hook agent conflicts with inherited actor overlay")
        return RuntimeIdentityBinding(
            runtime=binding.runtime,
            session_id=binding.session_id,
            actor_id=actor_id,
            root_actor_id=binding.root_actor_id,
        )

    def _hook_identity(self, value: object | None, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise RuntimeIdentityConflict(f"hook {field} must be a canonical identity")
        return value

    def _resolve_vendor_identity(
        self,
        environment: Mapping[str, object],
    ) -> tuple[SessionRuntime, SessionId, ActorId]:
        vendor_keys = tuple(
            key for key in (self._CODEX_SESSION_KEY, self._CLAUDE_SESSION_KEY) if key in environment
        )
        if not vendor_keys:
            raise RuntimeIdentityUnavailable("runtime-owned session identity is unavailable")
        if len(vendor_keys) != 1:
            raise RuntimeIdentityConflict("multiple runtime-owned session identities are present")

        vendor_key = vendor_keys[0]
        session_value = self._required_identity(environment, vendor_key)
        session_id = SessionId(session_value)
        if vendor_key == self._CODEX_SESSION_KEY:
            return (
                SessionRuntime.CODEX,
                session_id,
                ActorId(f"codex:session:{session_value}"),
            )
        return (
            SessionRuntime.CLAUDE_CODE,
            session_id,
            ActorId(f"claude-code:session:{session_value}"),
        )

    def _required_identity(self, environment: Mapping[str, object], key: str) -> str:
        value = environment.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeIdentityConflict(f"runtime identity {key} must be a non-empty string")
        return value.strip()


class StateHandle:
    """하나의 validated runtime session과 actor에 고정된 state facade입니다."""

    def __init__(self, kernel: SessionKernel, binding: RuntimeIdentityBinding) -> None:
        """Canonical kernel을 validated session/actor authority에 고정합니다.

        Args:
            kernel: Session identity로 canonical store를 선택하는 optimistic kernel입니다.
            binding: Runtime environment에서 검증된 exact session과 actor authority입니다.
        """
        self._kernel = kernel
        self._binding = binding

    @classmethod
    def initialize(
        cls,
        locator: SessionLocator,
        binding: RuntimeIdentityBinding,
    ) -> StateHandle:
        """Lifecycle boundary에서 root session을 idempotently 초기화합니다.

        Args:
            locator: Validated session identity를 canonical store에 연결하는 locator입니다.
            binding: Runtime environment에서 검증된 exact session과 actor authority입니다.

        Returns:
            한 session과 actor 밖으로 fallback하지 않는 state handle입니다.

        Raises:
            StateHandleAuthorityError: Root가 아닌 actor가 lifecycle initialization을
                시도하거나 existing session이 binding과 충돌하면 발생합니다.
        """
        if not binding.is_root:
            raise StateHandleAuthorityError("only the runtime root can initialize a session")
        handle = cls(SessionKernel(locator), binding)
        try:
            handle.inspect()
        except SessionNotFound:
            handle._kernel.apply(
                SessionStarted(
                    session_id=binding.session_id,
                    resume_id=ResumeId(str(binding.session_id)),
                    runtime=binding.runtime,
                    root_actor_id=binding.root_actor_id,
                    idempotency_key=f"state-handle:session-started:{binding.session_id}",
                )
            )
        return handle

    @classmethod
    def attach(
        cls,
        locator: SessionLocator,
        binding: RuntimeIdentityBinding,
    ) -> StateHandle:
        """Operational caller를 exact existing session/actor에만 결속시킵니다.

        Args:
            locator: Validated session identity를 canonical store에 연결하는 locator입니다.
            binding: Runtime environment에서 검증된 exact session과 actor authority입니다.

        Returns:
            Existing session과 actor를 검증한 path-free state handle입니다.

        Raises:
            SessionNotFound: Bound exact session이 lifecycle에서 시작되지 않았으면
                발생합니다.
            StateHandleAuthorityError: Runtime, root actor 또는 current actor가 persisted
                session과 다르면 발생합니다.
        """
        handle = cls(SessionKernel(locator), binding)
        handle.inspect()
        return handle

    @property
    def session_id(self) -> SessionId:
        """Handle이 exact state 조회와 mutation에 사용하는 session identity입니다.

        Returns:
            Runtime environment에서 검증된 read-only session identity입니다.
        """
        return self._binding.session_id

    @property
    def actor_id(self) -> ActorId:
        """Handle이 mutation authority를 행사하는 현재 actor identity입니다.

        Returns:
            Runtime environment에서 검증된 read-only actor identity입니다.
        """
        return self._binding.actor_id

    @property
    def runtime(self) -> SessionRuntime:
        """Handle의 root session identity를 발급한 runtime입니다.

        Returns:
            Runtime environment에서 검증된 read-only runtime 종류입니다.
        """
        return self._binding.runtime

    def inspect(self) -> ProcessState:
        """Bound exact session의 latest immutable snapshot을 조회합니다.

        Returns:
            다른 session으로 fallback하지 않고 binding과 일치하는 process state입니다.

        Raises:
            SessionNotFound: Bound exact session snapshot이 존재하지 않으면 발생합니다.
            StateHandleAuthorityError: Session runtime, root actor, current actor가 binding과
                일치하지 않으면 발생합니다.
        """
        state = self._kernel.inspect(self._binding.session_id)
        self._validate_state_authority(state)
        return state

    def apply(
        self,
        event: KernelEvent,
        expected_revision: int | None = None,
    ) -> ProcessState:
        """Current actor가 소유한 typed event를 optimistic transaction으로 적용합니다.

        Args:
            event: Bound session과 current actor가 authority를 가진 state transition입니다.
            expected_revision: Stale caller mutation을 막을 optional explicit compare version입니다.

        Returns:
            Implicit conflict retry 또는 explicit compare 뒤 commit한 immutable process state입니다.

        Raises:
            StateHandleAuthorityError: Event가 다른 session 또는 actor를 대신하면 발생합니다.
            SessionKernelError: Event가 kernel invariant를 만족하지 못하면 발생합니다.
        """
        self._validate_event_authority(event)
        return self._kernel.apply(event, expected_revision=expected_revision)

    def _session_artifact_directory(self) -> Path:
        """Session-bound infrastructure store가 사용할 canonical artifact root를 반환합니다.

        이 private capability는 caller가 path를 조립하는 public state selector가 아닙니다.
        Artifact store가 이미 검증된 handle의 exact session 밖으로 벗어나지 않도록 kernel
        locator 사용을 한 곳에 캡슐화합니다.

        Returns:
            Bound exact session의 canonical artifact directory입니다.
        """
        return self._kernel._session_paths(self._binding.session_id).artifacts

    def _repository_control_root(self) -> Path:
        """Read-only infrastructure adapter에 bound repository root를 제공합니다.

        Caller-selected path를 받지 않으며 public state selector로 노출하지 않습니다.
        Repository source readback 같은 infrastructure store가 exact handle을 만든
        SessionLocator의 control root 밖으로 이동하지 못하게 합니다.

        Returns:
            Handle을 생성한 SessionLocator의 immutable absolute control root입니다.
        """
        return self._kernel._locator.control_root

    def _validate_state_authority(self, state: ProcessState) -> None:
        if state.session.id != self._binding.session_id:
            raise StateHandleAuthorityError("state session does not match runtime binding")
        if state.session.runtime is not self._binding.runtime:
            raise StateHandleAuthorityError("state runtime does not match runtime binding")
        if state.session.root_actor_id != self._binding.root_actor_id:
            raise StateHandleAuthorityError("state root actor does not match runtime binding")
        if self._binding.actor_id not in state.actors:
            raise StateHandleAuthorityError("bound actor does not exist in exact session")

    def _validate_event_authority(self, event: KernelEvent) -> None:
        if event.session_id != self._binding.session_id:
            raise StateHandleAuthorityError("event session does not match runtime binding")
        if isinstance(event, SessionStarted):
            if (
                not self._binding.is_root
                or event.runtime is not self._binding.runtime
                or event.root_actor_id != self._binding.actor_id
            ):
                raise StateHandleAuthorityError("only the bound root actor can start its session")
            return
        if isinstance(event, ActorStarted):
            actor_namespace = f"{self._binding.runtime.value}:"
            if (
                event.kind is not ActorKind.SUBAGENT
                or event.parent_actor_id != self._binding.actor_id
                or not str(event.actor_id).startswith(actor_namespace)
                or not str(event.actor_id).removeprefix(actor_namespace).strip()
            ):
                raise StateHandleAuthorityError("an actor can only start its own subagent child")
            return
        if isinstance(event, ActorStopped):
            if event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("an actor can only stop its own identity")
            return
        if isinstance(event, SessionEnded):
            if not self._binding.is_root or event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("only the bound root actor can end its session")
            return
        if isinstance(event, (SessionResumed, SessionCompacted, EffectAcknowledged)):
            if not self._binding.is_root or event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError(
                    "only the bound root actor can mutate lifecycle delivery state"
                )
            return
        if isinstance(event, EffectPrepared):
            if event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("prepared effect actor does not match bound actor")
            return
        if isinstance(event, WorkflowStarted):
            if event.owner_actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("workflow owner does not match bound actor")
            return
        if isinstance(event, (WorkflowAdvanced, WorkflowFinalized)):
            if event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("workflow mutation actor does not match binding")
            return
        if isinstance(
            event,
            (
                MaterialActionPrepared,
                MaterialActionToolStarted,
                MaterialActionToolObserved,
                MaterialActionAbandoned,
                MaterialActionResolved,
            ),
        ):
            if event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError(
                    "material-action mutation actor does not match binding"
                )
            if (
                isinstance(event, MaterialActionPrepared)
                and event.batch.kind is MaterialActionKind.EXTERNAL_MUTATION
            ):
                raise StateHandleAuthorityError(
                    "external material action requires typed external resource authority"
                )
            return
        if isinstance(
            event,
            (
                ForegroundTurnPrompted,
                ForegroundTurnProvisioned,
                ForegroundTurnToolObserved,
                ForegroundTurnYielded,
                ForegroundTurnInvalidated,
                ForegroundTurnClosed,
                ForegroundTurnReplaced,
            ),
        ):
            if event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError(
                    "foreground turn mutation actor does not match binding"
                )
            return
        if isinstance(event, DelegationAssigned):
            if event.owner_actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("delegation owner does not match bound actor")
            return
        if isinstance(event, DelegationCancelled):
            if event.owner_actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("delegation owner does not match bound actor")
            return
        if isinstance(event, DelegationReported):
            if event.reporter_actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("delegation reporter does not match bound actor")
            return
        if isinstance(event, DelegationConsumed):
            if event.consumer_actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("delegation consumer does not match bound actor")
            return
        if isinstance(
            event,
            (
                HarnessIncidentRecorded,
                HarnessIncidentResolved,
                HarnessIncidentEscalated,
                HarnessIncidentsRefreshed,
                HarnessIncidentEvidenceSuperseded,
            ),
        ):
            if event.actor_id != self._binding.actor_id:
                raise StateHandleAuthorityError("incident mutation actor does not match binding")
            return
        raise StateHandleAuthorityError(
            f"event authority is not defined for {type(event).__name__}"
        )
