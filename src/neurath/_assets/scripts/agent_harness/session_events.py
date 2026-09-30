"""Typed session commands validated before entering the reducer."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from scripts.agent_harness.material_action import (
    AdaptiveActionBinding,
    MaterialActionBatch,
    MaterialActionKind,
    MaterialActionResolution,
    ObservableExpectation,
    ToolInvocation,
    ToolReceipt,
)
from scripts.agent_harness.session_model import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStatus,
    DelegationId,
    DelegationResult,
    DelegationTopologyPolicy,
    EffectId,
    ForegroundPromptAuthorityContext,
    ForegroundTurnReceipt,
    HarnessIncidentRecord,
    HarnessRegressionReceipt,
    ImmutableValue,
    IncidentId,
    InvalidSessionState,
    MonitorWorkflowStopProjection,
    OutboxEffect,
    ResumeId,
    SessionId,
    SessionRecord,
    SessionRuntime,
    TransitionRejected,
    WorkflowId,
    WorkflowStatus,
)


class KernelEvent(ImmutableValue):
    """Closed SessionKernel event family의 base value입니다."""

    __slots__ = ("idempotency_key", "session_id")

    def __init__(self, session_id: SessionId, idempotency_key: str) -> None:
        """Event를 exact session에 귀속시키고 caller-provided idempotency key를 정규화합니다.

        Args:
            session_id: Event가 읽고 갱신할 exact session identity입니다.
            idempotency_key: 동일 logical event를 식별하는 비어 있지 않은 key입니다.

        Raises:
            TransitionRejected: Idempotency key가 공백뿐이면 발생합니다.
        """
        if not idempotency_key.strip():
            raise TransitionRejected("idempotency_key must not be empty")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "idempotency_key", idempotency_key.strip())

    session_id: SessionId
    """Event가 다른 session state를 변경하지 못하도록 고정하는 identity입니다."""

    idempotency_key: str
    """동일 logical event를 나타내도록 caller가 부여한 정규화된 key입니다."""


class SessionStarted(KernelEvent):
    """Workflow 없이 새 session과 root actor를 초기화합니다."""

    __slots__ = (
        "effect",
        "lifecycle_provenance_id",
        "parent_session_id",
        "resume_id",
        "root_actor_id",
        "runtime",
    )

    def __init__(
        self,
        session_id: SessionId,
        resume_id: ResumeId,
        runtime: SessionRuntime,
        root_actor_id: ActorId,
        idempotency_key: str,
        parent_session_id: SessionId | None = None,
        lifecycle_provenance_id: str | None = None,
        effect: OutboxEffect | None = None,
    ) -> None:
        """새 session과 유일한 root actor를 초기화하는 event를 구성합니다.

        Args:
            session_id: 새 root execution tree의 canonical identity입니다.
            resume_id: Runtime이 exact continuation에 사용할 opaque handle입니다.
            runtime: Session identity와 resume handle을 발급한 runtime입니다.
            root_actor_id: Session 시작과 함께 생성할 유일한 root actor identity입니다.
            idempotency_key: 동일 session-start event에 caller가 부여한 key입니다.
            parent_session_id: Fork target이 복사할 exact source session입니다.
            lifecycle_provenance_id: Fork lineage를 증명하는 runtime event identity입니다.
            effect: Startup commit과 원자적으로 pending 처리할 optional adapter effect입니다.

        Raises:
            TransitionRejected: Idempotency key가 비었거나 fork lineage 쌍이
                유효하지 않으면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        try:
            normalized_parent, normalized_provenance = SessionRecord._normalize_lineage(
                session_id,
                parent_session_id,
                lifecycle_provenance_id,
            )
        except InvalidSessionState as error:
            raise TransitionRejected(str(error)) from error
        object.__setattr__(self, "resume_id", resume_id)
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "root_actor_id", root_actor_id)
        object.__setattr__(self, "parent_session_id", normalized_parent)
        object.__setattr__(self, "lifecycle_provenance_id", normalized_provenance)
        if effect is not None and effect.actor_id != root_actor_id:
            raise TransitionRejected("startup effect actor must be the root actor")
        object.__setattr__(self, "effect", effect)

    resume_id: ResumeId
    """Runtime exact continuation에 사용하는 opaque resume handle입니다."""

    runtime: SessionRuntime
    """새 session identity와 resume handle을 발급한 runtime입니다."""

    root_actor_id: ActorId
    """새 session actor topology에 함께 생성할 유일한 root identity입니다."""

    parent_session_id: SessionId | None
    """Fork target에서만 존재하는 exact source session identity입니다."""

    lifecycle_provenance_id: str | None
    """Parent lineage와 target initialization을 결속하는 evidence identity입니다."""

    effect: OutboxEffect | None
    """Startup snapshot과 함께 commit할 optional pending adapter effect입니다."""


class SessionResumed(KernelEvent):
    """Exact session resume handle과 rehydration delivery를 원자적으로 갱신합니다."""

    __slots__ = ("actor_id", "effect", "lifecycle_provenance_id", "resume_id")

    def __init__(
        self,
        *,
        session_id: SessionId,
        actor_id: ActorId,
        resume_id: ResumeId,
        lifecycle_provenance_id: str,
        idempotency_key: str,
        effect: OutboxEffect,
    ) -> None:
        """Root-authorized resume lifecycle event를 구성합니다.

        Args:
            session_id: Resume할 exact root execution tree identity입니다.
            actor_id: Rehydration effect 실행을 소유하는 exact actor입니다.
            resume_id: Runtime이 발급한 opaque continuation handle입니다.
            lifecycle_provenance_id: Resume와 source lifecycle을 결속하는 evidence identity입니다.
            idempotency_key: 동일 resume event를 중복 적용하지 않게 하는 key입니다.
            effect: 같은 actor가 실행할 pending rehydration adapter effect입니다.

        Raises:
            TransitionRejected: Provenance가 비었거나 effect actor가 다르면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        normalized_provenance = lifecycle_provenance_id.strip()
        if not normalized_provenance:
            raise TransitionRejected("resume lifecycle provenance must not be empty")
        if effect.actor_id != actor_id:
            raise TransitionRejected("resume effect actor must match lifecycle actor")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "resume_id", resume_id)
        object.__setattr__(self, "lifecycle_provenance_id", normalized_provenance)
        object.__setattr__(self, "effect", effect)

    actor_id: ActorId
    """Resume lifecycle과 effect execution을 소유하는 exact actor입니다."""

    resume_id: ResumeId
    """Runtime exact continuation에 사용할 opaque resume handle입니다."""

    lifecycle_provenance_id: str
    """Resume event와 원본 lifecycle transition을 결속하는 evidence identity입니다."""

    effect: OutboxEffect
    """같은 snapshot commit에 포함할 pending rehydration adapter effect입니다."""


class SessionCompacted(KernelEvent):
    """Compaction 경계와 exact-session rehydration delivery를 durable하게 기록합니다."""

    __slots__ = ("actor_id", "effect", "lifecycle_provenance_id")

    def __init__(
        self,
        *,
        session_id: SessionId,
        actor_id: ActorId,
        lifecycle_provenance_id: str,
        idempotency_key: str,
        effect: OutboxEffect,
    ) -> None:
        """Root-authorized compact lifecycle event를 구성합니다.

        Args:
            session_id: Compaction 경계를 기록할 exact root execution tree identity입니다.
            actor_id: Compaction rehydration effect 실행을 소유하는 exact actor입니다.
            lifecycle_provenance_id: Compact와 source lifecycle을 결속하는 evidence identity입니다.
            idempotency_key: 동일 compact event를 중복 적용하지 않게 하는 key입니다.
            effect: 같은 actor가 실행할 pending compaction adapter effect입니다.

        Raises:
            TransitionRejected: Provenance가 비었거나 effect actor가 다르면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        normalized_provenance = lifecycle_provenance_id.strip()
        if not normalized_provenance:
            raise TransitionRejected("compact lifecycle provenance must not be empty")
        if effect.actor_id != actor_id:
            raise TransitionRejected("compact effect actor must match lifecycle actor")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "lifecycle_provenance_id", normalized_provenance)
        object.__setattr__(self, "effect", effect)

    actor_id: ActorId
    """Compaction lifecycle과 effect execution을 소유하는 exact actor입니다."""

    lifecycle_provenance_id: str
    """Compact event와 원본 lifecycle transition을 결속하는 evidence identity입니다."""

    effect: OutboxEffect
    """같은 snapshot commit에 포함할 pending compaction adapter effect입니다."""


