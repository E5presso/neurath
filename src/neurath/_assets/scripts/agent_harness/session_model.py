"""Immutable session records, identities and domain errors; no persistence dependencies."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Self

from scripts.agent_harness.material_action import MaterialActionBatch
from scripts.agent_harness.skill_state_contract import SessionKernelError

PROCESS_STATE_SCHEMA = "neurath.coding-agent-process-state.v1"


ENCLAVE_SCHEMA = "neurath.coding-agent-enclave.v1"


MAX_PENDING_OUTBOX_EFFECTS = 128


class InvalidIdentity(SessionKernelError):
    """Runtime identity가 비었거나 canonical path에 안전하지 않을 때 발생합니다."""


class SessionNotFound(SessionKernelError):
    """Exact session snapshot이 없을 때 발생합니다."""


class InvalidSessionState(SessionKernelError):
    """Process-state snapshot이 schema 또는 identity invariant를 어길 때 발생합니다."""


class RevisionConflict(SessionKernelError):
    """Optimistic compare-and-swap의 원본 revision이 달라졌을 때 발생합니다."""


class TransitionRejected(SessionKernelError):
    """Typed event가 현재 state에서 허용되지 않을 때 발생합니다."""


class OptimisticRetryExhausted(SessionKernelError):
    """Implicit optimistic retry가 bounded attempt 안에 수렴하지 못했을 때 발생합니다."""


class InvalidRetryLimit(SessionKernelError):
    """Optimistic transaction retry 상한이 양수가 아닐 때 발생합니다."""


class Identifier(str):
    """Non-empty opaque identity를 타입별로 분리하는 immutable string value입니다."""

    def __new__(cls, value: str) -> Self:
        """공백을 제거한 비어 있지 않은 typed identity를 생성합니다.

        Args:
            value: Runtime boundary에서 받은 opaque identity 원문입니다.

        Returns:
            좌우 공백을 제거하고 concrete identifier subtype을 유지한 값입니다.

        Raises:
            InvalidIdentity: 문자열이 아니거나 공백 제거 뒤 비어 있으면 발생합니다.
        """
        if not isinstance(value, str) or not value.strip():
            raise InvalidIdentity(f"{cls.__name__} must be a non-empty string")
        return str.__new__(cls, value.strip())


class SessionId(Identifier):
    """하나의 root coding-agent execution tree identity입니다."""


class ResumeId(Identifier):
    """Runtime exact-resume handle입니다."""


class ActorId(Identifier):
    """Root agent 또는 subagent actor identity입니다."""


class TurnId(Identifier):
    """Runtime turn identity입니다."""


class WorkflowId(Identifier):
    """한 session 안의 workflow invocation identity입니다."""


class DelegationId(Identifier):
    """한 actor가 다른 actor에 맡긴 delegation identity입니다."""


class IncidentId(Identifier):
    """같은 rule의 반복 발생을 서로 구분하는 harness incident occurrence identity입니다."""


class WorktreeId(Identifier):
    """Shared worktree resource identity입니다."""


class EffectId(Identifier):
    """Transactional outbox의 pending external effect identity입니다."""


class SessionRuntime(StrEnum):
    """지원하는 opaque General Agent runtime입니다."""

    CODEX = "codex"
    """Codex가 발급한 session identity와 resume handle을 사용하는 runtime입니다."""

    CLAUDE_CODE = "claude-code"
    """Claude Code가 발급한 session identity와 resume handle을 사용하는 runtime입니다."""


class SessionStatus(StrEnum):
    """Coding-agent session lifecycle status입니다."""

    ACTIVE = "active"
    """Session이 새 state event를 받아 operational snapshot을 갱신할 수 있습니다."""

    ENDED = "ended"
    """Session이 terminal 상태여서 후속 mutation event를 거부합니다."""


class ActorKind(StrEnum):
    """Session actor의 topology role입니다."""

    ROOT = "root"
    """부모 없이 session execution tree를 소유하는 유일한 root actor입니다."""

    SUBAGENT = "subagent"
    """같은 session 안의 기존 actor를 부모로 가지는 delegated actor입니다."""


class ActorLineageAssurance(StrEnum):
    """Persisted parent pointer가 가지는 runtime provenance 보장 수준입니다."""

    UNATTESTED = "unattested"
    """Same-session topology는 보존하지만 host가 immediate parent를 증명하지 않았습니다."""

    HOST_ATTESTED = "host-attested"
    """Runtime host의 typed assurance가 exact immediate parent를 증명했습니다."""


class ActorStatus(StrEnum):
    """Actor mutation 가능 여부를 결정하는 lifecycle status입니다."""

    ACTIVE = "active"
    """Actor가 실행 중이며 새 delegation의 owner 또는 target이 될 수 있습니다."""

    IDLE = "idle"
    """Actor가 대기 중이지만 새 delegation의 owner 또는 target이 될 수 있습니다."""

    STOPPED = "stopped"
    """Actor 실행이 중단되어 새 delegation 참여가 허용되지 않습니다."""

    RETIRED = "retired"
    """Actor가 topology 기록에만 남고 새 delegation 참여에서 제외됩니다."""


class DelegationStatus(StrEnum):
    """Delegation delivery lifecycle status입니다."""

    PENDING = "pending"
    """Assignment가 생성됐지만 target actor의 결과가 아직 보고되지 않았습니다."""

    REPORTED = "reported"
    """Target actor의 결과가 owner actor에게 전달 가능한 상태입니다."""

    CONSUMED = "consumed"
    """Owner actor가 보고된 결과를 받아 delegation lifecycle을 마쳤습니다."""

    CANCELLED = "cancelled"
    """Owner actor가 report 전 assignment를 terminal abort로 마쳤습니다."""


class DelegationTopologyPolicy(StrEnum):
    """Delegation result가 주장할 수 있는 persisted actor-topology authority입니다."""

    UNSPECIFIED = "unspecified"
    """Legacy assignment처럼 topology intent를 증명하지 못하는 migration 상태입니다."""

    SAME_SESSION = "same-session"
    """Owner와 target이 같은 canonical session에 존재하는 delivery 계약입니다."""

    DIRECT_CHILD = "direct-child"
    """Target이 assignment owner의 exact direct child여야 하는 독립 평가 계약입니다."""


class WorkflowStatus(StrEnum):
    """Workflow aggregate가 추가 transition을 받을 수 있는지 나타냅니다."""

    ACTIVE = "active"
    """Workflow가 진행 중이며 owner actor가 payload를 갱신할 수 있습니다."""

    COMPLETED = "completed"
    """Workflow가 의도한 goal을 달성해 정상적으로 종료됐습니다."""

    FAILED = "failed"
    """Workflow가 더 이상 진행할 수 없는 실패 상태로 종료됐습니다."""


class ForegroundTurnStatus(StrEnum):
    """Current actor가 user control을 소유하고 있는 outer turn lifecycle입니다."""

    ACTIVE = "active"
    """Actor가 요청을 처리 중이며 terminal receipt가 없습니다."""

    READY_TO_STOP = "ready-to-stop"
    """Actor가 explicit yield receipt를 제출했고 Stop 검증을 기다립니다."""

    CLOSED = "closed"
    """Stop gate가 receipt와 모든 inner constraint를 검증해 control을 반환했습니다."""


class ForegroundTurnOutcome(StrEnum):
    """Agent가 foreground turn을 yield하는 이유를 표현하는 closed outcome입니다."""

    COMPLETED = "completed"
    """현재 사용자 요청을 완료하고 결과를 반환합니다."""

    AWAITING_INPUT = "awaiting-input"
    """다음 진행에 필요한 사용자의 구체적인 입력을 요청합니다."""

    FAILED = "failed"
    """현재 요청을 더 진행할 수 없는 실패를 설명하고 control을 반환합니다."""

    INCOMPLETE = "incomplete"
    """현재 runtime 근거를 사용할 수 없어 workflow를 보존하며 control을 반환합니다."""


class HarnessIncidentStatus(StrEnum):
    """Self-detected harness incident의 수정 소유권과 종료 상태입니다."""

    OPEN = "open"
    """근본 원인 수정 또는 loop-owner 이관이 아직 완료되지 않았습니다."""

    RESOLVED = "resolved"
    """Root cause, durable fix, exact-head regression receipt로 원인이 제거됐습니다."""

    ESCALATED = "escalated"
    """재현 정보와 함께 durable harness 수정 소유권을 loop owner에게 넘겼습니다."""


class CommitStage(StrEnum):
    """Crash-safety test가 관찰할 수 있는 durable commit 경계입니다."""

    BEFORE_REPLACE = "before-replace"
    """Temporary snapshot을 fsync한 뒤 canonical file을 교체하기 직전입니다."""


class EffectKind(StrEnum):
    """Commit 뒤 runtime adapter가 실행할 closed external effect family입니다."""

    CONTEXT_INJECTION = "context-injection"
    """Lifecycle rehydration context를 exact runtime session에 전달합니다."""

    DELIVERY = "delivery"
    """Actor 또는 monitor mailbox payload를 외부 runtime에 전달합니다."""

    WAKE = "wake"
    """Runtime capability가 허용할 때 exact suspended execution을 깨웁니다."""

    ALLOW = "allow"
    """Tool 또는 lifecycle 요청을 허용하는 adapter decision입니다."""

    DENY = "deny"
    """Tool 또는 lifecycle 요청을 차단하는 adapter decision입니다."""

    UNAVAILABLE = "unavailable"
    """요청한 runtime capability가 없어 명시적으로 수행할 수 없습니다."""


class ImmutableValue:
    """생성 뒤 attribute 변경을 거부하는 value-object base입니다."""

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 value object에 대한 모든 attribute 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: attribute에 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable value는 생성 뒤 항상 변경을 거부합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class SessionRecord(ImmutableValue):
    """Process state가 소유하는 session identity와 lifecycle입니다."""

    __slots__ = (
        "id",
        "last_lifecycle_idempotency_key",
        "lifecycle_provenance_id",
        "parent_session_id",
        "resume_id",
        "root_actor_id",
        "runtime",
        "status",
    )

    def __init__(
        self,
        session_id: SessionId,
        resume_id: ResumeId | None,
        runtime: SessionRuntime,
        root_actor_id: ActorId,
        status: SessionStatus,
        parent_session_id: SessionId | None = None,
        lifecycle_provenance_id: str | None = None,
        last_lifecycle_idempotency_key: str | None = None,
    ) -> None:
        """Session identity와 runtime lifecycle을 하나의 immutable record로 묶습니다.

        Args:
            session_id: Root execution tree를 다른 session과 격리하는 identity입니다.
            resume_id: Runtime이 exact continuation에 사용하는 opaque handle입니다.
            runtime: Session identity와 resume handle을 발급한 runtime 종류입니다.
            root_actor_id: 이 session의 유일한 root actor identity입니다.
            status: Session이 후속 mutation을 받을 수 있는지 나타내는 lifecycle입니다.
            parent_session_id: Fork target이 복사한 source session identity입니다.
            lifecycle_provenance_id: Parent lineage를 증명하는 runtime event identity입니다.
            last_lifecycle_idempotency_key: 마지막 explicit lifecycle event의 retry key입니다.

        Raises:
            InvalidSessionState: Fork lineage 쌍이 불완전하거나 self-parent이면
                발생합니다.
        """
        normalized_parent, normalized_provenance = self._normalize_lineage(
            session_id,
            parent_session_id,
            lifecycle_provenance_id,
        )
        object.__setattr__(self, "id", session_id)
        object.__setattr__(self, "resume_id", resume_id)
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "root_actor_id", root_actor_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "parent_session_id", normalized_parent)
        object.__setattr__(self, "lifecycle_provenance_id", normalized_provenance)
        normalized_lifecycle_key = (
            None
            if last_lifecycle_idempotency_key is None
            else last_lifecycle_idempotency_key.strip()
        )
        if normalized_lifecycle_key == "":
            raise InvalidSessionState("last_lifecycle_idempotency_key must be null or non-empty")
        object.__setattr__(
            self,
            "last_lifecycle_idempotency_key",
            normalized_lifecycle_key,
        )

    id: SessionId
    """Root execution tree를 다른 session과 격리하는 canonical identity입니다."""

    resume_id: ResumeId | None
    """Runtime exact continuation용 opaque handle이며 제공되지 않으면 null입니다."""

    runtime: SessionRuntime
    """Session identity와 resume handle의 발급 runtime입니다."""

    root_actor_id: ActorId
    """Session actor topology가 반드시 포함해야 하는 유일한 root identity입니다."""

    status: SessionStatus
    """Session이 후속 operational mutation을 받을 수 있는지 나타냅니다."""

    parent_session_id: SessionId | None
    """Fork로 생성된 session이 복사한 exact source session입니다."""

    lifecycle_provenance_id: str | None
    """Parent session lineage를 증명하는 runtime event identity입니다."""

    last_lifecycle_idempotency_key: str | None
    """마지막 explicit lifecycle transition의 retry identity입니다."""

    def to_payload(self) -> dict[str, str | None]:
        """Session record를 JSON-compatible payload로 변환합니다.

        Returns:
            Opaque identity와 enum을 문자열로 직렬화한 session object입니다.
        """
        return {
            "id": str(self.id),
            "resume_id": None if self.resume_id is None else str(self.resume_id),
            "runtime": self.runtime.value,
            "root_actor_id": str(self.root_actor_id),
            "status": self.status.value,
            "parent_session_id": (
                None if self.parent_session_id is None else str(self.parent_session_id)
            ),
            "lifecycle_provenance_id": self.lifecycle_provenance_id,
            "last_lifecycle_idempotency_key": self.last_lifecycle_idempotency_key,
        }

    @staticmethod
    def _normalize_lineage(
        session_id: SessionId,
        parent_session_id: SessionId | None,
        lifecycle_provenance_id: str | None,
    ) -> tuple[SessionId | None, str | None]:
        """Fork lineage 쌍을 검증하고 canonical value로 정규화합니다.

        Args:
            session_id: Lineage를 소유할 target session입니다.
            parent_session_id: Runtime이 증명한 source session입니다.
            lifecycle_provenance_id: Fork event의 stable provenance identity입니다.

        Returns:
            Both-null root lineage 또는 검증된 parent/provenance 쌍입니다.

        Raises:
            InvalidSessionState: Pair가 불완전하거나 self-parent이며 provenance가
                비어 있으면 발생합니다.
        """
        if (parent_session_id is None) != (lifecycle_provenance_id is None):
            raise InvalidSessionState(
                "parent_session_id and lifecycle_provenance_id must be provided together"
            )
        if parent_session_id is None:
            return None, None
        if parent_session_id == session_id:
            raise InvalidSessionState("session cannot be its own fork parent")
        assert lifecycle_provenance_id is not None
        normalized_provenance = lifecycle_provenance_id.strip()
        if not normalized_provenance:
            raise InvalidSessionState("lifecycle_provenance_id must not be empty")
        return parent_session_id, normalized_provenance


class ActorRecord(ImmutableValue):
    """Session 안 actor의 lineage와 lifecycle입니다."""

    __slots__ = ("id", "kind", "lineage_assurance", "parent_actor_id", "status")

    def __init__(
        self,
        actor_id: ActorId,
        parent_actor_id: ActorId | None,
        kind: ActorKind,
        status: ActorStatus,
        lineage_assurance: ActorLineageAssurance = ActorLineageAssurance.UNATTESTED,
    ) -> None:
        """Actor topology와 lifecycle을 하나의 immutable record로 묶습니다.

        Args:
            actor_id: Session 안에서 root 또는 subagent를 식별하는 identity입니다.
            parent_actor_id: Subagent lineage의 부모이며 root actor에는 존재하지 않습니다.
            kind: Actor가 root인지 delegated subagent인지 나타내는 topology role입니다.
            status: Actor의 새 delegation 참여 가능 여부를 나타내는 lifecycle입니다.
            lineage_assurance: Parent pointer에 대한 runtime host attestation 수준입니다.

        Raises:
            InvalidSessionState: Lineage assurance가 typed enum이 아니면 발생합니다.
        """
        if not isinstance(lineage_assurance, ActorLineageAssurance):
            raise InvalidSessionState("actor lineage assurance must be typed")
        object.__setattr__(self, "id", actor_id)
        object.__setattr__(self, "parent_actor_id", parent_actor_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "lineage_assurance", lineage_assurance)

    id: ActorId
    """Session actor map에서 record를 찾는 canonical identity입니다."""

    parent_actor_id: ActorId | None
    """Subagent lineage의 부모 identity이며 root actor에는 존재하지 않습니다."""

    kind: ActorKind
    """Actor가 root인지 delegated subagent인지 나타내는 topology role입니다."""

    status: ActorStatus
    """Actor가 새 delegation에 참여할 수 있는지 결정하는 lifecycle입니다."""

    lineage_assurance: ActorLineageAssurance
    """Immediate-parent authority가 host attestation에 결속되었는지 나타냅니다."""

    def to_payload(self) -> dict[str, str | None]:
        """Actor record를 JSON-compatible payload로 변환합니다.

        Returns:
            Identity, lineage, role, lifecycle을 문자열로 직렬화한 actor object입니다.
        """
        payload = {
            "id": str(self.id),
            "parent_actor_id": (
                None if self.parent_actor_id is None else str(self.parent_actor_id)
            ),
            "kind": self.kind.value,
            "status": self.status.value,
        }
        if self.lineage_assurance is ActorLineageAssurance.HOST_ATTESTED:
            payload["lineage_assurance"] = self.lineage_assurance.value
        return payload


class WorkflowRecord(ImmutableValue):
    """Workflow별 owner, goal, payload와 독립 CAS revision을 보존합니다."""

    __slots__ = (
        "goal",
        "id",
        "kind",
        "last_transition_idempotency_key",
        "owner_actor_id",
        "payload",
        "revision",
        "status",
    )

    def __init__(
        self,
        workflow_id: WorkflowId,
        owner_actor_id: ActorId,
        kind: str,
        goal: str | None,
        payload: Mapping[str, object],
        revision: int,
        status: WorkflowStatus,
        last_transition_idempotency_key: str | None = None,
    ) -> None:
        """하나의 workflow invocation을 session revision과 분리해 고정합니다.

        Args:
            workflow_id: 같은 session 안의 다른 workflow와 구분하는 identity입니다.
            owner_actor_id: Workflow payload와 lifecycle을 갱신할 actor입니다.
            kind: Process-ticket 등 workflow implementation을 식별하는 종류입니다.
            goal: Workflow가 소유하는 optional 실행 목표입니다.
            payload: Workflow kind가 소유하는 현재 operational projection입니다.
            revision: Workflow 자체 advance/finalize CAS에 사용할 version입니다.
            status: Workflow가 진행 중인지 terminal인지 나타내는 lifecycle입니다.
            last_transition_idempotency_key: 마지막 commit event의 stable identity입니다.

        Raises:
            InvalidSessionState: Idempotency key가 제공됐지만 공백뿐이면 발생합니다.
        """
        if (
            last_transition_idempotency_key is not None
            and not last_transition_idempotency_key.strip()
        ):
            raise InvalidSessionState("workflow last_transition_idempotency_key must not be empty")
        object.__setattr__(self, "id", workflow_id)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "payload", MappingProxyType(dict(payload)))
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "last_transition_idempotency_key",
            (
                None
                if last_transition_idempotency_key is None
                else last_transition_idempotency_key.strip()
            ),
        )

    id: WorkflowId
    """Session workflow map에서 invocation을 찾는 canonical identity입니다."""

    owner_actor_id: ActorId
    """Workflow의 advance와 finalize를 수행할 actor identity입니다."""

    kind: str
    """Workflow-specific payload를 해석할 실행 종류입니다."""

    goal: str | None
    """Workflow 자체가 소유하는 실행 목표이며 없을 수 있습니다."""

    payload: Mapping[str, object]
    """Workflow kind별 현재 operational state를 담은 read-only object입니다."""

    revision: int
    """Session 전체 revision과 독립적으로 stale workflow writer를 판별합니다."""

    status: WorkflowStatus
    """Workflow가 추가 payload transition을 받을 수 있는지 결정합니다."""

    last_transition_idempotency_key: str | None
    """동일 payload를 만든 별개 operation을 구분하는 마지막 event identity입니다."""

    def to_payload(self) -> dict[str, object]:
        """Typed workflow snapshot을 canonical JSON object로 변환합니다.

        Returns:
            Identity, owner, goal, payload, lifecycle, aggregate revision을 담은 object입니다.
        """
        return {
            "id": str(self.id),
            "owner_actor_id": str(self.owner_actor_id),
            "kind": self.kind,
            "goal": self.goal,
            "payload": dict(self.payload),
            "revision": self.revision,
            "status": self.status.value,
            "last_transition_idempotency_key": self.last_transition_idempotency_key,
        }


class ForegroundTurnReceipt(ImmutableValue):
    """Stop 직전 current actor가 명시적으로 제출한 terminal control-return receipt입니다."""

    __slots__ = ("outcome", "question", "reason", "summary")

    def __init__(
        self,
        outcome: ForegroundTurnOutcome,
        *,
        summary: str | None = None,
        question: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Outcome별 정확히 하나의 required evidence를 정규화합니다.

        Args:
            outcome: Completed, awaiting-input 또는 failed terminal intent입니다.
            summary: Completed outcome의 non-empty 결과 요약입니다.
            question: Awaiting-input outcome의 non-empty 사용자 질문입니다.
            reason: Failed outcome의 non-empty 실패 설명입니다.

        Raises:
            TransitionRejected: Outcome에 맞지 않거나 비어 있는 evidence이면 발생합니다.
        """
        normalized = {
            "summary": self._optional_text(summary),
            "question": self._optional_text(question),
            "reason": self._optional_text(reason),
        }
        required = {
            ForegroundTurnOutcome.COMPLETED: "summary",
            ForegroundTurnOutcome.AWAITING_INPUT: "question",
            ForegroundTurnOutcome.FAILED: "reason",
            ForegroundTurnOutcome.INCOMPLETE: "reason",
        }[outcome]
        if normalized[required] is None:
            raise TransitionRejected(f"foreground turn {outcome.value} requires {required}")
        unexpected = tuple(
            key for key, value in normalized.items() if key != required and value is not None
        )
        if unexpected:
            raise TransitionRejected(
                f"foreground turn {outcome.value} does not accept {', '.join(unexpected)}"
            )
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "summary", normalized["summary"])
        object.__setattr__(self, "question", normalized["question"])
        object.__setattr__(self, "reason", normalized["reason"])

    outcome: ForegroundTurnOutcome
    """Agent가 user control을 반환하는 typed outcome입니다."""

    summary: str | None
    """Completed outcome에서만 존재하는 결과 요약입니다."""

    question: str | None
    """Awaiting-input outcome에서만 존재하는 사용자 질문입니다."""

    reason: str | None
    """Failed outcome에서만 존재하는 실패 설명입니다."""

    def to_payload(self) -> dict[str, str | None]:
        """Receipt를 deterministic JSON-compatible object로 변환합니다.

        Returns:
            Outcome과 outcome별 evidence field를 모두 포함한 JSON object입니다.
        """
        return {
            "outcome": self.outcome.value,
            "summary": self.summary,
            "question": self.question,
            "reason": self.reason,
        }

    def _optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ForegroundPromptAuthorityContext(ImmutableValue):
    """User response 직전 adaptive question의 exact goal binding입니다."""

    __slots__ = (
        "claim_ids",
        "control_action",
        "criterion_ids",
        "goal_fingerprint",
        "intent_revision",
        "question_digest",
        "question_generation",
        "question_turn_revision",
        "source_revision",
        "workflow_id",
        "workflow_revision",
    )

    def __init__(
        self,
        *,
        workflow_id: WorkflowId,
        workflow_revision: int,
        goal_fingerprint: str,
        intent_revision: int,
        source_revision: str,
        criterion_ids: tuple[str, ...],
        claim_ids: tuple[str, ...],
        control_action: str,
        question_digest: str,
        question_generation: int,
        question_turn_revision: int,
    ) -> None:
        """Adaptive question을 원문 없이 workflow와 acceptance inventory에 결속합니다.

        Args:
            workflow_id: Question이 귀속된 exact active workflow입니다.
            workflow_revision: Question을 user에게 반환한 workflow-local revision입니다.
            goal_fingerprint: Question 시점의 immutable goal fingerprint입니다.
            intent_revision: Question 시점의 approved intent revision입니다.
            source_revision: Question 시점의 approved source revision입니다.
            criterion_ids: Goal contract가 소유한 전체 acceptance criterion identity입니다.
            claim_ids: 이 응답이 authority를 제공할 수 있는 bounded claim identity입니다.
            control_action: Ask-user 또는 await-user question kind입니다.
            question_digest: 사용자에게 먼저 반환된 exact question의 SHA-256입니다.
            question_generation: Question receipt가 속한 foreground generation입니다.
            question_turn_revision: Prompt 직전 question turn의 exact revision입니다.

        Raises:
            InvalidSessionState: Identity, revision, digest 또는 bounded collection이 invalid하면
                발생합니다.
        """
        if (
            not isinstance(workflow_revision, int)
            or isinstance(workflow_revision, bool)
            or workflow_revision < 0
        ):
            raise InvalidSessionState("prompt authority workflow revision must be non-negative")
        if (
            not isinstance(intent_revision, int)
            or isinstance(intent_revision, bool)
            or intent_revision < 1
        ):
            raise InvalidSessionState("prompt authority intent revision must be positive")
        if (
            not isinstance(question_generation, int)
            or isinstance(question_generation, bool)
            or question_generation < 1
        ):
            raise InvalidSessionState("prompt authority question generation must be positive")
        if (
            not isinstance(question_turn_revision, int)
            or isinstance(question_turn_revision, bool)
            or question_turn_revision < 0
        ):
            raise InvalidSessionState(
                "prompt authority question turn revision must be non-negative"
            )
        normalized_source = source_revision.strip()
        normalized_action = control_action.strip()
        if not normalized_source or not normalized_action:
            raise InvalidSessionState("prompt authority source and action must be non-empty")
        if re.fullmatch(r"[0-9a-f]{64}", goal_fingerprint) is None:
            raise InvalidSessionState("prompt authority goal fingerprint must be SHA-256")
        if re.fullmatch(r"[0-9a-f]{64}", question_digest) is None:
            raise InvalidSessionState("prompt authority question digest must be SHA-256")
        normalized_criteria = tuple(item.strip() for item in criterion_ids)
        normalized_claims = tuple(item.strip() for item in claim_ids)
        if (
            not normalized_criteria
            or not normalized_claims
            or any(not item for item in (*normalized_criteria, *normalized_claims))
            or len(normalized_criteria) != len(set(normalized_criteria))
            or len(normalized_claims) != len(set(normalized_claims))
        ):
            raise InvalidSessionState(
                "prompt authority criterion and claim identities must be non-empty and unique"
            )
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "workflow_revision", workflow_revision)
        object.__setattr__(self, "goal_fingerprint", goal_fingerprint)
        object.__setattr__(self, "intent_revision", intent_revision)
        object.__setattr__(self, "source_revision", normalized_source)
        object.__setattr__(self, "criterion_ids", tuple(sorted(normalized_criteria)))
        object.__setattr__(self, "claim_ids", tuple(sorted(normalized_claims)))
        object.__setattr__(self, "control_action", normalized_action)
        object.__setattr__(self, "question_digest", question_digest)
        object.__setattr__(self, "question_generation", question_generation)
        object.__setattr__(self, "question_turn_revision", question_turn_revision)

    workflow_id: WorkflowId
    """Question과 subsequent response가 귀속된 exact active workflow입니다."""

    workflow_revision: int
    """Question 반환 시점의 workflow-local optimistic revision입니다."""

    goal_fingerprint: str
    """Question 반환 시점의 immutable goal fingerprint입니다."""

    intent_revision: int
    """Question이 답변하려는 approved intent revision입니다."""

    source_revision: str
    """Question이 답변하려는 approved source revision입니다."""

    criterion_ids: tuple[str, ...]
    """Current goal contract가 소유한 전체 acceptance criterion identity입니다."""

    claim_ids: tuple[str, ...]
    """Subsequent response가 authority를 제공할 수 있는 bounded claim identity입니다."""

    control_action: str
    """Question을 발생시킨 ASK_USER 또는 AWAIT_USER control action입니다."""

    question_digest: str
    """사용자에게 먼저 반환한 canonical question bytes의 SHA-256입니다."""

    question_generation: int
    """Question receipt를 소유한 foreground generation입니다."""

    question_turn_revision: int
    """Question receipt를 소유한 exact foreground revision입니다."""

    def to_payload(self) -> dict[str, object]:
        """Raw question 없이 adaptive question binding을 JSON object로 반환합니다.

        Returns:
            Workflow, goal, criterion, claim과 question digest provenance입니다.
        """
        return {
            "workflow_id": str(self.workflow_id),
            "workflow_revision": self.workflow_revision,
            "goal_fingerprint": self.goal_fingerprint,
            "intent_revision": self.intent_revision,
            "source_revision": self.source_revision,
            "criterion_ids": list(self.criterion_ids),
            "claim_ids": list(self.claim_ids),
            "control_action": self.control_action,
            "question_digest": self.question_digest,
            "question_generation": self.question_generation,
            "question_turn_revision": self.question_turn_revision,
        }


