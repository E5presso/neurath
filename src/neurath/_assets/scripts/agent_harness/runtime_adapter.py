"""Codex와 Claude Code lifecycle payload를 runtime-neutral identity로 정규화합니다."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum

from scripts.agent_harness.session_kernel import ActorId, ResumeId, SessionId, SessionRuntime


class RuntimeAdapterError(ValueError):
    """Runtime payload가 identity 또는 capability contract를 만족하지 않습니다."""


class RuntimeCapability(StrEnum):
    """Runtime이 실제로 제공한다고 검증된 외부 control capability입니다."""

    SESSION_START_ADDITIONAL_CONTEXT = "session-start-additional-context"
    """SessionStart 응답에 복구용 추가 context를 주입할 수 있습니다."""
    SUBAGENT_START_ADDITIONAL_CONTEXT = "subagent-start-additional-context"
    """SubagentStart 응답에 새 actor용 초기 context를 주입할 수 있습니다."""
    EXPERIMENTAL_THREAD_INJECTION = "experimental-thread-injection"
    """Codex thread에 실험적 외부 context를 주입할 수 있습니다."""
    SESSION_FORK_LINEAGE = "session-fork-lineage"
    """Runtime이 source/target session과 stable fork provenance를 함께 증명합니다."""
    SESSION_END = "session-end"
    """Runtime이 exact root session의 terminal lifecycle event를 제공합니다."""


class LifecycleCause(StrEnum):
    """Vendor event를 정규화한 coding-agent lifecycle 원인입니다."""

    STARTUP = "startup"
    """새 root session이 최초로 시작된 lifecycle입니다."""
    RESUME = "resume"
    """기존 runtime session의 실행을 다시 이어 가는 lifecycle입니다."""
    COMPACT = "compact"
    """Context compaction 이후 session state를 복구하는 lifecycle입니다."""
    FORK = "fork"
    """기존 session lineage에서 새 분기를 시작한 lifecycle입니다."""
    SUBAGENT_START = "subagent-start"
    """Root session 아래에 새 subagent actor가 시작된 lifecycle입니다."""
    END = "end"
    """Exact root session이 더는 resume되지 않는 terminal lifecycle입니다."""
    NORMAL_TURN = "normal-turn"
    """Session 경계를 바꾸지 않는 일반 turn lifecycle입니다."""


class _ImmutableValue:
    """생성 이후 attribute mutation을 막는 runtime value-object base입니다."""

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        """생성 완료된 runtime value의 attribute 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable value를 생성 후 변경하려 하면 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class RuntimeProvenance(_ImmutableValue):
    """Canonical identity의 근거가 된 vendor identifier를 손실 없이 보존합니다."""

    __slots__ = (
        "event_name",
        "raw_actor_id",
        "raw_parent_actor_id",
        "raw_resume_id",
        "raw_session_id",
        "raw_turn_id",
    )

    def __init__(
        self,
        *,
        event_name: str,
        raw_session_id: str,
        raw_resume_id: str | None,
        raw_actor_id: str | None,
        raw_parent_actor_id: str | None,
        raw_turn_id: str | None = None,
    ) -> None:
        """Vendor payload의 원본 identity와 event provenance를 고정합니다.

        Args:
            event_name: Envelope을 생성하게 한 vendor lifecycle event 이름입니다.
            raw_session_id: Vendor가 제공한 원본 root session 식별자입니다.
            raw_resume_id: Vendor가 제공했거나 adapter가 확인한 resume handle입니다.
            raw_actor_id: Event를 발생시킨 vendor actor 또는 thread 식별자입니다.
            raw_parent_actor_id: Actor lineage에서 부모가 된 vendor 식별자입니다.
            raw_turn_id: Host가 event와 결속한 optional native turn 식별자입니다.

        Raises:
            RuntimeAdapterError: Event 이름이나 root session 식별자가 비어 있으면
                발생합니다.
        """
        if not event_name.strip() or not raw_session_id.strip():
            raise RuntimeAdapterError("runtime provenance event and session must not be empty")
        object.__setattr__(self, "event_name", event_name.strip())
        object.__setattr__(self, "raw_session_id", raw_session_id.strip())
        object.__setattr__(self, "raw_resume_id", raw_resume_id)
        object.__setattr__(self, "raw_actor_id", raw_actor_id)
        object.__setattr__(self, "raw_parent_actor_id", raw_parent_actor_id)
        object.__setattr__(self, "raw_turn_id", raw_turn_id)

    event_name: str
    """Envelope을 생성하게 한 vendor lifecycle event 이름입니다."""
    raw_session_id: str
    """Canonical session identity의 근거인 vendor 원본 식별자입니다."""
    raw_resume_id: str | None
    """Resume lifecycle을 재연결할 때 vendor가 사용하는 원본 handle입니다."""
    raw_actor_id: str | None
    """Event를 발생시킨 vendor actor 또는 thread의 원본 식별자입니다."""
    raw_parent_actor_id: str | None
    """Vendor actor lineage에서 부모를 가리키는 원본 식별자입니다."""
    raw_turn_id: str | None
    """Vendor host가 lifecycle event와 결속한 원본 turn 식별자입니다."""