class ActorStarted(KernelEvent):
    """동일 session의 actor map에 root 또는 subagent를 추가합니다."""

    __slots__ = (
        "actor_id",
        "effect",
        "kind",
        "lineage_assurance",
        "parent_actor_id",
    )

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        parent_actor_id: ActorId | None,
        kind: ActorKind,
        idempotency_key: str,
        effect: OutboxEffect | None = None,
        lineage_assurance: ActorLineageAssurance = ActorLineageAssurance.UNATTESTED,
    ) -> None:
        """기존 session topology에 actor를 추가하는 event를 구성합니다.

        Args:
            session_id: Actor를 추가할 exact session identity입니다.
            actor_id: Session actor map에 새로 등록할 identity입니다.
            parent_actor_id: Subagent lineage를 연결할 기존 parent identity입니다.
            kind: 새 actor의 root 또는 subagent topology role입니다.
            idempotency_key: 동일 actor-start event에 caller가 부여한 key입니다.
            effect: Actor start와 함께 pending 처리할 optional assignment delivery입니다.
            lineage_assurance: Host가 parent identity를 증명한 수준입니다.

        Raises:
            TransitionRejected: Idempotency key가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "parent_actor_id", parent_actor_id)
        object.__setattr__(self, "kind", kind)
        if not isinstance(lineage_assurance, ActorLineageAssurance):
            raise TransitionRejected("actor lineage assurance must be typed")
        object.__setattr__(self, "lineage_assurance", lineage_assurance)
        if effect is not None and effect.actor_id != actor_id:
            raise TransitionRejected("actor-start effect must target the new actor")
        object.__setattr__(self, "effect", effect)

    actor_id: ActorId
    """Session actor map에 등록할 actor identity입니다."""

    parent_actor_id: ActorId | None
    """Subagent lineage를 연결하는 parent identity이며 root에는 존재하지 않습니다."""

    kind: ActorKind
    """추가할 actor의 root 또는 delegated subagent topology role입니다."""

    lineage_assurance: ActorLineageAssurance
    """Parent pointer에 대한 typed host provenance 수준입니다."""

    effect: OutboxEffect | None
    """Actor topology와 원자적으로 commit할 optional pending delivery입니다."""


class ActorResumed(KernelEvent):
    """Host lifecycle resumes an attested child at an exact new native turn."""

    __slots__ = ("actor_id", "parent_actor_id", "expected_turn_revision", "vendor_turn_id")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        parent_actor_id: ActorId,
        expected_turn_revision: int,
        vendor_turn_id: str,
        idempotency_key: str,
    ) -> None:
        super().__init__(session_id, idempotency_key)
        if not isinstance(vendor_turn_id, str) or not vendor_turn_id.strip():
            raise TransitionRejected("actor resume requires a native turn identity")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "parent_actor_id", parent_actor_id)
        object.__setattr__(self, "expected_turn_revision", expected_turn_revision)
        object.__setattr__(self, "vendor_turn_id", vendor_turn_id)


class ActorStopped(KernelEvent):
    """Active session의 actor를 terminal lifecycle로 fencing합니다."""

    __slots__ = ("actor_id", "terminal_status")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        terminal_status: ActorStatus,
        idempotency_key: str,
    ) -> None:
        """Actor가 후속 operational mutation에 참여하지 못하게 하는 event입니다.

        Args:
            session_id: Actor가 속한 exact session identity입니다.
            actor_id: Session topology에서 terminal로 바꿀 actor identity입니다.
            terminal_status: Actor 실행 중단 또는 영구 retirement를 나타냅니다.
            idempotency_key: 동일 actor-stop event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Active/idle status를 terminal 결과로 요청하면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if terminal_status not in {ActorStatus.STOPPED, ActorStatus.RETIRED}:
            raise TransitionRejected("actor stop requires a terminal status")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "terminal_status", terminal_status)

    actor_id: ActorId
    """Session topology에 남지만 후속 mutation에서 fencing될 actor입니다."""

    terminal_status: ActorStatus
    """Actor의 종료가 temporary stop인지 permanent retirement인지 나타냅니다."""


class SessionEnded(KernelEvent):
    """Root actor의 exact session을 종료하고 모든 actor를 retire합니다."""

    __slots__ = ("actor_id",)

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        idempotency_key: str,
    ) -> None:
        """Session을 terminal state로 바꾸는 root-authorized event를 구성합니다.

        Args:
            session_id: 종료할 exact root execution tree identity입니다.
            actor_id: Session 종료를 요청하는 root actor identity입니다.
            idempotency_key: 동일 session-end event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Idempotency key가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)

    actor_id: ActorId
    """Session lifecycle 종료 권한을 확인할 root actor identity입니다."""


class EffectAcknowledged(KernelEvent):
    """Runtime adapter가 exact pending effect 실행을 완료했음을 기록합니다."""

    __slots__ = ("actor_id", "effect_id")

    def __init__(
        self,
        *,
        session_id: SessionId,
        actor_id: ActorId,
        effect_id: EffectId,
        idempotency_key: str,
    ) -> None:
        """ACK authority와 pending effect identity를 구성합니다.

        Args:
            session_id: Pending outbox를 소유하는 exact session identity입니다.
            actor_id: Effect 실행과 ACK를 소유하는 exact actor입니다.
            effect_id: 성공적으로 실행된 pending effect identity입니다.
            idempotency_key: 동일 acknowledgement를 중복 적용하지 않게 하는 key입니다.

        Raises:
            TransitionRejected: Idempotency key가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "effect_id", effect_id)

    actor_id: ActorId
    """Effect execution을 소유한 exact actor입니다."""

    effect_id: EffectId
    """성공적으로 실행되어 pending map에서 제거할 effect입니다."""