class ForegroundUserPromptReceipt(ImmutableValue):
    """Raw user prompt 대신 digest와 exact foreground provenance를 보존합니다."""

    __slots__ = (
        "authority_context",
        "generation",
        "prompt_digest",
        "turn_revision",
        "vendor_turn_id",
    )

    def __init__(
        self,
        *,
        prompt_digest: str,
        generation: int,
        turn_revision: int,
        vendor_turn_id: str | None,
        authority_context: ForegroundPromptAuthorityContext | None,
    ) -> None:
        """Current user prompt의 content digest와 runtime metadata를 고정합니다.

        Args:
            prompt_digest: Canonicalized raw prompt bytes의 SHA-256입니다.
            generation: Prompt가 연 또는 재활성화한 foreground generation입니다.
            turn_revision: Prompt transition 직후의 exact foreground revision입니다.
            vendor_turn_id: Runtime이 제공한 optional native turn provenance입니다.
            authority_context: 직전 adaptive question이 검증된 경우의 bounded binding입니다.

        Raises:
            InvalidSessionState: Digest, counter 또는 vendor provenance가 invalid하면 발생합니다.
        """
        if re.fullmatch(r"[0-9a-f]{64}", prompt_digest) is None:
            raise InvalidSessionState("foreground user prompt digest must be SHA-256")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise InvalidSessionState("foreground user prompt generation must be positive")
        if (
            not isinstance(turn_revision, int)
            or isinstance(turn_revision, bool)
            or turn_revision < 0
        ):
            raise InvalidSessionState("foreground user prompt revision must be non-negative")
        normalized_vendor = None if vendor_turn_id is None else vendor_turn_id.strip()
        if normalized_vendor == "":
            raise InvalidSessionState("foreground user prompt vendor turn must be non-empty")
        object.__setattr__(self, "prompt_digest", prompt_digest)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "turn_revision", turn_revision)
        object.__setattr__(self, "vendor_turn_id", normalized_vendor)
        object.__setattr__(self, "authority_context", authority_context)

    prompt_digest: str
    """Canonicalized current user prompt bytes의 SHA-256입니다."""

    generation: int
    """Current user prompt가 연 또는 재활성화한 foreground generation입니다."""

    turn_revision: int
    """Current user prompt transition 직후의 exact foreground revision입니다."""

    vendor_turn_id: str | None
    """Runtime이 제공한 경우 보존하는 native turn provenance입니다."""

    authority_context: ForegroundPromptAuthorityContext | None
    """Exact adaptive question 뒤 prompt일 때만 존재하는 bounded authority context입니다."""

    @property
    def authority_reference(self) -> str:
        """AuthorityReceipt가 current runtime prompt를 지목할 opaque identity를 반환합니다.

        Returns:
            Generation, revision과 optional vendor turn을 결속한 content-addressed reference입니다.
        """
        payload = json.dumps(
            {
                "generation": self.generation,
                "turn_revision": self.turn_revision,
                "vendor_turn_id": self.vendor_turn_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"user-prompt:{hashlib.sha256(payload).hexdigest()}"

    def to_payload(self) -> dict[str, object]:
        """Raw prompt를 제외한 runtime user receipt를 JSON object로 반환합니다.

        Returns:
            Digest, exact turn metadata와 optional adaptive authority context입니다.
        """
        return {
            "authority_reference": self.authority_reference,
            "prompt_digest": self.prompt_digest,
            "generation": self.generation,
            "turn_revision": self.turn_revision,
            "vendor_turn_id": self.vendor_turn_id,
            "authority_context": (
                None if self.authority_context is None else self.authority_context.to_payload()
            ),
        }


class ForegroundTurnRecord(ImmutableValue):
    """Actor별 latest outer turn generation과 optimistic revision을 보존합니다."""

    __slots__ = (
        "generation",
        "owner_actor_id",
        "receipt",
        "replacement_question",
        "revision",
        "status",
        "user_prompt_receipt",
        "vendor_turn_id",
    )

    def __init__(
        self,
        owner_actor_id: ActorId,
        generation: int,
        revision: int,
        status: ForegroundTurnStatus,
        receipt: ForegroundTurnReceipt | None,
        vendor_turn_id: str | None,
        user_prompt_receipt: ForegroundUserPromptReceipt | None = None,
        replacement_question: ForegroundTurnReceipt | None = None,
    ) -> None:
        """한 actor의 latest foreground turn snapshot을 검증해 고정합니다.

        Args:
            owner_actor_id: Turn lifecycle과 receipt를 소유하는 exact actor입니다.
            generation: Actor가 연 logical turn의 1-based sequence입니다.
            revision: Generation 사이에도 reset되지 않는 latest-turn CAS counter입니다.
            status: Active, ready-to-stop 또는 closed lifecycle입니다.
            receipt: Optional legacy terminal annotation입니다. Ready 상태에는 필요하지만
                runtime Stop으로 직접 닫힌 turn에는 존재하지 않을 수 있습니다.
            vendor_turn_id: Runtime이 제공한 optional provenance입니다.
            user_prompt_receipt: Raw prompt 없이 보존한 latest runtime prompt provenance입니다.

        Raises:
            InvalidSessionState: Counter, provenance, status와 receipt 조합이 invalid하면
                발생합니다.
        """
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise InvalidSessionState("foreground turn generation must be positive")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise InvalidSessionState("foreground turn revision must be non-negative")
        normalized_vendor_id = None if vendor_turn_id is None else vendor_turn_id.strip()
        if normalized_vendor_id == "":
            raise InvalidSessionState("foreground vendor turn id must be null or non-empty")
        if status is ForegroundTurnStatus.ACTIVE and receipt is not None:
            raise InvalidSessionState("active foreground turn cannot retain a receipt")
        if status is ForegroundTurnStatus.READY_TO_STOP and receipt is None:
            raise InvalidSessionState("ready foreground turn requires a receipt")
        if user_prompt_receipt is not None and (
            user_prompt_receipt.generation != generation
            or user_prompt_receipt.turn_revision > revision
        ):
            raise InvalidSessionState(
                "foreground user prompt receipt must belong to the current turn"
            )
        if replacement_question is not None and (
            not isinstance(replacement_question, ForegroundTurnReceipt)
            or replacement_question.outcome is not ForegroundTurnOutcome.AWAITING_INPUT
            or status is not ForegroundTurnStatus.CLOSED
            or receipt is None
            or receipt.outcome is not ForegroundTurnOutcome.INCOMPLETE
            or not isinstance(receipt.reason, str)
            or not receipt.reason.startswith("native foreground replaced:")
        ):
            raise InvalidSessionState("replacement question requires an interrupted closed turn")
        object.__setattr__(self, "replacement_question", replacement_question)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "vendor_turn_id", normalized_vendor_id)
        object.__setattr__(self, "user_prompt_receipt", user_prompt_receipt)

    owner_actor_id: ActorId
    """Turn start, yield와 Stop lifecycle을 소유하는 exact actor입니다."""

    generation: int
    """같은 actor가 닫힌 turn 이후 연 다음 turn의 단조 증가 sequence입니다."""

    revision: int
    """Generation 사이에도 단조 증가해 ABA를 막는 actor latest-turn CAS counter입니다."""

    status: ForegroundTurnStatus
    """Active, ready-to-stop 또는 closed outer lifecycle입니다."""

    receipt: ForegroundTurnReceipt | None
    """Ready 상태 또는 legacy annotated close에 결속된 optional terminal annotation입니다."""

    vendor_turn_id: str | None
    """Runtime이 제공한 경우에만 보존하는 optional provenance이며 identity가 아닙니다."""

    user_prompt_receipt: ForegroundUserPromptReceipt | None
    """Raw prompt 없이 current generation에 결속된 runtime-owned user provenance입니다."""

    replacement_question: ForegroundTurnReceipt | None
    """Prior canonical question retained only across an incomplete host replacement."""

    @property
    def awaiting_input_receipt(self) -> ForegroundTurnReceipt | None:
        """Question provenance is independent from the replacement outcome."""
        if (
            self.receipt is not None
            and self.receipt.outcome is ForegroundTurnOutcome.AWAITING_INPUT
        ):
            return self.receipt
        return self.replacement_question

    def to_payload(self) -> dict[str, object]:
        """Actor-keyed process-state payload에 넣을 immutable snapshot을 반환합니다.

        Returns:
            Turn identity, CAS counter, lifecycle과 receipt를 담은 JSON object입니다.
        """
        return {
            "owner_actor_id": str(self.owner_actor_id),
            "generation": self.generation,
            "revision": self.revision,
            "status": self.status.value,
            "receipt": None if self.receipt is None else self.receipt.to_payload(),
            "replacement_question": (
                None
                if self.replacement_question is None
                else self.replacement_question.to_payload()
            ),
            "vendor_turn_id": self.vendor_turn_id,
            "user_prompt_receipt": (
                None if self.user_prompt_receipt is None else self.user_prompt_receipt.to_payload()
            ),
        }


class DelegationResult(ImmutableValue):
    """Target actor가 보고한 판정과 durable outcome reference입니다."""

    __slots__ = ("blocking_findings", "outcome_ref", "summary", "verdict")

    def __init__(
        self,
        verdict: str,
        summary: str,
        outcome_ref: str,
        blocking_findings: tuple[str, ...],
    ) -> None:
        """Delegation 결과를 immutable delivery payload로 정규화합니다.

        Args:
            verdict: Target actor가 내린 비어 있지 않은 판정입니다.
            summary: Owner actor가 소비할 bounded 결과 요약입니다.
            outcome_ref: 상세 artifact나 영속 receipt를 가리키는 stable reference입니다.
            blocking_findings: Owner가 후속 조치해야 하는 blocker 요약들입니다.

        Raises:
            TransitionRejected: 필수 text나 blocking finding이 비어 있으면 발생합니다.
        """
        if not verdict.strip() or not summary.strip() or not outcome_ref.strip():
            raise TransitionRejected("delegation result text must not be empty")
        if any(not finding.strip() for finding in blocking_findings):
            raise TransitionRejected("delegation blocking findings must not be empty")
        object.__setattr__(self, "verdict", verdict.strip())
        object.__setattr__(self, "summary", summary.strip())
        object.__setattr__(self, "outcome_ref", outcome_ref.strip())
        object.__setattr__(
            self,
            "blocking_findings",
            tuple(finding.strip() for finding in blocking_findings),
        )

    verdict: str
    """Target actor의 delegation 수행 판정입니다."""

    summary: str
    """Owner actor가 process state에서 즉시 소비할 bounded 결과입니다."""

    outcome_ref: str
    """Bounded state 밖의 상세 산출물을 가리키는 stable reference입니다."""

    blocking_findings: tuple[str, ...]
    """Owner actor의 후속 조치를 요구하는 blocker 요약입니다."""

    def to_payload(self) -> dict[str, object]:
        """Result를 delegation record에 내장할 JSON object로 변환합니다.

        Returns:
            Verdict, summary, outcome reference, blocking findings를 담은 object입니다.
        """
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "outcome_ref": self.outcome_ref,
            "blocking_findings": list(self.blocking_findings),
        }


