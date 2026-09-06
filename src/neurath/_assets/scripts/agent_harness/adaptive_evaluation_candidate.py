"""독립 evaluator가 읽을 adaptive snapshot을 immutable session artifact로 고정합니다."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    InvalidAdaptiveControlState,
    validate_adaptive_control_transition,
)
from scripts.agent_harness.artifact_store import ArtifactStoreError, SessionArtifactStore
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStatus,
    DelegationStatus,
    DelegationTopologyPolicy,
    ProcessState,
    SessionStatus,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.state_handle import StateHandle


class AdaptiveEvaluationCandidateError(RuntimeError):
    """Evaluator candidate를 안전하게 준비하거나 읽을 수 없음을 나타냅니다."""


class AdaptiveEvaluationCandidateAuthorityError(AdaptiveEvaluationCandidateError):
    """Current actor가 candidate prepare/read authority를 갖지 않음을 나타냅니다."""


class AdaptiveEvaluationCandidateConflict(AdaptiveEvaluationCandidateError):
    """Candidate artifact read/write 동안 process state가 바뀌었음을 나타냅니다."""


class AdaptiveEvaluationCandidateInvalid(AdaptiveEvaluationCandidateError):
    """Assignment, artifact 또는 embedded adaptive state가 invalid함을 나타냅니다."""


@dataclass(frozen=True, slots=True)
class AdaptiveEvaluationCandidatePreparation:
    """Owner가 evaluator에게 전달할 immutable artifact와 assignment identity입니다."""

    candidate_ref: str
    """Full adaptive state artifact의 content-addressed reference입니다."""

    assignment_json: str
    """Candidate identity를 고정하는 canonical delegation assignment JSON입니다."""


@dataclass(frozen=True, slots=True)
class AdaptiveEvaluationCandidateReadback:
    """Evaluator가 함께 읽을 candidate state와 bounded execution trajectory입니다."""

    state: AdaptiveControlState
    """Independent semantic judgment의 exact adaptive candidate입니다."""

    trajectory: Mapping[str, object]
    """Raw transcript 없이 current material path만 담은 content-bound JSON입니다."""

    candidate_ref: str
    """State와 trajectory wrapper 전체의 content-addressed reference입니다."""


@dataclass(frozen=True, slots=True)
class _AdaptiveEvaluationCandidateArtifact:
    """Typed candidate와 source/target workflow CAS identity를 함께 보존합니다."""

    state: AdaptiveControlState
    reference: str
    workflow_revision: int
    target_workflow_revision: int
    workflow_payload_digest: str
    target_workflow_payload_digest: str
    trajectory: Mapping[str, object]
    trajectory_digest: str


class AdaptiveEvaluationCandidateStore:
    """Owner-prepared adaptive state와 direct child evaluator 사이의 artifact 경계입니다."""

    _ARTIFACT_SCHEMA = "neurath.adaptive-evaluation-candidate.v2"
    _TRAJECTORY_SCHEMA = "neurath.adaptive-evaluation-trajectory.v1"
    _ASSIGNMENT_KIND = "adaptive-goal-evaluation"
    _ASSIGNMENT_FIELDS = frozenset({
        "candidate_ref",
        "goal_fingerprint",
        "intent_revision",
        "kind",
        "source_revision",
        "trajectory_digest",
        "target_workflow_payload_digest",
        "target_workflow_revision",
        "workflow_id",
        "workflow_payload_digest",
        "workflow_revision",
    })
    _ARTIFACT_FIELDS = frozenset({
        "owner_actor_id",
        "schema",
        "session_id",
        "state",
        "trajectory",
        "trajectory_digest",
        "target_workflow_payload_digest",
        "target_workflow_revision",
        "workflow_id",
        "workflow_payload_digest",
        "workflow_revision",
    })

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Runtime-bound handle과 exact workflow selector를 고정합니다.

        Args:
            handle: Exact session과 current actor authority에 결속된 state facade입니다.
            workflow_id: Candidate가 속한 active workflow identity입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._artifacts = SessionArtifactStore(handle)

    def prepare(
        self,
        candidate: AdaptiveControlState,
    ) -> AdaptiveEvaluationCandidatePreparation:
        """Active workflow owner가 full adaptive state artifact와 assignment를 준비합니다.

        Args:
            candidate: Independent evaluator가 live state 대신 읽을 immutable snapshot입니다.

        Returns:
            Content digest reference와 canonical delegation assignment JSON입니다.

        Raises:
            AdaptiveEvaluationCandidateAuthorityError: Current actor가 active owner가 아니면
                발생합니다.
            AdaptiveEvaluationCandidateConflict: Artifact write 동안 process revision이
                달라지면 발생합니다.
            AdaptiveEvaluationCandidateInvalid: Candidate와 workflow goal이 다르거나 artifact
                serialization이 실패하면 발생합니다.
        """
        before = self._handle.inspect()
        workflow = self._require_active_owner(before)
        self._validate_candidate_transition(workflow, candidate)
        workflow_payload = self._json_object(workflow.payload, "workflow payload")
        target_payload = self._target_workflow_payload(workflow_payload, candidate)
        workflow_payload_digest = self._payload_digest(workflow_payload)
        target_workflow_payload_digest = self._payload_digest(target_payload)
        target_workflow_revision = workflow.revision + int(target_payload != workflow_payload)
        trajectory = self._trajectory(before, workflow.owner_actor_id)
        trajectory_digest = self._payload_digest(trajectory)
        artifact = {
            "owner_actor_id": str(workflow.owner_actor_id),
            "schema": self._ARTIFACT_SCHEMA,
            "session_id": str(self._handle.session_id),
            "state": dict(candidate.to_payload()),
            "trajectory": trajectory,
            "trajectory_digest": trajectory_digest,
            "target_workflow_payload_digest": target_workflow_payload_digest,
            "target_workflow_revision": target_workflow_revision,
            "workflow_id": str(self._workflow_id),
            "workflow_payload_digest": workflow_payload_digest,
            "workflow_revision": workflow.revision,
        }
        try:
            receipt = self._artifacts.put_json(artifact)
        except ArtifactStoreError as error:
            raise AdaptiveEvaluationCandidateInvalid(str(error)) from error
        after = self._handle.inspect()
        if after.revision != before.revision:
            raise AdaptiveEvaluationCandidateConflict(
                "process state changed while preparing adaptive evaluation candidate"
            )
        self._require_active_owner(after)
        assignment = {
            "candidate_ref": receipt.reference,
            "goal_fingerprint": candidate.contract.fingerprint,
            "intent_revision": candidate.contract.intent_revision,
            "kind": self._ASSIGNMENT_KIND,
            "source_revision": candidate.contract.source_revision,
            "trajectory_digest": trajectory_digest,
            "target_workflow_payload_digest": target_workflow_payload_digest,
            "target_workflow_revision": target_workflow_revision,
            "workflow_id": str(self._workflow_id),
            "workflow_payload_digest": workflow_payload_digest,
            "workflow_revision": workflow.revision,
        }
        return AdaptiveEvaluationCandidatePreparation(
            candidate_ref=receipt.reference,
            assignment_json=self._canonical_json(assignment),
        )

    def read(self, assignment_json: str) -> AdaptiveControlState:
        """Same-session active direct child가 digest-verified candidate를 typed decode합니다.

        Args:
            assignment_json: `prepare`가 만든 exact canonical assignment string입니다.

        Returns:
            Artifact에 저장됐던 full `AdaptiveControlState` snapshot입니다.

        Raises:
            AdaptiveEvaluationCandidateAuthorityError: Current actor가 active direct child가
                아니면 발생합니다.
            AdaptiveEvaluationCandidateConflict: Artifact read 동안 process revision이
                달라지면 발생합니다.
            AdaptiveEvaluationCandidateInvalid: Assignment, digest, wrapper schema, embedded
                state schema 또는 identity binding이 invalid하면 발생합니다.
        """
        return self.read_candidate(assignment_json).state

    def read_candidate(
        self,
        assignment_json: str,
    ) -> AdaptiveEvaluationCandidateReadback:
        """Direct child가 state와 current bounded material trajectory를 함께 읽습니다.

        Args:
            assignment_json: Owner가 delegation에 등록한 canonical candidate assignment입니다.

        Returns:
            Content-bound adaptive state, trajectory와 candidate reference입니다.

        Raises:
            AdaptiveEvaluationCandidateError: Assignment, authority, freshness 또는 artifact가
                exact current evaluation boundary와 다르면 발생합니다.
        """
        before = self._handle.inspect()
        workflow = self._require_active_child(before)
        assignment = self._decode_assignment(assignment_json)
        self._require_registered_assignment(before, workflow, assignment_json)
        if assignment["workflow_id"] != str(self._workflow_id):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment workflow mismatch"
            )
        artifact = self._candidate_from_assignment(
            assignment,
            workflow.owner_actor_id,
        )
        candidate = artifact.state
        self._validate_candidate_transition(workflow, candidate)
        self._require_source_workflow(workflow, artifact)
        self._require_current_trajectory(before, workflow.owner_actor_id, artifact)
        after = self._handle.inspect()
        if after.revision != before.revision:
            raise AdaptiveEvaluationCandidateConflict(
                "process state changed while reading adaptive evaluation candidate"
            )
        self._require_active_child(after)
        return AdaptiveEvaluationCandidateReadback(
            state=candidate,
            trajectory=dict(artifact.trajectory),
            candidate_ref=artifact.reference,
        )

    def current_trajectory_digest(self) -> str:
        """Owner의 current bounded material trajectory digest를 read-only로 반환합니다.

        Returns:
            Candidate report가 explicit assessment에 사용할 canonical SHA-256입니다.

        Raises:
            AdaptiveEvaluationCandidateAuthorityError: Current actor가 active owner가 아니면
                발생합니다.
            AdaptiveEvaluationCandidateConflict: Readback 도중 process revision이 바뀌면
                발생합니다.
        """
        before = self._handle.inspect()
        workflow = self._require_active_owner(before)
        digest = self._payload_digest(self._trajectory(before, workflow.owner_actor_id))
        after = self._handle.inspect()
        if after.revision != before.revision:
            raise AdaptiveEvaluationCandidateConflict(
                "process state changed while reading adaptive evaluation trajectory"
            )
        self._require_active_owner(after)
        return digest

    def verify_prepared(
        self,
        assignment_json: str,
        expected: AdaptiveControlState,
    ) -> str:
        """Owner가 registered assignment artifact와 proposed final state를 재검증합니다.

        Args:
            assignment_json: Owner가 delegation에 실제 등록한 canonical assignment입니다.
            expected: Persistence 또는 completion authority가 판정할 exact state입니다.

        Returns:
            Exact state artifact의 content-addressed candidate reference입니다.

        Raises:
            AdaptiveEvaluationCandidateAuthorityError: Current actor가 active owner가 아니거나
                assignment가 owner의 delegation에 등록되지 않았으면 발생합니다.
            AdaptiveEvaluationCandidateConflict: Readback 중 process revision이 바뀌거나 같은
                assignment가 둘 이상의 delegation에 재사용되면 발생합니다.
            AdaptiveEvaluationCandidateInvalid: Artifact state가 expected state와 다르면
                발생합니다.
        """
        before = self._handle.inspect()
        workflow = self._require_active_owner(before)
        assignment = self._decode_assignment(assignment_json)
        self._require_owner_registered_assignment(before, workflow, assignment_json)
        if assignment["workflow_id"] != str(self._workflow_id):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment workflow mismatch"
            )
        artifact = self._candidate_from_assignment(
            assignment,
            workflow.owner_actor_id,
        )
        candidate = artifact.state
        self._validate_candidate_transition(workflow, candidate)
        if candidate != expected:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation candidate does not match the expected final state"
            )
        self._require_admission_workflow(workflow, artifact)
        self._require_current_trajectory(before, workflow.owner_actor_id, artifact)
        after = self._handle.inspect()
        if after.revision != before.revision:
            raise AdaptiveEvaluationCandidateConflict(
                "process state changed while verifying adaptive evaluation candidate"
            )
        self._require_active_owner(after)
        return artifact.reference

    def _require_active_owner(self, state: ProcessState) -> WorkflowRecord:
        if state.session.status is not SessionStatus.ACTIVE:
            raise AdaptiveEvaluationCandidateAuthorityError("candidate session is not active")
        actor = state.actors.get(self._handle.actor_id)
        if actor is None or actor.status is not ActorStatus.ACTIVE:
            raise AdaptiveEvaluationCandidateAuthorityError("candidate owner actor is not active")
        workflow = state.workflows.get(self._workflow_id)
        if workflow is None:
            raise AdaptiveEvaluationCandidateAuthorityError("candidate workflow is missing")
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise AdaptiveEvaluationCandidateAuthorityError("candidate workflow is not active")
        if workflow.owner_actor_id != self._handle.actor_id:
            raise AdaptiveEvaluationCandidateAuthorityError(
                "only the active workflow owner can prepare a candidate"
            )
        return workflow

    def _require_registered_assignment(
        self,
        state: ProcessState,
        workflow: WorkflowRecord,
        assignment_json: str,
    ) -> None:
        matches = tuple(
            delegation
            for delegation in state.delegations.values()
            if delegation.owner_actor_id == workflow.owner_actor_id
            and delegation.target_actor_id == self._handle.actor_id
            and delegation.assignment == assignment_json
        )
        if not matches:
            raise AdaptiveEvaluationCandidateAuthorityError(
                "candidate assignment was not issued by the workflow owner"
            )
        if len(matches) != 1:
            raise AdaptiveEvaluationCandidateConflict(
                "candidate assignment must identify exactly one delegation"
            )
        if matches[0].status is not DelegationStatus.PENDING:
            raise AdaptiveEvaluationCandidateAuthorityError(
                "candidate assignment must belong to a pending delegation"
            )
        if matches[0].topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD:
            raise AdaptiveEvaluationCandidateAuthorityError(
                "candidate assignment requires persisted DIRECT_CHILD policy"
            )

    def _require_owner_registered_assignment(
        self,
        state: ProcessState,
        workflow: WorkflowRecord,
        assignment_json: str,
    ) -> None:
        matches = tuple(
            delegation
            for delegation in state.delegations.values()
            if delegation.owner_actor_id == workflow.owner_actor_id
            and delegation.assignment == assignment_json
        )
        if not matches:
            raise AdaptiveEvaluationCandidateAuthorityError(
                "candidate assignment was not registered by the workflow owner"
            )
        if len(matches) != 1:
            raise AdaptiveEvaluationCandidateConflict(
                "candidate assignment must identify exactly one delegation"
            )
        target = state.actors.get(matches[0].target_actor_id)
        if (
            matches[0].topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD
            or target is None
            or target.kind is not ActorKind.SUBAGENT
            or target.parent_actor_id != workflow.owner_actor_id
        ):
            raise AdaptiveEvaluationCandidateAuthorityError(
                "candidate assignment target is not a direct child evaluator"
            )

    def _require_active_child(self, state: ProcessState) -> WorkflowRecord:
        if state.session.status is not SessionStatus.ACTIVE:
            raise AdaptiveEvaluationCandidateAuthorityError("candidate session is not active")
        workflow = state.workflows.get(self._workflow_id)
        if workflow is None or workflow.status is not WorkflowStatus.ACTIVE:
            raise AdaptiveEvaluationCandidateAuthorityError("candidate workflow is not active")
        actor = state.actors.get(self._handle.actor_id)
        if (
            actor is None
            or actor.status is not ActorStatus.ACTIVE
            or actor.kind is not ActorKind.SUBAGENT
            or actor.parent_actor_id != workflow.owner_actor_id
        ):
            raise AdaptiveEvaluationCandidateAuthorityError(
                "candidate reader must be an active direct child of the workflow owner"
            )
        return workflow

    def _decode_assignment(self, assignment_json: str) -> dict[str, object]:
        if not isinstance(assignment_json, str) or not assignment_json:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment must be non-empty JSON"
            )
        try:
            decoded: object = json.loads(
                assignment_json,
                object_pairs_hook=self._unique_object,
            )
        except (json.JSONDecodeError, AdaptiveEvaluationCandidateInvalid) as error:
            if isinstance(error, AdaptiveEvaluationCandidateInvalid):
                raise
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment is not valid JSON"
            ) from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment must be a JSON object"
            )
        assignment = {str(key): value for key, value in decoded.items()}
        if frozenset(assignment) != self._ASSIGNMENT_FIELDS:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment fields do not match its schema"
            )
        if assignment_json != self._canonical_json(assignment):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment must use canonical JSON"
            )
        if assignment.get("kind") != self._ASSIGNMENT_KIND:
            raise AdaptiveEvaluationCandidateInvalid("adaptive evaluation assignment kind mismatch")
        intent_revision = assignment.get("intent_revision")
        if (
            not isinstance(intent_revision, int)
            or isinstance(intent_revision, bool)
            or intent_revision < 1
        ):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation intent revision must be positive"
            )
        for field in ("candidate_ref", "goal_fingerprint", "source_revision", "workflow_id"):
            value = assignment.get(field)
            if not isinstance(value, str) or not value.strip():
                raise AdaptiveEvaluationCandidateInvalid(
                    f"adaptive evaluation assignment {field} must be non-empty text"
                )
        for field in ("workflow_revision", "target_workflow_revision"):
            value = assignment.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise AdaptiveEvaluationCandidateInvalid(
                    f"adaptive evaluation assignment {field} must be non-negative"
                )
        for field in ("workflow_payload_digest", "target_workflow_payload_digest"):
            value = assignment.get(field)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise AdaptiveEvaluationCandidateInvalid(
                    f"adaptive evaluation assignment {field} must be SHA-256"
                )
        self._digest(
            assignment.get("trajectory_digest"),
            "assignment trajectory_digest",
        )
        return assignment

    def _decode_artifact(
        self,
        artifact: Mapping[str, object],
        owner_actor_id: object,
        reference: str,
    ) -> _AdaptiveEvaluationCandidateArtifact:
        if frozenset(artifact) != self._ARTIFACT_FIELDS:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation candidate fields do not match its schema"
            )
        expected_identity = {
            "owner_actor_id": str(owner_actor_id),
            "schema": self._ARTIFACT_SCHEMA,
            "session_id": str(self._handle.session_id),
            "workflow_id": str(self._workflow_id),
        }
        if any(artifact.get(key) != value for key, value in expected_identity.items()):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation candidate identity or schema mismatch"
            )
        state_payload = artifact.get("state")
        if not isinstance(state_payload, Mapping) or any(
            not isinstance(key, str) for key in state_payload
        ):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation candidate state must be an object"
            )
        workflow_revision = self._non_negative_integer(
            artifact.get("workflow_revision"),
            "candidate workflow_revision",
        )
        target_workflow_revision = self._non_negative_integer(
            artifact.get("target_workflow_revision"),
            "candidate target_workflow_revision",
        )
        if target_workflow_revision not in {workflow_revision, workflow_revision + 1}:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation target workflow revision must stay or advance by one"
            )
        workflow_payload_digest = self._digest(
            artifact.get("workflow_payload_digest"),
            "candidate workflow_payload_digest",
        )
        target_workflow_payload_digest = self._digest(
            artifact.get("target_workflow_payload_digest"),
            "candidate target_workflow_payload_digest",
        )
        trajectory_payload = artifact.get("trajectory")
        if not isinstance(trajectory_payload, Mapping) or any(
            not isinstance(key, str) for key in trajectory_payload
        ):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation trajectory must be an object"
            )
        trajectory = self._json_object(trajectory_payload, "trajectory")
        if frozenset(trajectory) != {"schema", "material_action"} or (
            trajectory.get("schema") != self._TRAJECTORY_SCHEMA
        ):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation trajectory schema is invalid"
            )
        material_action = trajectory.get("material_action")
        if material_action is not None and not isinstance(material_action, Mapping):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation material trajectory must be an object or null"
            )
        trajectory_digest = self._digest(
            artifact.get("trajectory_digest"),
            "candidate trajectory_digest",
        )
        if trajectory_digest != self._payload_digest(trajectory):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation trajectory digest does not match its payload"
            )
        if (
            target_workflow_revision == workflow_revision
            and target_workflow_payload_digest != workflow_payload_digest
        ):
            raise AdaptiveEvaluationCandidateInvalid(
                "no-op adaptive candidate must preserve its workflow payload digest"
            )
        try:
            state = AdaptiveControlState.from_payload(state_payload)
        except InvalidAdaptiveControlState as error:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation candidate state schema is invalid"
            ) from error
        return _AdaptiveEvaluationCandidateArtifact(
            state=state,
            reference=reference,
            workflow_revision=workflow_revision,
            target_workflow_revision=target_workflow_revision,
            workflow_payload_digest=workflow_payload_digest,
            target_workflow_payload_digest=target_workflow_payload_digest,
            trajectory=trajectory,
            trajectory_digest=trajectory_digest,
        )

    def _candidate_from_assignment(
        self,
        assignment: Mapping[str, object],
        owner_actor_id: object,
    ) -> _AdaptiveEvaluationCandidateArtifact:
        reference = assignment.get("candidate_ref")
        if not isinstance(reference, str):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation candidate_ref must be text"
            )
        try:
            artifact = self._artifacts.read_json(reference)
        except ArtifactStoreError as error:
            raise AdaptiveEvaluationCandidateInvalid(str(error)) from error
        candidate = self._decode_artifact(artifact, owner_actor_id, reference)
        self._verify_assignment(assignment, candidate)
        return candidate

    def _verify_assignment(
        self,
        assignment: Mapping[str, object],
        artifact: _AdaptiveEvaluationCandidateArtifact,
    ) -> None:
        candidate = artifact.state
        expected = {
            "candidate_ref": artifact.reference,
            "goal_fingerprint": candidate.contract.fingerprint,
            "intent_revision": candidate.contract.intent_revision,
            "kind": self._ASSIGNMENT_KIND,
            "source_revision": candidate.contract.source_revision,
            "trajectory_digest": artifact.trajectory_digest,
            "target_workflow_payload_digest": artifact.target_workflow_payload_digest,
            "target_workflow_revision": artifact.target_workflow_revision,
            "workflow_id": str(self._workflow_id),
            "workflow_payload_digest": artifact.workflow_payload_digest,
            "workflow_revision": artifact.workflow_revision,
        }
        if dict(assignment) != expected:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation assignment does not match its typed candidate"
            )

    def _require_source_workflow(
        self,
        workflow: WorkflowRecord,
        artifact: _AdaptiveEvaluationCandidateArtifact,
    ) -> None:
        if (
            workflow.revision != artifact.workflow_revision
            or self._payload_digest(workflow.payload) != artifact.workflow_payload_digest
        ):
            raise AdaptiveEvaluationCandidateConflict(
                "adaptive evaluation candidate source workflow revision is stale"
            )

    def _require_admission_workflow(
        self,
        workflow: WorkflowRecord,
        artifact: _AdaptiveEvaluationCandidateArtifact,
    ) -> None:
        current_digest = self._payload_digest(workflow.payload)
        if (
            workflow.revision == artifact.workflow_revision
            and current_digest == artifact.workflow_payload_digest
        ):
            return
        if (
            workflow.revision != artifact.target_workflow_revision
            or current_digest != artifact.target_workflow_payload_digest
            or not self._is_exact_adaptive_transition(workflow, artifact)
        ):
            raise AdaptiveEvaluationCandidateConflict(
                "adaptive evaluation candidate does not own the current workflow revision"
            )

    def _require_current_trajectory(
        self,
        state: ProcessState,
        owner_actor_id: ActorId,
        artifact: _AdaptiveEvaluationCandidateArtifact,
    ) -> None:
        current = self._trajectory(state, owner_actor_id)
        if self._payload_digest(current) != artifact.trajectory_digest:
            raise AdaptiveEvaluationCandidateConflict(
                "adaptive evaluation material trajectory changed after candidate preparation"
            )

    def _trajectory(
        self,
        state: ProcessState,
        owner_actor_id: ActorId,
    ) -> dict[str, object]:
        batch = state.material_actions.get(owner_actor_id)
        return self._json_object(
            {
                "schema": self._TRAJECTORY_SCHEMA,
                "material_action": None if batch is None else batch.to_payload(),
            },
            "trajectory",
        )

    def _is_exact_adaptive_transition(
        self,
        workflow: WorkflowRecord,
        artifact: _AdaptiveEvaluationCandidateArtifact,
    ) -> bool:
        if artifact.target_workflow_revision == artifact.workflow_revision:
            return artifact.target_workflow_payload_digest == artifact.workflow_payload_digest
        key = workflow.last_transition_idempotency_key
        if key is None:
            return False
        expected = (
            rf"skill-state:{re.escape(str(self._workflow_id))}:[0-9a-f]{{32}}:"
            rf"{artifact.workflow_revision}:{artifact.target_workflow_payload_digest}"
        )
        return re.fullmatch(expected, key) is not None

    def _target_workflow_payload(
        self,
        workflow_payload: Mapping[str, object],
        candidate: AdaptiveControlState,
    ) -> dict[str, object]:
        skill_state = workflow_payload.get("skill_state")
        if not isinstance(skill_state, Mapping) or any(
            not isinstance(key, str) for key in skill_state
        ):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive candidate workflow skill_state must be an object"
            )
        return {
            **workflow_payload,
            "skill_state": {
                **skill_state,
                "adaptive_control": dict(candidate.to_payload()),
            },
        }

    def _validate_candidate_transition(
        self,
        workflow: WorkflowRecord,
        candidate: AdaptiveControlState,
    ) -> None:
        """Initial workflow goal 또는 current typed contract에서의 전이를 검증합니다."""
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, Mapping):
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive candidate workflow skill_state must be an object"
            )
        raw_current = skill_state.get("adaptive_control")
        if raw_current is None:
            if workflow.goal != candidate.contract.goal:
                raise AdaptiveEvaluationCandidateInvalid(
                    "adaptive candidate goal does not match its initial workflow goal"
                )
            previous = None
            allow_goal_override = False
        else:
            if not isinstance(raw_current, Mapping):
                raise AdaptiveEvaluationCandidateInvalid(
                    "workflow adaptive_control snapshot must be an object"
                )
            try:
                previous = AdaptiveControlState.from_payload(raw_current)
            except InvalidAdaptiveControlState as error:
                raise AdaptiveEvaluationCandidateInvalid(
                    "current workflow adaptive_control snapshot is invalid"
                ) from error
            allow_goal_override = previous.contract.fingerprint != candidate.contract.fingerprint
        try:
            validate_adaptive_control_transition(
                previous,
                candidate,
                allow_goal_override=allow_goal_override,
            )
        except InvalidAdaptiveControlState as error:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive candidate is not a valid current-goal transition"
            ) from error

    def _payload_digest(self, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(self._canonical_json(payload).encode()).hexdigest()

    def _json_object(
        self,
        payload: Mapping[str, object],
        label: str,
    ) -> dict[str, object]:
        try:
            decoded: object = json.loads(self._canonical_json(payload))
        except json.JSONDecodeError as error:  # pragma: no cover - json.dumps invariant
            raise AdaptiveEvaluationCandidateInvalid(
                f"adaptive evaluation {label} is not JSON-compatible"
            ) from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise AdaptiveEvaluationCandidateInvalid(
                f"adaptive evaluation {label} must be a string-keyed object"
            )
        return {str(key): value for key, value in decoded.items()}

    def _non_negative_integer(self, value: object, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AdaptiveEvaluationCandidateInvalid(f"adaptive evaluation {label} is invalid")
        return value

    def _digest(self, value: object, label: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise AdaptiveEvaluationCandidateInvalid(f"adaptive evaluation {label} is invalid")
        return value

    def _unique_object(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded:
                raise AdaptiveEvaluationCandidateInvalid(
                    f"adaptive evaluation JSON has duplicate key: {key}"
                )
            decoded[key] = value
        return decoded

    def _canonical_json(self, payload: Mapping[str, object]) -> str:
        try:
            return json.dumps(
                dict(payload),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise AdaptiveEvaluationCandidateInvalid(
                "adaptive evaluation payload is not canonical JSON"
            ) from error