class EffectPrepared(KernelEvent):
    """External side effect 전에 actor-owned recoverable intent를 outbox에 기록합니다."""

    __slots__ = ("actor_id", "effect")

    def __init__(
        self,
        *,
        session_id: SessionId,
        actor_id: ActorId,
        effect: OutboxEffect,
        idempotency_key: str,
    ) -> None:
        """Pending effect와 mutation authority를 같은 session event로 결속합니다.

        Args:
            session_id: Recoverable intent를 소유할 exact session입니다.
            actor_id: External effect와 ACK를 소유하는 active actor입니다.
            effect: Commit 뒤 실행할 content-addressed pending instruction입니다.
            idempotency_key: 동일 preparation retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Effect actor와 event actor가 다르면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if effect.actor_id != actor_id:
            raise TransitionRejected("prepared effect actor must match lifecycle actor")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "effect", effect)

    actor_id: ActorId
    """Pending external effect와 acknowledgement를 소유하는 actor입니다."""

    effect: OutboxEffect
    """External mutation 전에 durable하게 commit할 recoverable instruction입니다."""


class WorkflowStarted(KernelEvent):
    """Session workflow map에 owner-bound active aggregate를 추가합니다."""

    __slots__ = ("goal", "kind", "owner_actor_id", "payload", "workflow_id")

    def __init__(
        self,
        session_id: SessionId,
        workflow_id: WorkflowId,
        owner_actor_id: ActorId,
        kind: str,
        goal: str | None,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> None:
        """Workflow의 identity, authority, optional goal, 초기 payload를 구성합니다.

        Args:
            session_id: Workflow가 속할 exact session identity입니다.
            workflow_id: 같은 session의 다른 workflow와 구분할 identity입니다.
            owner_actor_id: Workflow의 후속 transition을 소유할 actor입니다.
            kind: Persisted payload를 해석할 workflow implementation 종류입니다.
            goal: Session goal과 분리된 optional workflow 실행 목표입니다.
            payload: Workflow가 시작할 때 소유할 operational projection입니다.
            idempotency_key: 동일 workflow-start event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Kind, goal, payload key, idempotency key가 invalid하면
                발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if not kind.strip():
            raise TransitionRejected("workflow kind must not be empty")
        if goal is not None and not goal.strip():
            raise TransitionRejected("workflow goal must be null or non-empty")
        if any(not isinstance(key, str) for key in payload):
            raise TransitionRejected("workflow payload keys must be strings")
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "kind", kind.strip())
        object.__setattr__(self, "goal", None if goal is None else goal.strip())
        object.__setattr__(self, "payload", MappingProxyType(dict(payload)))

    workflow_id: WorkflowId
    """Session workflow map에 새로 등록할 identity입니다."""

    owner_actor_id: ActorId
    """Workflow의 advance와 finalize 권한을 소유할 actor입니다."""

    kind: str
    """Workflow-specific payload를 해석할 implementation 종류입니다."""

    goal: str | None
    """Workflow aggregate에만 귀속되는 optional 실행 목표입니다."""

    payload: Mapping[str, object]
    """Workflow의 revision zero에서 시작할 operational projection입니다."""


class WorkflowAdvanced(KernelEvent):
    """Owner actor가 workflow-local revision CAS로 payload를 갱신합니다."""

    __slots__ = ("actor_id", "expected_workflow_revision", "payload", "workflow_id")

    def __init__(
        self,
        session_id: SessionId,
        workflow_id: WorkflowId,
        actor_id: ActorId,
        expected_workflow_revision: int,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> None:
        """Workflow의 원본 revision과 대체할 payload를 함께 제출합니다.

        Args:
            session_id: Workflow가 속한 exact session identity입니다.
            workflow_id: Payload를 갱신할 workflow aggregate identity입니다.
            actor_id: Workflow owner와 일치해야 하는 mutation actor입니다.
            expected_workflow_revision: Caller가 읽은 workflow-local 원본 version입니다.
            payload: CAS 성공 시 현재 projection을 대체할 object입니다.
            idempotency_key: 동일 workflow-advance event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Revision이 음수이거나 payload key가 문자열이
                아니면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise TransitionRejected("workflow revision must be a non-negative integer")
        if any(not isinstance(key, str) for key in payload):
            raise TransitionRejected("workflow payload keys must be strings")
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_workflow_revision", expected_workflow_revision)
        object.__setattr__(self, "payload", MappingProxyType(dict(payload)))

    workflow_id: WorkflowId
    """Payload를 갱신할 exact workflow aggregate identity입니다."""

    actor_id: ActorId
    """Workflow owner 권한과 lifecycle fencing을 확인할 actor입니다."""

    expected_workflow_revision: int
    """Workflow 이외의 session mutation과 무관하게 비교할 원본 version입니다."""

    payload: Mapping[str, object]
    """CAS 성공 시 workflow의 현재 operational state를 대체할 object입니다."""


class ReservedSkillStateAdvanced(WorkflowAdvanced):
    """Typed skill-state store가 소유하는 reserved namespace CAS입니다."""

    __slots__ = ("reserved_namespaces",)

    def __init__(
        self,
        session_id: SessionId,
        workflow_id: WorkflowId,
        actor_id: ActorId,
        expected_workflow_revision: int,
        payload: Mapping[str, object],
        idempotency_key: str,
        *,
        reserved_namespaces: frozenset[str],
    ) -> None:
        """Exact typed owner namespace와 기존 workflow CAS input을 결합합니다.

        Args:
            session_id: Reserved mutation이 속한 exact session identity입니다.
            workflow_id: Typed namespace를 소유하는 workflow identity입니다.
            actor_id: Workflow owner 권한을 증명할 mutation actor입니다.
            expected_workflow_revision: CAS admission에 사용한 workflow-local 원본입니다.
            payload: Reducer가 reserved namespace 변경 권한과 대조할 workflow 후보입니다.
            idempotency_key: 같은 reserved mutation replay를 식별하는 caller key입니다.
            reserved_namespaces: Typed store가 이번 transition에서 변경 권한을 주장하는
                namespace입니다.

        Raises:
            TransitionRejected: Workflow CAS 입력이 invalid하거나 reserved namespace 집합이
                비었거나 공백 이름을 포함하면 발생합니다.
        """
        super().__init__(
            session_id,
            workflow_id,
            actor_id,
            expected_workflow_revision,
            payload,
            idempotency_key,
        )
        if not reserved_namespaces or any(not value.strip() for value in reserved_namespaces):
            raise TransitionRejected("reserved skill-state namespaces must be non-empty")
        object.__setattr__(self, "reserved_namespaces", reserved_namespaces)

    reserved_namespaces: frozenset[str]
    """Typed store가 invariant를 검증한 exact skill-state namespace입니다."""


class WorkflowFinalized(KernelEvent):
    """Owner actor가 workflow-local CAS 후 aggregate를 terminal로 바꿉니다."""

    __slots__ = (
        "actor_id",
        "expected_workflow_revision",
        "payload",
        "terminal_status",
        "workflow_id",
    )

    def __init__(
        self,
        session_id: SessionId,
        workflow_id: WorkflowId,
        actor_id: ActorId,
        expected_workflow_revision: int,
        terminal_status: WorkflowStatus,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> None:
        """Workflow의 마지막 payload와 completed/failed 결과를 제출합니다.

        Args:
            session_id: Workflow가 속한 exact session identity입니다.
            workflow_id: Terminal transition을 적용할 workflow identity입니다.
            actor_id: Workflow owner와 일치해야 하는 mutation actor입니다.
            expected_workflow_revision: Caller가 읽은 workflow-local 원본 version입니다.
            terminal_status: Completed 또는 failed로 고정할 최종 lifecycle입니다.
            payload: Final evidence를 포함할 마지막 operational projection입니다.
            idempotency_key: 동일 workflow-finalize event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Active status, invalid revision, non-string payload key를
                제출하면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if terminal_status is WorkflowStatus.ACTIVE:
            raise TransitionRejected("workflow finalization requires a terminal status")
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise TransitionRejected("workflow revision must be a non-negative integer")
        if any(not isinstance(key, str) for key in payload):
            raise TransitionRejected("workflow payload keys must be strings")
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_workflow_revision", expected_workflow_revision)
        object.__setattr__(self, "terminal_status", terminal_status)
        object.__setattr__(self, "payload", MappingProxyType(dict(payload)))

    workflow_id: WorkflowId
    """Terminal lifecycle로 고정할 exact workflow identity입니다."""

    actor_id: ActorId
    """Workflow owner 권한과 lifecycle fencing을 확인할 actor입니다."""

    expected_workflow_revision: int
    """Finalize CAS가 비교할 workflow-local 원본 version입니다."""

    terminal_status: WorkflowStatus
    """Workflow가 후속 transition을 받지 않게 하는 최종 lifecycle입니다."""

    payload: Mapping[str, object]
    """Workflow에 남을 final operational projection입니다."""


class PostCleanupFinalized(KernelEvent):
    """Authenticated issuer completes an already-cleaned worker without acting as it."""

    __slots__ = ("workflow_id", "actor_id", "original_owner", "expected_workflow_revision",
                 "payload", "admission_reference")
    terminal_status = WorkflowStatus.COMPLETED

    def __init__(self, *, session_id, workflow_id, actor_id, original_owner,
                 expected_workflow_revision, payload, admission_reference, idempotency_key):
        """Retain the actual issuer separately from the original workflow owner."""
        super().__init__(session_id, idempotency_key)
        for name, value in (("workflow_id", workflow_id), ("actor_id", actor_id),
                ("original_owner", original_owner), ("expected_workflow_revision", expected_workflow_revision),
                ("payload", MappingProxyType(dict(payload))), ("admission_reference", admission_reference)):
            object.__setattr__(self, name, value)


class ForegroundTurnProvisioned(KernelEvent):
    """Runtime start에서 provenance 없는 active outer turn을 선행 생성합니다."""

    __slots__ = ("actor_id",)

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        idempotency_key: str,
    ) -> None:
        """SessionStart와 exact recovery가 사용할 provisional turn event를 만듭니다.

        Args:
            session_id: Event가 mutation할 exact session입니다.
            actor_id: Provisional turn을 소유할 active actor입니다.
            idempotency_key: 동일 provision retry를 식별하는 stable key입니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)

    actor_id: ActorId
    """Provenance가 도착하기 전에 작업 authority를 받을 actor입니다."""


class ForegroundTurnPrompted(KernelEvent):
    """UserPromptSubmit provenance를 provisional 또는 다음 outer turn에 결합합니다."""

    __slots__ = (
        "actor_id",
        "authority_context",
        "prompt_digest",
        "vendor_turn_id",
    )

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        vendor_turn_id: str | None,
        idempotency_key: str,
        prompt_digest: str | None = None,
        authority_context: ForegroundPromptAuthorityContext | None = None,
    ) -> None:
        """Prompt에서 current actor의 latest turn 전이를 생성합니다.

        Args:
            session_id: Event가 mutation할 exact session입니다.
            actor_id: Prompt를 받은 current actor입니다.
            vendor_turn_id: Runtime이 제공한 optional provenance입니다.
            idempotency_key: 동일 prompt delivery를 식별하는 stable key입니다.
            prompt_digest: Hook이 canonical prompt 원문에서 계산한 optional SHA-256입니다.
            authority_context: 직전 adaptive question에서 hook이 읽은 optional binding입니다.

        Raises:
            TransitionRejected: Vendor turn ID가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        normalized = None if vendor_turn_id is None else vendor_turn_id.strip()
        if normalized == "":
            raise TransitionRejected("vendor turn id must be null or non-empty")
        if prompt_digest is not None and re.fullmatch(r"[0-9a-f]{64}", prompt_digest) is None:
            raise TransitionRejected("prompt digest must be null or SHA-256")
        if authority_context is not None and prompt_digest is None:
            raise TransitionRejected("prompt authority context requires a prompt digest")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "vendor_turn_id", normalized)
        object.__setattr__(self, "prompt_digest", prompt_digest)
        object.__setattr__(self, "authority_context", authority_context)

    actor_id: ActorId
    """Prompt를 받은 current actor identity입니다."""

    vendor_turn_id: str | None
    """Identity 결정에는 쓰지 않는 optional runtime provenance입니다."""

    prompt_digest: str | None
    """Raw prompt를 저장하지 않기 위해 hook boundary에서 계산한 optional SHA-256입니다."""

    authority_context: ForegroundPromptAuthorityContext | None
    """직전 adaptive question이 exact current state와 일치할 때만 존재하는 binding입니다."""