class RuntimeEnvelope(_ImmutableValue):
    """SessionKernel과 lifecycle service가 받는 validated runtime-neutral input입니다."""

    __slots__ = (
        "actor_id",
        "capabilities",
        "cause",
        "fork_provenance_id",
        "fork_source_session_id",
        "parent_actor_id",
        "provenance",
        "resume_id",
        "runtime",
        "session_id",
    )

    def __init__(
        self,
        *,
        runtime: SessionRuntime,
        session_id: SessionId,
        resume_id: ResumeId | None,
        actor_id: ActorId,
        parent_actor_id: ActorId | None,
        cause: LifecycleCause,
        capabilities: frozenset[RuntimeCapability],
        provenance: RuntimeProvenance,
        fork_source_session_id: SessionId | None = None,
        fork_provenance_id: str | None = None,
    ) -> None:
        """검증된 session, actor, lifecycle 정보를 immutable envelope로 묶습니다.

        Args:
            runtime: Payload를 제공한 coding-agent runtime 종류입니다.
            session_id: Runtime 경계를 넘어 비교할 canonical root session identity입니다.
            resume_id: 기존 runtime session을 다시 여는 데 쓰는 typed handle입니다.
            actor_id: 현재 event를 수행하는 root 또는 subagent의 canonical
                identity입니다.
            parent_actor_id: Actor lineage에서 바로 위 부모의 canonical identity입니다.
            cause: Vendor event에서 정규화한 lifecycle 전이 원인입니다.
            capabilities: 해당 runtime에서 실제로 확인된 외부 control capability
                집합입니다.
            provenance: Canonical identity를 도출한 vendor 원본 값과 event 근거입니다.
            fork_source_session_id: Runtime이 증명한 fork source exact session입니다.
            fork_provenance_id: Runtime이 제공한 stable fork lineage evidence입니다.

        Raises:
            RuntimeAdapterError: Fork lineage field가 일부만 있거나 fork 외 lifecycle에
                제공되면 발생합니다.
        """
        if (fork_source_session_id is None) != (fork_provenance_id is None):
            raise RuntimeAdapterError("fork source session and provenance must be paired")
        if fork_source_session_id is not None and cause is not LifecycleCause.FORK:
            raise RuntimeAdapterError("fork lineage is only valid for a fork lifecycle")
        normalized_fork_provenance = (
            None if fork_provenance_id is None else fork_provenance_id.strip()
        )
        if fork_provenance_id is not None and not normalized_fork_provenance:
            raise RuntimeAdapterError("fork provenance must not be empty")
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "resume_id", resume_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "parent_actor_id", parent_actor_id)
        object.__setattr__(self, "cause", cause)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "fork_source_session_id", fork_source_session_id)
        object.__setattr__(self, "fork_provenance_id", normalized_fork_provenance)

    runtime: SessionRuntime
    """Payload와 lifecycle control을 소유한 coding-agent runtime입니다."""
    session_id: SessionId
    """Actor들과 resume 시도를 묶는 canonical root session identity입니다."""
    resume_id: ResumeId | None
    """기존 runtime session을 다시 열 때 사용하는 typed resume handle입니다."""
    actor_id: ActorId
    """현재 lifecycle event를 수행하는 root 또는 subagent identity입니다."""
    parent_actor_id: ActorId | None
    """Actor lineage에서 현재 actor의 바로 위 부모 identity입니다."""
    cause: LifecycleCause
    """Vendor event에서 정규화한 session lifecycle 전이 원인입니다."""
    capabilities: frozenset[RuntimeCapability]
    """Runtime probe로 실제 제공 여부를 확인한 control capability 집합입니다."""
    provenance: RuntimeProvenance
    """Canonical identity와 lifecycle 판단을 추적할 vendor 원본 근거입니다."""
    fork_source_session_id: SessionId | None
    """Capability-proven fork에서만 존재하는 source exact session입니다."""
    fork_provenance_id: str | None
    """Capability-proven fork에서만 존재하는 stable lineage evidence입니다."""


