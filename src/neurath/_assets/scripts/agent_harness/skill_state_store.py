"""Skill operational state를 workflow payload namespace에 optimistic하게 보존합니다."""

import fcntl
import hashlib
import json
import uuid
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType

from scripts.agent_harness.session_kernel import (
    ImmutableValue,
    ProcessState,
    ReservedSkillStateAdvanced,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_contract import (
    SkillStateReservedMutation,
    SkillStateStoreError,
)
from scripts.agent_harness.state_handle import StateHandle

type SkillStateMutation = (
    Mapping[str, object] | Callable[[Mapping[str, object]], Mapping[str, object]]
)


class SkillStateWorkflowNotFound(SkillStateStoreError):
    """Bound exact session에 요청한 workflow가 없을 때 발생합니다."""


class SkillStateAuthorityError(SkillStateStoreError):
    """현재 StateHandle actor가 workflow owner가 아닐 때 발생합니다."""


class SkillStateWorkflowTerminal(SkillStateStoreError):
    """Terminal workflow의 skill state를 읽거나 갱신하려 할 때 발생합니다."""


class InvalidSkillState(SkillStateStoreError):
    """Skill state namespace 또는 mutation 결과가 JSON object가 아닐 때 발생합니다."""


class SkillStateConflict(SkillStateStoreError):
    """Workflow-local optimistic revision이 caller 원본과 달라졌을 때 발생합니다."""


class SkillStateReservedNamespaceError(SkillStateStoreError):
    """Generic mutation이 typed owner가 있는 reserved namespace를 바꾸려 함을 나타냅니다."""


class SkillStateRetryExhausted(SkillStateStoreError):
    """Implicit optimistic update가 bounded attempt 안에 수렴하지 못했을 때 발생합니다."""


class InvalidSkillStateRetryLimit(SkillStateStoreError):
    """Skill-state optimistic retry 상한이 양수가 아닐 때 발생합니다."""


class SkillStateSnapshot(ImmutableValue):
    """Workflow revision과 그 revision에서의 skill-state object를 함께 고정합니다."""

    __slots__ = ("_workflow_payload", "skill_state", "workflow_id", "workflow_revision")

    def __init__(
        self,
        workflow_id: WorkflowId,
        workflow_revision: int,
        skill_state: Mapping[str, object],
        workflow_payload: Mapping[str, object],
    ) -> None:
        """CAS 원본과 namespace projection을 immutable snapshot으로 구성합니다.

        Args:
            workflow_id: Snapshot이 속한 exact workflow identity입니다.
            workflow_revision: Workflow-local compare-and-swap 원본 version입니다.
            skill_state: Workflow payload의 validated skill_state object입니다.
            workflow_payload: Commit 때 unrelated namespace를 보존할 전체 payload입니다.
        """
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "workflow_revision", workflow_revision)
        object.__setattr__(self, "skill_state", MappingProxyType(dict(skill_state)))
        object.__setattr__(self, "_workflow_payload", MappingProxyType(dict(workflow_payload)))

    workflow_id: WorkflowId
    """Snapshot이 속한 exact workflow identity입니다."""

    workflow_revision: int
    """Workflow 전체 payload를 보호하는 aggregate-local CAS version입니다."""

    skill_state: Mapping[str, object]
    """Skill-specific operational state의 read-only top-level object입니다."""

    _workflow_payload: Mapping[str, object]
    """Unrelated workflow namespace를 다음 commit에 보존하기 위한 원본 payload입니다."""


class _ReservedSkillStateCandidate(Mapping[str, object]):
    """Validated reserved namespace capability를 commit input 자체에 캡슐화합니다."""

    __slots__ = ("_payload", "reserved_namespaces")

    def __init__(
        self,
        payload: Mapping[str, object],
        reserved_namespaces: frozenset[str],
    ) -> None:
        """Top-level read-only candidate와 exact changed reserved namespace를 고정합니다.

        Args:
            payload: Typed domain mutation이 만든 complete skill-state candidate mapping입니다.
            reserved_namespaces: Candidate에서 변경을 허가받은 exact namespace 집합입니다.
        """
        self._payload = MappingProxyType(dict(payload))
        self.reserved_namespaces = reserved_namespaces

    def __getitem__(self, key: str) -> object:
        """Candidate의 exact namespace 값을 읽습니다.

        Args:
            key: 조회할 top-level skill-state namespace입니다.

        Returns:
            Typed mutation이 산출한 해당 namespace 값입니다.

        Raises:
            KeyError: Candidate에 요청한 namespace가 없으면 발생합니다.
        """
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        """Candidate가 보존하는 namespace 순회를 제공합니다.

        Returns:
            Immutable candidate의 top-level namespace iterator입니다.
        """
        return iter(self._payload)

    def __len__(self) -> int:
        """Candidate에 포함된 namespace 수를 반환합니다.

        Returns:
            Typed replacement object의 top-level namespace 개수입니다.
        """
        return len(self._payload)