class ForegroundTurnToolObserved(KernelEvent):
    """PreToolUse에서 yielded receipt가 더는 final이 아님을 기록합니다."""

    __slots__ = ("actor_id",)

    def __init__(self, session_id: SessionId, actor_id: ActorId, idempotency_key: str) -> None:
        """Tool observation이 ready receipt를 stale하게 만드는 event를 생성합니다.

        Args:
            session_id: Event가 mutation할 exact session입니다.
            actor_id: Tool call을 시작한 current actor입니다.
            idempotency_key: 동일 observation retry를 식별하는 stable key입니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)

    actor_id: ActorId
    """Tool call을 시작한 current actor identity입니다."""


class MaterialActionPrepared(KernelEvent):
    """Current actor foreground turn에 material-action batch intent를 준비합니다."""

    __slots__ = ("actor_id", "batch")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        batch_id: str,
        sequence: int,
        expected_turn_generation: int,
        expected_turn_revision: int,
        kind: MaterialActionKind,
        targets: tuple[str, ...],
        expectations: tuple[ObservableExpectation, ...],
        adaptive_binding: AdaptiveActionBinding | None,
        idempotency_key: str,
    ) -> None:
        """Raw intent 없이 exact turn과 observable contract에 결속된 batch를 만듭니다.

        Args:
            session_id: Material intent가 mutation할 exact runtime session입니다.
            actor_id: Current foreground turn과 batch authority를 소유하는 actor입니다.
            batch_id: Retry와 후속 tool event가 공유할 stable batch identity입니다.
            sequence: 같은 actor의 직전 resolved batch 다음 monotonic 순번입니다.
            expected_turn_generation: Intent를 결속할 current foreground turn generation입니다.
            expected_turn_revision: Prepare 시점 foreground turn CAS revision입니다.
            kind: Target와 adaptive authority 규칙을 선택하는 material action 종류입니다.
            targets: Batch 안 invocation이 변경할 수 있는 normalized exact target입니다.
            expectations: Completion을 판정할 observable baseline과 expected delta입니다.
            adaptive_binding: Semantic intent를 exact adaptive goal에 결속하는 provenance입니다.
            idempotency_key: 동일 prepare event retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Batch identity, actor-turn 또는 observable contract가 invalid할
                때 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        try:
            batch = MaterialActionBatch.prepare(
                batch_id=batch_id,
                sequence=sequence,
                session_id=str(session_id),
                actor_id=str(actor_id),
                turn_generation=expected_turn_generation,
                turn_revision=expected_turn_revision,
                kind=kind,
                targets=targets,
                expectations=expectations,
                adaptive_binding=adaptive_binding,
            )
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "batch", batch)

    actor_id: ActorId
    """Prepared batch와 exact foreground turn을 소유하는 actor identity입니다."""
    batch: MaterialActionBatch
    """Constructor가 검증하고 정규화한 OPEN material-action batch입니다."""

    @property
    def batch_id(self) -> str:
        """Prepared batch identity를 노출합니다.

        Returns:
            Retry와 후속 event가 공유하는 stable batch identity입니다.
        """
        return self.batch.batch_id

    @property
    def expectations(self) -> tuple[ObservableExpectation, ...]:
        """Prepared observable expectations를 노출합니다.

        Returns:
            Completion 판정에 사용할 normalized expectation tuple입니다.
        """
        return self.batch.expectations


