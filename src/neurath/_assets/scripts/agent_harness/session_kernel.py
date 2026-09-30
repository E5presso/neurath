"""Session application service and stable public API for existing adapters."""

from __future__ import annotations

import time
from collections.abc import (
    Mapping,
)

from scripts.agent_harness.adaptive_control import (
    ControlAction,
)
from scripts.agent_harness.adaptive_policy import (
    requires_adaptive_control_for_workflow,
    validate_adaptive_control_policy_transition,
)
from scripts.agent_harness.adaptive_resource_admission import (
    validate_efficiency_resource_admission,
)
from scripts.agent_harness.adaptive_state import (
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    InvalidAdaptiveControlState,
)
from scripts.agent_harness.adaptive_transition import (
    validate_adaptive_control_transition,
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
from scripts.agent_harness.session_events import (
    ActorResumed,
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
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnReplaced,
    ForegroundTurnToolObserved,
    ForegroundTurnYielded,
    HarnessIncidentEscalated,
    HarnessIncidentEvidenceSuperseded,
    HarnessIncidentRecorded,
    HarnessIncidentResolved,
    HarnessIncidentsRefreshed,
    KernelEvent,
    PostCleanupFinalized,
    MaterialActionAbandoned,
    MaterialActionPrepared,
    MaterialActionResolved,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    ReservedSkillStateAdvanced,
    SessionCompacted,
    SessionEnded,
    SessionResumed,
    SessionStarted,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowStarted,
)
from scripts.agent_harness.session_model import (
    ENCLAVE_SCHEMA,
    MAX_PENDING_OUTBOX_EFFECTS,
    PROCESS_STATE_SCHEMA,
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorRecord,
    ActorStatus,
    CommitStage,
    DelegationId,
    DelegationRecord,
    DelegationResult,
    DelegationStatus,
    DelegationTopologyPolicy,
    EffectId,
    EffectKind,
    ForegroundPromptAuthorityContext,
    ForegroundTurnOutcome,
    ForegroundTurnReceipt,
    ForegroundTurnRecord,
    ForegroundTurnStatus,
    ForegroundUserPromptReceipt,
    HarnessIncidentEvidenceArchive,
    HarnessIncidentRecord,
    HarnessIncidentStatus,
    HarnessRegressionReceipt,
    Identifier,
    ImmutableValue,
    IncidentId,
    InvalidIdentity,
    InvalidRetryLimit,
    InvalidSessionState,
    MonitorWorkflowStopProjection,
    OptimisticRetryExhausted,
    OutboxEffect,
    ProcessState,
    ResumeId,
    RevisionConflict,
    SessionId,
    SessionNotFound,
    SessionRecord,
    SessionRuntime,
    SessionStatus,
    TransitionRejected,
    TurnId,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
    WorktreeId,
)
from scripts.agent_harness.session_paths import (
    SessionLocator,
    SessionPaths,
)
from scripts.agent_harness.session_reducer import (
    SessionStateReducer,
)
from scripts.agent_harness.session_state_codec import (
    SessionStateCodec,
    SessionStateValidator,
)
from scripts.agent_harness.session_store import (
    SessionStateStore,
)
from scripts.agent_harness.skill_state_contract import (
    SessionKernelError,
)
from scripts.agent_harness.workflow_terminal import (
    WorkflowTerminalPolicy,
)

__all__ = [
    "ActorId",
    "ActorKind",
    "ActorLineageAssurance",
    "ActorRecord",
    "ActorResumed",
    "ActorStarted",
    "ActorStatus",
    "ActorStopped",
    "AdaptiveActionBinding",
    "AdaptiveControlSnapshot",
    "AdaptiveControlState",
    "CommitStage",
    "ControlAction",
    "DelegationAssigned",
    "DelegationCancelled",
    "DelegationConsumed",
    "DelegationId",
    "DelegationRecord",
    "DelegationReported",
    "DelegationResult",
    "DelegationStatus",
    "DelegationTopologyPolicy",
    "ENCLAVE_SCHEMA",
    "EffectAcknowledged",
    "EffectId",
    "EffectKind",
    "EffectPrepared",
    "ForegroundPromptAuthorityContext",
    "ForegroundTurnClosed",
    "ForegroundTurnInvalidated",
    "ForegroundTurnOutcome",
    "ForegroundTurnPrompted",
    "ForegroundTurnProvisioned",
    "ForegroundTurnReceipt",
    "ForegroundTurnRecord",
    "ForegroundTurnReplaced",
    "ForegroundTurnStatus",
    "ForegroundTurnToolObserved",
    "ForegroundTurnYielded",
    "ForegroundUserPromptReceipt",
    "HarnessIncidentEscalated",
    "HarnessIncidentEvidenceArchive",
    "HarnessIncidentEvidenceSuperseded",
    "HarnessIncidentRecord",
    "HarnessIncidentRecorded",
    "HarnessIncidentResolved",
    "HarnessIncidentStatus",
    "HarnessIncidentsRefreshed",
    "HarnessRegressionReceipt",
    "Identifier",
    "ImmutableValue",
    "IncidentId",
    "InvalidAdaptiveControlState",
    "InvalidIdentity",
    "InvalidRetryLimit",
    "InvalidSessionState",
    "KernelEvent",
    "MAX_PENDING_OUTBOX_EFFECTS",
    "MaterialActionAbandoned",
    "MaterialActionBatch",
    "MaterialActionKind",
    "MaterialActionPrepared",
    "MaterialActionResolution",
    "MaterialActionResolved",
    "MaterialActionStatus",
    "MaterialActionToolObserved",
    "MaterialActionToolStarted",
    "MonitorWorkflowStopProjection",
    "ObservableExpectation",
    "OptimisticRetryExhausted",
    "OutboxEffect",
    "PROCESS_STATE_SCHEMA",
    "ProcessState",
    "ReservedSkillStateAdvanced",
    "ResumeId",
    "RevisionConflict",
    "SessionCompacted",
    "SessionEnded",
    "SessionId",
    "SessionKernelError",
    "SessionLocator",
    "SessionNotFound",
    "SessionPaths",
    "SessionRecord",
    "SessionResumed",
    "SessionRuntime",
    "SessionStarted",
    "SessionStateCodec",
    "SessionStateReducer",
    "SessionStateStore",
    "SessionStateValidator",
    "SessionStatus",
    "ToolInvocation",
    "ToolReceipt",
    "ToolReceiptOutcome",
    "TransitionRejected",
    "TurnId",
    "WorkflowAdvanced",
    "WorkflowFinalized",
    "WorkflowId",
    "WorkflowRecord",
    "WorkflowStarted",
    "WorkflowStatus",
    "WorkflowTerminalPolicy",
    "WorktreeId",
    "requires_adaptive_control_for_workflow",
    "validate_adaptive_control_policy_transition",
    "validate_adaptive_control_transition",
    "validate_efficiency_resource_admission",
]


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
        return isinstance(event, ReservedSkillStateAdvanced | WorkflowFinalized | PostCleanupFinalized)

    def finalize_cleaned_transaction(self, transaction, event, expected_revision):
        """Commit only the typed issuer recovery inside its task/result transaction.

        SQLite owns the CAS. Do not take session file locks after acquiring its
        writer lock; the application holds the original provider lifetime fence.
        """
        if not isinstance(event, PostCleanupFinalized):
            raise TransitionRejected("post-cleanup transaction requires its typed issuer event")
        store = SessionStateStore(self._locator.locate(event.session_id).process_state)
        source = store.read_transaction(transaction, event.session_id)
        if source.revision != expected_revision:
            raise RevisionConflict("post-cleanup source process revision changed")
        self._validate_adaptive_authority(source, event)
        candidate = SessionStateReducer().reduce(source, event).with_revision(source.revision + 1)
        from scripts.agent_harness.session_state_codec import SessionStateCodec
        transaction.put("session", str(event.session_id), SessionStateCodec().encode(candidate),
                        expected_revision=source.revision)
        return candidate

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

        if isinstance(event, PostCleanupFinalized):
            from scripts.agent_harness.post_cleanup_admission import verify_admission
            verify_admission(self._locator, state, event)
        if not isinstance(event, ReservedSkillStateAdvanced | WorkflowFinalized | PostCleanupFinalized):
            raise TransitionRejected("adaptive admission requires a workflow event")
        workflow = state.workflows.get(event.workflow_id)
        if workflow is None:
            raise TransitionRejected(f"workflow is missing: {event.workflow_id}")
        handle = StateHandle(
            self,
            RuntimeIdentityBinding(
                runtime=state.session.runtime,
                session_id=state.session.id,
                actor_id=event.original_owner if isinstance(event, PostCleanupFinalized) else event.actor_id,
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
