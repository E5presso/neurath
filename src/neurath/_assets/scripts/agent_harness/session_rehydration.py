"""Exact-session enclave rehydration과 explicit resource lifecycle을 제공합니다."""

import hashlib
import json
from enum import StrEnum
from pathlib import Path

from scripts.agent_harness.enclave_store import (
    EnclaveConflict,
    EnclaveSnapshot,
    EnclaveStateInvalid,
    EnclaveStore,
)
from scripts.agent_harness.material_action import MaterialActionBatch, MaterialActionStatus
from scripts.agent_harness.runtime_adapter import (
    LifecycleCause,
    RuntimeCapability,
    RuntimeEnvelope,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorStatus,
    ActorStopped,
    DelegationStatus,
    EffectAcknowledged,
    EffectId,
    EffectKind,
    EffectPrepared,
    InvalidSessionState,
    OutboxEffect,
    ProcessState,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
    SessionStarted,
    SessionStatus,
    TransitionRejected,
    WorkflowStatus,
    WorktreeId,
)
from scripts.agent_harness.worktree_registry import (
    WorktreeClaim,
    WorktreeLeaseConflict,
    WorktreeNotClaimed,
    WorktreeRegistry,
)


class SessionRehydrationError(RuntimeError):
    """Session lifecycle contract가 요청을 안전하게 완료할 수 없음을 나타냅니다."""


class LifecycleConflict(SessionRehydrationError):
    """Fork 또는 handoff의 expected lifecycle state가 current state와 다릅니다."""


class StaleFencingTokenError(SessionRehydrationError):
    """Current resource owner generation과 다른 writer를 거부합니다."""


class RehydrationStatus(StrEnum):
    """Runtime context injection의 결정 결과입니다."""

    READY = "ready"
    """Exact session context가 injection 가능한 상태입니다."""
    SKIPPED = "skipped"
    """현재 lifecycle event에는 rehydration이 필요하지 않습니다."""
    BLOCKED = "blocked"
    """Fail-closed diagnostic 때문에 context injection을 거부했습니다."""


class RehydrationDiagnostic(StrEnum):
    """Context를 주입하지 않은 machine-readable 원인입니다."""

    CAPABILITY_UNAVAILABLE = "capability-unavailable"
    """Runtime에 stable additional-context capability가 없습니다."""
    TERMINAL_SESSION = "terminal-session"
    """Exact session이 이미 terminal 상태입니다."""
    CORRUPT_STATE = "corrupt-state"
    """Exact session state 또는 enclave가 canonical schema를 위반합니다."""
    ORPHAN_SESSION = "orphan-session"
    """Session directory 일부만 존재하거나 canonical state가 없습니다."""
    RUNTIME_MISMATCH = "runtime-mismatch"
    """Runtime envelope와 persisted session runtime이 다릅니다."""