class MaterialActionToolStarted(KernelEvent):
    """PreTool request digest 하나를 open material-action batch에 시작합니다."""

    __slots__ = ("actor_id", "batch_id", "expected_batch_revision", "invocation")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        batch_id: str,
        expected_batch_revision: int,
        invocation_id: str,
        tool_name: str,
        request_digest: str,
        targets: tuple[str, ...],
        idempotency_key: str,
    ) -> None:
        """Normalized PreTool metadata만 보존하는 typed start event를 만듭니다.

        Args:
            session_id: In-flight invocation을 기록할 exact runtime session입니다.
            actor_id: Prepared batch와 tool call authority를 소유하는 actor입니다.
            batch_id: Invocation을 추가할 current OPEN batch identity입니다.
            expected_batch_revision: PreTool 직전 caller가 읽은 batch CAS revision입니다.
            invocation_id: Matching PostTool payload와 공유할 tool-use identity입니다.
            tool_name: Normalized request를 실행할 canonical runtime tool name입니다.
            request_digest: Raw input 대신 request equality를 고정하는 SHA-256입니다.
            targets: Prepared batch 범위 안에서 tool이 변경하려는 exact target입니다.
            idempotency_key: 동일 PreTool delivery retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Batch revision, identity, request 또는 target metadata가 invalid할
                때 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_batch_revision, int)
            or isinstance(expected_batch_revision, bool)
            or expected_batch_revision < 0
        ):
            raise TransitionRejected("material-action batch revision must be non-negative")
        try:
            invocation = ToolInvocation.started(
                invocation_id=invocation_id,
                tool_name=tool_name,
                request_digest=request_digest,
                targets=targets,
            )
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "batch_id", batch_id.strip())
        object.__setattr__(self, "expected_batch_revision", expected_batch_revision)
        object.__setattr__(self, "invocation", invocation)
        if not self.batch_id:
            raise TransitionRejected("material-action batch identity must be non-empty")

    actor_id: ActorId
    """Invocation start mutation authority를 소유하는 actor identity입니다."""
    batch_id: str
    """새 in-flight invocation을 받을 current material-action batch identity입니다."""
    expected_batch_revision: int
    """Start reducer가 비교할 caller-observed batch-local CAS revision입니다."""
    invocation: ToolInvocation
    """Receipt가 없고 STARTED 상태인 normalized tool invocation입니다."""


class MaterialActionToolObserved(KernelEvent):
    """Runtime PostTool receipt를 matching material-action invocation에 결속합니다."""

    __slots__ = (
        "actor_id",
        "batch_id",
        "expected_batch_revision",
        "invocation_id",
        "receipt",
    )

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        batch_id: str,
        expected_batch_revision: int,
        invocation_id: str,
        receipt: ToolReceipt,
        idempotency_key: str,
    ) -> None:
        """Output 원문 없이 digest와 observable readback만 가진 observation event를 만듭니다.

        Args:
            session_id: PostTool receipt를 기록할 exact runtime session입니다.
            actor_id: Prepared batch와 in-flight invocation authority를 소유하는 actor입니다.
            batch_id: Matching STARTED invocation을 가진 current batch identity입니다.
            expected_batch_revision: PostTool 직전 caller가 읽은 batch CAS revision입니다.
            invocation_id: Receipt를 결속할 exact in-flight tool-use identity입니다.
            receipt: Request digest, outcome과 current observable readback을 가진 receipt입니다.
            idempotency_key: 동일 PostTool delivery retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Batch revision이나 batch/invocation identity가 invalid할 때
                발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_batch_revision, int)
            or isinstance(expected_batch_revision, bool)
            or expected_batch_revision < 0
        ):
            raise TransitionRejected("material-action batch revision must be non-negative")
        normalized_batch = batch_id.strip()
        normalized_invocation = invocation_id.strip()
        if not normalized_batch or not normalized_invocation:
            raise TransitionRejected("material-action batch and invocation identities are required")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "batch_id", normalized_batch)
        object.__setattr__(self, "expected_batch_revision", expected_batch_revision)
        object.__setattr__(self, "invocation_id", normalized_invocation)
        object.__setattr__(self, "receipt", receipt)

    actor_id: ActorId
    """PostTool observation mutation authority를 소유하는 actor identity입니다."""
    batch_id: str
    """Receipt를 누적할 current material-action batch identity입니다."""
    expected_batch_revision: int
    """Observe reducer가 비교할 caller-observed batch-local CAS revision입니다."""
    invocation_id: str
    """Receipt가 소비할 current in-flight tool-use identity입니다."""
    receipt: ToolReceipt
    """Raw output 없이 request digest와 observable readback을 보존한 PostTool receipt입니다."""


class MaterialActionAbandoned(KernelEvent):
    """Missing PostTool invocation을 UNKNOWN/BLOCKED로 원자 terminalize합니다."""

    __slots__ = (
        "actor_id",
        "batch_id",
        "expected_batch_revision",
        "expected_turn_generation",
        "invocation_id",
    )

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        batch_id: str,
        expected_batch_revision: int,
        expected_turn_generation: int,
        invocation_id: str,
        idempotency_key: str,
    ) -> None:
        """Runtime-neutral abandonment event를 exact actor turn과 batch에 결속합니다.

        Args:
            session_id: Abandoned invocation을 소유한 exact runtime session입니다.
            actor_id: Current foreground turn과 material batch를 소유한 actor입니다.
            batch_id: Missing PostTool invocation을 가진 current batch입니다.
            expected_batch_revision: Abandon 직전 caller가 읽은 batch CAS revision입니다.
            expected_turn_generation: Stop/cancellation 경계의 foreground generation입니다.
            invocation_id: UNKNOWN receipt로 닫을 exact in-flight tool-use identity입니다.
            idempotency_key: 같은 abandonment delivery를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Identity 또는 revision 값이 invalid하면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_batch_revision, int)
            or isinstance(expected_batch_revision, bool)
            or expected_batch_revision < 0
            or not isinstance(expected_turn_generation, int)
            or isinstance(expected_turn_generation, bool)
            or expected_turn_generation < 1
        ):
            raise TransitionRejected("material-action abandonment revisions are invalid")
        normalized_batch = batch_id.strip()
        normalized_invocation = invocation_id.strip()
        if not normalized_batch or not normalized_invocation:
            raise TransitionRejected("material-action abandonment identities are required")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "batch_id", normalized_batch)
        object.__setattr__(self, "expected_batch_revision", expected_batch_revision)
        object.__setattr__(self, "expected_turn_generation", expected_turn_generation)
        object.__setattr__(self, "invocation_id", normalized_invocation)

    actor_id: ActorId
    """Abandonment authority를 소유한 current actor identity입니다."""
    batch_id: str
    """In-flight invocation을 가진 current material-action batch입니다."""
    expected_batch_revision: int
    """Atomic abandon reducer가 비교할 batch-local CAS revision입니다."""
    expected_turn_generation: int
    """Abandonment가 허용된 current foreground turn generation입니다."""
    invocation_id: str
    """Execution 결과를 알 수 없어 UNKNOWN으로 닫을 exact tool-use identity입니다."""


class MaterialActionResolved(KernelEvent):
    """Observed material-action batch를 terminal resolution으로 닫습니다."""

    __slots__ = ("actor_id", "batch_id", "expected_batch_revision", "resolution")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        batch_id: str,
        expected_batch_revision: int,
        resolution: MaterialActionResolution,
        idempotency_key: str,
    ) -> None:
        """Exact batch revision에 대한 terminal resolution event를 만듭니다.

        Args:
            session_id: Terminal resolution을 기록할 exact runtime session입니다.
            actor_id: Batch lifecycle과 resolution authority를 소유하는 actor입니다.
            batch_id: Terminal 판정을 적용할 current material-action batch identity입니다.
            expected_batch_revision: Resolve 직전 caller가 읽은 batch CAS revision입니다.
            resolution: Completed, aborted 또는 blocked 중 explicit terminal 판정입니다.
            idempotency_key: 동일 resolution retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Batch revision, identity 또는 resolution 값이 invalid할 때
                발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_batch_revision, int)
            or isinstance(expected_batch_revision, bool)
            or expected_batch_revision < 0
        ):
            raise TransitionRejected("material-action batch revision must be non-negative")
        normalized_batch = batch_id.strip()
        if not normalized_batch:
            raise TransitionRejected("material-action batch identity must be non-empty")
        try:
            normalized_resolution = MaterialActionResolution(resolution)
        except ValueError as error:
            raise TransitionRejected("material-action resolution is invalid") from error
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "batch_id", normalized_batch)
        object.__setattr__(self, "expected_batch_revision", expected_batch_revision)
        object.__setattr__(self, "resolution", normalized_resolution)

    actor_id: ActorId
    """Terminal resolution mutation authority를 소유하는 actor identity입니다."""
    batch_id: str
    """Terminal 판정을 적용할 current material-action batch identity입니다."""
    expected_batch_revision: int
    """Resolve reducer가 비교할 caller-observed batch-local CAS revision입니다."""
    resolution: MaterialActionResolution
    """Batch를 닫을 normalized completed, aborted 또는 blocked 판정입니다."""