class DelegationRecord(ImmutableValue):
    """동시에 여러 개 존재할 수 있는 delegation의 현재 snapshot입니다."""

    __slots__ = (
        "_result",
        "assignment",
        "id",
        "owner_actor_id",
        "status",
        "target_actor_id",
        "topology_policy",
    )

    def __init__(
        self,
        delegation_id: DelegationId,
        owner_actor_id: ActorId,
        target_actor_id: ActorId,
        assignment: str,
        status: DelegationStatus,
        result: DelegationResult | None = None,
        topology_policy: DelegationTopologyPolicy = DelegationTopologyPolicy.UNSPECIFIED,
    ) -> None:
        """독립 delegation의 participants, assignment, delivery 상태를 보존합니다.

        Args:
            delegation_id: 다른 concurrent delegation과 구분하는 identity입니다.
            owner_actor_id: 작업을 맡기고 결과를 소비하는 actor identity입니다.
            target_actor_id: Assignment를 수행하도록 지명된 actor identity입니다.
            assignment: Target actor에게 전달된 구체적인 작업 내용입니다.
            status: Assignment 결과의 delivery lifecycle입니다.
            result: Target actor가 reported transition으로 제출한 typed result입니다.
            topology_policy: Assignment admission에서 고정한 actor-topology 계약입니다.
        """
        object.__setattr__(self, "id", delegation_id)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "target_actor_id", target_actor_id)
        object.__setattr__(self, "assignment", assignment)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "_result", result)
        object.__setattr__(self, "topology_policy", topology_policy)

    id: DelegationId
    """Delegation map에서 concurrent assignment를 독립적으로 찾는 identity입니다."""

    owner_actor_id: ActorId
    """Assignment를 발행하고 보고 결과를 소비하는 actor identity입니다."""

    target_actor_id: ActorId
    """Assignment 수행 책임을 받은 actor identity입니다."""

    assignment: str
    """Target actor가 수행해야 할 구체적인 작업 내용입니다."""

    status: DelegationStatus
    """Assignment 결과가 pending, reported, consumed 중 어디까지 전달됐는지 나타냅니다."""

    topology_policy: DelegationTopologyPolicy
    """Independent evidence 소비자가 caller hint 대신 읽는 persisted topology 계약입니다."""

    _result: DelegationResult | None

    @property
    def result(self) -> DelegationResult:
        """Reported 이후 target actor에 귀속된 typed result를 반환합니다.

        Returns:
            Reporter identity 검증을 거쳐 delegation에 고정된 결과입니다.

        Raises:
            TransitionRejected: Pending delegation에는 아직 result가 없으면 발생합니다.
        """
        if self._result is None:
            raise TransitionRejected(f"delegation result is not reported: {self.id}")
        return self._result

    def to_payload(self) -> dict[str, object]:
        """Delegation record를 JSON-compatible payload로 변환합니다.

        Returns:
            Participants, assignment, lifecycle, optional result를 직렬화한 object입니다.
        """
        payload: dict[str, object] = {
            "id": str(self.id),
            "owner_actor_id": str(self.owner_actor_id),
            "target_actor_id": str(self.target_actor_id),
            "assignment": self.assignment,
            "status": self.status.value,
            "result": None if self._result is None else self._result.to_payload(),
        }
        if self.topology_policy is not DelegationTopologyPolicy.UNSPECIFIED:
            payload["topology_policy"] = self.topology_policy.value
        return payload


