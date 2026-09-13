"""Session-scoped coding-agent state의 identity, reducer, optimistic store를 제공합니다."""

import fcntl
import hashlib
import json
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Self

from scripts.agent_harness.adaptive_control import ControlAction
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    InvalidAdaptiveControlState,
    validate_adaptive_control_transition,
    validate_efficiency_resource_admission,
)
from scripts.agent_harness.adaptive_policy import (
    requires_adaptive_control_for_workflow,
    validate_adaptive_control_policy_transition,
)
from scripts.agent_harness.material_action import (
    AdaptiveActionBinding,
    MaterialActionBatch,
    MaterialActionKind,
    MaterialActionResolution,
    MaterialActionStatus,
    ObservableExpectation,
    ToolInvocation,
    ToolReceipt,
    ToolReceiptOutcome,
)
from scripts.agent_harness.session_state_codec import (  # noqa: F401 - public snapshot API
    SessionStateCodec,
    SessionStateValidator,
)
from scripts.agent_harness.skill_state_contract import SessionKernelError
from scripts.agent_harness.workflow_terminal import WorkflowTerminalPolicy

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


class SessionPaths(ImmutableValue):
    """한 exact session의 canonical persistence path 모음입니다."""

    __slots__ = (
        "artifacts",
        "directory",
        "enclave",
        "enclave_lock",
        "process_state",
        "process_state_lock",
    )

    def __init__(self, directory: Path) -> None:
        """Exact session directory에서 모든 canonical persistence path를 계산합니다.

        Args:
            directory: 단일 session이 소유하는 canonical control-plane directory입니다.
        """
        object.__setattr__(self, "directory", directory)
        object.__setattr__(self, "process_state", directory / ".process-state.json")
        object.__setattr__(self, "process_state_lock", directory / ".process-state.json.lock")
        object.__setattr__(self, "enclave", directory / "enclave.json")
        object.__setattr__(self, "enclave_lock", directory / "enclave.json.lock")
        object.__setattr__(self, "artifacts", directory / "artifacts")

    directory: Path
    """단일 exact session이 소유하는 canonical control-plane directory입니다."""

    process_state: Path
    """Revision과 operational snapshot을 보존하는 canonical JSON file입니다."""

    process_state_lock: Path
    """Process-state compare-and-swap commit 구간을 직렬화하는 lock file입니다."""

    enclave: Path
    """Session-private durable fact를 격리해 보존하는 enclave JSON file입니다."""

    enclave_lock: Path
    """Enclave 최초 생성을 직렬화하는 lock file입니다."""

    artifacts: Path
    """Exact session 실행에서 생성한 artifact를 격리하는 directory입니다."""