class ForegroundTurnYielded(KernelEvent):
    """Actor가 turn-local CAS로 terminal control-return receipt를 제출합니다."""

    __slots__ = ("actor_id", "expected_turn_revision", "receipt")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        expected_turn_revision: int,
        receipt: ForegroundTurnReceipt,
        idempotency_key: str,
    ) -> None:
        """Active turn에 outcome-specific receipt를 제출하는 CAS event를 생성합니다.

        Args:
            session_id: Event가 mutation할 exact session입니다.
            actor_id: Terminal control return을 선언한 actor입니다.
            expected_turn_revision: Caller가 읽은 latest-turn CAS counter입니다.
            receipt: Outcome별 required evidence를 가진 terminal receipt입니다.
            idempotency_key: 동일 yield retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Expected revision이 non-negative integer가 아니면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_turn_revision, int)
            or isinstance(expected_turn_revision, bool)
            or expected_turn_revision < 0
        ):
            raise TransitionRejected("foreground turn revision must be non-negative")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_turn_revision", expected_turn_revision)
        object.__setattr__(self, "receipt", receipt)

    actor_id: ActorId
    """Terminal control return을 선언한 current actor입니다."""

    expected_turn_revision: int
    """Yield CAS가 비교할 actor latest-turn counter입니다."""

    receipt: ForegroundTurnReceipt
    """Ready-to-stop 상태와 결속할 outcome-specific evidence입니다."""


class ForegroundTurnInvalidated(KernelEvent):
    """Stop failure 또는 later activity가 ready receipt를 active로 되돌립니다."""

    __slots__ = ("actor_id", "expected_turn_revision")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        expected_turn_revision: int,
        idempotency_key: str,
    ) -> None:
        """Ready receipt를 active로 되돌리는 CAS event를 생성합니다.

        Args:
            session_id: Event가 mutation할 exact session입니다.
            actor_id: Ready receipt를 소유한 current actor입니다.
            expected_turn_revision: Caller가 읽은 latest-turn CAS counter입니다.
            idempotency_key: 동일 invalidation retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Expected revision이 non-negative integer가 아니면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_turn_revision, int)
            or isinstance(expected_turn_revision, bool)
            or expected_turn_revision < 0
        ):
            raise TransitionRejected("foreground turn revision must be non-negative")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_turn_revision", expected_turn_revision)

    actor_id: ActorId
    """Receipt가 stale해진 current actor입니다."""

    expected_turn_revision: int
    """Invalidation CAS가 비교할 actor latest-turn counter입니다."""


class ForegroundTurnClosed(KernelEvent):
    """Stop gate가 verified ready turn을 terminal closed로 소비합니다."""

    __slots__ = ("actor_id", "expected_turn_revision", "monitor_transitions")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        expected_turn_revision: int,
        idempotency_key: str,
        monitor_transitions: tuple[MonitorWorkflowStopProjection, ...] = (),
    ) -> None:
        """Verified ready turn을 closed로 소비하는 CAS event를 생성합니다.

        Args:
            session_id: Event가 mutation할 exact session입니다.
            actor_id: Stop gate를 통과한 current actor입니다.
            expected_turn_revision: Caller가 검증한 ready-turn CAS counter입니다.
            idempotency_key: 동일 close retry를 식별하는 stable key입니다.
            monitor_transitions: 같은 process CAS에 포함할 monitor workflow 후보입니다.

        Raises:
            TransitionRejected: Expected revision이 non-negative integer가 아니면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_turn_revision, int)
            or isinstance(expected_turn_revision, bool)
            or expected_turn_revision < 0
        ):
            raise TransitionRejected("foreground turn revision must be non-negative")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_turn_revision", expected_turn_revision)
        if any(not isinstance(item, MonitorWorkflowStopProjection) for item in monitor_transitions):
            raise TransitionRejected("monitor transitions must be typed projections")
        workflow_ids = tuple(item.workflow_id for item in monitor_transitions)
        if len(set(workflow_ids)) != len(workflow_ids):
            raise TransitionRejected("monitor transition workflow identities must be unique")
        object.__setattr__(
            self,
            "monitor_transitions",
            tuple(sorted(monitor_transitions, key=lambda item: str(item.workflow_id))),
        )

    actor_id: ActorId
    """Stop gate를 통과한 current actor입니다."""

    expected_turn_revision: int
    """Close CAS가 비교할 ready-turn counter입니다."""

    monitor_transitions: tuple[MonitorWorkflowStopProjection, ...]


class ForegroundTurnReplaced(KernelEvent):
    """Host-verified successor가 active foreground를 중단했음을 기록합니다."""

    __slots__ = ("actor_id", "expected_turn_revision", "replacement_reference")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        expected_turn_revision: int,
        replacement_reference: str,
        idempotency_key: str,
    ) -> None:
        """Normal Stop과 분리된 native interruption transition을 생성합니다."""
        super().__init__(session_id, idempotency_key)
        if (
            not isinstance(expected_turn_revision, int)
            or isinstance(expected_turn_revision, bool)
            or expected_turn_revision < 0
        ):
            raise TransitionRejected("foreground replacement revision must be non-negative")
        if not isinstance(replacement_reference, str):
            raise TransitionRejected("foreground replacement reference must be text")
        normalized = replacement_reference.strip()
        if (
            not normalized
            or chr(0) in normalized
            or len(normalized.encode("utf-8")) > 1024
            or any(character.isspace() for character in normalized)
        ):
            raise TransitionRejected("foreground replacement reference is invalid")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_turn_revision", expected_turn_revision)
        object.__setattr__(self, "replacement_reference", normalized)

    actor_id: ActorId
    expected_turn_revision: int
    replacement_reference: str
    """Turn close와 같은 process revision에 commit할 canonical monitor 후보입니다."""


class DelegationAssigned(KernelEvent):
    """Singleton slot 없이 delegation map에 pending assignment를 추가합니다."""

    __slots__ = (
        "assignment",
        "delegation_id",
        "owner_actor_id",
        "target_actor_id",
        "topology_policy",
    )

    def __init__(
        self,
        session_id: SessionId,
        delegation_id: DelegationId,
        owner_actor_id: ActorId,
        target_actor_id: ActorId,
        assignment: str,
        idempotency_key: str,
        topology_policy: DelegationTopologyPolicy = DelegationTopologyPolicy.UNSPECIFIED,
    ) -> None:
        """두 actor 사이에 독립 pending delegation을 추가하는 event를 구성합니다.

        Args:
            session_id: Delegation이 속할 exact session identity입니다.
            delegation_id: Concurrent assignment를 독립적으로 식별하는 identity입니다.
            owner_actor_id: 작업을 맡기고 결과를 소비할 actor identity입니다.
            target_actor_id: Assignment를 수행할 actor identity입니다.
            assignment: Target actor에게 전달할 비어 있지 않은 작업 내용입니다.
            idempotency_key: 동일 assignment event에 caller가 부여한 key입니다.
            topology_policy: Reducer가 admission하고 record에 보존할 topology 계약입니다.

        Raises:
            TransitionRejected: Assignment 또는 idempotency key가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if not assignment.strip():
            raise TransitionRejected("delegation assignment must not be empty")
        if not isinstance(topology_policy, DelegationTopologyPolicy):
            raise TransitionRejected("delegation topology policy must be typed")
        object.__setattr__(self, "delegation_id", delegation_id)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "target_actor_id", target_actor_id)
        object.__setattr__(self, "assignment", assignment.strip())
        object.__setattr__(self, "topology_policy", topology_policy)

    delegation_id: DelegationId
    """Delegation map에서 concurrent assignment를 구분하는 identity입니다."""

    owner_actor_id: ActorId
    """Assignment를 발행하고 결과를 소비할 actor identity입니다."""

    target_actor_id: ActorId
    """Assignment 수행 책임을 받을 actor identity입니다."""

    assignment: str
    """Target actor에게 전달되는 공백이 제거된 작업 내용입니다."""

    topology_policy: DelegationTopologyPolicy
    """Assignment 결과가 주장할 수 있는 actor-topology authority입니다."""