class ImmutableValue:
    """Lifecycle boundary value를 생성 이후 immutable하게 유지합니다."""

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        """생성 완료 후 모든 attribute mutation을 거부합니다.

        Args:
            name: Mutation을 시도한 attribute 이름입니다.
            value: Mutation을 시도한 새 값입니다.

        Raises:
            AttributeError: Immutable lifecycle value를 변경하면 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class RehydrationDecision(ImmutableValue):
    """Runtime hook이 그대로 소비할 수 있는 exact-session injection 결정입니다."""

    __slots__ = (
        "additional_context",
        "diagnostic",
        "hook_event_name",
        "optional_context_start_bytes",
        "session_id",
        "status",
    )

    def __init__(
        self,
        *,
        status: RehydrationStatus,
        session_id: SessionId,
        hook_event_name: str,
        additional_context: str | None,
        optional_context_start_bytes: int | None,
        diagnostic: RehydrationDiagnostic | None,
    ) -> None:
        """Exact session injection 결과를 immutable value로 구성합니다.

        Args:
            status: Injection 가능, skip 또는 blocked 결과입니다.
            session_id: Decision이 결속된 exact session입니다.
            hook_event_name: 결과를 소비할 vendor hook event 이름입니다.
            additional_context: Ready일 때 주입할 bounded context입니다.
            optional_context_start_bytes: Optional enclave section의 structural byte offset입니다.
            diagnostic: Blocked 또는 skipped 원인을 나타내는 typed code입니다.

        Raises:
            ValueError: Context와 structural byte offset이 서로 일치하지 않으면 발생합니다.
        """
        encoded_size = 0 if additional_context is None else len(additional_context.encode("utf-8"))
        if additional_context is None and optional_context_start_bytes is not None:
            raise ValueError("context boundary requires additional context")
        if optional_context_start_bytes is not None and not (
            0 <= optional_context_start_bytes <= encoded_size
        ):
            raise ValueError("context boundary must be within UTF-8 context bytes")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "hook_event_name", hook_event_name)
        object.__setattr__(self, "additional_context", additional_context)
        object.__setattr__(
            self,
            "optional_context_start_bytes",
            optional_context_start_bytes,
        )
        object.__setattr__(self, "diagnostic", diagnostic)

    status: RehydrationStatus
    """Context injection의 결정 상태입니다."""
    session_id: SessionId
    """다른 session fallback을 허용하지 않는 exact identity입니다."""
    hook_event_name: str
    """Runtime adapter가 보존한 vendor lifecycle event 이름입니다."""
    additional_context: str | None
    """Ready decision에서만 존재하는 bounded enclave context입니다."""
    optional_context_start_bytes: int | None
    """User text search 없이 optional enclave를 찾는 UTF-8 structural offset입니다."""
    diagnostic: RehydrationDiagnostic | None
    """Context를 주입하지 못한 typed 원인입니다."""


class ForkLineage(ImmutableValue):
    """Runtime이 증명한 source/target session fork identity입니다."""

    __slots__ = (
        "provenance_id",
        "runtime",
        "source_session_id",
        "target_resume_id",
        "target_session_id",
    )

    def __init__(
        self,
        *,
        runtime: SessionRuntime,
        source_session_id: SessionId,
        target_session_id: SessionId,
        provenance_id: str,
        target_resume_id: ResumeId | None = None,
    ) -> None:
        """Source와 독립 target을 vendor provenance와 결합합니다.

        Args:
            runtime: Fork를 증명한 coding-agent runtime입니다.
            source_session_id: Snapshot을 제공할 active session입니다.
            target_session_id: 새 independent directory를 가질 session입니다.
            provenance_id: Vendor fork event의 stable evidence identity입니다.
            target_resume_id: Runtime이 제공한 target exact-resume handle입니다.

        Raises:
            LifecycleConflict: Source/target이 같거나 provenance가 비면 발생합니다.
        """
        if source_session_id == target_session_id:
            raise LifecycleConflict("fork target session must differ from source session")
        if not provenance_id.strip():
            raise LifecycleConflict("fork provenance_id must not be empty")
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "source_session_id", source_session_id)
        object.__setattr__(self, "target_session_id", target_session_id)
        object.__setattr__(
            self,
            "target_resume_id",
            target_resume_id or ResumeId(str(target_session_id)),
        )
        object.__setattr__(self, "provenance_id", provenance_id.strip())

    runtime: SessionRuntime
    """Fork lifecycle을 보고한 coding-agent runtime입니다."""
    source_session_id: SessionId
    """한 번 읽을 source enclave의 exact session identity입니다."""
    target_session_id: SessionId
    """독립 state/enclave directory를 가질 새 session identity입니다."""
    target_resume_id: ResumeId
    """Target session을 exact resume하기 위한 opaque handle입니다."""
    provenance_id: str
    """Fork lineage를 증명하는 vendor event identity입니다."""


class ForkReceipt(ImmutableValue):
    """독립 target session에 복사된 한 enclave snapshot의 receipt입니다."""

    __slots__ = (
        "provenance_id",
        "source_enclave_digest",
        "source_session_id",
        "target_session_id",
    )

    def __init__(
        self,
        *,
        source_session_id: SessionId,
        target_session_id: SessionId,
        source_enclave_digest: str,
        provenance_id: str,
    ) -> None:
        """완료된 fork의 source snapshot과 target identity를 보존합니다.

        Args:
            source_session_id: Snapshot을 제공한 session입니다.
            target_session_id: 독립 snapshot을 받은 새 session입니다.
            source_enclave_digest: 한 번 읽은 source enclave content digest입니다.
            provenance_id: Fork를 증명한 vendor event identity입니다.
        """
        object.__setattr__(self, "source_session_id", source_session_id)
        object.__setattr__(self, "target_session_id", target_session_id)
        object.__setattr__(self, "source_enclave_digest", source_enclave_digest)
        object.__setattr__(self, "provenance_id", provenance_id)

    source_session_id: SessionId
    """Snapshot source의 exact session identity입니다."""
    target_session_id: SessionId
    """독립 enclave를 소유하는 target session identity입니다."""
    source_enclave_digest: str
    """복사 시점 source enclave의 canonical content digest입니다."""
    provenance_id: str
    """Fork lifecycle의 vendor provenance identity입니다."""


class HandoffProof(ImmutableValue):
    """Resource lease 이전 전에 확보해야 하는 durable handoff evidence입니다."""

    __slots__ = (
        "durable_flush_receipt",
        "exact_resume_id",
        "next_owner_id",
        "previous_fencing_token",
        "previous_owner_id",
        "session_id",
        "worktree_id",
    )

    def __init__(
        self,
        *,
        session_id: SessionId,
        worktree_id: str | WorktreeId,
        previous_owner_id: ActorId,
        next_owner_id: ActorId,
        previous_fencing_token: str,
        durable_flush_receipt: str,
        exact_resume_id: ResumeId,
    ) -> None:
        """Fenced handoff에 필요한 current lease와 durable evidence를 구성합니다.

        Args:
            session_id: Previous/next owner가 속한 exact session입니다.
            worktree_id: Ownership을 이전할 shared resource identity입니다.
            previous_owner_id: Current lease를 보유해야 하는 actor입니다.
            next_owner_id: 새 lease를 받을 active actor입니다.
            previous_fencing_token: Caller가 read한 current generation token입니다.
            durable_flush_receipt: Previous owner state가 durable함을 증명합니다.
            exact_resume_id: Next owner execution의 exact resume handle입니다.

        Raises:
            LifecycleConflict: Owner가 같거나 required proof가 비면 발생합니다.
        """
        if previous_owner_id == next_owner_id:
            raise LifecycleConflict("handoff must change the resource owner")
        if not previous_fencing_token.strip():
            raise LifecycleConflict("handoff previous_fencing_token must not be empty")
        if not durable_flush_receipt.strip():
            raise LifecycleConflict("handoff durable_flush_receipt must not be empty")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "worktree_id", WorktreeId(str(worktree_id)))
        object.__setattr__(self, "previous_owner_id", previous_owner_id)
        object.__setattr__(self, "next_owner_id", next_owner_id)
        object.__setattr__(self, "previous_fencing_token", previous_fencing_token.strip())
        object.__setattr__(self, "durable_flush_receipt", durable_flush_receipt.strip())
        object.__setattr__(self, "exact_resume_id", exact_resume_id)

    session_id: SessionId
    """Handoff actor가 속한 exact session identity입니다."""
    worktree_id: WorktreeId
    """Ownership을 이전할 shared resource identity입니다."""
    previous_owner_id: ActorId
    """Current lease를 반납하는 actor identity입니다."""
    next_owner_id: ActorId
    """새 generation lease를 받을 actor identity입니다."""
    previous_fencing_token: str
    """Caller가 read한 previous generation의 opaque token입니다."""
    durable_flush_receipt: str
    """Previous owner state가 durable하게 flush되었다는 evidence입니다."""
    exact_resume_id: ResumeId
    """Next owner execution의 exact runtime resume handle입니다."""


class ResourceLease(ImmutableValue):
    """Caller가 subsequent mutation에 제출하는 current worktree lease입니다."""

    __slots__ = (
        "epoch",
        "fencing_token",
        "owner_actor_id",
        "session_id",
        "worktree_id",
    )

    def __init__(self, claim: WorktreeClaim) -> None:
        """Canonical registry claim을 caller-facing fenced lease로 고정합니다.

        Args:
            claim: WorktreeRegistry가 commit하거나 read한 current claim입니다.
        """
        object.__setattr__(self, "worktree_id", claim.worktree_id)
        object.__setattr__(self, "session_id", claim.session_id)
        object.__setattr__(self, "owner_actor_id", claim.actor_id)
        object.__setattr__(self, "epoch", claim.lease_epoch)
        object.__setattr__(self, "fencing_token", claim.fencing_token)

    worktree_id: WorktreeId
    """Lease가 보호하는 shared worktree identity입니다."""
    session_id: SessionId
    """Current owner actor가 속한 session identity입니다."""
    owner_actor_id: ActorId
    """Current generation에서 mutation 가능한 actor identity입니다."""
    epoch: int
    """Claim/handoff마다 단조 증가하는 generation입니다."""
    fencing_token: str
    """Current generation에만 유효한 opaque writer token입니다."""


class HandoffReceipt(ResourceLease):
    """Flush/resume proof와 새 fenced owner를 결합한 handoff receipt입니다."""

    __slots__ = (
        "durable_flush_receipt",
        "exact_resume_id",
        "previous_owner_id",
    )

    def __init__(self, claim: WorktreeClaim, proof: HandoffProof) -> None:
        """새 current lease와 handoff evidence를 하나의 receipt로 결합합니다.

        Args:
            claim: Registry가 commit한 next-owner claim입니다.
            proof: Lease 이전을 허용한 durable handoff proof입니다.
        """
        super().__init__(claim)
        object.__setattr__(self, "previous_owner_id", proof.previous_owner_id)
        object.__setattr__(self, "durable_flush_receipt", proof.durable_flush_receipt)
        object.__setattr__(self, "exact_resume_id", proof.exact_resume_id)

    previous_owner_id: ActorId
    """새 generation에서 mutation authority를 잃은 actor입니다."""
    durable_flush_receipt: str
    """Previous owner의 durable state flush evidence입니다."""
    exact_resume_id: ResumeId
    """Next owner가 이어받은 exact runtime resume handle입니다."""


class EnclaveContextRenderer:
    """Typed enclave snapshot을 bounded runtime context text로 직렬화합니다."""

    def render(self, snapshot: EnclaveSnapshot) -> str:
        """현재 fact만 deterministic order로 포함한 context block을 반환합니다.

        Args:
            snapshot: Exact session에서 검증된 current enclave snapshot입니다.

        Returns:
            Runtime `additionalContext`에 넣을 bounded plain text입니다.
        """
        lines = [f'<neurath-enclave session_id="{snapshot.session_id}">']
        for key, fact in sorted(snapshot.facts.items()):
            lines.append(
                f"- {key}: {fact.value} "
                f"[source={fact.source_kind.value}, turn={fact.source_turn_id}]"
            )
        lines.append("</neurath-enclave>")
        return "\n".join(lines)


class SessionContextRenderer:
    """Exact session의 enclave와 actor-scoped workflow context를 결합합니다."""

    def __init__(self) -> None:
        """Latest-only enclave renderer를 session operational projection과 조합합니다."""
        self._enclave_renderer = EnclaveContextRenderer()

    def render(
        self,
        snapshot: EnclaveSnapshot,
        state: ProcessState,
        envelope: RuntimeEnvelope,
    ) -> str:
        """Lifecycle actor에게 허용된 현재 context만 deterministic하게 직렬화합니다.

        Root actor는 같은 session의 active workflow goal을 모두 복원합니다. Subagent는
        자신의 active workflow와 자신을 target으로 하는 pending assignment만 받습니다.
        Workflow payload 전체는 주입하지 않아 operational secret과 무관 state가 context로
        확산되지 않게 합니다.

        Args:
            snapshot: Exact session의 latest-only enclave입니다.
            state: 같은 session의 validated operational snapshot입니다.
            envelope: Context를 받을 current lifecycle actor identity입니다.

        Returns:
            Enclave, 허용된 workflow goal, assignment를 결합한 context text입니다.
        """
        return self.render_with_boundary(snapshot, state, envelope)[0]

    def render_with_boundary(
        self,
        snapshot: EnclaveSnapshot,
        state: ProcessState,
        envelope: RuntimeEnvelope,
    ) -> tuple[str, int]:
        """Context text와 optional enclave가 시작하는 structural byte offset을 반환합니다.

        Args:
            snapshot: Exact session의 latest-only enclave입니다.
            state: 같은 session의 validated operational snapshot입니다.
            envelope: Context를 받을 lifecycle actor identity입니다.

        Returns:
            Deterministic context text와 enclave 시작 UTF-8 byte offset입니다.
        """
        critical_sections: list[str] = []
        is_root = envelope.actor_id == state.session.root_actor_id
        workflows = [
            {
                "goal": workflow.goal,
                "id": str(workflow.id),
                "kind": workflow.kind,
                "owner_actor_id": str(workflow.owner_actor_id),
            }
            for workflow in state.workflows.values()
            if workflow.status is WorkflowStatus.ACTIVE
            and workflow.goal is not None
            and (is_root or workflow.owner_actor_id == envelope.actor_id)
        ]
        if workflows:
            critical_sections.append(
                self._json_block(
                    "neurath-active-workflows",
                    sorted(workflows, key=lambda workflow: str(workflow["id"])),
                )
            )
        if not is_root:
            assignments = [
                {
                    "assignment": delegation.assignment,
                    "id": str(delegation.id),
                    "owner_actor_id": str(delegation.owner_actor_id),
                }
                for delegation in state.delegations.values()
                if delegation.target_actor_id == envelope.actor_id
                and delegation.status is DelegationStatus.PENDING
            ]
            if assignments:
                critical_sections.insert(
                    0,
                    self._json_block(
                        "neurath-assignments",
                        sorted(assignments, key=lambda assignment: str(assignment["id"])),
                    ),
                )
        material_action = state.material_actions.get(envelope.actor_id)
        if material_action is not None and material_action.status is MaterialActionStatus.OPEN:
            critical_sections.append(
                self._json_block(
                    "neurath-open-material-action",
                    self._material_action_summary(material_action),
                )
            )
        critical = "\n".join(critical_sections)
        enclave = self._enclave_renderer.render(snapshot)
        if not critical:
            return enclave, 0
        prefix = f"{critical}\n"
        return f"{prefix}{enclave}", len(prefix.encode("utf-8"))

    def render_empty(self, session_id: SessionId) -> tuple[str, int]:
        """새 session의 fact 없는 initial enclave와 structural boundary를 반환합니다.

        Args:
            session_id: 아직 operational projection이 없는 startup session입니다.

        Returns:
            Empty enclave text와 optional section의 zero byte offset입니다.
        """
        return self._enclave_renderer.render(EnclaveSnapshot(session_id, {})), 0

    def _material_action_summary(self, batch: MaterialActionBatch) -> dict[str, object]:
        """Open batch에서 compaction 이후 필요한 bounded intent field만 선택합니다.

        Tool invocation, request/output digest와 reasoning text는 projection에 포함하지
        않습니다. Domain-level collection bound를 가진 target과 expectation identity만
        deterministic order로 복원합니다.
        """
        binding = batch.adaptive_binding
        return {
            "adaptive_binding": (
                None
                if binding is None
                else {
                    "goal_fingerprint": binding.goal_fingerprint,
                    "workflow_id": binding.workflow_id,
                    "workflow_revision": binding.workflow_revision,
                }
            ),
            "batch_id": batch.batch_id,
            "expectation_ids": [item.observable_id for item in batch.expectations],
            "kind": batch.kind.value,
            "revision": batch.revision,
            "sequence": batch.sequence,
            "status": batch.status.value,
            "targets": list(batch.targets),
        }

    def _json_block(self, name: str, payload: object) -> str:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"<{name}>{serialized}</{name}>"


class SessionRehydrator:
    """Runtime lifecycle에서 matching session 하나만 context로 복원합니다."""

    _REHYDRATION_CAUSES = frozenset({
        LifecycleCause.STARTUP,
        LifecycleCause.RESUME,
        LifecycleCause.COMPACT,
        LifecycleCause.FORK,
        LifecycleCause.SUBAGENT_START,
    })

    def __init__(self, locator: SessionLocator, enclaves: EnclaveStore) -> None:
        """Canonical locator와 enclave store에 exact-session resolver를 결합합니다.

        Args:
            locator: Session identity를 canonical directory로 변환합니다.
            enclaves: Validated latest-only enclave snapshot store입니다.
        """
        self._locator = locator
        self._kernel = SessionKernel(locator)
        self._enclaves = enclaves
        self._renderer = SessionContextRenderer()

    def rehydrate(self, envelope: RuntimeEnvelope) -> RehydrationDecision:
        """Exact runtime session에 대해 context injection 가능 여부를 결정합니다.

        Args:
            envelope: Adapter가 검증한 runtime identity와 lifecycle cause입니다.

        Returns:
            다른 session fallback 없이 결정된 injection 결과입니다.
        """
        if envelope.cause not in self._REHYDRATION_CAUSES:
            return self._decision(envelope, RehydrationStatus.SKIPPED)
        required_capability = self._required_capability(envelope.cause)
        if required_capability not in envelope.capabilities:
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.CAPABILITY_UNAVAILABLE,
            )
        try:
            state = self._kernel.inspect(envelope.session_id)
        except SessionNotFound:
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.ORPHAN_SESSION,
            )
        except InvalidSessionState:
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.CORRUPT_STATE,
            )
        if state.session.status is SessionStatus.ENDED:
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.TERMINAL_SESSION,
            )
        if state.session.runtime is not envelope.runtime:
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.RUNTIME_MISMATCH,
            )
        paths = self._locator.locate(envelope.session_id)
        if not paths.enclave.is_file():
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.ORPHAN_SESSION,
            )
        try:
            snapshot = self._enclaves.read(envelope.session_id)
        except EnclaveStateInvalid:
            return self._decision(
                envelope,
                RehydrationStatus.BLOCKED,
                diagnostic=RehydrationDiagnostic.CORRUPT_STATE,
            )
        additional_context, optional_context_start_bytes = self._renderer.render_with_boundary(
            snapshot,
            state,
            envelope,
        )
        return self._decision(
            envelope,
            RehydrationStatus.READY,
            additional_context=additional_context,
            optional_context_start_bytes=optional_context_start_bytes,
        )

    def initial_context(self, envelope: RuntimeEnvelope) -> RehydrationDecision:
        """SessionStarted와 원자 결속할 fact 없는 startup context를 구성합니다.

        Args:
            envelope: 새 exact session의 validated startup identity입니다.

        Returns:
            Empty initial enclave와 structural optional boundary를 가진 ready decision입니다.

        Raises:
            ValueError: Startup 이외 lifecycle에 사용하면 발생합니다.
        """
        if envelope.cause is not LifecycleCause.STARTUP:
            raise ValueError("initial context is available only for startup")
        additional_context, optional_context_start_bytes = self._renderer.render_empty(
            envelope.session_id
        )
        return self._decision(
            envelope,
            RehydrationStatus.READY,
            additional_context=additional_context,
            optional_context_start_bytes=optional_context_start_bytes,
        )

    def _required_capability(self, cause: LifecycleCause) -> RuntimeCapability:
        """Lifecycle cause에 실제로 대응하는 context output capability를 반환합니다.

        Args:
            cause: Rehydration 대상으로 검증된 lifecycle cause입니다.

        Returns:
            Session 또는 subagent hook이 각각 요구하는 capability입니다.
        """
        if cause is LifecycleCause.SUBAGENT_START:
            return RuntimeCapability.SUBAGENT_START_ADDITIONAL_CONTEXT
        return RuntimeCapability.SESSION_START_ADDITIONAL_CONTEXT

    def _decision(
        self,
        envelope: RuntimeEnvelope,
        status: RehydrationStatus,
        *,
        additional_context: str | None = None,
        optional_context_start_bytes: int | None = None,
        diagnostic: RehydrationDiagnostic | None = None,
    ) -> RehydrationDecision:
        return RehydrationDecision(
            status=status,
            session_id=envelope.session_id,
            hook_event_name=envelope.provenance.event_name,
            additional_context=additional_context,
            optional_context_start_bytes=optional_context_start_bytes,
            diagnostic=diagnostic,
        )


class SessionLifecycle:
    """Fork snapshot과 fenced worktree ownership lifecycle을 조정합니다."""

    def __init__(self, locator: SessionLocator, enclaves: EnclaveStore) -> None:
        """Session state, enclave와 shared worktree registry를 결합합니다.

        Args:
            locator: Exact session과 shared resource root의 canonical locator입니다.
            enclaves: Bounded optimistic enclave snapshot store입니다.
        """
        self._locator = locator
        self._kernel = SessionKernel(locator)
        self._enclaves = enclaves
        self._worktrees = WorktreeRegistry(locator)

    def fork(self, lineage: ForkLineage) -> ForkReceipt:
        """Runtime-proven source enclave를 새 independent session에 원자 복사합니다.

        Args:
            lineage: Source, target, runtime과 vendor provenance입니다.

        Returns:
            Source snapshot digest와 독립 target identity를 보존한 receipt입니다.

        Raises:
            LifecycleConflict: Source가 terminal이거나 target lineage가 충돌하거나
                retry target에 부분 snapshot이 남았으면 발생합니다.
        """
        source_state = self._kernel.inspect(lineage.source_session_id)
        if source_state.session.status is SessionStatus.ENDED:
            raise LifecycleConflict("terminal session cannot be forked")
        if source_state.session.runtime is not lineage.runtime:
            raise LifecycleConflict("fork runtime does not match source session")
        source_snapshot = self._enclaves.read(lineage.source_session_id)
        target_paths = self._locator.locate(lineage.target_session_id)
        if not target_paths.process_state.exists() and target_paths.enclave.exists():
            raise LifecycleConflict("fork target has an orphan enclave")
        if target_paths.artifacts.is_dir() and any(target_paths.artifacts.iterdir()):
            raise LifecycleConflict("fork target has pre-existing artifacts")
        target_root_actor_id = ActorId(
            f"{lineage.runtime.value}:session:{lineage.target_session_id}"
        )
        try:
            target_state = self._kernel.apply(
                SessionStarted(
                    session_id=lineage.target_session_id,
                    resume_id=lineage.target_resume_id,
                    runtime=lineage.runtime,
                    root_actor_id=target_root_actor_id,
                    idempotency_key=f"fork:{lineage.provenance_id}",
                    parent_session_id=lineage.source_session_id,
                    lifecycle_provenance_id=lineage.provenance_id,
                )
            )
        except (InvalidSessionState, TransitionRejected) as error:
            raise LifecycleConflict("fork target lineage conflicts with persisted state") from error
        self._validate_fork_target(target_state, lineage, target_root_actor_id)
        try:
            target_snapshot = self._enclaves.read(lineage.target_session_id)
        except EnclaveStateInvalid as error:
            raise LifecycleConflict("fork target enclave is not recoverable") from error
        if not self._same_fact_payloads(target_snapshot, source_snapshot):
            if target_snapshot.facts:
                raise LifecycleConflict(
                    "fork target contains a partial or foreign enclave snapshot"
                )
            try:
                self._enclaves.replace_facts(
                    lineage.target_session_id,
                    target_root_actor_id,
                    source_snapshot.facts,
                    expected_digest=target_snapshot.digest,
                )
            except EnclaveConflict as error:
                raise LifecycleConflict(
                    "fork target enclave changed during snapshot commit"
                ) from error
        return ForkReceipt(
            source_session_id=lineage.source_session_id,
            target_session_id=lineage.target_session_id,
            source_enclave_digest=source_snapshot.digest,
            provenance_id=lineage.provenance_id,
        )

    def _validate_fork_target(
        self,
        state: ProcessState,
        lineage: ForkLineage,
        root_actor_id: ActorId,
    ) -> None:
        """Retry target이 exact initialized fork lineage인지 fail-closed로 검증합니다.

        Args:
            state: SessionStarted의 commit 또는 idempotent read 결과입니다.
            lineage: Caller가 제출한 source, target, runtime provenance입니다.
            root_actor_id: Target runtime identity에서 결정론적으로 파생한 root입니다.

        Raises:
            LifecycleConflict: Target이 fork 초기화 이외의 state를 포함하거나
                lineage evidence와 다르면 발생합니다.
        """
        session = state.session
        expected_session = (
            lineage.target_session_id,
            lineage.target_resume_id,
            lineage.runtime,
            root_actor_id,
            SessionStatus.ACTIVE,
            lineage.source_session_id,
            lineage.provenance_id,
            f"fork:{lineage.provenance_id}",
        )
        actual_session = (
            session.id,
            session.resume_id,
            session.runtime,
            session.root_actor_id,
            session.status,
            session.parent_session_id,
            session.lifecycle_provenance_id,
            session.last_lifecycle_idempotency_key,
        )
        root_actor = state.actors.get(root_actor_id)
        delivery_only_projections = (
            root_actor is not None
            and root_actor.to_payload()
            == {
                "id": str(root_actor_id),
                "parent_actor_id": None,
                "kind": "root",
                "status": "active",
            }
            and set(state.actors) == {root_actor_id}
            and not state.workflows
            and not state.delegations
            and state.resources == {"worktrees": {}}
            and not state.mailboxes
            and not state.incidents
            and self._fork_retry_outbox_is_delivery_only(state, lineage, root_actor_id)
            and not state.foreground_turns
            and not state.material_actions
        )
        if actual_session != expected_session or not delivery_only_projections:
            raise LifecycleConflict("fork target is not an exact initialized lineage")

    @staticmethod
    def _fork_retry_outbox_is_delivery_only(
        state: ProcessState,
        lineage: ForkLineage,
        root_actor_id: ActorId,
    ) -> bool:
        """ACK 전 exact fork context delivery만 초기 lineage delta로 허용합니다.

        Args:
            state: Retry target의 current aggregate snapshot입니다.
            lineage: 동일해야 하는 source, target, runtime provenance입니다.
            root_actor_id: Fork target의 deterministic root actor입니다.

        Returns:
            Outbox가 비었거나 exact fork context delivery 하나뿐이면 참입니다.
        """
        if not state.outbox:
            return True
        if len(state.outbox) != 1:
            return False
        effect = next(iter(state.outbox.values()))
        payload = effect.payload
        return (
            effect.actor_id == root_actor_id
            and effect.kind is EffectKind.CONTEXT_INJECTION
            and payload.get("actor_id") == str(root_actor_id)
            and payload.get("cause") == LifecycleCause.FORK.value
            and payload.get("runtime") == lineage.runtime.value
            and payload.get("session_id") == str(lineage.target_session_id)
        )

    def _same_fact_payloads(
        self,
        left: EnclaveSnapshot,
        right: EnclaveSnapshot,
    ) -> bool:
        """Session identity를 제외한 latest fact payload이 같은지 비교합니다.

        Args:
            left: Target의 current enclave snapshot입니다.
            right: Fork 시작 시 한 번 읽은 source snapshot입니다.

        Returns:
            Stable key와 value/provenance payload이 모두 같으면 True입니다.
        """
        left_facts = {key: fact.to_payload() for key, fact in left.facts.items()}
        right_facts = {key: fact.to_payload() for key, fact in right.facts.items()}
        return left_facts == right_facts

    def claim_worktree(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        worktree_id: str | WorktreeId,
        path: Path,
    ) -> ResourceLease:
        """Active actor에게 existing worktree의 mutation lease를 claim합니다.

        Args:
            session_id: Owner actor가 속한 exact session입니다.
            actor_id: Current mutation owner가 될 active actor입니다.
            worktree_id: Shared resource registry identity입니다.
            path: Existing canonical worktree directory입니다.

        Returns:
            Epoch과 opaque fencing token이 포함된 current lease입니다.
        """
        claim = self._worktrees.claim(
            WorktreeClaim(
                worktree_id=WorktreeId(str(worktree_id)),
                path=path,
                session_id=session_id,
                actor_id=actor_id,
            )
        )
        return ResourceLease(claim)

    def handoff(self, proof: HandoffProof) -> HandoffReceipt:
        """Durable flush와 exact resume proof 뒤 worktree lease를 이전합니다.

        Args:
            proof: 이전 owner의 current token과 next owner resume evidence입니다.

        Returns:
            증가한 epoch과 새 fencing token을 가진 handoff receipt입니다.

        Raises:
            StaleFencingTokenError: Expected owner/token이 current lease와 다르면 발생합니다.
        """
        try:
            current = self._worktrees.get(proof.worktree_id)
        except WorktreeNotClaimed as error:
            raise StaleFencingTokenError(
                f"worktree {proof.worktree_id} has no current lease"
            ) from error
        pending = self._pending_handoff_effect(proof)
        if pending is None:
            self._require_previous_lease(current, proof)
            pending = self._handoff_effect(proof, current)
            self._kernel.apply(
                EffectPrepared(
                    session_id=proof.session_id,
                    actor_id=proof.previous_owner_id,
                    effect=pending,
                    idempotency_key=f"handoff-prepare:{pending.delivery_key}",
                )
            )
        else:
            self._validate_handoff_effect(pending, proof)
        next_claim = self._transfer_or_recover(current, proof, pending)
        self._retire_previous_actor(proof)
        self._kernel.apply(
            EffectAcknowledged(
                session_id=proof.session_id,
                actor_id=proof.previous_owner_id,
                effect_id=pending.id,
                idempotency_key=f"handoff-ack:{pending.delivery_key}",
            )
        )
        return HandoffReceipt(next_claim, proof)

    def _pending_handoff_effect(self, proof: HandoffProof) -> OutboxEffect | None:
        """Same proof의 durable prepared effect가 있으면 exact identity로 반환합니다.

        Args:
            proof: Retry 여부를 판정할 caller handoff evidence입니다.

        Returns:
            Pending effect 또는 아직 prepare되지 않았으면 None입니다.
        """
        state = self._kernel.inspect(proof.session_id)
        return state.outbox.get(self._handoff_effect_id(proof))

    def _handoff_effect(
        self,
        proof: HandoffProof,
        previous_claim: WorktreeClaim,
    ) -> OutboxEffect:
        """External lease CAS 전에 commit할 recoverable handoff instruction을 만듭니다.

        Args:
            proof: Durable flush와 exact-resume evidence입니다.
            previous_claim: Caller proof가 가리키는 current fenced generation입니다.

        Returns:
            Same proof retry에서 같은 identity를 갖는 pending outbox effect입니다.
        """
        proof_digest = self._handoff_proof_digest(proof)
        return OutboxEffect(
            effect_id=EffectId(f"handoff-{proof_digest}"),
            actor_id=proof.previous_owner_id,
            kind=EffectKind.DELIVERY,
            delivery_key=f"worktree-handoff:{proof_digest}",
            payload={
                "operation": "worktree-handoff",
                "worktree_id": str(proof.worktree_id),
                "session_id": str(proof.session_id),
                "previous_owner_id": str(proof.previous_owner_id),
                "next_owner_id": str(proof.next_owner_id),
                "previous_lease_epoch": previous_claim.lease_epoch,
                "previous_fencing_token_sha256": self._sha256(proof.previous_fencing_token),
                "durable_flush_receipt_sha256": self._sha256(proof.durable_flush_receipt),
                "exact_resume_id": str(proof.exact_resume_id),
                "proof_sha256": proof_digest,
            },
        )

    def _handoff_effect_id(self, proof: HandoffProof) -> EffectId:
        return EffectId(f"handoff-{self._handoff_proof_digest(proof)}")

    def _handoff_proof_digest(self, proof: HandoffProof) -> str:
        canonical = json.dumps(
            {
                "durable_flush_receipt": proof.durable_flush_receipt,
                "exact_resume_id": str(proof.exact_resume_id),
                "next_owner_id": str(proof.next_owner_id),
                "previous_fencing_token": proof.previous_fencing_token,
                "previous_owner_id": str(proof.previous_owner_id),
                "session_id": str(proof.session_id),
                "worktree_id": str(proof.worktree_id),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return self._sha256(canonical)

    def _sha256(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _validate_handoff_effect(
        self,
        effect: OutboxEffect,
        proof: HandoffProof,
    ) -> None:
        payload = effect.payload
        if (
            effect.kind is not EffectKind.DELIVERY
            or effect.actor_id != proof.previous_owner_id
            or payload.get("operation") != "worktree-handoff"
            or payload.get("worktree_id") != str(proof.worktree_id)
            or payload.get("session_id") != str(proof.session_id)
            or payload.get("previous_owner_id") != str(proof.previous_owner_id)
            or payload.get("next_owner_id") != str(proof.next_owner_id)
            or payload.get("proof_sha256") != self._handoff_proof_digest(proof)
        ):
            raise LifecycleConflict("pending handoff effect does not match retry proof")

    def _require_previous_lease(
        self,
        claim: WorktreeClaim,
        proof: HandoffProof,
    ) -> None:
        if (
            claim.session_id != proof.session_id
            or claim.actor_id != proof.previous_owner_id
            or claim.fencing_token != proof.previous_fencing_token
        ):
            raise StaleFencingTokenError(f"worktree {proof.worktree_id} expected lease is stale")

    def _transfer_or_recover(
        self,
        current: WorktreeClaim,
        proof: HandoffProof,
        pending: OutboxEffect,
    ) -> WorktreeClaim:
        if self._is_recoverable_target_claim(current, proof, pending):
            return current
        try:
            self._require_previous_lease(current, proof)
        except StaleFencingTokenError:
            self._abort_handoff_effect(proof, pending)
            raise
        try:
            return self._worktrees.handoff(
                current,
                next_session_id=proof.session_id,
                next_actor_id=proof.next_owner_id,
                transition_id=self._handoff_proof_digest(proof),
            )
        except (WorktreeLeaseConflict, WorktreeNotClaimed) as error:
            try:
                latest = self._worktrees.get(proof.worktree_id)
            except WorktreeNotClaimed:
                latest = None
            if latest is not None and self._is_recoverable_target_claim(
                latest,
                proof,
                pending,
            ):
                return latest
            self._abort_handoff_effect(proof, pending)
            raise StaleFencingTokenError(
                f"worktree {proof.worktree_id} changed during handoff"
            ) from error

    def _abort_handoff_effect(
        self,
        proof: HandoffProof,
        pending: OutboxEffect,
    ) -> None:
        """Stale proof가 남긴 exact pending intent를 idempotent ACK로 제거합니다.

        Args:
            proof: Abort할 exact handoff proof의 session과 actor identity입니다.
            pending: 더 이상 resource commit으로 회복할 수 없는 prepared effect입니다.
        """
        self._kernel.apply(
            EffectAcknowledged(
                session_id=proof.session_id,
                actor_id=proof.previous_owner_id,
                effect_id=pending.id,
                idempotency_key=f"handoff-abort:{pending.delivery_key}",
            )
        )

    def _is_recoverable_target_claim(
        self,
        claim: WorktreeClaim,
        proof: HandoffProof,
        pending: OutboxEffect,
    ) -> bool:
        previous_epoch = pending.payload.get("previous_lease_epoch")
        transition_id = pending.payload.get("proof_sha256")
        return (
            isinstance(previous_epoch, int)
            and not isinstance(previous_epoch, bool)
            and isinstance(transition_id, str)
            and transition_id == self._handoff_proof_digest(proof)
            and claim.worktree_id == proof.worktree_id
            and claim.session_id == proof.session_id
            and claim.actor_id == proof.next_owner_id
            and claim.lease_epoch == previous_epoch + 1
            and claim.transition_id == transition_id
        )

    def _retire_previous_actor(self, proof: HandoffProof) -> None:
        """Transferred lease receipt를 반환하기 전에 previous actor를 영구 fencing합니다.

        Args:
            proof: Retire할 exact session/actor와 handoff identity입니다.
        """
        self._kernel.apply(
            ActorStopped(
                session_id=proof.session_id,
                actor_id=proof.previous_owner_id,
                terminal_status=ActorStatus.RETIRED,
                idempotency_key=(
                    f"handoff-retire:{proof.worktree_id}:{proof.previous_owner_id}:"
                    f"{self._handoff_proof_digest(proof)}"
                ),
            )
        )

    def assert_mutation_allowed(
        self,
        worktree_id: str | WorktreeId,
        actor_id: ActorId,
        fencing_token: str,
    ) -> None:
        """Exact current owner와 fencing token이 일치하지 않으면 mutation을 거부합니다.

        Args:
            worktree_id: Mutation 대상 shared resource입니다.
            actor_id: Mutation을 요청한 actor입니다.
            fencing_token: Caller가 보유한 lease generation token입니다.

        Raises:
            StaleFencingTokenError: Claim이 없거나 owner/token이 current 값과 다르면
                발생합니다.
        """
        canonical_id = WorktreeId(str(worktree_id))
        try:
            current = self._worktrees.get(canonical_id)
        except WorktreeNotClaimed as error:
            raise StaleFencingTokenError(f"worktree {canonical_id} has no current lease") from error
        if current.actor_id != actor_id or current.fencing_token != fencing_token:
            raise StaleFencingTokenError(
                f"actor {actor_id} does not hold current lease for {canonical_id}"
            )