class RuntimeAdapter(ABC):
    """Vendor payload 정규화가 구현해야 하는 explicit port입니다."""

    @abstractmethod
    def normalize(self, payload: Mapping[str, object]) -> RuntimeEnvelope:
        """Vendor payload를 validated runtime-neutral envelope로 변환합니다.

        Args:
            payload: Vendor hook 또는 app-server가 전달한 lifecycle payload입니다.

        Returns:
            Session, actor, lifecycle identity를 정규화한 immutable envelope입니다.

        Raises:
            RuntimeAdapterError: 필수 identity가 없거나 payload 의미가 모호하면
                발생합니다.
        """


class _RuntimePayloadReader:
    """Raw mapping 검증을 adapter 사이에서 일관되게 적용합니다."""

    def required_string(self, payload: Mapping[str, object], key: str) -> str:
        """Payload에서 필수 non-empty string을 공백 없이 읽습니다.

        Args:
            payload: Vendor lifecycle field를 담은 raw mapping입니다.
            key: 필수 string을 읽을 payload key입니다.

        Returns:
            앞뒤 공백을 제거한 필수 field 값입니다.

        Raises:
            RuntimeAdapterError: Field가 없거나 비어 있거나 string이 아니면
                발생합니다.
        """
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeAdapterError(f"runtime payload requires non-empty {key}")
        return value.strip()

    def optional_string(self, payload: Mapping[str, object], key: str) -> str | None:
        """Payload의 optional string을 읽되 잘못 표현된 값은 거부합니다.

        Args:
            payload: Vendor lifecycle field를 담은 raw mapping입니다.
            key: Optional string을 읽을 payload key입니다.

        Returns:
            Field가 없으면 `None`, 있으면 앞뒤 공백을 제거한 값입니다.

        Raises:
            RuntimeAdapterError: 존재하는 field가 비었거나 string이 아니면
                발생합니다.
        """
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeAdapterError(f"runtime payload {key} must be a non-empty string")
        return value.strip()

    def capability_strings(self, payload: Mapping[str, object]) -> frozenset[str]:
        """Vendor capability collection을 중복 없는 raw string 집합으로 읽습니다.

        Args:
            payload: 선택적인 capability collection을 담은 raw mapping입니다.

        Returns:
            각 capability의 공백을 제거하고 중복을 없앤 immutable 집합입니다.

        Raises:
            RuntimeAdapterError: Collection 또는 그 원소의 형식이 올바르지 않으면
                발생합니다.
        """
        value = payload.get("capabilities", ())
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise RuntimeAdapterError("runtime payload capabilities must be a collection")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise RuntimeAdapterError("runtime payload capabilities must contain strings")
        return frozenset(str(item).strip() for item in value)

    def lifecycle_cause(self, event_name: str, source: str | None) -> LifecycleCause:
        """Vendor event와 SessionStart source를 stable lifecycle cause로 정규화합니다.

        Args:
            event_name: Vendor hook 또는 app-server lifecycle event 이름입니다.
            source: SessionStart가 발생한 startup, resume, compact, fork 근거입니다.

        Returns:
            Runtime별 event 표현을 통합한 lifecycle 원인입니다.

        Raises:
            RuntimeAdapterError: 지원하지 않는 SessionStart source이면 발생합니다.
        """
        if event_name == "SubagentStart":
            return LifecycleCause.SUBAGENT_START
        if event_name == "SessionEnd":
            return LifecycleCause.END
        if event_name != "SessionStart":
            return LifecycleCause.NORMAL_TURN
        mapping = {
            "startup": LifecycleCause.STARTUP,
            "clear": LifecycleCause.STARTUP,
            "resume": LifecycleCause.RESUME,
            "compact": LifecycleCause.COMPACT,
            "fork": LifecycleCause.FORK,
        }
        if source is None:
            return LifecycleCause.STARTUP
        try:
            return mapping[source]
        except KeyError as error:
            raise RuntimeAdapterError(f"unsupported SessionStart source: {source}") from error