class DelegationReported(KernelEvent):
    """Exact target actor가 pending delegation에 typed result를 귀속시킵니다."""

    __slots__ = ("delegation_id", "reporter_actor_id", "result")

    def __init__(
        self,
        session_id: SessionId,
        delegation_id: DelegationId,
        reporter_actor_id: ActorId,
        result: DelegationResult,
        idempotency_key: str,
    ) -> None:
        """Delegation identity와 reporter identity를 함께 고정한 결과 event입니다.

        Args:
            session_id: Delegation이 속한 exact session identity입니다.
            delegation_id: Result를 연결할 pending delegation identity입니다.
            reporter_actor_id: Assignment의 exact target이어야 하는 actor입니다.
            result: Owner에게 전달할 typed verdict와 outcome reference입니다.
            idempotency_key: 동일 delegation-report event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Idempotency key가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "delegation_id", delegation_id)
        object.__setattr__(self, "reporter_actor_id", reporter_actor_id)
        object.__setattr__(self, "result", result)

    delegation_id: DelegationId
    """Target actor의 result를 담을 exact delegation identity입니다."""

    reporter_actor_id: ActorId
    """Delegation target과 일치해야 하는 result reporter identity입니다."""

    result: DelegationResult
    """Delegation target의 identity 확인 후 record에 고정할 typed result입니다."""


class DelegationCancelled(KernelEvent):
    """Exact owner actor가 pending delegation을 terminal abort로 마칩니다."""

    __slots__ = ("delegation_id", "owner_actor_id", "reason")

    def __init__(
        self,
        session_id: SessionId,
        delegation_id: DelegationId,
        owner_actor_id: ActorId,
        reason: str,
        idempotency_key: str,
    ) -> None:
        """Pending assignment와 취소 권한 및 사유를 하나의 typed event로 구성합니다.

        Args:
            session_id: Delegation이 속한 exact session identity입니다.
            delegation_id: 취소할 pending delegation identity입니다.
            owner_actor_id: Assignment의 exact owner여야 하는 actor입니다.
            reason: Spawn 실패 등 terminal abort의 비어 있지 않은 설명입니다.
            idempotency_key: 동일 cancellation retry를 식별하는 stable key입니다.

        Raises:
            TransitionRejected: Reason이 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if not reason.strip():
            raise TransitionRejected("delegation cancellation reason must not be empty")
        object.__setattr__(self, "delegation_id", delegation_id)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "reason", reason.strip())

    delegation_id: DelegationId
    """Terminal abort로 전환할 exact delegation identity입니다."""

    owner_actor_id: ActorId
    """Delegation을 생성했고 cancellation 권한을 가진 actor identity입니다."""

    reason: str
    """Cancellation result summary로 보존할 bounded abort 설명입니다."""


class DelegationConsumed(KernelEvent):
    """Exact owner actor가 reported delegation의 delivery lifecycle을 마칩니다."""

    __slots__ = ("consumer_actor_id", "delegation_id")

    def __init__(
        self,
        session_id: SessionId,
        delegation_id: DelegationId,
        consumer_actor_id: ActorId,
        idempotency_key: str,
    ) -> None:
        """Reported result를 delegation owner가 소비했음을 표현합니다.

        Args:
            session_id: Delegation이 속한 exact session identity입니다.
            delegation_id: Reported에서 consumed로 바꿀 delegation identity입니다.
            consumer_actor_id: Assignment의 exact owner이어야 하는 actor입니다.
            idempotency_key: 동일 delegation-consume event에 caller가 부여한 key입니다.

        Raises:
            TransitionRejected: Idempotency key가 공백뿐이면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "delegation_id", delegation_id)
        object.__setattr__(self, "consumer_actor_id", consumer_actor_id)

    delegation_id: DelegationId
    """Owner actor가 result delivery를 마칠 exact delegation identity입니다."""

    consumer_actor_id: ActorId
    """Delegation owner과 일치해야 하는 result consumer identity입니다."""


class HarnessIncidentRecorded(KernelEvent):
    """Session actor가 관찰한 새 harness incident occurrence를 open으로 기록합니다."""

    __slots__ = ("actor_id", "occurrence_id", "recorded_at", "rule_id", "symptom")

    def __init__(
        self,
        session_id: SessionId,
        occurrence_id: IncidentId,
        rule_id: str,
        actor_id: ActorId,
        symptom: str,
        recorded_at: str,
        idempotency_key: str,
    ) -> None:
        """Clock과 identity 발급이 끝난 open incident event를 구성합니다.

        Args:
            session_id: Incident가 귀속될 exact session identity입니다.
            occurrence_id: Stable rule의 이번 발생을 구분하는 identity입니다.
            rule_id: 반복 발생을 같은 근본 invariant로 묶는 stable identity입니다.
            actor_id: 실패를 관찰한 exact session actor입니다.
            symptom: 재현 가능한 workflow failure 설명입니다.
            recorded_at: Caller가 mutation retry 전에 한 번 캡처한 timestamp입니다.
            idempotency_key: 동일 record intent를 식별하는 key입니다.

        Raises:
            TransitionRejected: 필수 observation text가 비었으면 발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if not rule_id.strip() or not symptom.strip() or not recorded_at.strip():
            raise TransitionRejected("incident record text must not be empty")
        object.__setattr__(self, "occurrence_id", occurrence_id)
        object.__setattr__(self, "rule_id", rule_id.strip())
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "symptom", symptom.strip())
        object.__setattr__(self, "recorded_at", recorded_at.strip())

    occurrence_id: IncidentId
    """Stable rule의 이번 발생을 구분하는 session-local identity입니다."""

    rule_id: str
    """반복 occurrence를 같은 근본 harness invariant로 묶는 identity입니다."""

    actor_id: ActorId
    """Incident를 관찰하고 record authority를 행사하는 actor입니다."""

    symptom: str
    """Agent가 실행 중 직접 관찰한 재현 가능한 workflow failure입니다."""

    recorded_at: str
    """Optimistic retry 밖에서 한 번 캡처한 occurrence timestamp입니다."""