class SkillStateStore:
    """StateHandle과 WorkflowId에 고정된 skill-state optimistic transaction입니다.

    Callable mutation은 I/O, clock, random, 외부 mutation 같은 side effect가 없는 pure
    transform이어야 합니다. Python callable 내부의 side effect를 runtime에서 완전히
    차단할 수 없으므로 이 경계는 caller contract입니다. Implicit `update`는 충돌 시
    callable을 latest snapshot에서 여러 번 실행할 수 있습니다.
    """

    _NAMESPACE = "skill_state"
    _RESERVED_NAMESPACES = frozenset({"adaptive_control"})

    def __init__(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        max_retries: int = 64,
    ) -> None:
        """Exact session actor와 workflow에 path-free store를 고정합니다.

        Args:
            handle: Runtime identity와 current actor에 이미 고정된 canonical facade입니다.
            workflow_id: Operational state를 소유하는 exact active workflow입니다.
            max_retries: Implicit update가 workflow conflict 뒤 재시도할 상한입니다.

        Raises:
            InvalidSkillStateRetryLimit: Retry 상한이 양수가 아니면 발생합니다.
        """
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 1:
            raise InvalidSkillStateRetryLimit("max_retries must be a positive integer")
        self._handle = handle
        self._workflow_id = workflow_id
        self._max_retries = max_retries

    def read(self) -> SkillStateSnapshot:
        """Bound exact active workflow의 validated skill-state snapshot을 읽습니다.

        Returns:
            Workflow-local revision과 read-only skill-state object를 포함한 snapshot입니다.

        Raises:
            SkillStateWorkflowNotFound: Exact workflow가 session에 없으면 발생합니다.
            SkillStateAuthorityError: Handle actor가 workflow owner가 아니면 발생합니다.
            SkillStateWorkflowTerminal: Workflow가 active가 아니면 발생합니다.
            InvalidSkillState: Namespace가 없거나 JSON object가 아니면 발생합니다.
        """
        state = self._handle.inspect()
        workflow = state.workflows.get(self._workflow_id)
        if workflow is None:
            raise SkillStateWorkflowNotFound(f"workflow is missing: {self._workflow_id}")
        return self._snapshot(workflow)

    @property
    def workflow_id(self) -> WorkflowId:
        """Bound exact workflow identity를 higher-level typed store에 제공합니다.

        Returns:
            Constructor에서 검증 대상으로 고정한 workflow identity입니다.
        """
        return self._workflow_id

    def read_process_state(self) -> ProcessState:
        """Workflow owner와 lifecycle을 검증한 same-session aggregate를 읽습니다.

        Returns:
            Adaptive admission이 sibling material receipt를 대조할 immutable process state입니다.

        Raises:
            SkillStateWorkflowNotFound: Bound workflow가 exact session에 없을 때 발생합니다.
            SkillStateStoreError: Workflow owner, lifecycle 또는 payload가 invalid할 때 발생합니다.
        """
        state = self._handle.inspect()
        workflow = state.workflows.get(self._workflow_id)
        if workflow is None:
            raise SkillStateWorkflowNotFound(f"workflow is missing: {self._workflow_id}")
        self._snapshot(workflow)
        return state

    def update(self, mutation: SkillStateMutation) -> SkillStateSnapshot:
        """Pure mutation을 latest skill state에 적용해 bounded optimistic retry합니다.

        Mapping mutation은 current object에 key를 merge합니다. Callable mutation은
        read-only top-level current object를 받아 전체 새 object를 반환해야 하며, conflict가
        발생하면 여러 번 호출될 수 있으므로 반드시 side-effect free여야 합니다. Transform은
        SessionKernel의 짧은 commit mutex를 획득하기 전에 실행됩니다.

        Args:
            mutation: Merge할 object 또는 current state를 새 object로 바꾸는 pure callable입니다.

        Returns:
            Commit에 성공한 workflow revision과 skill-state snapshot입니다.

        Raises:
            SkillStateRetryExhausted: Workflow 충돌이 retry 상한 안에 수렴하지 않으면
                발생합니다.
            InvalidSkillState: Mutation 입력 또는 결과가 JSON object가 아니면 발생합니다.
            SkillStateStoreError: Workflow identity, owner, lifecycle invariant가 틀리면
                발생합니다.
        """
        operation_id = uuid.uuid4().hex
        for _attempt in range(self._max_retries):
            snapshot = self.read()
            candidate = self._transform(snapshot.skill_state, mutation)
            if candidate == snapshot.skill_state:
                return snapshot
            try:
                return self._commit(snapshot, candidate, operation_id)
            except SkillStateConflict:
                continue
        raise SkillStateRetryExhausted(
            f"workflow {self._workflow_id} did not converge after {self._max_retries} retries"
        )

    def compare_and_update(
        self,
        expected_workflow_revision: int,
        mutation: SkillStateMutation,
    ) -> SkillStateSnapshot:
        """Caller가 읽은 exact workflow revision에 mutation을 한 번만 CAS합니다.

        Explicit compare는 conflict를 숨기거나 transformer를 재실행하지 않습니다.
        Callable은 이 경계에서도 side-effect free여야 하며 transform은 commit mutex 밖에서
        실행됩니다.

        Args:
            expected_workflow_revision: Caller가 읽은 workflow-local 원본 version입니다.
            mutation: Merge할 object 또는 current state를 새 object로 바꾸는 pure callable입니다.

        Returns:
            Exact 원본에 commit된 새 workflow revision과 skill-state snapshot입니다.

        Raises:
            SkillStateConflict: Expected revision이 latest workflow와 다르면 발생합니다.
            InvalidSkillState: Revision 또는 mutation 결과가 invalid하면 발생합니다.
            SkillStateStoreError: Workflow identity, owner, lifecycle invariant가 틀리면
                발생합니다.
        """
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise InvalidSkillState("expected workflow revision must be non-negative")
        snapshot = self.read()
        if snapshot.workflow_revision != expected_workflow_revision:
            raise SkillStateConflict(
                f"expected workflow revision {expected_workflow_revision}, "
                f"got {snapshot.workflow_revision}"
            )
        candidate = self._transform(snapshot.skill_state, mutation)
        if candidate == snapshot.skill_state:
            return self._compare_no_op(snapshot)
        return self._commit(snapshot, candidate, uuid.uuid4().hex)

    def _compare_no_op(self, snapshot: SkillStateSnapshot) -> SkillStateSnapshot:
        """Explicit no-op CAS를 canonical commit mutex 아래에서 선형화합니다.

        Args:
            snapshot: Transform이 no-op으로 판정된 caller 원본 workflow입니다.

        Returns:
            Mutex 획득 시점에도 revision이 일치하는 current workflow snapshot입니다.

        Raises:
            SkillStateConflict: Transform 중 workflow revision이 바뀌면 발생합니다.
            SkillStateWorkflowNotFound: Bound workflow가 canonical state에서 사라지면
                발생합니다.
            SkillStateStoreError: Current workflow의 authority, lifecycle, payload가
                store invariant와 다르면 발생합니다.
        """
        paths = self._handle._kernel._session_paths(self._handle.session_id)
        with paths.process_state_lock.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                state = self._handle.inspect()
                workflow = state.workflows.get(self._workflow_id)
                if workflow is None:
                    raise SkillStateWorkflowNotFound(f"workflow is missing: {self._workflow_id}")
                if workflow.revision != snapshot.workflow_revision:
                    raise SkillStateConflict(
                        f"expected workflow revision {snapshot.workflow_revision}, "
                        f"got {workflow.revision}"
                    )
                return self._snapshot(workflow)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _snapshot(self, workflow: WorkflowRecord) -> SkillStateSnapshot:
        if workflow.owner_actor_id != self._handle.actor_id:
            raise SkillStateAuthorityError(
                f"workflow owner {workflow.owner_actor_id} does not match "
                f"actor {self._handle.actor_id}"
            )
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise SkillStateWorkflowTerminal(f"workflow is terminal: {workflow.id}")
        if self._NAMESPACE not in workflow.payload:
            raise InvalidSkillState("workflow payload is missing skill_state")
        skill_state = workflow.payload[self._NAMESPACE]
        if not isinstance(skill_state, Mapping):
            raise InvalidSkillState("workflow skill_state must be an object")
        self._validate_object(skill_state)
        return SkillStateSnapshot(
            workflow_id=workflow.id,
            workflow_revision=workflow.revision,
            skill_state=skill_state,
            workflow_payload=workflow.payload,
        )

    def _transform(
        self,
        current: Mapping[str, object],
        mutation: SkillStateMutation,
    ) -> Mapping[str, object]:
        if isinstance(mutation, Mapping):
            candidate: object = {**current, **mutation}
        elif callable(mutation):
            candidate = mutation(MappingProxyType(dict(current)))
        else:
            raise InvalidSkillState("skill-state mutation must be an object or callable")
        if not isinstance(candidate, Mapping):
            raise InvalidSkillState("skill-state mutation must return an object")
        self._validate_object(candidate)
        reserved_namespaces = self._validate_reserved_namespaces(
            current,
            candidate,
            mutation,
        )
        if reserved_namespaces:
            return _ReservedSkillStateCandidate(candidate, reserved_namespaces)
        return MappingProxyType(dict(candidate))

    def _validate_reserved_namespaces(
        self,
        current: Mapping[str, object],
        candidate: Mapping[str, object],
        mutation: SkillStateMutation,
    ) -> frozenset[str]:
        changed = frozenset(
            namespace
            for namespace in self._RESERVED_NAMESPACES
            if (namespace in current) != (namespace in candidate)
            or (
                namespace in current
                and namespace in candidate
                and current[namespace] != candidate[namespace]
            )
        )
        if not changed:
            return frozenset()
        authorized = self._reserved_namespaces(mutation)
        if not changed.issubset(authorized):
            names = ", ".join(sorted(changed))
            raise SkillStateReservedNamespaceError(
                f"reserved skill-state namespace requires its typed store: {names}"
            )
        return changed

    def _reserved_namespaces(self, mutation: SkillStateMutation) -> frozenset[str]:
        return (
            mutation.reserved_namespaces
            if isinstance(mutation, SkillStateReservedMutation)
            else frozenset()
        )

    def _commit(
        self,
        snapshot: SkillStateSnapshot,
        candidate: Mapping[str, object],
        operation_id: str,
    ) -> SkillStateSnapshot:
        payload = dict(snapshot._workflow_payload)
        payload[self._NAMESPACE] = dict(candidate)
        mutation_namespaces = (
            candidate.reserved_namespaces
            if isinstance(candidate, _ReservedSkillStateCandidate)
            else frozenset()
        )
        idempotency_key = self._idempotency_key(
            snapshot.workflow_revision,
            payload,
            operation_id,
        )
        event = (
            ReservedSkillStateAdvanced(
                session_id=self._handle.session_id,
                workflow_id=self._workflow_id,
                actor_id=self._handle.actor_id,
                expected_workflow_revision=snapshot.workflow_revision,
                payload=payload,
                idempotency_key=idempotency_key,
                reserved_namespaces=mutation_namespaces,
            )
            if mutation_namespaces
            else WorkflowAdvanced(
                session_id=self._handle.session_id,
                workflow_id=self._workflow_id,
                actor_id=self._handle.actor_id,
                expected_workflow_revision=snapshot.workflow_revision,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        )
        try:
            committed = self._handle.apply(event)
        except TransitionRejected as error:
            latest = self.read()
            if latest.workflow_revision != snapshot.workflow_revision:
                raise SkillStateConflict(
                    f"expected workflow revision {snapshot.workflow_revision}, "
                    f"got {latest.workflow_revision}"
                ) from error
            raise
        workflow = committed.workflows.get(self._workflow_id)
        if workflow is None:
            raise SkillStateWorkflowNotFound(f"workflow is missing: {self._workflow_id}")
        return self._snapshot(workflow)

    def _validate_object(self, value: Mapping[str, object]) -> None:
        if any(not isinstance(key, str) for key in value):
            raise InvalidSkillState("skill-state keys must be strings")
        self._canonical_json(value)

    def _canonical_json(self, value: Mapping[str, object]) -> str:
        try:
            return json.dumps(
                dict(value),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise InvalidSkillState("skill-state must be JSON-compatible") from error

    def _idempotency_key(
        self,
        expected_workflow_revision: int,
        payload: Mapping[str, object],
        operation_id: str,
    ) -> str:
        digest = hashlib.sha256(self._canonical_json(payload).encode()).hexdigest()
        return (
            f"skill-state:{self._workflow_id}:{operation_id}:{expected_workflow_revision}:{digest}"
        )
