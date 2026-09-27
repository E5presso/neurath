"""Pure session transitions and cross-aggregate admission rules."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from scripts.agent_harness.adaptive_control import ControlAction
from scripts.agent_harness.adaptive_policy import (
    requires_adaptive_control_for_workflow,
    validate_adaptive_control_policy_transition,
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
    MaterialActionResolution,
    MaterialActionStatus,
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
    MAX_PENDING_OUTBOX_EFFECTS,
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorRecord,
    ActorStatus,
    DelegationRecord,
    DelegationResult,
    DelegationStatus,
    DelegationTopologyPolicy,
    EffectId,
    ForegroundPromptAuthorityContext,
    ForegroundTurnOutcome,
    ForegroundTurnReceipt,
    ForegroundTurnRecord,
    ForegroundTurnStatus,
    ForegroundUserPromptReceipt,
    HarnessIncidentRecord,
    HarnessIncidentStatus,
    IncidentId,
    OutboxEffect,
    ProcessState,
    ResumeId,
    SessionNotFound,
    SessionRecord,
    SessionStatus,
    TransitionRejected,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.workflow_terminal import WorkflowTerminalPolicy


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
        interruption_identity = "\x1f".join(
            (
                str(event.session_id),
                str(event.resume_id),
                event.lifecycle_provenance_id,
                invocation.invocation_id,
            )
        )
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
        return state.__replace__(outbox=outbox)

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
        return state.__replace__(outbox=outbox)

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
        return state.__replace__(session=session, outbox=outbox)

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
        return state.__replace__(actors=actors, outbox=outbox)

    def _resume_actor(self, state: ProcessState, event: ActorResumed) -> ProcessState:
        actor = state.actors.get(event.actor_id)
        turn = state.foreground_turns.get(event.actor_id)
        parent_turn = state.foreground_turns.get(event.parent_actor_id)
        if (
            actor is None
            or actor.kind is not ActorKind.SUBAGENT
            or actor.status is not ActorStatus.STOPPED
            or actor.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
            or actor.parent_actor_id != event.parent_actor_id
            or event.parent_actor_id != state.session.root_actor_id
            or turn is None
            or turn.status is not ForegroundTurnStatus.CLOSED
            or turn.revision != event.expected_turn_revision
            or turn.vendor_turn_id == event.vendor_turn_id
            or parent_turn is None
            or parent_turn.status is not ForegroundTurnStatus.ACTIVE
        ):
            raise TransitionRejected(
                "actor resume lacks an exact stopped direct child and new turn"
            )
        self._require_available_actor(state, event.parent_actor_id, "actor parent")
        actors = dict(state.actors)
        actors[event.actor_id] = ActorRecord(
            actor.id, actor.parent_actor_id, actor.kind, ActorStatus.ACTIVE, actor.lineage_assurance
        )
        turns = dict(state.foreground_turns)
        turns[event.actor_id] = ForegroundTurnRecord(
            event.actor_id,
            turn.generation + 1,
            turn.revision + 1,
            ForegroundTurnStatus.ACTIVE,
            None,
            event.vendor_turn_id,
        )
        return state.__replace__(actors=actors, foreground_turns=turns)

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
        return state.__replace__(actors=actors)

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
        return state.__replace__(session=session, actors=actors)

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
        if event.kind == "autopilot" and isinstance(event.payload.get("phase_run"), dict):
            turn = state.foreground_turns.get(event.owner_actor_id)
            prompt = None if turn is None else turn.user_prompt_receipt
            if (
                prompt is None
                or event.payload.get("invocation_prompt_digest") != prompt.prompt_digest
                or event.payload.get("invocation_prompt_reference") != prompt.authority_reference
            ):
                raise TransitionRejected("autopilot workflow prompt binding changed")
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
        return state.__replace__(workflows=workflows)

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
        return state.__replace__(workflows=workflows)

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
        return state.__replace__(workflows=workflows)

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
        identity = "\x1f".join(
            (
                str(event.session_id),
                str(event.actor_id),
                event.batch_id,
                event.invocation_id,
                str(event.expected_turn_generation),
            )
        )
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
        return state.__replace__(material_actions=batches)

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
                replacement_question=(
                    current.receipt
                    if current.receipt is not None
                    and current.receipt.outcome is ForegroundTurnOutcome.AWAITING_INPUT
                    else None
                ),
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
        return state.__replace__(foreground_turns=turns)

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
        return state.__replace__(delegations=delegations)

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
        return state.__replace__(delegations=delegations)

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
        return state.__replace__(delegations=delegations)

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
        return state.__replace__(delegations=delegations)

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
        return state.__replace__(incidents=incidents)

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