class ClaudeCodeRuntimeAdapter(RuntimeAdapter):
    """Claude Code hook payload의 root session과 subagent identity를 분리합니다."""

    def __init__(self) -> None:
        """Claude Code payload field를 검증할 reader를 준비합니다."""
        self._reader = _RuntimePayloadReader()

    def normalize(self, payload: Mapping[str, object]) -> RuntimeEnvelope:
        """Claude Code hook payload를 canonical RuntimeEnvelope로 변환합니다.

        Args:
            payload: Claude Code hook이 전달한 session 또는 subagent lifecycle
                payload입니다.

        Returns:
            Root session과 actor lineage를 분리한 immutable runtime envelope입니다.

        Raises:
            RuntimeAdapterError: Field 형식이나 SessionStart source가 잘못됐거나 root
                event에 부모가 선언되면 발생합니다.
        """
        event_name = self._reader.required_string(payload, "hook_event_name")
        raw_session_id = self._reader.required_string(payload, "session_id")
        raw_actor_id = self._reader.optional_string(payload, "agent_id")
        raw_parent_id = self._reader.optional_string(payload, "parent_agent_id")
        source = self._reader.optional_string(payload, "source")
        cause = self._reader.lifecycle_cause(event_name, source)
        session_id = SessionId(raw_session_id)
        root_actor_id = ActorId(f"claude-code:session:{raw_session_id}")
        actor_id = root_actor_id if raw_actor_id is None else ActorId(f"claude-code:{raw_actor_id}")
        parent_actor_id = self._parent_actor_id(raw_parent_id, raw_actor_id, root_actor_id)
        raw_resume_id = raw_session_id if cause is LifecycleCause.RESUME else None
        capabilities = self._capabilities(event_name)
        return RuntimeEnvelope(
            runtime=SessionRuntime.CLAUDE_CODE,
            session_id=session_id,
            resume_id=None if raw_resume_id is None else ResumeId(raw_resume_id),
            actor_id=actor_id,
            parent_actor_id=parent_actor_id,
            cause=cause,
            capabilities=capabilities,
            provenance=RuntimeProvenance(
                event_name=event_name,
                raw_session_id=raw_session_id,
                raw_resume_id=raw_resume_id,
                raw_actor_id=raw_actor_id,
                raw_parent_actor_id=raw_parent_id,
            ),
        )

    def _parent_actor_id(
        self,
        raw_parent_id: str | None,
        raw_actor_id: str | None,
        root_actor_id: ActorId,
    ) -> ActorId | None:
        if raw_actor_id is None:
            if raw_parent_id is not None:
                raise RuntimeAdapterError("root Claude event cannot declare parent_agent_id")
            return None
        if raw_parent_id is None:
            return None
        return ActorId(f"claude-code:{raw_parent_id}")

    def _capabilities(self, event_name: str) -> frozenset[RuntimeCapability]:
        if event_name == "SessionStart":
            return frozenset({RuntimeCapability.SESSION_START_ADDITIONAL_CONTEXT})
        if event_name == "SubagentStart":
            return frozenset({RuntimeCapability.SUBAGENT_START_ADDITIONAL_CONTEXT})
        if event_name == "SessionEnd":
            return frozenset({RuntimeCapability.SESSION_END})
        return frozenset()


