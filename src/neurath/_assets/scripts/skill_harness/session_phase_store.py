"""Phase runner projection을 exact session workflow namespace에 보존합니다."""

from collections.abc import Mapping
from pathlib import Path

from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityError,
    AdaptiveControlAuthorityVerifier,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlStore,
    AdaptiveControlStoreError,
)
from scripts.agent_harness.delegation_evidence import (
    ConsumedDelegationEvidenceReader,
    ConsumedDelegationEvidenceSnapshot,
    FinalReviewEvidencePolicy,
    FinalReviewVerification,
)
from scripts.agent_harness.evaluation_admission import EvaluationAdmissionPolicy
from scripts.agent_harness.harness_incident import (
    validate_harness_incidents as validate_session_harness_incidents,
)
from scripts.agent_harness.session_kernel import (
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowId,
    WorkflowRecord,
    WorkflowStarted,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import StateHandle
from scripts.agent_harness.workflow_terminal import WorkflowTerminalPolicy
from scripts.skill_harness.phase_runner import (
    TERMINAL_PHASE_STATUSES,
    AdaptiveControlPhaseReadback,
    AdaptiveControlTransitionReadback,
    PhaseRunnerError,
    PhaseRunState,
    PhaseRunStore,
)


class SessionPhaseStoreError(PhaseRunnerError):
    """Session-scoped phase projection contract 위반의 base error입니다."""

    def __init__(self, message: str) -> None:
        """Phase runner가 JSON error로 반환할 stable code를 결합합니다.

        Args:
            message: Session workflow state 위반의 구체적인 설명입니다.
        """
        super().__init__("STATE_INVALID", message)


class PhaseStateMissingError(SessionPhaseStoreError):
    """선택한 exact workflow 또는 phase namespace가 없을 때 발생합니다."""

    def __init__(self, message: str) -> None:
        """Missing state를 다른 integrity 위반과 구분합니다.

        Args:
            message: 누락된 workflow 또는 namespace 설명입니다.
        """
        PhaseRunnerError.__init__(self, "STATE_MISSING", message)


class PhaseStateIdentityError(SessionPhaseStoreError):
    """Workflow owner, skill, run, goal identity가 selector와 다를 때 발생합니다."""


class PhaseStateIntegrityError(SessionPhaseStoreError):
    """Persisted phase payload와 workflow lifecycle의 shape가 유효하지 않을 때 발생합니다."""


class PhaseStateTerminalError(SessionPhaseStoreError):
    """Terminal workflow에 추가 transition을 요청할 때 발생합니다."""


class PhaseWorkflowConflict(SessionPhaseStoreError):
    """Caller가 읽은 workflow-local revision이 canonical revision과 다를 때 발생합니다."""

    def __init__(self, message: str) -> None:
        """Stale optimistic writer를 stable conflict code로 표현합니다.

        Args:
            message: Expected/current workflow revision 설명입니다.
        """
        PhaseRunnerError.__init__(self, "STATE_CONFLICT", message)


class PhaseStateSnapshot:
    """Phase projection과 workflow-local optimistic revision을 함께 고정합니다."""

    __slots__ = ("state", "workflow_revision", "workflow_status")

    def __init__(
        self,
        state: PhaseRunState,
        workflow_revision: int,
        workflow_status: WorkflowStatus,
    ) -> None:
        """한 번 읽은 phase projection과 CAS key를 immutable하게 보관합니다.

        Args:
            state: Phase runner가 해석하는 현재 operational projection입니다.
            workflow_revision: 다음 advance/finalize가 명시적으로 제출할 원본 revision입니다.
            workflow_status: Workflow aggregate의 active 또는 terminal lifecycle입니다.
        """
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "workflow_revision", workflow_revision)
        object.__setattr__(self, "workflow_status", workflow_status)

    state: PhaseRunState
    """Workflow payload의 `phase_run` namespace에서 decode한 현재 phase state입니다."""

    workflow_revision: int
    """Session revision과 독립적으로 stale phase writer를 fencing하는 CAS key입니다."""

    workflow_status: WorkflowStatus
    """Workflow가 추가 phase transition을 받을 수 있는지 나타내는 lifecycle입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 snapshot의 attribute 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: Attribute에 대입하려 한 값입니다.

        Raises:
            AttributeError: Snapshot은 생성 뒤 항상 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class SessionPhaseStateStore:
    """StateHandle과 WorkflowId로 단일 phase projection을 선택하는 optimistic store입니다.

    Store는 충돌을 내부에서 재시도하지 않습니다. Phase transition은 latest state에서 다시
    계산해야 의미가 보존되므로 stale revision은 `PhaseWorkflowConflict`로 caller에게
    반환합니다. Session 전체에서 발생한 unrelated CAS 충돌만 `StateHandle`의 bounded
    retry가 처리합니다.
    """

    _PHASE_NAMESPACE = "phase_run"

    def __init__(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        skill: str,
        run_id: str,
    ) -> None:
        """Exact session workflow와 persisted phase identity를 고정합니다.

        Args:
            handle: Runtime이 검증한 exact session과 actor authority입니다.
            workflow_id: 같은 session 안에서 phase run을 소유할 workflow identity입니다.
            skill: Workflow kind와 phase payload가 반드시 공유할 skill identity입니다.
            run_id: Persisted `PhaseRunState.run_id`가 반드시 일치해야 하는 identity입니다.

        Raises:
            PhaseStateIdentityError: Skill 또는 run identity가 비어 있으면 발생합니다.
        """
        if not skill.strip():
            raise PhaseStateIdentityError("phase store skill must be non-empty")
        if not run_id.strip():
            raise PhaseStateIdentityError("phase store run identity must be non-empty")
        self._handle = handle
        self._workflow_id = workflow_id
        self._skill = skill.strip()
        self._run_id = run_id.strip()

    @property
    def workflow_id(self) -> WorkflowId:
        """Store가 선택한 exact workflow identity를 반환합니다.

        Returns:
            StateHandle의 bound session 안에서만 해석되는 workflow identity입니다.
        """
        return self._workflow_id

    @property
    def skill(self) -> str:
        """Workflow kind와 phase payload에 요구하는 skill identity를 반환합니다.

        Returns:
            생성 시 공백을 제거해 고정한 skill identity입니다.
        """
        return self._skill

    @property
    def run_id(self) -> str:
        """Phase payload에 요구하는 run identity를 반환합니다.

        Returns:
            생성 시 공백을 제거해 고정한 phase-run identity입니다.
        """
        return self._run_id

    def initialize(self, state: PhaseRunState) -> PhaseStateSnapshot:
        """WorkflowStarted로 namespaced initial phase projection을 생성합니다.

        Args:
            state: Selector와 같은 skill/run을 가진 non-terminal initial phase state입니다.

        Returns:
            Revision zero의 active workflow와 round-trip한 phase snapshot입니다.

        Raises:
            PhaseStateIdentityError: State의 skill/run이 selector와 다르면 발생합니다.
            PhaseStateTerminalError: 이미 terminal인 state를 초기화하면 발생합니다.
            TransitionRejected: Workflow identity가 다른 aggregate에 이미 사용됐으면
                발생합니다.
        """
        phase_payload = self._encode(state)
        if state.terminal_state is not None:
            raise PhaseStateTerminalError("cannot initialize a terminal phase state")
        if state.adaptive_control_required:
            admission = EvaluationAdmissionPolicy().inspect(
                self._handle.inspect(),
                self._handle.actor_id,
            )
            if admission["status"] == "unavailable":
                raise PhaseRunnerError(
                    "EVALUATOR_UNAVAILABLE",
                    "no current host-attested direct child evaluator; retain a state-free review "
                    "and retry init after host registration; no workflow was created",
                )
        process_state = self._handle.apply(
            WorkflowStarted(
                session_id=self._handle.session_id,
                workflow_id=self._workflow_id,
                owner_actor_id=self._handle.actor_id,
                kind=self._skill,
                goal=state.north_star,
                payload={
                    self._PHASE_NAMESPACE: phase_payload,
                    "skill_state": {},
                },
                idempotency_key=f"phase-store:initialize:{self._workflow_id}",
            )
        )
        return self._decode(process_state.workflows[self._workflow_id])

    def read(self) -> PhaseStateSnapshot:
        """Bound session의 exact workflow에서 latest phase projection을 읽습니다.

        Returns:
            다른 workflow payload namespace를 노출하지 않는 phase snapshot입니다.

        Raises:
            PhaseStateMissingError: Exact workflow 또는 phase namespace가 없으면 발생합니다.
            PhaseStateIdentityError: Workflow identity가 selector와 다르면 발생합니다.
            PhaseStateIntegrityError: Persisted payload 또는 lifecycle이 invalid하면
                발생합니다.
        """
        return self._decode(self._current_workflow())

    def read_skill_state(self) -> Mapping[str, object]:
        """같은 workflow payload의 skill_state namespace를 read-only object로 반환합니다.

        Returns:
            Phase transition과 sibling으로 보존되는 current operational state입니다.

        Raises:
            PhaseStateIntegrityError: Namespace가 JSON object가 아니면 발생합니다.
        """
        workflow = self._current_workflow()
        raw_state = workflow.payload.get("skill_state")
        if not isinstance(raw_state, dict) or any(not isinstance(key, str) for key in raw_state):
            raise PhaseStateIntegrityError("skill_state namespace must be a string-keyed object")
        return {str(key): value for key, value in raw_state.items()}

    def verify_adaptive_control_evidence(
        self,
        evidence: Mapping[str, object],
    ) -> AdaptiveControlPhaseReadback:
        """Submitted receipt와 current external authority를 exact workflow에서 재검증합니다.

        Args:
            evidence: Current adaptive receipt라고 제출된 canonical JSON object입니다.

        Returns:
            Current persisted receipt, external authority, goal을 묶은 read-back입니다.

        Raises:
            AdaptiveControlStoreError: Receipt와 current contract revision이 다르면 발생합니다.
        """
        adaptive = AdaptiveControlStore(SkillStateStore(self._handle, self._workflow_id))
        receipt = adaptive.verify_evidence(evidence)
        snapshot = adaptive.read()
        if (
            snapshot.workflow_revision != receipt.workflow_revision
            or snapshot.state.contract.fingerprint != receipt.goal_fingerprint
        ):
            raise AdaptiveControlStoreError(
                "adaptive contract changed while reading phase evidence"
            )
        authority = AdaptiveControlAuthorityVerifier(
            self._handle,
            self._workflow_id,
        ).verify()
        return AdaptiveControlPhaseReadback(
            receipt=receipt,
            authority=authority,
            contract_goal=snapshot.state.contract.goal,
        )

    def read_adaptive_control_transition(self) -> AdaptiveControlTransitionReadback:
        """한 workflow revision의 decision, authority, criterion metadata를 읽습니다.

        Returns:
            Current decision과 exact authority 및 immutable criterion metadata입니다.

        Raises:
            AdaptiveControlStoreError: Read 중 authority revision이 바뀌면 발생합니다.
        """
        snapshot = AdaptiveControlStore(SkillStateStore(self._handle, self._workflow_id)).read()
        authority = AdaptiveControlAuthorityVerifier(
            self._handle,
            self._workflow_id,
        ).verify()
        if (
            authority.workflow_id != snapshot.workflow_id
            or authority.workflow_revision != snapshot.workflow_revision
            or authority.goal_fingerprint != snapshot.state.contract.fingerprint
        ):
            raise AdaptiveControlStoreError(
                "adaptive authority changed while reading phase transition"
            )
        return AdaptiveControlTransitionReadback(
            receipt=snapshot.receipt(),
            authority=authority,
            contract_goal=snapshot.state.contract.goal,
            criteria=snapshot.state.contract.criteria,
            blocker_gap_ids=tuple(
                sorted(
                    gap.gap_id
                    for gap in snapshot.state.inventory.gaps
                    if gap.is_blocked_for(snapshot.state.inventory)
                )
            ),
            execution_status=snapshot.state.execution_status,
        )

    def read_review_evidence(
        self,
        expected_kind: str,
        reviewed_head_sha: str,
        *,
        delegation_id: str | None = None,
    ) -> tuple[ConsumedDelegationEvidenceSnapshot, FinalReviewVerification]:
        """Exact workflow의 consumed review result를 단일 shared policy로 검증합니다.

        Args:
            expected_kind: Phase contract가 요구하는 exact review delegation kind입니다.
            reviewed_head_sha: Assignment가 고정한 exact commit입니다.

        Returns:
            Digest-verified snapshot과 canonical review verification입니다.
        """
        snapshot = ConsumedDelegationEvidenceReader(
            self._handle,
            self._workflow_id,
        ).read(
            kind=expected_kind,
            reviewed_head_sha=reviewed_head_sha,
            delegation_id=delegation_id,
        )
        verification = FinalReviewEvidencePolicy().verify(
            snapshot,
            expected_kind=expected_kind,
        )
        return snapshot, verification

    def read_consumed_delegation_evidence(
        self,
        expected_kind: str,
        reviewed_head_sha: str,
    ) -> ConsumedDelegationEvidenceSnapshot:
        """Direct-child evaluator의 consumed artifact를 exact workflow에서 읽습니다.

        Args:
            expected_kind: Phase가 요구하는 exact delegation kind입니다.
            reviewed_head_sha: Assignment가 결속한 exact commit입니다.

        Returns:
            Exact workflow와 direct-child topology에 결속된 immutable snapshot입니다.
        """
        return ConsumedDelegationEvidenceReader(
            self._handle,
            self._workflow_id,
        ).read(
            kind=expected_kind,
            reviewed_head_sha=reviewed_head_sha,
        )

    def validate_harness_incidents(self, worktree: Path) -> None:
        """Bound StateHandle이 읽은 typed incident projection만 terminal gate에 전달합니다.

        Args:
            worktree: Resolution evidence가 결속된 repository root입니다.
        """
        validate_session_harness_incidents(self._handle.inspect(), worktree)

    def advance(
        self,
        state: PhaseRunState,
        expected_workflow_revision: int,
    ) -> PhaseStateSnapshot:
        """WorkflowAdvanced로 phase namespace만 optimistic CAS 갱신합니다.

        Args:
            state: Latest phase snapshot에서 계산한 non-terminal replacement projection입니다.
            expected_workflow_revision: Caller가 원본 snapshot에서 읽은 workflow revision입니다.

        Returns:
            Sibling namespace를 보존하고 phase projection만 교체한 next snapshot입니다.

        Raises:
            PhaseWorkflowConflict: Canonical workflow revision이 원본과 다르면 발생합니다.
            PhaseStateTerminalError: State 또는 canonical workflow가 terminal이면 발생합니다.
            PhaseStateIdentityError: State의 skill/run이 selector와 다르면 발생합니다.
        """
        phase_payload = self._encode(state)
        if state.terminal_state is not None:
            raise PhaseStateTerminalError("terminal phase state requires finalize")
        workflow = self._active_workflow(expected_workflow_revision)
        payload = dict(workflow.payload)
        payload[self._PHASE_NAMESPACE] = phase_payload
        event = WorkflowAdvanced(
            session_id=self._handle.session_id,
            workflow_id=self._workflow_id,
            actor_id=self._handle.actor_id,
            expected_workflow_revision=expected_workflow_revision,
            payload=payload,
            idempotency_key=(
                f"phase-store:advance:{self._workflow_id}:{expected_workflow_revision}"
            ),
        )
        return self._apply_transition(event, expected_workflow_revision)

    def finalize(
        self,
        state: PhaseRunState,
        expected_workflow_revision: int,
    ) -> PhaseStateSnapshot:
        """WorkflowFinalized로 phase namespace와 terminal lifecycle을 함께 commit합니다.

        Args:
            state: `terminal_state`가 기록된 final phase projection입니다.
            expected_workflow_revision: Caller가 원본 snapshot에서 읽은 workflow revision입니다.

        Returns:
            Sibling namespace를 보존한 completed 또는 failed terminal snapshot입니다.

        Raises:
            PhaseWorkflowConflict: Canonical workflow revision이 원본과 다르면 발생합니다.
            PhaseStateTerminalError: Final state에 terminal marker가 없거나 workflow가 이미
                terminal이면 발생합니다.
            PhaseStateIdentityError: State의 skill/run이 selector와 다르면 발생합니다.
        """
        phase_payload = self._encode(state)
        if state.terminal_state is None:
            raise PhaseStateTerminalError("final phase state must declare terminal_state")
        workflow = self._active_workflow(expected_workflow_revision)
        payload = dict(workflow.payload)
        payload[self._PHASE_NAMESPACE] = phase_payload
        terminal_status = self._terminal_status(state.terminal_state)
        if terminal_status is WorkflowStatus.COMPLETED:
            self._validate_adaptive_completion(
                workflow,
                required=state.adaptive_control_required,
            )
        event = WorkflowFinalized(
            session_id=self._handle.session_id,
            workflow_id=self._workflow_id,
            actor_id=self._handle.actor_id,
            expected_workflow_revision=expected_workflow_revision,
            terminal_status=terminal_status,
            payload=payload,
            idempotency_key=(
                f"phase-store:finalize:{self._workflow_id}:{expected_workflow_revision}"
            ),
        )
        return self._apply_transition(event, expected_workflow_revision)

    def _validate_adaptive_completion(
        self,
        workflow: WorkflowRecord,
        *,
        required: bool,
    ) -> None:
        """Adaptive namespace가 있는 success finalization을 current authority로 닫습니다."""
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, Mapping) or "adaptive_control" not in skill_state:
            if required:
                raise PhaseStateTerminalError(
                    "adaptive-required workflow has no adaptive control state"
                )
            return
        try:
            AdaptiveControlAuthorityVerifier(
                self._handle,
                self._workflow_id,
            ).verify_completion(workflow.revision)
        except AdaptiveControlAuthorityError as error:
            raise PhaseStateTerminalError("adaptive completion authority is invalid") from error

    def _current_workflow(self) -> WorkflowRecord:
        workflow = self._handle.inspect().workflows.get(self._workflow_id)
        if workflow is None:
            raise PhaseStateMissingError(f"phase workflow is missing: {self._workflow_id}")
        return workflow

    def _active_workflow(self, expected_workflow_revision: int) -> WorkflowRecord:
        workflow = self._current_workflow()
        self._decode(workflow)
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise PhaseStateTerminalError(f"phase workflow is terminal: {self._workflow_id}")
        if workflow.revision != expected_workflow_revision:
            raise PhaseWorkflowConflict(
                f"expected workflow revision {expected_workflow_revision}, got {workflow.revision}"
            )
        return workflow

    def _apply_transition(
        self,
        event: WorkflowAdvanced | WorkflowFinalized,
        expected_workflow_revision: int,
    ) -> PhaseStateSnapshot:
        try:
            process_state = self._handle.apply(event)
        except TransitionRejected as error:
            latest = self._current_workflow()
            if latest.status is not WorkflowStatus.ACTIVE:
                raise PhaseStateTerminalError(
                    f"phase workflow became terminal: {self._workflow_id}"
                ) from error
            if latest.revision != expected_workflow_revision:
                raise PhaseWorkflowConflict(
                    f"expected workflow revision {expected_workflow_revision}, "
                    f"got {latest.revision}"
                ) from error
            raise
        return self._decode(process_state.workflows[self._workflow_id])

    def _decode(self, workflow: WorkflowRecord) -> PhaseStateSnapshot:
        if workflow.owner_actor_id != self._handle.actor_id:
            raise PhaseStateIdentityError("phase workflow owner does not match bound actor")
        if workflow.kind != self._skill:
            raise PhaseStateIdentityError(
                f"phase workflow skill is {workflow.kind}, expected {self._skill}"
            )
        raw_phase = workflow.payload.get(self._PHASE_NAMESPACE)
        if raw_phase is None:
            raise PhaseStateMissingError("workflow payload has no phase_run namespace")
        if not isinstance(raw_phase, dict) or any(not isinstance(key, str) for key in raw_phase):
            raise PhaseStateIntegrityError("phase_run namespace must be a string-keyed object")
        phase_payload: dict[str, object] = dict(raw_phase)
        if phase_payload.get("schema_version") != 1:
            raise PhaseStateIntegrityError("phase_run schema_version must be 1")
        try:
            state = PhaseRunState.from_payload(phase_payload)
        except PhaseRunnerError as error:
            raise PhaseStateIntegrityError("phase_run namespace is invalid") from error
        canonical_payload = state.as_payload()
        if "adaptive_control_required" not in phase_payload:
            legacy_canonical = dict(canonical_payload)
            legacy_canonical.pop("adaptive_control_required")
            payload_is_canonical = legacy_canonical == phase_payload
        else:
            payload_is_canonical = canonical_payload == phase_payload
        if not payload_is_canonical:
            raise PhaseStateIntegrityError("phase_run namespace is not canonical")
        self._validate_phase_identity(state)
        if workflow.goal != state.north_star:
            raise PhaseStateIdentityError("workflow goal and phase north star do not match")
        self._validate_lifecycle(workflow.status, state.terminal_state)
        if workflow.status is not WorkflowStatus.ACTIVE:
            try:
                WorkflowTerminalPolicy().validate_phase(
                    workflow.payload,
                    workflow.payload,
                    completed=workflow.status is WorkflowStatus.COMPLETED,
                )
            except ValueError as error:
                raise PhaseStateIntegrityError(str(error)) from error
        return PhaseStateSnapshot(state, workflow.revision, workflow.status)

    def _encode(self, state: PhaseRunState) -> dict[str, object]:
        self._validate_phase_identity(state)
        payload = state.as_payload()
        try:
            decoded = PhaseRunState.from_payload(payload)
        except PhaseRunnerError as error:
            raise PhaseStateIntegrityError("phase state cannot be encoded canonically") from error
        if decoded.as_payload() != payload:
            raise PhaseStateIntegrityError("phase state encoding would lose information")
        return payload

    def _validate_phase_identity(self, state: PhaseRunState) -> None:
        if state.skill != self._skill:
            raise PhaseStateIdentityError(
                f"phase state skill is {state.skill}, expected {self._skill}"
            )
        if state.run_id != self._run_id:
            raise PhaseStateIdentityError(
                f"phase state run is {state.run_id}, expected {self._run_id}"
            )

    def _validate_lifecycle(
        self,
        workflow_status: WorkflowStatus,
        terminal_state: str | None,
    ) -> None:
        if workflow_status is WorkflowStatus.ACTIVE:
            if terminal_state is not None:
                raise PhaseStateIntegrityError(
                    "active workflow cannot contain a terminal phase state"
                )
            return
        if terminal_state is None:
            raise PhaseStateIntegrityError("terminal workflow must contain terminal phase state")
        expected_status = self._terminal_status(terminal_state)
        if workflow_status is not expected_status:
            raise PhaseStateIntegrityError("workflow status does not match phase terminal state")

    def _terminal_status(self, terminal_state: str) -> WorkflowStatus:
        if terminal_state in TERMINAL_PHASE_STATUSES:
            return WorkflowStatus.FAILED
        return WorkflowStatus.COMPLETED


class SessionPhaseRunnerStore(PhaseRunStore):
    """기존 PhaseRunner의 read/write port를 session workflow CAS에 연결합니다.

    Adapter는 같은 command 안에서 `read()`한 workflow revision만 다음 `write()`에
    사용합니다. Stale 계산 결과를 latest state에 자동 재적용하지 않으며 underlying
    `PhaseWorkflowConflict`를 그대로 노출합니다.
    """

    def __init__(self, store: SessionPhaseStateStore) -> None:
        """Exact phase store를 runner-compatible port로 감쌉니다.

        Args:
            store: StateHandle과 workflow identity에 이미 고정된 phase store입니다.
        """
        self._store = store
        self._last_snapshot: PhaseStateSnapshot | None = None

    @classmethod
    def open_existing(
        cls,
        handle: StateHandle,
        workflow_id: WorkflowId,
    ) -> SessionPhaseRunnerStore:
        """Persisted workflow payload에서 skill과 run identity를 검증해 adapter를 엽니다.

        Args:
            handle: Runtime이 검증한 exact session/actor authority입니다.
            workflow_id: 재개할 phase workflow identity입니다.

        Returns:
            Manual state path 없이 existing workflow에 고정된 runner store입니다.

        Raises:
            PhaseStateMissingError: Workflow 또는 phase namespace가 없으면 발생합니다.
            PhaseStateIntegrityError: Phase namespace를 decode할 수 없으면 발생합니다.
        """
        workflow = handle.inspect().workflows.get(workflow_id)
        if workflow is None:
            raise PhaseStateMissingError(f"phase workflow is missing: {workflow_id}")
        raw_phase = workflow.payload.get(SessionPhaseStateStore._PHASE_NAMESPACE)
        if not isinstance(raw_phase, dict) or any(not isinstance(key, str) for key in raw_phase):
            raise PhaseStateIntegrityError("phase_run namespace must be a string-keyed object")
        try:
            phase_state = PhaseRunState.from_payload(dict(raw_phase))
        except PhaseRunnerError as error:
            raise PhaseStateIntegrityError("phase_run namespace is invalid") from error
        adapter = cls(
            SessionPhaseStateStore(
                handle=handle,
                workflow_id=workflow_id,
                skill=workflow.kind,
                run_id=phase_state.run_id,
            )
        )
        adapter._store.read()
        return adapter

    def read(self) -> PhaseRunState:
        """Latest phase state를 읽고 다음 write의 workflow revision을 고정합니다.

        Returns:
            PhaseRunner가 현재 phase를 계산할 immutable projection입니다.
        """
        snapshot = self._store.read()
        self._last_snapshot = snapshot
        return snapshot.state

    def write(self, state: PhaseRunState) -> None:
        """Initialize 또는 직전 read에 대응하는 optimistic transition을 commit합니다.

        Args:
            state: PhaseRunner가 initial/current projection에서 계산한 replacement입니다.

        Raises:
            PhaseWorkflowConflict: 직전 read 이후 workflow가 변경되면 발생합니다.
            PhaseStateTerminalError: Terminal lifecycle과 state marker가 맞지 않으면
                발생합니다.
        """
        if self._last_snapshot is None:
            self._last_snapshot = self._store.initialize(state)
            return
        expected_revision = self._last_snapshot.workflow_revision
        if state.terminal_state is None:
            self._last_snapshot = self._store.advance(state, expected_revision)
            return
        self._last_snapshot = self._store.finalize(state, expected_revision)

    def read_skill_state(self) -> Mapping[str, object]:
        """Underlying exact workflow의 skill-specific namespace를 반환합니다.

        Returns:
            Phase evidence와 terminal gate가 검증할 current skill-state object입니다.
        """
        return self._store.read_skill_state()

    def verify_adaptive_control_evidence(
        self,
        evidence: Mapping[str, object],
    ) -> AdaptiveControlPhaseReadback:
        """Underlying exact workflow에서 receipt와 external authority를 함께 읽습니다.

        Args:
            evidence: Current adaptive receipt라고 제출된 canonical JSON object입니다.

        Returns:
            Underlying store가 검증한 receipt와 external authority입니다.
        """
        return self._store.verify_adaptive_control_evidence(evidence)

    def read_adaptive_control_transition(self) -> AdaptiveControlTransitionReadback:
        """Underlying exact workflow의 current transition readiness를 반환합니다.

        Returns:
            같은 revision의 decision, authority, criterion metadata입니다.
        """
        return self._store.read_adaptive_control_transition()

    def read_review_evidence(
        self,
        expected_kind: str,
        reviewed_head_sha: str,
        *,
        delegation_id: str | None = None,
    ) -> tuple[ConsumedDelegationEvidenceSnapshot, FinalReviewVerification]:
        """Exact workflow의 consumed review artifact를 shared policy로 검증합니다.

        Args:
            expected_kind: 현재 phase가 요구하는 delegation kind입니다.
            reviewed_head_sha: Assignment가 결속한 exact commit입니다.

        Returns:
            Immutable delegation snapshot과 canonical C01-C14 verification입니다.
        """
        return self._store.read_review_evidence(
            expected_kind, reviewed_head_sha, delegation_id=delegation_id
        )

    def read_consumed_delegation_evidence(
        self,
        expected_kind: str,
        reviewed_head_sha: str,
    ) -> ConsumedDelegationEvidenceSnapshot:
        """Direct-child consumed evaluator artifact를 shared reader로 검증합니다.

        Args:
            expected_kind: Phase가 요구하는 exact delegation kind입니다.
            reviewed_head_sha: Assignment가 결속한 exact commit입니다.

        Returns:
            Shared reader가 검증한 consumed delegation snapshot입니다.
        """
        return self._store.read_consumed_delegation_evidence(
            expected_kind,
            reviewed_head_sha,
        )

    def validate_harness_incidents(self, worktree: Path) -> None:
        """Typed process incident projection을 terminal gate로 검증합니다.

        Args:
            worktree: Resolution evidence가 결속된 repository root입니다.
        """
        self._store.validate_harness_incidents(worktree)