class HarnessRegressionReceipt(ImmutableValue):
    """실제로 실행된 regression command를 exact Git head와 output digest에 결속합니다."""

    __slots__ = ("command", "exit_code", "head_sha", "output_sha256", "verified_at")

    def __init__(
        self,
        command: str,
        exit_code: int,
        head_sha: str,
        verified_at: str,
        output_sha256: str,
    ) -> None:
        """검증 실행의 재현 정보와 결과 fingerprint를 immutable receipt로 만듭니다.

        Args:
            command: Shell expansion 없이 실행한 regression command 원문입니다.
            exit_code: 실행 process가 반환한 정수 종료 코드입니다.
            head_sha: 실행 당시 repository의 exact commit SHA입니다.
            verified_at: Command 실행이 완료된 timezone-aware timestamp입니다.
            output_sha256: 표준 출력과 오류를 결속한 SHA-256 digest입니다.

        Raises:
            InvalidSessionState: 필수 문자열이 비었거나 exit code가 정수가 아니면
                발생합니다.
        """
        values = (command, head_sha, verified_at, output_sha256)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise InvalidSessionState("regression receipt text must not be empty")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise InvalidSessionState("regression receipt exit_code must be an integer")
        object.__setattr__(self, "command", command.strip())
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "head_sha", head_sha.strip())
        object.__setattr__(self, "verified_at", verified_at.strip())
        object.__setattr__(self, "output_sha256", output_sha256.strip())

    command: str
    """Receipt가 증명하는 exact regression command입니다."""

    exit_code: int
    """Command가 반환한 process exit code입니다."""

    head_sha: str
    """Regression이 실행된 exact repository head입니다."""

    verified_at: str
    """Regression 실행이 완료된 timezone-aware timestamp입니다."""

    output_sha256: str
    """Command output 전체를 결속하는 SHA-256 digest입니다."""

    def __eq__(self, other: object) -> bool:
        """Receipt의 모든 persisted field가 같을 때 동일한 evidence로 판정합니다.

        Args:
            other: 비교할 runtime object입니다.

        Returns:
            같은 concrete receipt와 payload이면 True입니다.
        """
        return (
            isinstance(other, HarnessRegressionReceipt) and self.to_payload() == other.to_payload()
        )

    def __hash__(self) -> int:
        """Immutable receipt field로 stable in-process hash를 계산합니다.

        Returns:
            Receipt의 persisted field tuple에 대한 hash입니다.
        """
        return hash(
            (
                self.command,
                self.exit_code,
                self.head_sha,
                self.verified_at,
                self.output_sha256,
            )
        )

    def to_payload(self) -> dict[str, object]:
        """Receipt를 canonical JSON object로 변환합니다.

        Returns:
            Command, exit code, head, timestamp, output digest를 담은 object입니다.
        """
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "head_sha": self.head_sha,
            "verified_at": self.verified_at,
            "output_sha256": self.output_sha256,
        }