class SessionLocator:
    """Validated session identity를 canonical control-plane path로 변환합니다."""

    def __init__(self, control_root: Path) -> None:
        """Repository 공통 control-plane root에 locator를 고정합니다.

        Args:
            control_root: 모든 linked worktree가 공유할 repository control root입니다.
        """
        self._control_root = control_root.absolute()

    @property
    def control_root(self) -> Path:
        """Repository control-plane root를 반환합니다.

        Returns:
            Session directory와 resource registry를 포함하는 absolute root입니다.
        """
        return self._control_root

    @property
    def worktree_registry_root(self) -> Path:
        """Cross-session worktree claim registry path를 반환합니다.

        Returns:
            모든 session이 공유하는 worktree claim directory입니다.
        """
        return __import__("scripts._neurath_paths", fromlist=["state_path"]).state_path(self._control_root, "resources/worktrees")

    @classmethod
    def from_worktree(cls, worktree: Path) -> SessionLocator:
        """Git common directory에서 linked worktree 공통 control root를 결정합니다.

        Args:
            worktree: Repository 또는 linked worktree 안의 경로입니다.

        Returns:
            Git common directory를 기준으로 모든 worktree가 공유하는 locator입니다.

        Raises:
            subprocess.CalledProcessError: 경로가 유효한 Git worktree가 아니면 발생합니다.
        """
        completed = subprocess.run(
            (
                "git",
                "-C",
                str(worktree),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        common_directory = Path(completed.stdout.strip()).resolve()
        if common_directory.name == ".git":
            return cls(common_directory.parent)
        return cls(common_directory)

    def locate(self, session_id: SessionId) -> SessionPaths:
        """Exact session directory를 scan 없이 결정합니다.

        Args:
            session_id: Canonical directory 이름으로 사용할 validated session identity입니다.

        Returns:
            다른 session으로 fallback하지 않는 exact persistence path 모음입니다.

        Raises:
            InvalidIdentity: Session identity가 path traversal을 허용하면 발생합니다.
        """
        self._validate_path_identity(session_id)
        return SessionPaths(__import__("scripts._neurath_paths", fromlist=["state_path"]).state_path(self._control_root, "runs") / str(session_id))

    def _validate_path_identity(self, session_id: SessionId) -> None:
        if session_id in {SessionId("."), SessionId("..")}:
            raise InvalidIdentity(f"unsafe session id: {session_id}")
        if "/" in session_id or "\\" in session_id or "\x00" in session_id:
            raise InvalidIdentity(f"unsafe session id: {session_id}")


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
            or receipt is None or receipt.outcome is not ForegroundTurnOutcome.INCOMPLETE
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
        if self.receipt is not None and self.receipt.outcome is ForegroundTurnOutcome.AWAITING_INPUT:
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
                None if self.replacement_question is None else self.replacement_question.to_payload()
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
        return hash((
            self.command,
            self.exit_code,
            self.head_sha,
            self.verified_at,
            self.output_sha256,
        ))

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
            payload.update({
                "root_cause": self.root_cause,
                "harness_fix": list(self.harness_fix),
                "regression_evidence": [
                    receipt.to_payload() for receipt in self.regression_evidence
                ],
                "resolved_at": self.resolved_at,
            })
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

    def with_revision(self, revision: int) -> ProcessState:
        """내용을 유지하고 CAS revision만 바꾼 새 snapshot을 반환합니다.

        Args:
            revision: Commit 직전에 확정된 다음 compare-and-swap version입니다.

        Returns:
            Operational data는 공유하고 요청한 revision을 가진 immutable snapshot입니다.
        """
        return ProcessState(
            revision,
            self.session,
            self.actors,
            self.workflows,
            self.delegations,
            self.resources,
            self.mailboxes,
            self.incidents,
            self.outbox,
            self.foreground_turns,
            self.material_actions,
        )

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

    def __init__(self, session_id: SessionId, actor_id: ActorId, parent_actor_id: ActorId,
                 expected_turn_revision: int, vendor_turn_id: str, idempotency_key: str) -> None:
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
            not normalized or chr(0) in normalized
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


class SessionStateReducer:
    """I/O나 clock access 없이 typed event를 immutable state로 reduce합니다."""

    _RESERVED_SKILL_STATE_NAMESPACES = frozenset({"adaptive_control"})

    def reduce(self, state: ProcessState | None, event: KernelEvent) -> ProcessState:
        """현재 snapshot과 typed event에서 부작용 없이 다음 snapshot을 계산합니다.

        Args:
            state: Event 적용 전 snapshot이며 session 시작 전에는 존재하지 않습니다.
            event: Session lifecycle과 topology를 변경하려는 closed-family event입니다.

        Returns:
            Event가 반영된 immutable snapshot 또는 idempotent 재적용 시 기존 snapshot입니다.

        Raises:
            SessionNotFound: Session 시작 외 event에 대응하는 snapshot이 없으면 발생합니다.
            TransitionRejected: Session identity, terminal 상태, topology 또는 reference
                invariant상 event를 적용할 수 없으면 발생합니다.
        """
        if isinstance(event, SessionStarted):
            return self._start_session(state, event)
        if state is None:
            raise SessionNotFound(f"session state is missing: {event.session_id}")
        if state.session.id != event.session_id:
            raise TransitionRejected("event session does not match state session")
        if isinstance(event, SessionEnded):
            return self._end_session(state, event)
        if isinstance(event, EffectAcknowledged):
            return self._acknowledge_effect(state, event)
        if state.session.status is SessionStatus.ENDED:
            raise TransitionRejected("terminal session rejects mutations")
        if isinstance(event, EffectPrepared):
            return self._prepare_effect(state, event)
        if isinstance(event, SessionResumed):
            return self._resume_session(state, event)
        if isinstance(event, SessionCompacted):
            return self._compact_session(state, event)
        if isinstance(event, ActorStarted):
            return self._start_actor(state, event)
        if isinstance(event, ActorResumed):
            return self._resume_actor(state, event)
        if isinstance(event, ActorStopped):
            return self._stop_actor(state, event)
        if isinstance(event, WorkflowStarted):
            return self._start_workflow(state, event)
        if isinstance(event, WorkflowAdvanced):
            return self._advance_workflow(state, event)
        if isinstance(event, WorkflowFinalized):
            return self._finalize_workflow(state, event)
        if isinstance(event, ForegroundTurnProvisioned):
            return self._provision_foreground_turn(state, event)
        if isinstance(event, ForegroundTurnPrompted):
            return self._prompt_foreground_turn(state, event)
        if isinstance(event, ForegroundTurnToolObserved):
            return self._observe_foreground_turn_tool(state, event)
        if isinstance(event, MaterialActionPrepared):
            return self._prepare_material_action(state, event)
        if isinstance(event, MaterialActionToolStarted):
            return self._start_material_action_tool(state, event)
        if isinstance(event, MaterialActionToolObserved):
            return self._observe_material_action_tool(state, event)
        if isinstance(event, MaterialActionAbandoned):
            return self._abandon_material_action_tool(state, event)
        if isinstance(event, MaterialActionResolved):
            return self._resolve_material_action(state, event)
        if isinstance(event, ForegroundTurnYielded):
            return self._yield_foreground_turn(state, event)
        if isinstance(event, ForegroundTurnInvalidated):
            return self._invalidate_foreground_turn(state, event)
        if isinstance(event, ForegroundTurnClosed):
            return self._close_foreground_turn(state, event)
        if isinstance(event, ForegroundTurnReplaced):
            return self._replace_foreground_turn(state, event)
        if isinstance(event, DelegationAssigned):
            return self._assign_delegation(state, event)
        if isinstance(event, DelegationCancelled):
            return self._cancel_delegation(state, event)
        if isinstance(event, DelegationReported):
            return self._report_delegation(state, event)
        if isinstance(event, DelegationConsumed):
            return self._consume_delegation(state, event)
        if isinstance(event, HarnessIncidentRecorded):
            return self._record_incident(state, event)
        if isinstance(event, HarnessIncidentResolved):
            return self._resolve_incident(state, event)
        if isinstance(event, HarnessIncidentEscalated):
            return self._escalate_incident(state, event)
        if isinstance(event, HarnessIncidentsRefreshed):
            return self._refresh_incidents(state, event)
        if isinstance(event, HarnessIncidentEvidenceSuperseded):
            return self._supersede_incident_evidence(state, event)
        raise TransitionRejected(f"unsupported event type: {type(event).__name__}")

    def _start_session(
        self,
        state: ProcessState | None,
        event: SessionStarted,
    ) -> ProcessState:
        if state is not None:
            expected = (
                state.session.id,
                state.session.resume_id,
                state.session.runtime,
                state.session.root_actor_id,
                state.session.parent_session_id,
                state.session.lifecycle_provenance_id,
            )
            requested = (
                event.session_id,
                event.resume_id,
                event.runtime,
                event.root_actor_id,
                event.parent_session_id,
                event.lifecycle_provenance_id,
            )
            if expected == requested:
                return state
            raise TransitionRejected(f"session already exists: {event.session_id}")
        root_actor = ActorRecord(
            event.root_actor_id,
            None,
            ActorKind.ROOT,
            ActorStatus.ACTIVE,
        )
        return ProcessState(
            revision=0,
            session=SessionRecord(
                event.session_id,
                event.resume_id,
                event.runtime,
                event.root_actor_id,
                SessionStatus.ACTIVE,
                event.parent_session_id,
                event.lifecycle_provenance_id,
                event.idempotency_key,
            ),
            actors={event.root_actor_id: root_actor},
            outbox=({} if event.effect is None else {event.effect.id: event.effect}),
        )

    def _resume_session(
        self,
        state: ProcessState,
        event: SessionResumed,
    ) -> ProcessState:
        self._require_root_lifecycle_actor(state, event.actor_id)
        if state.session.last_lifecycle_idempotency_key == event.idempotency_key:
            if state.session.resume_id != event.resume_id:
                raise TransitionRejected("resume retry changed its opaque resume handle")
            return state
        resumed = self._with_session_lifecycle(
            state,
            resume_id=event.resume_id,
            idempotency_key=event.idempotency_key,
            effect=event.effect,
        )
        batch = resumed.material_actions.get(event.actor_id)
        if batch is None or batch.in_flight is None:
            return resumed
        invocation = batch.in_flight
        interruption_identity = "\x1f".join((
            str(event.session_id),
            str(event.resume_id),
            event.lifecycle_provenance_id,
            invocation.invocation_id,
        ))
        receipt = ToolReceipt(
            receipt_id=(
                "runtime-interrupted:"
                f"{hashlib.sha256(interruption_identity.encode('utf-8')).hexdigest()}"
            ),
            request_digest=invocation.request_digest,
            outcome=ToolReceiptOutcome.UNKNOWN,
            output_digest=hashlib.sha256(b"runtime-interrupted").hexdigest(),
            observations=(),
        )
        try:
            recovered = batch.observe_tool(invocation.invocation_id, receipt).resolve(
                MaterialActionResolution.BLOCKED
            )
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        return self._with_material_action(resumed, event.actor_id, recovered)

    def _compact_session(
        self,
        state: ProcessState,
        event: SessionCompacted,
    ) -> ProcessState:
        self._require_root_lifecycle_actor(state, event.actor_id)
        if state.session.last_lifecycle_idempotency_key == event.idempotency_key:
            return state
        return self._with_session_lifecycle(
            state,
            resume_id=state.session.resume_id,
            idempotency_key=event.idempotency_key,
            effect=event.effect,
        )

    def _acknowledge_effect(
        self,
        state: ProcessState,
        event: EffectAcknowledged,
    ) -> ProcessState:
        effect = state.outbox.get(event.effect_id)
        if effect is None:
            return state
        if effect.actor_id != event.actor_id:
            raise TransitionRejected("effect actor does not match pending delivery owner")
        outbox = dict(state.outbox)
        del outbox[event.effect_id]
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _prepare_effect(
        self,
        state: ProcessState,
        event: EffectPrepared,
    ) -> ProcessState:
        existing = state.outbox.get(event.effect.id)
        if existing is not None:
            if existing.same_snapshot(event.effect):
                return state
            raise TransitionRejected(f"outbox effect identity already exists: {event.effect.id}")
        self._require_available_actor(state, event.actor_id, "effect owner")
        outbox = self._append_effect(state.outbox, event.effect)
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _with_session_lifecycle(
        self,
        state: ProcessState,
        *,
        resume_id: ResumeId | None,
        idempotency_key: str,
        effect: OutboxEffect,
    ) -> ProcessState:
        outbox = self._append_effect(state.outbox, effect)
        session = SessionRecord(
            state.session.id,
            resume_id,
            state.session.runtime,
            state.session.root_actor_id,
            state.session.status,
            state.session.parent_session_id,
            state.session.lifecycle_provenance_id,
            idempotency_key,
        )
        return ProcessState(
            state.revision,
            session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _append_effect(
        self,
        current: Mapping[EffectId, OutboxEffect],
        effect: OutboxEffect,
    ) -> dict[EffectId, OutboxEffect]:
        existing = current.get(effect.id)
        if existing is not None:
            if existing.same_snapshot(effect):
                return dict(current)
            raise TransitionRejected(f"outbox effect identity already exists: {effect.id}")
        if any(item.delivery_key == effect.delivery_key for item in current.values()):
            raise TransitionRejected(f"outbox delivery key already exists: {effect.delivery_key}")
        if len(current) >= MAX_PENDING_OUTBOX_EFFECTS:
            raise TransitionRejected("pending outbox capacity is exhausted")
        outbox = dict(current)
        outbox[effect.id] = effect
        return outbox

    def _require_root_lifecycle_actor(
        self,
        state: ProcessState,
        actor_id: ActorId,
    ) -> None:
        if actor_id != state.session.root_actor_id:
            raise TransitionRejected("lifecycle transition requires the root actor")
        self._require_available_actor(state, actor_id, "root actor")

    def _start_actor(self, state: ProcessState, event: ActorStarted) -> ProcessState:
        current = state.actors.get(event.actor_id)
        if current is not None:
            if (
                current.parent_actor_id == event.parent_actor_id
                and current.kind is event.kind
                and current.status is ActorStatus.ACTIVE
                and current.lineage_assurance is event.lineage_assurance
            ):
                return state
            raise TransitionRejected(f"actor identity already exists: {event.actor_id}")
        if event.kind is ActorKind.ROOT:
            raise TransitionRejected("a session cannot start a second root actor")
        if event.parent_actor_id is None:
            raise TransitionRejected(f"parent actor is missing: {event.parent_actor_id}")
        self._require_available_actor(state, event.parent_actor_id, "actor parent")
        actors = dict(state.actors)
        actors[event.actor_id] = ActorRecord(
            event.actor_id,
            event.parent_actor_id,
            event.kind,
            ActorStatus.ACTIVE,
            event.lineage_assurance,
        )
        outbox = (
            dict(state.outbox)
            if event.effect is None
            else self._append_effect(state.outbox, event.effect)
        )
        return ProcessState(
            state.revision,
            state.session,
            actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _resume_actor(self, state: ProcessState, event: ActorResumed) -> ProcessState:
        actor = state.actors.get(event.actor_id)
        turn = state.foreground_turns.get(event.actor_id)
        parent_turn = state.foreground_turns.get(event.parent_actor_id)
        if (actor is None or actor.kind is not ActorKind.SUBAGENT
                or actor.status is not ActorStatus.STOPPED
                or actor.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
                or actor.parent_actor_id != event.parent_actor_id
                or event.parent_actor_id != state.session.root_actor_id
                or turn is None or turn.status is not ForegroundTurnStatus.CLOSED
                or turn.revision != event.expected_turn_revision
                or turn.vendor_turn_id == event.vendor_turn_id
                or parent_turn is None or parent_turn.status is not ForegroundTurnStatus.ACTIVE):
            raise TransitionRejected("actor resume lacks an exact stopped direct child and new turn")
        self._require_available_actor(state, event.parent_actor_id, "actor parent")
        actors = dict(state.actors)
        actors[event.actor_id] = ActorRecord(actor.id, actor.parent_actor_id, actor.kind,
                                             ActorStatus.ACTIVE, actor.lineage_assurance)
        turns = dict(state.foreground_turns)
        turns[event.actor_id] = ForegroundTurnRecord(
            event.actor_id, turn.generation + 1, turn.revision + 1,
            ForegroundTurnStatus.ACTIVE, None, event.vendor_turn_id,
        )
        return ProcessState(state.revision, state.session, actors, state.workflows,
                            state.delegations, state.resources, state.mailboxes, state.incidents,
                            state.outbox, turns, state.material_actions)

    def _stop_actor(self, state: ProcessState, event: ActorStopped) -> ProcessState:
        actor = state.actors.get(event.actor_id)
        if actor is None:
            raise TransitionRejected(f"actor is missing: {event.actor_id}")
        if event.actor_id == state.session.root_actor_id:
            raise TransitionRejected("root actor is retired only by session end")
        if actor.status is event.terminal_status:
            return state
        if actor.status is ActorStatus.RETIRED or (
            actor.status is ActorStatus.STOPPED and event.terminal_status is not ActorStatus.RETIRED
        ):
            raise TransitionRejected(f"actor is already terminal: {event.actor_id}")
        actors = dict(state.actors)
        actors[event.actor_id] = ActorRecord(
            actor.id,
            actor.parent_actor_id,
            actor.kind,
            event.terminal_status,
            actor.lineage_assurance,
        )
        return ProcessState(
            state.revision,
            state.session,
            actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _end_session(self, state: ProcessState, event: SessionEnded) -> ProcessState:
        if event.actor_id != state.session.root_actor_id:
            raise TransitionRejected("only the root actor can end a session")
        if state.session.status is SessionStatus.ENDED:
            return state
        self._require_available_actor(state, event.actor_id, "session owner")
        actors = {
            actor_id: ActorRecord(
                actor.id,
                actor.parent_actor_id,
                actor.kind,
                ActorStatus.RETIRED,
                actor.lineage_assurance,
            )
            for actor_id, actor in state.actors.items()
        }
        session = SessionRecord(
            state.session.id,
            state.session.resume_id,
            state.session.runtime,
            state.session.root_actor_id,
            SessionStatus.ENDED,
            state.session.parent_session_id,
            state.session.lifecycle_provenance_id,
            event.idempotency_key,
        )
        return ProcessState(
            state.revision,
            session,
            actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _start_workflow(
        self,
        state: ProcessState,
        event: WorkflowStarted,
    ) -> ProcessState:
        existing = state.workflows.get(event.workflow_id)
        if existing is not None:
            if (
                existing.owner_actor_id == event.owner_actor_id
                and existing.kind == event.kind
                and existing.goal == event.goal
                and existing.payload == event.payload
                and existing.revision == 0
                and existing.status is WorkflowStatus.ACTIVE
            ):
                return state
            raise TransitionRejected(f"workflow identity already exists: {event.workflow_id}")
        self._require_available_actor(state, event.owner_actor_id, "workflow owner")
        self._require_adaptive_control_policy_transition(
            event.kind,
            None,
            event.payload,
        )
        self._require_reserved_skill_state_preserved(None, event.payload, frozenset())
        workflows = dict(state.workflows)
        workflows[event.workflow_id] = WorkflowRecord(
            event.workflow_id,
            event.owner_actor_id,
            event.kind,
            event.goal,
            event.payload,
            0,
            WorkflowStatus.ACTIVE,
            event.idempotency_key,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _advance_workflow(
        self,
        state: ProcessState,
        event: WorkflowAdvanced,
    ) -> ProcessState:
        workflow = state.workflows.get(event.workflow_id)
        if workflow is None:
            raise TransitionRejected(f"workflow is missing: {event.workflow_id}")
        self._authorize_workflow_actor(state, workflow, event.actor_id)
        if workflow.last_transition_idempotency_key == event.idempotency_key:
            if (
                workflow.revision == event.expected_workflow_revision + 1
                and workflow.payload == event.payload
                and workflow.status is WorkflowStatus.ACTIVE
            ):
                return state
            raise TransitionRejected("workflow idempotency key was reused with different intent")
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise TransitionRejected(f"workflow is terminal: {event.workflow_id}")
        if workflow.revision != event.expected_workflow_revision:
            raise TransitionRejected(
                f"expected workflow revision {event.expected_workflow_revision}, "
                f"got {workflow.revision}"
            )
        self._require_adaptive_control_policy_transition(
            workflow.kind,
            workflow.payload,
            event.payload,
        )
        changed_reserved = self._changed_reserved_skill_state_namespaces(
            workflow.payload,
            event.payload,
        )
        if changed_reserved:
            if not isinstance(event, ReservedSkillStateAdvanced):
                names = ", ".join(sorted(changed_reserved))
                raise TransitionRejected(
                    f"reserved skill-state namespace requires typed mutation: {names}"
                )
            self._validate_adaptive_control_transition(
                workflow.payload,
                event.payload,
            )
        self._require_reserved_skill_state_preserved(
            workflow.payload,
            event.payload,
            changed_reserved,
        )
        try:
            WorkflowTerminalPolicy().validate_transition(workflow.payload, event.payload)
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        workflows = dict(state.workflows)
        workflows[event.workflow_id] = WorkflowRecord(
            workflow.id,
            workflow.owner_actor_id,
            workflow.kind,
            workflow.goal,
            event.payload,
            workflow.revision + 1,
            workflow.status,
            event.idempotency_key,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _finalize_workflow(
        self,
        state: ProcessState,
        event: WorkflowFinalized,
    ) -> ProcessState:
        workflow = state.workflows.get(event.workflow_id)
        if workflow is None:
            raise TransitionRejected(f"workflow is missing: {event.workflow_id}")
        self._authorize_workflow_actor(state, workflow, event.actor_id)
        if workflow.last_transition_idempotency_key == event.idempotency_key:
            if (
                workflow.revision == event.expected_workflow_revision + 1
                and workflow.payload == event.payload
                and workflow.status is event.terminal_status
            ):
                return state
            raise TransitionRejected("workflow idempotency key was reused with different intent")
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise TransitionRejected(f"workflow is terminal: {event.workflow_id}")
        if workflow.revision != event.expected_workflow_revision:
            raise TransitionRejected(
                f"expected workflow revision {event.expected_workflow_revision}, "
                f"got {workflow.revision}"
            )
        self._require_adaptive_control_policy_transition(
            workflow.kind,
            workflow.payload,
            event.payload,
        )
        self._require_reserved_skill_state_preserved(
            workflow.payload,
            event.payload,
            frozenset(),
        )
        if event.terminal_status is WorkflowStatus.COMPLETED:
            self._require_adaptive_completion_projection(workflow)
        previous_phase = workflow.payload.get("phase_run")
        if isinstance(previous_phase, Mapping) and requires_adaptive_control_for_workflow(
            workflow.kind,
            workflow.payload,
        ):
            candidate_phase = event.payload.get("phase_run")
            if (
                previous_phase.get("current_phase_id") is not None
                or not isinstance(candidate_phase, Mapping)
                or {key: value for key, value in previous_phase.items() if key != "terminal_state"}
                != {key: value for key, value in candidate_phase.items() if key != "terminal_state"}
            ):
                raise TransitionRejected(
                    "adaptive finalization requires previously completed phase results"
                )
        try:
            WorkflowTerminalPolicy().validate_phase(
                workflow.payload,
                event.payload,
                completed=event.terminal_status is WorkflowStatus.COMPLETED,
            )
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        workflows = dict(state.workflows)
        workflows[event.workflow_id] = WorkflowRecord(
            workflow.id,
            workflow.owner_actor_id,
            workflow.kind,
            workflow.goal,
            event.payload,
            workflow.revision + 1,
            event.terminal_status,
            event.idempotency_key,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _require_reserved_skill_state_preserved(
        self,
        current_payload: Mapping[str, object] | None,
        candidate_payload: Mapping[str, object],
        authorized_namespaces: frozenset[str],
    ) -> None:
        changed = self._changed_reserved_skill_state_namespaces(
            current_payload,
            candidate_payload,
        )
        if not changed.issubset(authorized_namespaces):
            names = ", ".join(sorted(changed))
            raise TransitionRejected(
                f"reserved skill-state namespace requires typed mutation: {names}"
            )

    def _changed_reserved_skill_state_namespaces(
        self,
        current_payload: Mapping[str, object] | None,
        candidate_payload: Mapping[str, object],
    ) -> frozenset[str]:
        """Old/new payload에서 실제로 달라진 reserved namespace를 계산합니다."""
        current = self._skill_state_namespaces(current_payload)
        candidate = self._skill_state_namespaces(candidate_payload)
        return frozenset(
            namespace
            for namespace in self._RESERVED_SKILL_STATE_NAMESPACES
            if (namespace in current) != (namespace in candidate)
            or (
                namespace in current
                and namespace in candidate
                and current[namespace] != candidate[namespace]
            )
        )

    def _validate_adaptive_control_transition(
        self,
        current_payload: Mapping[str, object],
        candidate_payload: Mapping[str, object],
    ) -> None:
        """Caller label과 무관하게 canonical adaptive old-to-new 전이를 검증합니다."""
        current = self._skill_state_namespaces(current_payload)
        candidate = self._skill_state_namespaces(candidate_payload)
        raw_candidate = candidate.get("adaptive_control")
        if not isinstance(raw_candidate, Mapping):
            raise TransitionRejected("adaptive_control candidate must be a canonical object")
        raw_previous = current.get("adaptive_control")
        if raw_previous is not None and not isinstance(raw_previous, Mapping):
            raise TransitionRejected("persisted adaptive_control state is invalid")
        try:
            previous = (
                None if raw_previous is None else AdaptiveControlState.from_payload(raw_previous)
            )
            next_state = AdaptiveControlState.from_payload(raw_candidate)
            goal_changed = (
                previous is not None
                and previous.contract.fingerprint != next_state.contract.fingerprint
            )
            validate_adaptive_control_transition(
                previous,
                next_state,
                allow_goal_override=goal_changed,
            )
        except InvalidAdaptiveControlState as error:
            raise TransitionRejected("adaptive_control transition is invalid") from error

    def _require_adaptive_completion_projection(self, workflow: WorkflowRecord) -> None:
        """Completed가 current canonical adaptive projection에서만 파생되게 합니다."""
        skill_state = self._skill_state_namespaces(workflow.payload)
        raw_state = skill_state.get("adaptive_control")
        if raw_state is None:
            try:
                required = requires_adaptive_control_for_workflow(
                    workflow.kind,
                    workflow.payload,
                )
            except (TypeError, ValueError) as error:
                raise TransitionRejected("persisted adaptive workflow policy is invalid") from error
            if required:
                raise TransitionRejected(
                    f"adaptive workflow {workflow.id} requires an adaptive_control snapshot"
                )
            return
        if not isinstance(raw_state, Mapping):
            raise TransitionRejected("persisted adaptive_control state is invalid")
        try:
            adaptive = AdaptiveControlState.from_payload(raw_state)
            receipt = AdaptiveControlSnapshot(
                workflow_id=workflow.id,
                workflow_revision=workflow.revision,
                state=adaptive,
            ).receipt()
        except InvalidAdaptiveControlState as error:
            raise TransitionRejected("persisted adaptive_control state is invalid") from error
        if (
            receipt.decision.action is not ControlAction.COMPLETE
            or not receipt.ambiguity.ready
            or not receipt.decision.achieved
            or not receipt.attainment.achieved
        ):
            raise TransitionRejected(
                f"adaptive workflow {workflow.id} requires current COMPLETE and achieved authority"
            )

    def _require_adaptive_control_policy_transition(
        self,
        workflow_kind: str,
        current_payload: Mapping[str, object] | None,
        candidate_payload: Mapping[str, object],
    ) -> None:
        """Persisted phase applicability가 start 뒤 변하지 않았는지 검증합니다.

        Args:
            workflow_kind: Workflow aggregate가 고정한 implementation kind입니다.
            current_payload: Start에서는 `None`, 이후에는 current workflow projection입니다.
            candidate_payload: Event가 제출한 다음 workflow projection입니다.

        Raises:
            TransitionRejected: Marker가 invalid하거나 admission policy와 다르면 발생합니다.
        """
        try:
            validate_adaptive_control_policy_transition(
                workflow_kind,
                current_payload,
                candidate_payload,
            )
        except (TypeError, ValueError) as error:
            raise TransitionRejected("workflow adaptive policy transition is invalid") from error

    def _skill_state_namespaces(
        self,
        payload: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        if payload is None:
            return MappingProxyType({})
        skill_state = payload.get("skill_state")
        if not isinstance(skill_state, Mapping):
            return MappingProxyType({})
        return skill_state

    def _provision_foreground_turn(
        self,
        state: ProcessState,
        event: ForegroundTurnProvisioned,
    ) -> ProcessState:
        """Actor에게 provenance 없는 최초 active turn을 idempotently 보장합니다."""
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        current = state.foreground_turns.get(event.actor_id)
        if current is not None:
            return state
        return self._with_foreground_turn(
            state,
            event.actor_id,
            ForegroundTurnRecord(
                event.actor_id,
                1,
                0,
                ForegroundTurnStatus.ACTIVE,
                None,
                None,
                None,
            ),
        )

    def _prompt_foreground_turn(
        self,
        state: ProcessState,
        event: ForegroundTurnPrompted,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        current = state.foreground_turns.get(event.actor_id)
        if current is not None and current.status is ForegroundTurnStatus.ACTIVE:
            return self._bind_active_foreground_prompt(state, current, event)
        self._validate_prompt_authority_context(state, current, event)
        if current is None:
            raise TransitionRejected(
                "foreground turn is missing; recover the exact session before UserPromptSubmit"
            )
        if current.status is ForegroundTurnStatus.CLOSED:
            generation = current.generation + 1
            revision = current.revision + 1
            next_turn = ForegroundTurnRecord(
                event.actor_id,
                generation,
                revision,
                ForegroundTurnStatus.ACTIVE,
                None,
                event.vendor_turn_id,
                self._user_prompt_receipt(event, generation, revision),
            )
        else:
            generation = current.generation
            revision = current.revision + 1
            next_turn = ForegroundTurnRecord(
                event.actor_id,
                generation,
                revision,
                ForegroundTurnStatus.ACTIVE,
                None,
                event.vendor_turn_id or current.vendor_turn_id,
                self._user_prompt_receipt(event, generation, revision),
            )
        return self._with_foreground_turn(state, event.actor_id, next_turn)

    def _bind_active_foreground_prompt(
        self,
        state: ProcessState,
        current: ForegroundTurnRecord,
        event: ForegroundTurnPrompted,
    ) -> ProcessState:
        """같은 활성 턴의 추가 입력을 수용하고 재전송과 출처 충돌을 구분합니다."""
        if current.vendor_turn_id is None and current.user_prompt_receipt is None:
            if event.authority_context is not None:
                raise TransitionRejected(
                    "provisional foreground turn cannot claim prior prompt authority"
                )
            if event.vendor_turn_id is None and event.prompt_digest is None:
                return state
        else:
            if (
                event.vendor_turn_id is not None
                and current.vendor_turn_id is not None
                and event.vendor_turn_id != current.vendor_turn_id
            ):
                raise TransitionRejected(
                    "active foreground turn has conflicting vendor turn provenance"
                )
            receipt = current.user_prompt_receipt
            if (
                event.vendor_turn_id in {None, current.vendor_turn_id}
                and event.prompt_digest == (None if receipt is None else receipt.prompt_digest)
                and (
                    event.authority_context is None
                    or self._same_prompt_authority(
                        event.authority_context,
                        None if receipt is None else receipt.authority_context,
                    )
                )
            ):
                return state
            if event.prompt_digest is None or event.authority_context is not None:
                raise TransitionRejected(
                    "active foreground turn already has different prompt provenance"
                )
        revision = current.revision + 1
        candidate = self._with_foreground_turn(
            state,
            event.actor_id,
            ForegroundTurnRecord(
                event.actor_id,
                current.generation,
                revision,
                ForegroundTurnStatus.ACTIVE,
                None,
                event.vendor_turn_id or current.vendor_turn_id,
                self._user_prompt_receipt(event, current.generation, revision),
            ),
        )
        batch = state.material_actions.get(event.actor_id)
        if batch is not None and batch.status is MaterialActionStatus.OPEN:
            candidate = self._with_material_action(
                candidate,
                event.actor_id,
                replace(batch, turn_revision=revision, revision=batch.revision + 1),
            )
        return candidate

    def _same_prompt_authority(
        self,
        requested: ForegroundPromptAuthorityContext | None,
        persisted: ForegroundPromptAuthorityContext | None,
    ) -> bool:
        if requested is None or persisted is None:
            return requested is None and persisted is None
        return requested.to_payload() == persisted.to_payload()

    def _validate_prompt_authority_context(
        self,
        state: ProcessState,
        current: ForegroundTurnRecord | None,
        event: ForegroundTurnPrompted,
    ) -> None:
        context = event.authority_context
        if context is None:
            return
        question_receipt = None if current is None else current.awaiting_input_receipt
        if (
            current is None
            or current.status
            not in {ForegroundTurnStatus.READY_TO_STOP, ForegroundTurnStatus.CLOSED}
            or question_receipt is None
            or question_receipt.outcome is not ForegroundTurnOutcome.AWAITING_INPUT
            or question_receipt.question is None
        ):
            raise TransitionRejected(
                "prompt authority context requires the exact preceding user question"
            )
        question_digest = hashlib.sha256(
            question_receipt.question.strip().encode("utf-8")
        ).hexdigest()
        if (
            context.question_digest != question_digest
            or context.question_generation != current.generation
            or context.question_turn_revision != current.revision
        ):
            raise TransitionRejected("prompt authority question provenance is stale")
        workflow = state.workflows.get(context.workflow_id)
        if (
            workflow is None
            or workflow.status is not WorkflowStatus.ACTIVE
            or workflow.owner_actor_id != event.actor_id
            or workflow.revision != context.workflow_revision
        ):
            raise TransitionRejected("prompt authority workflow provenance is stale")

    def _user_prompt_receipt(
        self,
        event: ForegroundTurnPrompted,
        generation: int,
        revision: int,
    ) -> ForegroundUserPromptReceipt | None:
        if event.prompt_digest is None:
            return None
        return ForegroundUserPromptReceipt(
            prompt_digest=event.prompt_digest,
            generation=generation,
            turn_revision=revision,
            vendor_turn_id=event.vendor_turn_id,
            authority_context=event.authority_context,
        )

    def _observe_foreground_turn_tool(
        self,
        state: ProcessState,
        event: ForegroundTurnToolObserved,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        current = state.foreground_turns.get(event.actor_id)
        if current is None or current.status is not ForegroundTurnStatus.READY_TO_STOP:
            return state
        next_turn = ForegroundTurnRecord(
            current.owner_actor_id,
            current.generation,
            current.revision + 1,
            ForegroundTurnStatus.ACTIVE,
            None,
            current.vendor_turn_id,
            current.user_prompt_receipt,
        )
        return self._with_foreground_turn(state, event.actor_id, next_turn)

    def _prepare_material_action(
        self,
        state: ProcessState,
        event: MaterialActionPrepared,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "material-action owner")
        turn = state.foreground_turns.get(event.actor_id)
        if (
            turn is None
            or turn.status is not ForegroundTurnStatus.ACTIVE
            or turn.generation != event.batch.turn_generation
            or turn.revision != event.batch.turn_revision
        ):
            raise TransitionRejected("material action requires the exact active foreground turn")
        current = state.material_actions.get(event.actor_id)
        if current is not None and current.batch_id == event.batch.batch_id:
            if current.same_intent(event.batch):
                return state
            raise TransitionRejected("material-action batch identity has a different intent")
        if current is None:
            if event.batch.sequence != 1:
                raise TransitionRejected("first material-action batch sequence must be one")
        else:
            if current.status is MaterialActionStatus.OPEN:
                raise TransitionRejected("actor already has an open material-action batch")
            if event.batch.sequence != current.sequence + 1:
                raise TransitionRejected("material-action batch sequence must be monotonic")
        self._validate_material_action_binding(state, event.actor_id, event.batch.adaptive_binding)
        return self._with_material_action(state, event.actor_id, event.batch)

    def _start_material_action_tool(
        self,
        state: ProcessState,
        event: MaterialActionToolStarted,
    ) -> ProcessState:
        current = self._material_action_batch(state, event.actor_id, event.batch_id)
        self._validate_material_action_binding(
            state,
            event.actor_id,
            current.adaptive_binding,
        )
        try:
            candidate = current.start_tool(
                invocation_id=event.invocation.invocation_id,
                tool_name=event.invocation.tool_name,
                request_digest=event.invocation.request_digest,
                targets=event.invocation.targets,
            )
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        if candidate is current:
            return state
        self._require_material_action_revision(current, event.expected_batch_revision)
        return self._with_material_action(state, event.actor_id, candidate)

    def _observe_material_action_tool(
        self,
        state: ProcessState,
        event: MaterialActionToolObserved,
    ) -> ProcessState:
        current = self._material_action_batch(state, event.actor_id, event.batch_id)
        self._validate_material_action_binding(
            state,
            event.actor_id,
            current.adaptive_binding,
        )
        try:
            candidate = current.observe_tool(event.invocation_id, event.receipt)
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        if candidate is current:
            return state
        self._require_material_action_revision(current, event.expected_batch_revision)
        return self._with_material_action(state, event.actor_id, candidate)

    def _resolve_material_action(
        self,
        state: ProcessState,
        event: MaterialActionResolved,
    ) -> ProcessState:
        current = self._material_action_batch(state, event.actor_id, event.batch_id)
        # Aborting or blocking obsolete intent records no successful effect.
        # Keep its original provenance; only completion needs current authority.
        # The domain resolver still rejects every unobserved in-flight call.
        if event.resolution is MaterialActionResolution.COMPLETED:
            self._validate_material_action_binding(
                state,
                event.actor_id,
                current.adaptive_binding,
            )
        try:
            candidate = current.resolve(event.resolution)
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        if candidate is current:
            return state
        self._require_material_action_revision(current, event.expected_batch_revision)
        return self._with_material_action(state, event.actor_id, candidate)

    def _abandon_material_action_tool(
        self,
        state: ProcessState,
        event: MaterialActionAbandoned,
    ) -> ProcessState:
        """Unobserved invocation을 raw-free UNKNOWN receipt와 BLOCKED resolution으로 닫습니다."""
        current = self._material_action_batch(state, event.actor_id, event.batch_id)
        turn = state.foreground_turns.get(event.actor_id)
        if turn is None or turn.generation != event.expected_turn_generation:
            raise TransitionRejected("material-action abandonment foreground turn is stale")
        self._validate_material_action_binding(
            state,
            event.actor_id,
            current.adaptive_binding,
        )
        invocation = next(
            (item for item in current.invocations if item.invocation_id == event.invocation_id),
            None,
        )
        if invocation is None:
            raise TransitionRejected("material-action abandonment requires exact in-flight tool")
        identity = "\x1f".join((
            str(event.session_id),
            str(event.actor_id),
            event.batch_id,
            event.invocation_id,
            str(event.expected_turn_generation),
        ))
        receipt = ToolReceipt(
            receipt_id=(
                f"runtime-abandoned:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
            ),
            request_digest=invocation.request_digest,
            outcome=ToolReceiptOutcome.UNKNOWN,
            output_digest=hashlib.sha256(b"runtime-abandoned-without-posttool").hexdigest(),
            observations=(),
        )
        if (
            invocation is not None
            and invocation.receipt == receipt
            and current.status is MaterialActionStatus.RESOLVED
            and current.resolution is MaterialActionResolution.BLOCKED
        ):
            return state
        if current.in_flight is not invocation:
            raise TransitionRejected("material-action abandonment requires exact in-flight tool")
        self._require_material_action_revision(current, event.expected_batch_revision)
        try:
            candidate = current.observe_tool(event.invocation_id, receipt).resolve(
                MaterialActionResolution.BLOCKED
            )
        except ValueError as error:
            raise TransitionRejected(str(error)) from error
        return self._with_material_action(state, event.actor_id, candidate)

    def _validate_material_action_binding(
        self,
        state: ProcessState,
        actor_id: ActorId,
        binding: AdaptiveActionBinding | None,
    ) -> None:
        if binding is None:
            return
        workflow = state.workflows.get(WorkflowId(binding.workflow_id))
        if (
            workflow is None
            or workflow.owner_actor_id != actor_id
            or workflow.status is not WorkflowStatus.ACTIVE
            or workflow.revision != binding.workflow_revision
        ):
            raise TransitionRejected("material-action adaptive workflow provenance is stale")
        skill_state = self._skill_state_namespaces(workflow.payload)
        raw_adaptive = skill_state.get("adaptive_control")
        if not isinstance(raw_adaptive, Mapping):
            raise TransitionRejected("material action requires adaptive goal authority")
        try:
            adaptive = AdaptiveControlState.from_payload(raw_adaptive)
        except InvalidAdaptiveControlState as error:
            raise TransitionRejected("material action adaptive goal is invalid") from error
        if adaptive.contract.fingerprint != binding.goal_fingerprint:
            raise TransitionRejected("material-action adaptive goal provenance is stale")

    def _material_action_batch(
        self,
        state: ProcessState,
        actor_id: ActorId,
        batch_id: str,
    ) -> MaterialActionBatch:
        self._require_available_actor(state, actor_id, "material-action owner")
        current = state.material_actions.get(actor_id)
        if current is None or current.batch_id != batch_id:
            raise TransitionRejected(f"material-action batch is missing: {batch_id}")
        return current

    def _require_material_action_revision(
        self,
        batch: MaterialActionBatch,
        expected_revision: int,
    ) -> None:
        if batch.revision != expected_revision:
            raise TransitionRejected(
                f"expected material-action batch revision {expected_revision}, got {batch.revision}"
            )

    def _with_material_action(
        self,
        state: ProcessState,
        actor_id: ActorId,
        batch: MaterialActionBatch,
    ) -> ProcessState:
        batches = dict(state.material_actions)
        batches[actor_id] = batch
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            batches,
        )

    def _yield_foreground_turn(
        self,
        state: ProcessState,
        event: ForegroundTurnYielded,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        current = state.foreground_turns.get(event.actor_id)
        if current is None:
            raise TransitionRejected("foreground turn is missing")
        if (
            current.status is ForegroundTurnStatus.READY_TO_STOP
            and current.revision == event.expected_turn_revision + 1
            and current.receipt is not None
            and current.receipt.to_payload() == event.receipt.to_payload()
        ):
            return state
        self._require_turn_revision(current, event.expected_turn_revision)
        if current.status is not ForegroundTurnStatus.ACTIVE:
            raise TransitionRejected("foreground turn yield requires active status")
        next_turn = ForegroundTurnRecord(
            current.owner_actor_id,
            current.generation,
            current.revision + 1,
            ForegroundTurnStatus.READY_TO_STOP,
            event.receipt,
            current.vendor_turn_id,
            current.user_prompt_receipt,
        )
        return self._with_foreground_turn(state, event.actor_id, next_turn)

    def _invalidate_foreground_turn(
        self,
        state: ProcessState,
        event: ForegroundTurnInvalidated,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        current = state.foreground_turns.get(event.actor_id)
        if current is None:
            raise TransitionRejected("foreground turn is missing")
        if current.status is ForegroundTurnStatus.ACTIVE:
            return state
        self._require_turn_revision(current, event.expected_turn_revision)
        if current.status is not ForegroundTurnStatus.READY_TO_STOP:
            raise TransitionRejected("closed foreground turn cannot be invalidated")
        next_turn = ForegroundTurnRecord(
            current.owner_actor_id,
            current.generation,
            current.revision + 1,
            ForegroundTurnStatus.ACTIVE,
            None,
            current.vendor_turn_id,
            current.user_prompt_receipt,
        )
        return self._with_foreground_turn(state, event.actor_id, next_turn)

    def _close_foreground_turn(
        self,
        state: ProcessState,
        event: ForegroundTurnClosed,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        candidate = state
        for projection in event.monitor_transitions:
            workflow = candidate.workflows.get(projection.workflow_id)
            if workflow is None:
                raise TransitionRejected(f"workflow is missing: {projection.workflow_id}")
            payload = dict(workflow.payload)
            payload["skill_state"] = dict(projection.skill_state)
            candidate = self._advance_workflow(
                candidate,
                WorkflowAdvanced(
                    session_id=event.session_id,
                    workflow_id=projection.workflow_id,
                    actor_id=event.actor_id,
                    expected_workflow_revision=projection.expected_workflow_revision,
                    payload=payload,
                    idempotency_key=(
                        f"{event.idempotency_key}:monitor-workflow:"
                        f"{projection.workflow_id}:{projection.expected_workflow_revision}"
                    ),
                ),
            )
        current = candidate.foreground_turns.get(event.actor_id)
        if current is None:
            raise TransitionRejected("foreground turn is missing")
        if (
            current.status is ForegroundTurnStatus.CLOSED
            and current.revision == event.expected_turn_revision + 1
        ):
            return state
        self._require_turn_revision(current, event.expected_turn_revision)
        if current.status not in {
            ForegroundTurnStatus.ACTIVE,
            ForegroundTurnStatus.READY_TO_STOP,
        }:
            raise TransitionRejected("foreground turn close requires an open status")
        next_turn = ForegroundTurnRecord(
            current.owner_actor_id,
            current.generation,
            current.revision + 1,
            ForegroundTurnStatus.CLOSED,
            current.receipt,
            current.vendor_turn_id,
            current.user_prompt_receipt,
        )
        return self._with_foreground_turn(candidate, event.actor_id, next_turn)

    def _replace_foreground_turn(
        self,
        state: ProcessState,
        event: ForegroundTurnReplaced,
    ) -> ProcessState:
        """Host successor evidence로 active turn만 incomplete/closed 처리합니다."""
        self._require_available_actor(state, event.actor_id, "foreground turn owner")
        current = state.foreground_turns.get(event.actor_id)
        if current is None:
            raise TransitionRejected("foreground turn is missing")
        reason = f"native foreground replaced:{event.replacement_reference}"
        if (
            current.status is ForegroundTurnStatus.CLOSED
            and current.revision == event.expected_turn_revision + 1
            and current.receipt is not None
            and current.receipt.outcome is ForegroundTurnOutcome.INCOMPLETE
            and current.receipt.reason == reason
        ):
            return state
        self._require_turn_revision(current, event.expected_turn_revision)
        if current.status not in {ForegroundTurnStatus.ACTIVE, ForegroundTurnStatus.READY_TO_STOP}:
            raise TransitionRejected("foreground replacement requires an open native turn")
        return self._with_foreground_turn(
            state,
            event.actor_id,
            ForegroundTurnRecord(
                current.owner_actor_id,
                current.generation,
                current.revision + 1,
                ForegroundTurnStatus.CLOSED,
                ForegroundTurnReceipt(
                    ForegroundTurnOutcome.INCOMPLETE,
                    reason=reason,
                ),
                current.vendor_turn_id,
                current.user_prompt_receipt,
                replacement_question=(current.receipt
                    if current.receipt is not None
                    and current.receipt.outcome is ForegroundTurnOutcome.AWAITING_INPUT else None),
            ),
        )

    def _require_turn_revision(
        self,
        turn: ForegroundTurnRecord,
        expected_revision: int,
    ) -> None:
        if turn.revision != expected_revision:
            raise TransitionRejected(
                f"expected foreground turn revision {expected_revision}, got {turn.revision}"
            )

    def _with_foreground_turn(
        self,
        state: ProcessState,
        actor_id: ActorId,
        turn: ForegroundTurnRecord,
    ) -> ProcessState:
        turns = dict(state.foreground_turns)
        turns[actor_id] = turn
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            turns,
            state.material_actions,
        )

    def _assign_delegation(
        self,
        state: ProcessState,
        event: DelegationAssigned,
    ) -> ProcessState:
        existing = state.delegations.get(event.delegation_id)
        if existing is not None:
            if (
                existing.owner_actor_id == event.owner_actor_id
                and existing.target_actor_id == event.target_actor_id
                and existing.assignment == event.assignment
                and existing.topology_policy is event.topology_policy
            ):
                return state
            raise TransitionRejected(f"delegation identity already exists: {event.delegation_id}")
        for actor_id in (event.owner_actor_id, event.target_actor_id):
            actor = state.actors.get(actor_id)
            if actor is None or actor.status not in {ActorStatus.ACTIVE, ActorStatus.IDLE}:
                raise TransitionRejected(f"delegation actor is unavailable: {actor_id}")
        target = state.actors[event.target_actor_id]
        if event.topology_policy is DelegationTopologyPolicy.DIRECT_CHILD and (
            target.kind is not ActorKind.SUBAGENT or target.parent_actor_id != event.owner_actor_id
        ):
            raise TransitionRejected(
                "direct-child delegation target must be the owner's direct child"
            )
        if (
            event.topology_policy is DelegationTopologyPolicy.DIRECT_CHILD
            and target.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
        ):
            raise TransitionRejected(
                "direct-child delegation target requires host-attested immediate-parent lineage"
            )
        delegations = dict(state.delegations)
        delegations[event.delegation_id] = DelegationRecord(
            event.delegation_id,
            event.owner_actor_id,
            event.target_actor_id,
            event.assignment,
            DelegationStatus.PENDING,
            topology_policy=event.topology_policy,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _report_delegation(
        self,
        state: ProcessState,
        event: DelegationReported,
    ) -> ProcessState:
        delegation = state.delegations.get(event.delegation_id)
        if delegation is None:
            raise TransitionRejected(f"delegation is missing: {event.delegation_id}")
        if event.reporter_actor_id != delegation.target_actor_id:
            raise TransitionRejected("only the delegation target can report its result")
        self._require_available_actor(state, event.reporter_actor_id, "delegation reporter")
        if delegation.status is not DelegationStatus.PENDING:
            if (
                delegation.target_actor_id == event.reporter_actor_id
                and delegation._result is not None
                and delegation._result.to_payload() == event.result.to_payload()
            ):
                return state
            raise TransitionRejected(
                f"delegation result is already reported: {event.delegation_id}"
            )
        delegations = dict(state.delegations)
        delegations[event.delegation_id] = DelegationRecord(
            delegation.id,
            delegation.owner_actor_id,
            delegation.target_actor_id,
            delegation.assignment,
            DelegationStatus.REPORTED,
            event.result,
            delegation.topology_policy,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _cancel_delegation(
        self,
        state: ProcessState,
        event: DelegationCancelled,
    ) -> ProcessState:
        delegation = state.delegations.get(event.delegation_id)
        if delegation is None:
            raise TransitionRejected(f"delegation is missing: {event.delegation_id}")
        if event.owner_actor_id != delegation.owner_actor_id:
            raise TransitionRejected("only the delegation owner can cancel it")
        self._require_available_actor(state, event.owner_actor_id, "delegation owner")
        cancellation_result = DelegationResult(
            verdict="cancelled",
            summary=event.reason,
            outcome_ref=f"urn:neurath:delegation-cancelled:{event.delegation_id}",
            blocking_findings=(),
        )
        if delegation.status is DelegationStatus.CANCELLED:
            if delegation.result.to_payload() == cancellation_result.to_payload():
                return state
            raise TransitionRejected(
                f"delegation cancellation reason changed: {event.delegation_id}"
            )
        if delegation.status is not DelegationStatus.PENDING:
            raise TransitionRejected(f"delegation is not pending: {event.delegation_id}")
        delegations = dict(state.delegations)
        delegations[event.delegation_id] = DelegationRecord(
            delegation.id,
            delegation.owner_actor_id,
            delegation.target_actor_id,
            delegation.assignment,
            DelegationStatus.CANCELLED,
            cancellation_result,
            delegation.topology_policy,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _consume_delegation(
        self,
        state: ProcessState,
        event: DelegationConsumed,
    ) -> ProcessState:
        delegation = state.delegations.get(event.delegation_id)
        if delegation is None:
            raise TransitionRejected(f"delegation is missing: {event.delegation_id}")
        if event.consumer_actor_id != delegation.owner_actor_id:
            raise TransitionRejected("only the delegation owner can consume its result")
        self._require_available_actor(state, event.consumer_actor_id, "delegation consumer")
        if delegation.status is DelegationStatus.CONSUMED:
            return state
        if delegation.status is not DelegationStatus.REPORTED:
            raise TransitionRejected(f"delegation result is not reported: {event.delegation_id}")
        delegations = dict(state.delegations)
        delegations[event.delegation_id] = DelegationRecord(
            delegation.id,
            delegation.owner_actor_id,
            delegation.target_actor_id,
            delegation.assignment,
            DelegationStatus.CONSUMED,
            delegation.result,
            delegation.topology_policy,
        )
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _record_incident(
        self,
        state: ProcessState,
        event: HarnessIncidentRecorded,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "incident reporter")
        candidate = HarnessIncidentRecord(
            event.occurrence_id,
            event.rule_id,
            event.actor_id,
            HarnessIncidentStatus.OPEN,
            event.symptom,
            event.recorded_at,
        )
        existing = state.incidents.get(event.occurrence_id)
        if existing is not None:
            if existing.same_snapshot(candidate):
                return state
            raise TransitionRejected(f"incident identity already exists: {event.occurrence_id}")
        if any(
            incident.rule_id == event.rule_id and incident.status is HarnessIncidentStatus.OPEN
            for incident in state.incidents.values()
        ):
            raise TransitionRejected(f"open incident already exists: {event.rule_id}")
        incidents = dict(state.incidents)
        incidents[event.occurrence_id] = candidate
        return self._with_incidents(state, incidents)

    def _resolve_incident(
        self,
        state: ProcessState,
        event: HarnessIncidentResolved,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "incident resolver")
        incident = self._require_incident(state, event.occurrence_id)
        if incident.status is HarnessIncidentStatus.RESOLVED:
            if (
                incident.root_cause == event.root_cause.strip()
                and incident.harness_fix == tuple(path.strip() for path in event.harness_fix)
                and incident.regression_evidence == event.regression_evidence
                and incident.resolved_at == event.resolved_at.strip()
            ):
                return state
            raise TransitionRejected(f"incident is not open: {event.occurrence_id}")
        resolved = incident.resolve(
            event.root_cause,
            event.harness_fix,
            event.regression_evidence,
            event.resolved_at,
        )
        incidents = dict(state.incidents)
        incidents[event.occurrence_id] = resolved
        return self._with_incidents(state, incidents)

    def _escalate_incident(
        self,
        state: ProcessState,
        event: HarnessIncidentEscalated,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "incident escalator")
        incident = self._require_incident(state, event.occurrence_id)
        if incident.status is HarnessIncidentStatus.ESCALATED:
            if (
                incident.escalation_summary == event.summary.strip()
                and incident.reproduction_commands
                == tuple(command.strip() for command in event.reproduction_commands)
                and incident.escalated_at == event.escalated_at.strip()
            ):
                return state
            raise TransitionRejected(f"incident is not open: {event.occurrence_id}")
        escalated = incident.escalate(
            event.summary,
            event.reproduction_commands,
            event.escalated_at,
        )
        incidents = dict(state.incidents)
        incidents[event.occurrence_id] = escalated
        return self._with_incidents(state, incidents)

    def _refresh_incidents(
        self,
        state: ProcessState,
        event: HarnessIncidentsRefreshed,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "incident evidence refresher")
        incidents = dict(state.incidents)
        replacements: dict[IncidentId, HarnessIncidentRecord] = {}
        for expected in event.expected_incidents:
            current = self._require_incident(state, expected.id)
            candidate = expected.refresh(event.regression_evidence, event.refreshed_at)
            if current.same_snapshot(candidate):
                replacements[expected.id] = current
                continue
            if not current.same_snapshot(expected):
                raise TransitionRejected("resolved incident evidence changed during refresh")
            replacements[expected.id] = candidate
        incidents.update(replacements)
        if all(
            state.incidents[incident_id] is replacement
            for incident_id, replacement in replacements.items()
        ):
            return state
        return self._with_incidents(state, incidents)

    def _supersede_incident_evidence(
        self,
        state: ProcessState,
        event: HarnessIncidentEvidenceSuperseded,
    ) -> ProcessState:
        self._require_available_actor(state, event.actor_id, "incident evidence superseder")
        current = self._require_incident(state, event.expected_incident.id)
        candidate = event.expected_incident.supersede(
            event.harness_fix,
            event.regression_evidence,
            event.superseded_at,
        )
        if current.same_snapshot(candidate):
            return state
        if not current.same_snapshot(event.expected_incident):
            raise TransitionRejected("resolved incident evidence changed during supersede")
        incidents = dict(state.incidents)
        incidents[current.id] = candidate
        return self._with_incidents(state, incidents)

    def _require_incident(
        self,
        state: ProcessState,
        occurrence_id: IncidentId,
    ) -> HarnessIncidentRecord:
        incident = state.incidents.get(occurrence_id)
        if incident is None:
            raise TransitionRejected(f"incident is missing: {occurrence_id}")
        return incident

    def _with_incidents(
        self,
        state: ProcessState,
        incidents: Mapping[IncidentId, HarnessIncidentRecord],
    ) -> ProcessState:
        return ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            incidents,
            state.outbox,
            state.foreground_turns,
            state.material_actions,
        )

    def _authorize_workflow_actor(
        self,
        state: ProcessState,
        workflow: WorkflowRecord,
        actor_id: ActorId,
    ) -> None:
        if actor_id != workflow.owner_actor_id:
            raise TransitionRejected("only the workflow owner can mutate it")
        self._require_available_actor(state, actor_id, "workflow owner")

    def _require_available_actor(
        self,
        state: ProcessState,
        actor_id: ActorId,
        role: str,
    ) -> ActorRecord:
        actor = state.actors.get(actor_id)
        if actor is None or actor.status not in {ActorStatus.ACTIVE, ActorStatus.IDLE}:
            raise TransitionRejected(f"{role} is unavailable: {actor_id}")
        return actor


class SessionStateStore:
    """Revision-based optimistic CAS와 짧은 commit mutex로 snapshot을 저장합니다."""

    def __init__(
        self,
        process_state_path: Path,
        commit_observer: Callable[[CommitStage], None] | None = None,
        max_retries: int = 64,
    ) -> None:
        """Canonical snapshot path에 optimistic transaction boundary를 구성합니다.

        Args:
            process_state_path: Exact session의 canonical process-state JSON path입니다.
            commit_observer: Crash-safety 검증이 durable commit 경계를 관찰할 callback입니다.
            max_retries: Implicit transaction이 revision conflict 뒤 재시도할 상한입니다.

        Raises:
            InvalidRetryLimit: Retry 상한이 1보다 작으면 발생합니다.
        """
        if max_retries < 1:
            raise InvalidRetryLimit("max_retries must be positive")
        self._path = process_state_path
        self._lock_path = process_state_path.with_name(f"{process_state_path.name}.lock")
        from scripts.agent_harness.runtime_database import RuntimeDatabase

        # The old address remains a migration key, never a new JSON snapshot.
        path = process_state_path.absolute()
        if path.parents[1].name != "runs":
            raise InvalidSessionState("session address must belong to the runtime runs directory")
        if path.parents[2].name == ".agents":
            control_root = path.parents[3]
        elif path.parents[2].name == "local" and path.parents[3].name == ".neurath":
            control_root = path.parents[4]
        else:
            raise InvalidSessionState("session address has no common runtime root")
        self._database = RuntimeDatabase(control_root)
        self._record_key = path.parent.name
        self._codec = SessionStateCodec()
        self._reducer = SessionStateReducer()
        self._commit_observer = commit_observer
        self._max_retries = max_retries

    def read(self, expected_session_id: SessionId | None = None) -> ProcessState:
        """Atomic snapshot file을 lock-free로 읽고 typed state로 검증합니다.

        Args:
            expected_session_id: 다른 session의 snapshot을 수용하지 않도록 확인할 identity입니다.

        Returns:
            Schema와 cross-record invariant를 통과한 latest immutable snapshot입니다.

        Raises:
            SessionNotFound: Canonical snapshot file이 존재하지 않으면 발생합니다.
            InvalidSessionState: File이 유효한 JSON snapshot이 아니거나 identity가 다르면
                발생합니다.
        """
        state = self._read_snapshot(expected_session_id, missing_allowed=False)
        if state is None:
            raise SessionNotFound(f"session state is missing: {self._path}")
        return state

    def transact(
        self,
        event: KernelEvent,
        expected_revision: int | None = None,
    ) -> ProcessState:
        """Event를 optimistic CAS로 commit하며 implicit 호출은 충돌 시 재시도합니다.

        Args:
            event: Exact session snapshot에 적용할 typed state transition입니다.
            expected_revision: Caller가 읽은 원본을 강제할 explicit compare version입니다.

        Returns:
            Canonical file에 atomic replace된 snapshot 또는 idempotent 기존 snapshot입니다.

        Raises:
            RevisionConflict: Explicit expected revision이 latest snapshot과 다르면 발생합니다.
            OptimisticRetryExhausted: Implicit transaction이 retry 상한 안에 commit하지
                못하면 발생합니다.
            SessionNotFound: Session 시작 외 event의 snapshot이 존재하지 않으면 발생합니다.
            TransitionRejected: Event가 현재 session state의 invariant와 충돌하면 발생합니다.
            InvalidSessionState: Existing canonical snapshot을 검증할 수 없으면 발생합니다.
        """
        for _attempt in range(self._max_retries):
            snapshot = self._read_snapshot(event.session_id, missing_allowed=True)
            snapshot_revision = None if snapshot is None else snapshot.revision
            if expected_revision is not None and snapshot_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, got {snapshot_revision}"
                )
            candidate = self._reducer.reduce(snapshot, event)
            if candidate is snapshot:
                if snapshot_revision is None:
                    raise InvalidSessionState("no-op transition requires a canonical snapshot")
                try:
                    self._compare_revision_under_lock(event.session_id, snapshot_revision)
                except RevisionConflict:
                    if expected_revision is not None:
                        raise
                    continue
                return candidate
            try:
                return self._compare_and_commit(
                    event.session_id,
                    snapshot_revision,
                    candidate,
                    enforce_task_gate=not isinstance(event, ForegroundTurnReplaced),
                )
            except RevisionConflict:
                if expected_revision is not None:
                    raise
        raise OptimisticRetryExhausted(
            f"session {event.session_id} did not converge after {self._max_retries} retries"
        )

    def _compare_revision_under_lock(
        self,
        session_id: SessionId,
        expected_revision: int,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._database.transaction() as tx:
                    latest = self._decode_record(tx.get("session", self._record_key), session_id)
                    latest_revision = None if latest is None else latest.revision
                    if latest_revision != expected_revision:
                        raise RevisionConflict(
                            f"expected revision {expected_revision}, got {latest_revision}"
                        )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _compare_and_commit(
        self,
        session_id: SessionId,
        expected_revision: int | None,
        candidate: ProcessState,
        *,
        enforce_task_gate: bool = True,
    ) -> ProcessState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._database.transaction() as tx:
                    latest = self._decode_record(tx.get("session", self._record_key), session_id)
                    latest_revision = None if latest is None else latest.revision
                    if latest_revision != expected_revision:
                        raise RevisionConflict(
                            f"expected revision {expected_revision}, got {latest_revision}"
                        )
                    next_revision = 0 if latest_revision is None else latest_revision + 1
                    committed = candidate.with_revision(next_revision)
                    root_turn = committed.foreground_turns.get(committed.session.root_actor_id)
                    old_turn = (None if latest is None else
                                latest.foreground_turns.get(latest.session.root_actor_id))
                    if (
                        enforce_task_gate
                        and root_turn is not None
                        and root_turn.status is ForegroundTurnStatus.CLOSED
                        and (old_turn is None or old_turn.status is not ForegroundTurnStatus.CLOSED)
                    ):
                        from scripts.agent_harness.task_service import require_settled_tasks
                        try:
                            require_settled_tasks(tx, committed)
                        except ValueError as error:
                            raise TransitionRejected(f"task Stop gate: {error}") from error
                    tx.put("session", self._record_key, self._codec.encode(committed),
                           expected_revision=latest_revision)
                    for actor_id, turn in committed.foreground_turns.items():
                        prompt = turn.user_prompt_receipt
                        if prompt is None or actor_id != committed.session.root_actor_id:
                            continue
                        payload = json.dumps({"actor_id": str(actor_id), **prompt.to_payload()},
                            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                        namespace = f"prompt:{session_id}"
                        old_prompt = tx.get(namespace, prompt.authority_reference)
                        if old_prompt is None:
                            tx.put(namespace, prompt.authority_reference, payload, expected_revision=None)
                        elif old_prompt.payload != payload:
                            raise InvalidSessionState("native prompt reference changed its content")
                    if self._commit_observer is not None:
                        self._commit_observer(CommitStage.BEFORE_REPLACE)
                return committed
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_snapshot(
        self,
        expected_session_id: SessionId | None,
        missing_allowed: bool,
    ) -> ProcessState | None:
        from scripts.agent_harness.runtime_database import CorruptRecord, LegacyStateChanged
        import sqlite3
        try:
            return self._load_snapshot(expected_session_id, missing_allowed)
        except (CorruptRecord, LegacyStateChanged, json.JSONDecodeError,
                UnicodeError, OSError, sqlite3.Error) as error:
            raise InvalidSessionState("cannot read canonical session state") from error

    def _load_snapshot(self, expected_session_id, missing_allowed):
        with self._database.transaction() as tx:
            record = tx.get("session", self._record_key)
            deleted = tx.was_deleted("session", self._record_key)
        if record is None and not deleted and self._path.is_file():
            def validate(content):
                return self._codec.decode(json.loads(content), expected_session_id).revision
            record = self._database.import_legacy("session", self._record_key, self._path, validate)
        state = self._decode_record(record, expected_session_id)
        if state is None and not missing_allowed:
            raise SessionNotFound(f"session state is missing: {self._record_key}")
        return state

    def _decode_record(self, record, expected_session_id):
        if record is None:
            return None
        try:
            state = self._codec.decode(json.loads(record.payload), expected_session_id)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise InvalidSessionState("cannot decode persisted session") from error
        if state.revision != record.revision:
            raise InvalidSessionState("session and database revisions differ")
        return state

    def exists(self) -> bool:
        """Check canonical state, including a validated pre-cutover import."""
        return self._read_snapshot(None, missing_allowed=True) is not None

    def read_transaction(self, transaction, expected_session_id: SessionId) -> ProcessState:
        """Read authority inside a caller's shared task or Stop transaction.

        This performs no nested connection, migration or domain transition.
        The caller must use this project's database and the exact session key.
        """
        databases = transaction.connection.execute("PRAGMA database_list").fetchall()
        main = next((row[2] for row in databases if row[1] == "main"), None)
        if main is None or Path(main).resolve() != self._database.path.resolve():
            raise InvalidSessionState("session transaction belongs to another project")
        if self._record_key != str(expected_session_id):
            raise InvalidSessionState("session transaction identity mismatch")
        state = self._decode_record(transaction.get("session", self._record_key), expected_session_id)
        if state is None:
            raise SessionNotFound(f"session state is missing: {expected_session_id}")
        return state

    def modified_at(self) -> float:
        self.read()
        with self._database.transaction() as tx:
            return tx.connection.execute(
                "SELECT updated FROM runtime_records WHERE namespace='session' AND key=?",
                (self._record_key,),
            ).fetchone()[0]


class SessionKernel:
    """Skill과 adapter가 canonical path를 몰라도 state event를 적용하게 합니다."""

    _MAX_ADMISSION_RETRIES = 64

    def __init__(self, locator: SessionLocator) -> None:
        """Session identity를 exact persistence path로 연결하는 facade를 구성합니다.

        Args:
            locator: Repository control root에 고정된 canonical session path resolver입니다.
        """
        self._locator = locator

    def apply(
        self,
        event: KernelEvent,
        expected_revision: int | None = None,
    ) -> ProcessState:
        """Typed event를 exact session store에 optimistic transaction으로 적용합니다.

        Args:
            event: Canonical snapshot에 적용할 session-scoped state transition입니다.
            expected_revision: Stale caller의 overwrite를 막을 explicit compare version입니다.

        Returns:
            Event가 반영되어 canonical path에 commit된 immutable snapshot입니다.

        Raises:
            RevisionConflict: Explicit compare version이 latest revision과 다르면 발생합니다.
            OptimisticRetryExhausted: Implicit transaction이 retry 상한 안에 수렴하지
                못하면 발생합니다.
            TransitionRejected: Event가 current session invariant상 허용되지 않으면
                발생합니다.
            InvalidSessionState: Existing canonical snapshot을 검증할 수 없으면 발생합니다.
        """
        paths = self._locator.locate(event.session_id)
        store = SessionStateStore(paths.process_state)
        state = (
            self._transact_with_adaptive_admission(store, event, expected_revision)
            if self._requires_adaptive_admission(event)
            else store.transact(event, expected_revision)
        )
        if isinstance(event, SessionStarted):
            self._initialize_enclave(paths, event.session_id)
        return state

    def _requires_adaptive_admission(self, event: KernelEvent) -> bool:
        """External adaptive authority를 확인해야 하는 final aggregate event인지 반환합니다."""
        return isinstance(event, ReservedSkillStateAdvanced | WorkflowFinalized)

    def _transact_with_adaptive_admission(
        self,
        store: SessionStateStore,
        event: KernelEvent,
        expected_revision: int | None,
    ) -> ProcessState:
        """Authority readback과 process revision CAS를 하나의 bounded retry로 결합합니다."""
        from scripts.agent_harness.adaptive_control_authority import (  # noqa: PLC0415
            AdaptiveControlAuthorityError,
        )

        for _attempt in range(self._MAX_ADMISSION_RETRIES):
            snapshot = store.read(event.session_id)
            if expected_revision is not None and snapshot.revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, got {snapshot.revision}"
                )
            candidate = SessionStateReducer().reduce(snapshot, event)
            if candidate is snapshot:
                return store.transact(event, expected_revision=snapshot.revision)
            try:
                self._validate_adaptive_authority(snapshot, event)
            except AdaptiveControlAuthorityError as error:
                latest = store.read(event.session_id)
                if expected_revision is None and latest.revision != snapshot.revision:
                    continue
                raise TransitionRejected("adaptive control authority is invalid") from error
            try:
                return store.transact(event, expected_revision=snapshot.revision)
            except RevisionConflict:
                if expected_revision is not None:
                    raise
        raise OptimisticRetryExhausted(
            f"session {event.session_id} adaptive admission did not converge after "
            f"{self._MAX_ADMISSION_RETRIES} retries"
        )

    def _validate_adaptive_authority(
        self,
        state: ProcessState,
        event: KernelEvent,
    ) -> None:
        """Current process snapshot의 candidate 또는 completion authority를 재대조합니다."""
        from scripts.agent_harness.adaptive_control_authority import (  # noqa: PLC0415
            AdaptiveControlAuthorityVerifier,
        )
        from scripts.agent_harness.state_handle import (  # noqa: PLC0415
            RuntimeIdentityBinding,
            StateHandle,
        )

        if not isinstance(event, ReservedSkillStateAdvanced | WorkflowFinalized):
            raise TransitionRejected("adaptive admission requires a workflow event")
        workflow = state.workflows.get(event.workflow_id)
        if workflow is None:
            raise TransitionRejected(f"workflow is missing: {event.workflow_id}")
        handle = StateHandle(
            self,
            RuntimeIdentityBinding(
                runtime=state.session.runtime,
                session_id=state.session.id,
                actor_id=event.actor_id,
                root_actor_id=state.session.root_actor_id,
            ),
        )
        verifier = AdaptiveControlAuthorityVerifier(handle, workflow.id)
        if isinstance(event, ReservedSkillStateAdvanced):
            current = SessionStateReducer()._skill_state_namespaces(workflow.payload)
            candidate = SessionStateReducer()._skill_state_namespaces(event.payload)
            raw_current = current.get("adaptive_control")
            raw_candidate = candidate.get("adaptive_control")
            if raw_current == raw_candidate:
                return
            if not isinstance(raw_candidate, Mapping):
                raise TransitionRejected("adaptive_control candidate must be a canonical object")
            candidate_state = AdaptiveControlState.from_payload(raw_candidate)
            if raw_current is not None and not isinstance(raw_current, Mapping):
                raise TransitionRejected("persisted adaptive_control state is invalid")
            current_state = (
                None if raw_current is None else AdaptiveControlState.from_payload(raw_current)
            )
            if current_state is None and (
                workflow.goal is None
                or candidate_state.contract.goal.strip() != workflow.goal.strip()
            ):
                raise TransitionRejected(
                    "initial adaptive contract goal must match the workflow goal"
                )
            verification = verifier.validate_candidate(
                candidate_state,
                workflow.revision,
            )
            if (
                verification.workflow_id != workflow.id
                or verification.workflow_revision != workflow.revision
                or verification.goal_fingerprint != candidate_state.contract.fingerprint
            ):
                raise TransitionRejected("adaptive candidate authority is stale")
            validate_efficiency_resource_admission(
                current_state,
                candidate_state,
                session_id=str(state.session.id),
                actor_id=str(event.actor_id),
                workflow_id=str(workflow.id),
                workflow_revision=workflow.revision,
                material_batch=state.material_actions.get(event.actor_id),
            )
            return
        skill_state = SessionStateReducer()._skill_state_namespaces(workflow.payload)
        raw_state = skill_state.get("adaptive_control")
        if event.terminal_status is WorkflowStatus.FAILED:
            phase = event.payload.get("phase_run")
            if (
                isinstance(phase, Mapping)
                and phase.get("terminal_state") == "blocked"
                and WorkflowTerminalPolicy().watchdog_expired(
                    workflow.kind,
                    workflow.payload,
                    time.time(),
                )
            ):
                return
            required = requires_adaptive_control_for_workflow(workflow.kind, workflow.payload)
            if raw_state is None and not required:
                return
            if not isinstance(raw_state, Mapping):
                raise TransitionRejected("adaptive failure requires current typed execution state")
            adaptive = AdaptiveControlState.from_payload(raw_state)
            if isinstance(phase, Mapping) and phase.get("terminal_state") == "blocked":
                receipt = AdaptiveControlSnapshot(
                    workflow.id, workflow.revision, adaptive
                ).receipt()
                selected = receipt.ambiguity.selected_gap_id
                if receipt.decision.action is not ControlAction.BLOCKED or not any(
                    gap.gap_id == selected and gap.is_blocked_for(adaptive.inventory)
                    for gap in adaptive.inventory.gaps
                ):
                    raise TransitionRejected(
                        "blocked workflow requires a current authoritative blocker"
                    )
            elif adaptive.execution_status.value != "failed":
                raise TransitionRejected("failed workflow requires a typed execution failure")
            verification = verifier.verify()
            if not verification.complete or verification.workflow_revision != workflow.revision:
                raise TransitionRejected("adaptive failure authority is unavailable or stale")
            return
        if raw_state is None:
            return
        if not isinstance(raw_state, Mapping):
            raise TransitionRejected("persisted adaptive_control state is invalid")
        verifier.verify_completion(workflow.revision)

    def inspect(self, session_id: SessionId) -> ProcessState:
        """Exact session snapshot만 읽고 다른 directory로 fallback하지 않습니다.

        Args:
            session_id: 조회할 root execution tree의 exact identity입니다.

        Returns:
            해당 identity의 validated latest immutable snapshot입니다.

        Raises:
            InvalidIdentity: Session identity가 canonical path에 안전하지 않으면 발생합니다.
            SessionNotFound: 해당 exact session snapshot이 존재하지 않으면 발생합니다.
            InvalidSessionState: Snapshot schema, identity, record invariant가 틀리면
                발생합니다.
        """
        paths = self._locator.locate(session_id)
        return SessionStateStore(paths.process_state).read(session_id)

    def _session_paths(self, session_id: SessionId) -> SessionPaths:
        """State-bound infrastructure adapter에 exact session paths를 제공합니다.

        Args:
            session_id: Canonical persistence directory를 선택할 validated identity입니다.

        Returns:
            다른 session fallback 없이 계산한 internal persistence paths입니다.
        """
        return self._locator.locate(session_id)

    def _initialize_enclave(self, paths: SessionPaths, session_id: SessionId) -> None:
        from scripts.agent_harness.enclave_store import EnclaveStore
        EnclaveStore(self._locator, max_bytes=4096).initialize(session_id)