class HarnessIncidentResolved(KernelEvent):
    """Open incident를 root cause, durable fix, regression receipt로 닫습니다."""

    __slots__ = (
        "actor_id",
        "harness_fix",
        "occurrence_id",
        "regression_evidence",
        "resolved_at",
        "root_cause",
    )

    def __init__(
        self,
        session_id: SessionId,
        occurrence_id: IncidentId,
        actor_id: ActorId,
        root_cause: str,
        harness_fix: tuple[str, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        resolved_at: str,
        idempotency_key: str,
    ) -> None:
        """External regression이 끝난 complete resolution event를 구성합니다.

        Args:
            session_id: Incident가 속한 exact session identity입니다.
            occurrence_id: Open에서 resolved로 바꿀 exact occurrence입니다.
            actor_id: Resolution mutation을 제출하는 available actor입니다.
            root_cause: 재발을 설명하는 근본 원인입니다.
            harness_fix: 원인을 제거한 durable repository path입니다.
            regression_evidence: Fix를 실제 실행해 만든 exact-head receipt입니다.
            resolved_at: Caller가 retry 전에 한 번 캡처한 resolution timestamp입니다.
            idempotency_key: 동일 resolve intent를 식별하는 key입니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "occurrence_id", occurrence_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "root_cause", root_cause)
        object.__setattr__(self, "harness_fix", tuple(harness_fix))
        object.__setattr__(self, "regression_evidence", tuple(regression_evidence))
        object.__setattr__(self, "resolved_at", resolved_at)

    occurrence_id: IncidentId
    """Resolved lifecycle로 전이할 exact occurrence identity입니다."""

    actor_id: ActorId
    """Resolution mutation authority를 행사하는 current actor입니다."""

    root_cause: str
    """재발을 설명하고 point fix를 배제하는 근본 원인입니다."""

    harness_fix: tuple[str, ...]
    """근본 원인을 제거한 durable repository-relative path입니다."""

    regression_evidence: tuple[HarnessRegressionReceipt, ...]
    """Current fix를 exact head에서 실행한 regression receipt입니다."""

    resolved_at: str
    """Optimistic retry 밖에서 한 번 캡처한 resolution timestamp입니다."""


class HarnessIncidentEscalated(KernelEvent):
    """Open incident의 durable fix 소유권을 loop owner에게 이관합니다."""

    __slots__ = (
        "actor_id",
        "escalated_at",
        "occurrence_id",
        "reproduction_commands",
        "summary",
    )

    def __init__(
        self,
        session_id: SessionId,
        occurrence_id: IncidentId,
        actor_id: ActorId,
        summary: str,
        reproduction_commands: tuple[str, ...],
        escalated_at: str,
        idempotency_key: str,
    ) -> None:
        """Loop owner가 이어받을 complete handoff event를 구성합니다.

        Args:
            session_id: Incident가 속한 exact session identity입니다.
            occurrence_id: Open에서 escalated로 바꿀 exact occurrence입니다.
            actor_id: Ownership handoff를 제출하는 available actor입니다.
            summary: Loop owner가 수정 맥락을 복원할 이관 설명입니다.
            reproduction_commands: 결함을 다시 관찰할 command입니다.
            escalated_at: Caller가 retry 전에 한 번 캡처한 handoff timestamp입니다.
            idempotency_key: 동일 escalation intent를 식별하는 key입니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "occurrence_id", occurrence_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "reproduction_commands", tuple(reproduction_commands))
        object.__setattr__(self, "escalated_at", escalated_at)

    occurrence_id: IncidentId
    """Loop-owner ownership으로 전이할 exact occurrence identity입니다."""

    actor_id: ActorId
    """Escalation mutation authority를 행사하는 current actor입니다."""

    summary: str
    """Loop owner가 durable harness 수정을 이어받기 위한 handoff 설명입니다."""

    reproduction_commands: tuple[str, ...]
    """이관된 failure를 반복 관찰할 command 목록입니다."""

    escalated_at: str
    """Optimistic retry 밖에서 한 번 캡처한 ownership handoff timestamp입니다."""


class HarnessIncidentsRefreshed(KernelEvent):
    """외부 regression 중 target evidence가 바뀌지 않은 resolved occurrence를 원자 갱신합니다."""

    __slots__ = ("actor_id", "expected_incidents", "refreshed_at", "regression_evidence")

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        expected_incidents: tuple[HarnessIncidentRecord, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        refreshed_at: str,
        idempotency_key: str,
    ) -> None:
        """Batch regression 전에 읽은 originals와 새 receipt를 한 event로 묶습니다.

        Args:
            session_id: Target occurrences가 속한 exact session identity입니다.
            actor_id: Receipt refresh mutation을 제출하는 available actor입니다.
            expected_incidents: External command 실행 전에 읽은 exact resolved originals입니다.
            regression_evidence: Batch 전체에 한 번 실행한 current-head receipt입니다.
            refreshed_at: Caller가 retry 전에 한 번 캡처한 refresh timestamp입니다.
            idempotency_key: 동일 batch refresh intent를 식별하는 key입니다.

        Raises:
            TransitionRejected: Target, receipt, timestamp가 비었거나 ID가 중복되면
                발생합니다.
        """
        super().__init__(session_id, idempotency_key)
        if not expected_incidents or not regression_evidence or not refreshed_at.strip():
            raise TransitionRejected("incident refresh evidence must not be empty")
        incident_ids = tuple(incident.id for incident in expected_incidents)
        if len(set(incident_ids)) != len(incident_ids):
            raise TransitionRejected("incident refresh targets must be unique")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_incidents", tuple(expected_incidents))
        object.__setattr__(self, "regression_evidence", tuple(regression_evidence))
        object.__setattr__(self, "refreshed_at", refreshed_at.strip())

    actor_id: ActorId
    """Batch refresh mutation authority를 행사하는 current actor입니다."""

    expected_incidents: tuple[HarnessIncidentRecord, ...]
    """External regression 실행 전에 읽어 CAS 비교에 사용할 originals입니다."""

    regression_evidence: tuple[HarnessRegressionReceipt, ...]
    """모든 target fix를 latest head에서 검증한 shared receipt입니다."""

    refreshed_at: str
    """Optimistic retry 밖에서 한 번 캡처한 receipt refresh timestamp입니다."""


class HarnessIncidentEvidenceSuperseded(KernelEvent):
    """Resolved occurrence의 obsolete evidence를 검증된 replacement로 교체합니다."""

    __slots__ = (
        "actor_id",
        "expected_incident",
        "harness_fix",
        "regression_evidence",
        "superseded_at",
    )

    def __init__(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        expected_incident: HarnessIncidentRecord,
        harness_fix: tuple[str, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        superseded_at: str,
        idempotency_key: str,
    ) -> None:
        """External replacement 검증 전 original과 새 evidence를 event로 묶습니다.

        Args:
            session_id: Occurrence가 속한 exact session identity입니다.
            actor_id: Supersession mutation을 제출하는 available actor입니다.
            expected_incident: Replacement 검증 전에 읽은 exact resolved original입니다.
            harness_fix: Current가 될 replacement durable fix path입니다.
            regression_evidence: Replacement를 exact head에서 실행한 receipt입니다.
            superseded_at: Caller가 retry 전에 한 번 캡처한 replacement timestamp입니다.
            idempotency_key: 동일 supersession intent를 식별하는 key입니다.
        """
        super().__init__(session_id, idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_incident", expected_incident)
        object.__setattr__(self, "harness_fix", tuple(harness_fix))
        object.__setattr__(self, "regression_evidence", tuple(regression_evidence))
        object.__setattr__(self, "superseded_at", superseded_at)

    actor_id: ActorId
    """Evidence supersession authority를 행사하는 current actor입니다."""

    expected_incident: HarnessIncidentRecord
    """External replacement 검증 전에 읽어 CAS 비교에 사용할 original입니다."""

    harness_fix: tuple[str, ...]
    """Obsolete resolution path를 대체할 current durable fix path입니다."""

    regression_evidence: tuple[HarnessRegressionReceipt, ...]
    """Replacement fix를 exact head에서 실행한 regression receipt입니다."""

    superseded_at: str
    """Optimistic retry 밖에서 한 번 캡처한 evidence replacement timestamp입니다."""