class HarnessIncidentEvidenceArchive(ImmutableValue):
    """Supersede가 교체한 이전 resolved evidence를 감사용으로 보존합니다."""

    __slots__ = ("harness_fix", "regression_evidence", "superseded_at")

    def __init__(
        self,
        harness_fix: tuple[str, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        superseded_at: str,
    ) -> None:
        """교체 직전 fix와 receipt를 하나의 immutable archive entry로 묶습니다.

        Args:
            harness_fix: 더 이상 current가 아닌 durable harness 경로입니다.
            regression_evidence: 교체 전 경로를 검증했던 exact-head receipt입니다.
            superseded_at: Replacement가 commit된 timezone-aware timestamp입니다.

        Raises:
            InvalidSessionState: Archive evidence 또는 timestamp가 비었으면 발생합니다.
        """
        if not harness_fix or any(not path.strip() for path in harness_fix):
            raise InvalidSessionState("archived harness_fix must not be empty")
        if not regression_evidence or not superseded_at.strip():
            raise InvalidSessionState("archived regression evidence must not be empty")
        object.__setattr__(self, "harness_fix", tuple(path.strip() for path in harness_fix))
        object.__setattr__(self, "regression_evidence", tuple(regression_evidence))
        object.__setattr__(self, "superseded_at", superseded_at.strip())

    harness_fix: tuple[str, ...]
    """Replacement 전 resolution이 가리켰던 durable harness 경로입니다."""

    regression_evidence: tuple[HarnessRegressionReceipt, ...]
    """Replacement 전 resolution path를 검증했던 receipt입니다."""

    superseded_at: str
    """Previous evidence가 current 지위를 잃은 timestamp입니다."""

    def to_payload(self) -> dict[str, object]:
        """Archived evidence를 canonical JSON object로 변환합니다.

        Returns:
            Previous fix, receipts, supersession timestamp를 담은 object입니다.
        """
        return {
            "harness_fix": list(self.harness_fix),
            "regression_evidence": [receipt.to_payload() for receipt in self.regression_evidence],
            "superseded_at": self.superseded_at,
        }


class HarnessIncidentRecord(ImmutableValue):
    """한 harness rule occurrence의 latest lifecycle과 검증 evidence를 소유합니다."""

    __slots__ = (
        "actor_id",
        "escalated_at",
        "escalation_summary",
        "evidence_refreshed_at",
        "evidence_superseded_at",
        "harness_fix",
        "id",
        "recorded_at",
        "regression_evidence",
        "reproduction_commands",
        "resolved_at",
        "root_cause",
        "rule_id",
        "status",
        "superseded_resolution_evidence",
        "symptom",
    )

    def __init__(
        self,
        occurrence_id: IncidentId,
        rule_id: str,
        actor_id: ActorId,
        status: HarnessIncidentStatus,
        symptom: str,
        recorded_at: str,
        *,
        root_cause: str | None = None,
        harness_fix: tuple[str, ...] = (),
        regression_evidence: tuple[HarnessRegressionReceipt, ...] = (),
        resolved_at: str | None = None,
        escalation_summary: str | None = None,
        reproduction_commands: tuple[str, ...] = (),
        escalated_at: str | None = None,
        evidence_refreshed_at: str | None = None,
        evidence_superseded_at: str | None = None,
        superseded_resolution_evidence: tuple[HarnessIncidentEvidenceArchive, ...] = (),
    ) -> None:
        """Occurrence identity와 status별 complete evidence shape를 검증합니다.

        Args:
            occurrence_id: 같은 stable rule의 반복을 구분하는 identity입니다.
            rule_id: 여러 occurrence를 같은 근본 invariant로 묶는 stable identity입니다.
            actor_id: Incident를 최초 기록한 session actor입니다.
            status: Open, resolved, escalated 중 current lifecycle입니다.
            symptom: Agent가 관찰한 재현 가능한 workflow failure입니다.
            recorded_at: Incident를 처음 기록한 timezone-aware timestamp입니다.
            root_cause: Resolved occurrence의 근본 원인입니다.
            harness_fix: Resolved occurrence가 가리키는 durable fix 경로입니다.
            regression_evidence: Fix를 검증한 exact-head command receipt입니다.
            resolved_at: Resolution이 확정된 timestamp입니다.
            escalation_summary: Loop owner가 수정을 이어받을 handoff 요약입니다.
            reproduction_commands: Escalated occurrence를 재현할 command입니다.
            escalated_at: Ownership handoff가 확정된 timestamp입니다.
            evidence_refreshed_at: Current fix receipt를 최신 head에서 갱신한 timestamp입니다.
            evidence_superseded_at: Current fix/evidence가 replacement로 바뀐 timestamp입니다.
            superseded_resolution_evidence: 교체 전 resolution evidence의 감사 기록입니다.

        Raises:
            InvalidSessionState: Identity, text 또는 status별 evidence shape가 불완전하면
                발생합니다.
        """
        if not rule_id.strip() or not symptom.strip() or not recorded_at.strip():
            raise InvalidSessionState("incident identity and observed symptom must not be empty")
        normalized_fix = tuple(path.strip() for path in harness_fix)
        normalized_commands = tuple(command.strip() for command in reproduction_commands)
        if any(not path for path in normalized_fix) or any(
            not command for command in normalized_commands
        ):
            raise InvalidSessionState("incident evidence text must not be empty")
        self._validate_lifecycle(
            status,
            root_cause,
            normalized_fix,
            regression_evidence,
            resolved_at,
            escalation_summary,
            normalized_commands,
            escalated_at,
            superseded_resolution_evidence,
        )
        object.__setattr__(self, "id", occurrence_id)
        object.__setattr__(self, "rule_id", rule_id.strip())
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "symptom", symptom.strip())
        object.__setattr__(self, "recorded_at", recorded_at.strip())
        object.__setattr__(self, "root_cause", None if root_cause is None else root_cause.strip())
        object.__setattr__(self, "harness_fix", normalized_fix)
        object.__setattr__(self, "regression_evidence", tuple(regression_evidence))
        object.__setattr__(
            self, "resolved_at", None if resolved_at is None else resolved_at.strip()
        )
        object.__setattr__(
            self,
            "escalation_summary",
            None if escalation_summary is None else escalation_summary.strip(),
        )
        object.__setattr__(self, "reproduction_commands", normalized_commands)
        object.__setattr__(
            self,
            "escalated_at",
            None if escalated_at is None else escalated_at.strip(),
        )
        object.__setattr__(
            self,
            "evidence_refreshed_at",
            None if evidence_refreshed_at is None else evidence_refreshed_at.strip(),
        )
        object.__setattr__(
            self,
            "evidence_superseded_at",
            None if evidence_superseded_at is None else evidence_superseded_at.strip(),
        )
        object.__setattr__(
            self,
            "superseded_resolution_evidence",
            tuple(superseded_resolution_evidence),
        )

    id: IncidentId
    """Session incident map에서 occurrence를 찾는 identity입니다."""

    rule_id: str
    """같은 root invariant의 반복 occurrence를 묶는 stable identity입니다."""

    actor_id: ActorId
    """Incident를 최초 관찰하고 기록한 session actor입니다."""

    status: HarnessIncidentStatus
    """Occurrence의 current resolution 또는 ownership lifecycle입니다."""

    symptom: str
    """Incident record를 생성한 관찰 가능한 workflow failure입니다."""

    recorded_at: str
    """Occurrence를 처음 기록한 timezone-aware timestamp입니다."""

    root_cause: str | None
    """Resolved occurrence에서만 존재하는 재발 원인입니다."""

    harness_fix: tuple[str, ...]
    """Resolved occurrence에서 원인을 제거한 repository-relative path입니다."""

    regression_evidence: tuple[HarnessRegressionReceipt, ...]
    """Current fix를 검증한 exact-head command receipt입니다."""

    resolved_at: str | None
    """Resolved lifecycle이 확정된 timestamp입니다."""

    escalation_summary: str | None
    """Escalated occurrence의 loop-owner handoff 요약입니다."""

    reproduction_commands: tuple[str, ...]
    """Loop owner가 escalated occurrence를 재현할 command입니다."""

    escalated_at: str | None
    """Durable fix ownership이 loop owner에게 이관된 timestamp입니다."""

    evidence_refreshed_at: str | None
    """Current resolution receipt가 latest head에서 다시 생성된 timestamp입니다."""

    evidence_superseded_at: str | None
    """Current resolution evidence가 replacement로 바뀐 timestamp입니다."""

    superseded_resolution_evidence: tuple[HarnessIncidentEvidenceArchive, ...]
    """Replacement 이전 resolution evidence의 append-only 감사 기록입니다."""

    def resolve(
        self,
        root_cause: str,
        harness_fix: tuple[str, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        resolved_at: str,
    ) -> HarnessIncidentRecord:
        """Open occurrence를 complete root-cause evidence와 함께 resolved로 닫습니다.

        Args:
            root_cause: 재발을 설명하는 비어 있지 않은 근본 원인입니다.
            harness_fix: 원인을 제거한 durable repository path입니다.
            regression_evidence: Current fix를 실행 검증한 exact-head receipt입니다.
            resolved_at: Resolution이 확정된 timestamp입니다.

        Returns:
            기존 identity와 observation을 보존한 resolved record입니다.

        Raises:
            TransitionRejected: Occurrence가 open이 아니면 발생합니다.
            InvalidSessionState: Resolution evidence가 불완전하면 발생합니다.
        """
        if self.status is not HarnessIncidentStatus.OPEN:
            raise TransitionRejected(f"incident is not open: {self.id}")
        return HarnessIncidentRecord(
            self.id,
            self.rule_id,
            self.actor_id,
            HarnessIncidentStatus.RESOLVED,
            self.symptom,
            self.recorded_at,
            root_cause=root_cause,
            harness_fix=harness_fix,
            regression_evidence=regression_evidence,
            resolved_at=resolved_at,
        )

    def escalate(
        self,
        summary: str,
        reproduction_commands: tuple[str, ...],
        escalated_at: str,
    ) -> HarnessIncidentRecord:
        """Open occurrence의 durable fix 소유권을 loop owner에게 이관합니다.

        Args:
            summary: Loop owner가 원인 수정을 이어받는 데 필요한 설명입니다.
            reproduction_commands: 결함을 다시 관찰할 command 목록입니다.
            escalated_at: Ownership handoff가 확정된 timestamp입니다.

        Returns:
            재현 evidence와 handoff route를 가진 escalated record입니다.

        Raises:
            TransitionRejected: Occurrence가 open이 아니면 발생합니다.
            InvalidSessionState: Handoff evidence가 비었으면 발생합니다.
        """
        if self.status is not HarnessIncidentStatus.OPEN:
            raise TransitionRejected(f"incident is not open: {self.id}")
        return HarnessIncidentRecord(
            self.id,
            self.rule_id,
            self.actor_id,
            HarnessIncidentStatus.ESCALATED,
            self.symptom,
            self.recorded_at,
            escalation_summary=summary,
            reproduction_commands=reproduction_commands,
            escalated_at=escalated_at,
        )

    def refresh(
        self,
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        refreshed_at: str,
    ) -> HarnessIncidentRecord:
        """Resolved occurrence의 current fix를 유지하며 exact-head receipt만 갱신합니다.

        Args:
            regression_evidence: Latest head에서 다시 실행한 current fix receipt입니다.
            refreshed_at: Receipt refresh가 완료된 timestamp입니다.

        Returns:
            Resolution identity와 history를 보존한 refreshed record입니다.

        Raises:
            TransitionRejected: Occurrence가 resolved가 아니면 발생합니다.
        """
        if self.status is not HarnessIncidentStatus.RESOLVED:
            raise TransitionRejected(f"incident is not resolved: {self.id}")
        return HarnessIncidentRecord(
            self.id,
            self.rule_id,
            self.actor_id,
            self.status,
            self.symptom,
            self.recorded_at,
            root_cause=self.root_cause,
            harness_fix=self.harness_fix,
            regression_evidence=regression_evidence,
            resolved_at=self.resolved_at,
            evidence_refreshed_at=refreshed_at,
            evidence_superseded_at=self.evidence_superseded_at,
            superseded_resolution_evidence=self.superseded_resolution_evidence,
        )

    def supersede(
        self,
        harness_fix: tuple[str, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        superseded_at: str,
    ) -> HarnessIncidentRecord:
        """Obsolete resolution evidence를 archive하고 current replacement로 교체합니다.

        Args:
            harness_fix: 현재 branch의 replacement durable fix path입니다.
            regression_evidence: Replacement path를 검증한 exact-head receipt입니다.
            superseded_at: Previous evidence가 archive된 timestamp입니다.

        Returns:
            Previous evidence history와 replacement를 가진 resolved record입니다.

        Raises:
            TransitionRejected: Occurrence가 resolved가 아니면 발생합니다.
        """
        if self.status is not HarnessIncidentStatus.RESOLVED:
            raise TransitionRejected(f"incident is not resolved: {self.id}")
        archive = HarnessIncidentEvidenceArchive(
            self.harness_fix,
            self.regression_evidence,
            superseded_at,
        )
        return HarnessIncidentRecord(
            self.id,
            self.rule_id,
            self.actor_id,
            self.status,
            self.symptom,
            self.recorded_at,
            root_cause=self.root_cause,
            harness_fix=harness_fix,
            regression_evidence=regression_evidence,
            resolved_at=self.resolved_at,
            evidence_refreshed_at=self.evidence_refreshed_at,
            evidence_superseded_at=superseded_at,
            superseded_resolution_evidence=(*self.superseded_resolution_evidence, archive),
        )

    def same_snapshot(self, other: HarnessIncidentRecord) -> bool:
        """Optimistic external-work event가 읽은 원본과 current record를 비교합니다.

        Args:
            other: Regression 실행 전에 읽은 expected incident record입니다.

        Returns:
            Persisted payload 전체가 같으면 True입니다.
        """
        return self.to_payload() == other.to_payload()

    def to_payload(self) -> dict[str, object]:
        """Status별 complete shape만 포함하는 canonical incident object를 만듭니다.

        Returns:
            Stable/occurrence identity, observation, lifecycle evidence를 담은 object입니다.
        """
        payload: dict[str, object] = {
            "id": str(self.id),
            "rule_id": self.rule_id,
            "occurrence_id": str(self.id),
            "actor_id": str(self.actor_id),
            "status": self.status.value,
            "symptom": self.symptom,
            "recorded_at": self.recorded_at,
        }
        if self.status is HarnessIncidentStatus.RESOLVED:
            payload.update(
                {
                    "root_cause": self.root_cause,
                    "harness_fix": list(self.harness_fix),
                    "regression_evidence": [
                        receipt.to_payload() for receipt in self.regression_evidence
                    ],
                    "resolved_at": self.resolved_at,
                }
            )
            if self.evidence_refreshed_at is not None:
                payload["evidence_refreshed_at"] = self.evidence_refreshed_at
            if self.evidence_superseded_at is not None:
                payload["evidence_superseded_at"] = self.evidence_superseded_at
            if self.superseded_resolution_evidence:
                payload["superseded_resolution_evidence"] = [
                    evidence.to_payload() for evidence in self.superseded_resolution_evidence
                ]
        elif self.status is HarnessIncidentStatus.ESCALATED:
            payload["escalation"] = {
                "handoff_route": "loop-owner",
                "summary": self.escalation_summary,
                "reproduction_commands": list(self.reproduction_commands),
            }
            payload["escalated_at"] = self.escalated_at
        return payload

    def _validate_lifecycle(
        self,
        status: HarnessIncidentStatus,
        root_cause: str | None,
        harness_fix: tuple[str, ...],
        regression_evidence: tuple[HarnessRegressionReceipt, ...],
        resolved_at: str | None,
        escalation_summary: str | None,
        reproduction_commands: tuple[str, ...],
        escalated_at: str | None,
        superseded_resolution_evidence: tuple[HarnessIncidentEvidenceArchive, ...],
    ) -> None:
        if status is HarnessIncidentStatus.OPEN:
            if any(
                value
                for value in (
                    root_cause,
                    harness_fix,
                    regression_evidence,
                    resolved_at,
                    escalation_summary,
                    reproduction_commands,
                    escalated_at,
                    superseded_resolution_evidence,
                )
            ):
                raise InvalidSessionState("open incident cannot contain terminal evidence")
            return
        if status is HarnessIncidentStatus.RESOLVED:
            if (
                root_cause is None
                or not root_cause.strip()
                or not harness_fix
                or not regression_evidence
                or resolved_at is None
                or not resolved_at.strip()
            ):
                raise InvalidSessionState("resolved incident evidence must be complete")
            if escalation_summary is not None or reproduction_commands or escalated_at is not None:
                raise InvalidSessionState("resolved incident cannot contain escalation evidence")
            return
        if (
            escalation_summary is None
            or not escalation_summary.strip()
            or not reproduction_commands
            or escalated_at is None
            or not escalated_at.strip()
        ):
            raise InvalidSessionState("escalated incident evidence must be complete")
        if root_cause is not None or harness_fix or regression_evidence or resolved_at is not None:
            raise InvalidSessionState("escalated incident cannot contain resolution evidence")


class OutboxEffect(ImmutableValue):
    """State commit 뒤 exact adapter가 실행할 bounded pending effect입니다."""

    __slots__ = ("actor_id", "delivery_key", "id", "kind", "payload")

    def __init__(
        self,
        *,
        effect_id: EffectId,
        actor_id: ActorId,
        kind: EffectKind,
        delivery_key: str,
        payload: Mapping[str, object],
    ) -> None:
        """Effect identity, authority, idempotency와 detached payload를 고정합니다.

        Args:
            effect_id: Pending map에서 effect를 식별하는 opaque identity입니다.
            actor_id: Effect 실행과 ACK를 소유하는 exact session actor입니다.
            kind: Runtime adapter가 실행할 closed effect 종류입니다.
            delivery_key: External side effect retry가 중복 실행되지 않게 하는 key입니다.
            payload: Reducer 밖에서 완전히 준비된 JSON-compatible instruction입니다.

        Raises:
            TransitionRejected: Delivery key 또는 payload key가 invalid하면 발생합니다.
        """
        if not delivery_key.strip():
            raise TransitionRejected("outbox delivery_key must not be empty")
        if any(not isinstance(key, str) for key in payload):
            raise TransitionRejected("outbox payload keys must be strings")
        object.__setattr__(self, "id", effect_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "delivery_key", delivery_key.strip())
        object.__setattr__(self, "payload", MappingProxyType(dict(payload)))

    id: EffectId
    """Pending outbox map의 stable effect identity입니다."""

    actor_id: ActorId
    """Effect execution과 ACK authority를 가진 actor입니다."""

    kind: EffectKind
    """Runtime adapter가 실행할 closed effect 종류입니다."""

    delivery_key: str
    """External retry에서 사용하는 idempotency key입니다."""

    payload: Mapping[str, object]
    """Commit 전에 준비된 read-only external instruction입니다."""

    def to_payload(self) -> dict[str, object]:
        """Canonical snapshot에 저장할 JSON-compatible payload를 반환합니다.

        Returns:
            Effect identity, authority, 종류와 detached instruction을 담은 payload입니다.
        """
        return {
            "id": str(self.id),
            "actor_id": str(self.actor_id),
            "kind": self.kind.value,
            "delivery_key": self.delivery_key,
            "payload": dict(self.payload),
        }

    def same_snapshot(self, other: OutboxEffect) -> bool:
        """두 effect가 같은 logical pending delivery인지 비교합니다.

        Args:
            other: Canonical payload 동등성을 비교할 다른 pending effect입니다.

        Returns:
            모든 serialized field가 같으면 참입니다.
        """
        return self.to_payload() == other.to_payload()


class ProcessState(ImmutableValue):
    """한 session의 immutable latest operational snapshot입니다."""

    __slots__ = (
        "actors",
        "delegations",
        "foreground_turns",
        "incidents",
        "mailboxes",
        "material_actions",
        "outbox",
        "resources",
        "revision",
        "session",
        "workflows",
    )

    def __init__(
        self,
        revision: int,
        session: SessionRecord,
        actors: Mapping[ActorId, ActorRecord],
        workflows: Mapping[WorkflowId, WorkflowRecord] | None = None,
        delegations: Mapping[DelegationId, DelegationRecord] | None = None,
        resources: Mapping[str, object] | None = None,
        mailboxes: Mapping[str, object] | None = None,
        incidents: Mapping[IncidentId, HarnessIncidentRecord] | None = None,
        outbox: Mapping[EffectId, OutboxEffect] | None = None,
        foreground_turns: Mapping[ActorId, ForegroundTurnRecord] | None = None,
        material_actions: Mapping[ActorId, MaterialActionBatch] | None = None,
    ) -> None:
        """한 revision의 validated operational data를 read-only snapshot으로 고정합니다.

        Args:
            revision: Optimistic compare-and-swap가 비교하는 non-negative version입니다.
            session: Snapshot이 귀속되는 exact session identity와 lifecycle입니다.
            actors: Actor identity별 topology 및 lifecycle record입니다.
            workflows: Session 안 workflow invocation의 persisted projection입니다.
            delegations: Delegation identity별 독립 assignment snapshot입니다.
            resources: Worktree 같은 cross-actor resource의 persisted claim입니다.
            mailboxes: Actor 간 durable message delivery state입니다.
            incidents: Session execution 중 기록된 harness incident state입니다.
            outbox: Commit 뒤 외부 delivery를 기다리는 durable event state입니다.
            foreground_turns: Actor별 latest outer turn lifecycle입니다.
            material_actions: Actor별 latest material mutation batch입니다.
        """
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "session", session)
        object.__setattr__(self, "actors", MappingProxyType(dict(actors)))
        object.__setattr__(self, "workflows", MappingProxyType(dict(workflows or {})))
        object.__setattr__(self, "delegations", MappingProxyType(dict(delegations or {})))
        object.__setattr__(
            self,
            "resources",
            MappingProxyType(dict(resources or {"worktrees": {}})),
        )
        object.__setattr__(self, "mailboxes", MappingProxyType(dict(mailboxes or {})))
        object.__setattr__(self, "incidents", MappingProxyType(dict(incidents or {})))
        object.__setattr__(self, "outbox", MappingProxyType(dict(outbox or {})))
        object.__setattr__(
            self,
            "foreground_turns",
            MappingProxyType(dict(foreground_turns or {})),
        )
        object.__setattr__(
            self,
            "material_actions",
            MappingProxyType(dict(material_actions or {})),
        )

    revision: int
    """Optimistic compare-and-swap가 stale writer를 판별하는 snapshot version입니다."""

    session: SessionRecord
    """Snapshot이 귀속되는 exact session identity와 lifecycle record입니다."""

    actors: Mapping[ActorId, ActorRecord]
    """Actor identity를 lineage 및 lifecycle record로 연결하는 read-only map입니다."""

    workflows: Mapping[WorkflowId, WorkflowRecord]
    """Workflow identity를 typed aggregate snapshot으로 연결하는 read-only map입니다."""

    delegations: Mapping[DelegationId, DelegationRecord]
    """동시에 존재하는 delegation을 identity별로 보존하는 read-only map입니다."""

    resources: Mapping[str, object]
    """Worktree 등 session actor가 사용하는 durable resource claim projection입니다."""

    mailboxes: Mapping[str, object]
    """Actor 사이의 durable message delivery 상태를 보존하는 projection입니다."""

    incidents: Mapping[IncidentId, HarnessIncidentRecord]
    """Occurrence identity를 typed harness incident aggregate로 연결하는 projection입니다."""

    outbox: Mapping[EffectId, OutboxEffect]
    """Snapshot commit 뒤 외부 delivery를 기다리는 event projection입니다."""

    foreground_turns: Mapping[ActorId, ForegroundTurnRecord]
    """Actor별 latest foreground turn aggregate를 연결하는 read-only map입니다."""

    material_actions: Mapping[ActorId, MaterialActionBatch]
    """Actor별 latest material-action batch를 연결하는 read-only map입니다."""

    def __replace__(self, **changes: object) -> ProcessState:
        """Copy this snapshot while replacing named projections and preserving all others.

        Constructors remain responsible for freezing mappings. Reject unknown fields
        before rebuilding so a misspelled projection cannot silently lose an update.
        """
        unknown = changes.keys() - self.__slots__
        if unknown:
            raise TypeError(f"unknown ProcessState fields: {', '.join(sorted(unknown))}")
        return ProcessState(
            **{name: changes.get(name, getattr(self, name)) for name in self.__slots__}
        )

    def with_revision(self, revision: int) -> ProcessState:
        """Preserve every aggregate projection while advancing the CAS revision."""
        return self.__replace__(revision=revision)

    def to_payload(self) -> dict[str, object]:
        """Snapshot을 standard `.process-state.json` payload로 변환합니다.

        Returns:
            Schema marker와 모든 operational projection을 담은 JSON-compatible object입니다.
        """
        return {
            "schema": PROCESS_STATE_SCHEMA,
            "revision": self.revision,
            "session": self.session.to_payload(),
            "actors": {
                str(actor_id): actor.to_payload() for actor_id, actor in self.actors.items()
            },
            "workflows": {
                str(workflow_id): workflow.to_payload()
                for workflow_id, workflow in self.workflows.items()
            },
            "foreground_turns": {
                str(actor_id): turn.to_payload() for actor_id, turn in self.foreground_turns.items()
            },
            "material_actions": {
                str(actor_id): batch.to_payload()
                for actor_id, batch in self.material_actions.items()
            },
            "delegations": {
                str(delegation_id): delegation.to_payload()
                for delegation_id, delegation in self.delegations.items()
            },
            "resources": dict(self.resources),
            "mailboxes": dict(self.mailboxes),
            "incidents": {
                str(incident_id): incident.to_payload()
                for incident_id, incident in self.incidents.items()
            },
            "outbox": {
                str(effect_id): effect.to_payload() for effect_id, effect in self.outbox.items()
            },
        }


class MonitorWorkflowStopProjection(ImmutableValue):
    """Foreground Stop과 함께 commit할 monitor workflow의 immutable 후보입니다."""

    __slots__ = ("expected_workflow_revision", "skill_state", "workflow_id")

    def __init__(
        self,
        *,
        workflow_id: WorkflowId,
        expected_workflow_revision: int,
        skill_state: Mapping[str, object],
    ) -> None:
        """한 번 읽은 workflow revision과 pure Stop transform 결과를 고정합니다.

        Args:
            workflow_id: Stop projection을 적용할 exact monitor workflow입니다.
            expected_workflow_revision: Caller가 캡처한 workflow-local CAS revision입니다.
            skill_state: StopTransitionMutation이 만든 complete skill-state 후보입니다.

        Raises:
            TransitionRejected: Revision이 음수이거나 skill-state key가 문자열이 아니면
                발생합니다.
        """
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise TransitionRejected("monitor workflow revision must be non-negative")
        if any(not isinstance(key, str) for key in skill_state):
            raise TransitionRejected("monitor workflow skill-state keys must be strings")
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "expected_workflow_revision", expected_workflow_revision)
        object.__setattr__(self, "skill_state", MappingProxyType(dict(skill_state)))

    workflow_id: WorkflowId
    """Projection이 갱신할 exact workflow identity입니다."""

    expected_workflow_revision: int
    """Foreground Stop 진입 시 캡처한 workflow-local CAS revision입니다."""

    skill_state: Mapping[str, object]
    """Unrelated workflow payload와 결합할 complete monitor skill-state 후보입니다."""