class CodexRuntimeAdapter(RuntimeAdapter):
    """Codex thread lineage와 root session/resume identity를 분리합니다."""

    def __init__(self) -> None:
        """Codex payload field와 capability를 검증할 reader를 준비합니다."""
        self._reader = _RuntimePayloadReader()

    def normalize(self, payload: Mapping[str, object]) -> RuntimeEnvelope:
        """Codex hook/app-server payload를 canonical RuntimeEnvelope로 변환합니다.

        Args:
            payload: Codex가 전달한 session, thread, capability lifecycle payload입니다.

        Returns:
            Root session, thread lineage, resume handle을 분리한 immutable envelope입니다.

        Raises:
            RuntimeAdapterError: Field나 capability 형식, SessionStart source가
                잘못됐거나 actor와 thread identity가 충돌하면 발생합니다.
        """
        event_name = self._reader.required_string(payload, "hook_event_name")
        raw_session_id = self._reader.required_string(payload, "session_id")
        raw_thread_id = self._reader.optional_string(payload, "thread_id")
        raw_agent_id = self._reader.optional_string(payload, "agent_id")
        if raw_thread_id is not None and raw_agent_id is not None and raw_thread_id != raw_agent_id:
            raise RuntimeAdapterError("Codex agent_id conflicts with thread_id")
        raw_actor_id = raw_agent_id or raw_thread_id
        raw_actor_alias = self._reader.optional_string(payload, "actor_id")
        if raw_actor_alias is not None and raw_actor_alias != raw_actor_id:
            raise RuntimeAdapterError("Codex actor_id conflicts with child identity")
        raw_parent_id = self._reader.optional_string(payload, "parent_thread_id")
        raw_turn_id = self._reader.optional_string(payload, "turn_id")
        raw_resume_id = self._reader.optional_string(payload, "resume_id")
        raw_fork_source_session_id = self._reader.optional_string(
            payload,
            "source_session_id",
        )
        raw_fork_provenance_id = self._reader.optional_string(
            payload,
            "fork_provenance_id",
        )
        source = self._reader.optional_string(payload, "source")
        cause = self._reader.lifecycle_cause(event_name, source)
        actor_id = (
            ActorId(f"codex:session:{raw_session_id}")
            if raw_actor_id is None
            else ActorId(f"codex:{raw_actor_id}")
        )
        parent_actor_id = None if raw_parent_id is None else ActorId(f"codex:{raw_parent_id}")
        raw_capabilities = self._reader.capability_strings(payload)
        capabilities = self._capabilities(
            event_name,
            cause,
            raw_capabilities,
            raw_fork_source_session_id,
            raw_fork_provenance_id,
        )
        return RuntimeEnvelope(
            runtime=SessionRuntime.CODEX,
            session_id=SessionId(raw_session_id),
            resume_id=None if raw_resume_id is None else ResumeId(raw_resume_id),
            actor_id=actor_id,
            parent_actor_id=parent_actor_id,
            cause=cause,
            capabilities=capabilities,
            provenance=RuntimeProvenance(
                event_name=event_name,
                raw_session_id=raw_session_id,
                raw_resume_id=raw_resume_id,
                raw_actor_id=raw_actor_id,
                raw_parent_actor_id=raw_parent_id,
                raw_turn_id=raw_turn_id,
            ),
            fork_source_session_id=(
                None
                if raw_fork_source_session_id is None
                else SessionId(raw_fork_source_session_id)
            ),
            fork_provenance_id=raw_fork_provenance_id,
        )

    def _capabilities(
        self,
        event_name: str,
        cause: LifecycleCause,
        raw_capabilities: frozenset[str],
        raw_fork_source_session_id: str | None,
        raw_fork_provenance_id: str | None,
    ) -> frozenset[RuntimeCapability]:
        normalized: set[RuntimeCapability] = set()
        if event_name == "SessionStart":
            normalized.add(RuntimeCapability.SESSION_START_ADDITIONAL_CONTEXT)
        if event_name == "SessionEnd":
            normalized.add(RuntimeCapability.SESSION_END)
        if event_name == "SubagentStart" or "subagent_start_additional_context" in raw_capabilities:
            normalized.add(RuntimeCapability.SUBAGENT_START_ADDITIONAL_CONTEXT)
        if "experimental_thread_injection" in raw_capabilities:
            normalized.add(RuntimeCapability.EXPERIMENTAL_THREAD_INJECTION)
        if "session_fork_lineage" in raw_capabilities:
            if (
                cause is not LifecycleCause.FORK
                or raw_fork_source_session_id is None
                or raw_fork_provenance_id is None
            ):
                raise RuntimeAdapterError(
                    "session_fork_lineage requires a fork source and provenance"
                )
            normalized.add(RuntimeCapability.SESSION_FORK_LINEAGE)
        return frozenset(normalized)
