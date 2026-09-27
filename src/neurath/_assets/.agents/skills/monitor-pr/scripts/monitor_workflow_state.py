"""Workflow mailbox persistence and pure retryable state transitions."""

import hashlib
import json
import time
import uuid
from collections.abc import Mapping
from typing import Protocol


from scripts.agent_harness.session_kernel import (
    DelegationStatus,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateRetryExhausted,
    SkillStateSnapshot,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    StateHandle,
)

NATIVE_TURN_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


class MonitorWorkflowStateError(RuntimeError):
    """Workflow-local monitor state가 identity 또는 shape invariant를 위반했습니다."""


class MonitorWorkflowMutation(Protocol):
    """SkillStateStore가 retry할 수 있는 side-effect-free transition 계약입니다."""

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current skill state를 새 immutable candidate로 변환합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local skill state입니다.

        Returns:
            Side effect 없이 계산한 다음 workflow-local state candidate입니다.
        """


class MonitorWorkflowDocument:
    """Owner lifecycle과 mailbox shape를 한 pure mutation 안에서 정규화합니다."""

    _OWNER_STATES = frozenset({"active", "idle", "recovering", "terminal"})

    def __init__(self, current: Mapping[str, object], session_id: str) -> None:
        """Retry input을 detached mutable document로 검증합니다.

        Args:
            current: CAS retry에서 받은 latest workflow-local skill state입니다.
            session_id: Owner lifecycle과 반드시 일치해야 하는 exact session ID입니다.

        Raises:
            MonitorWorkflowStateError: Lifecycle 또는 mailbox identity와 shape가 invalid할 때 발생합니다.
        """
        self._state = dict(current)
        lifecycle = current.get("owner_lifecycle")
        if not isinstance(lifecycle, Mapping):
            raise MonitorWorkflowStateError("workflow-local owner lifecycle is missing")
        if lifecycle.get("state") not in self._OWNER_STATES:
            raise MonitorWorkflowStateError("owner lifecycle state is invalid")
        if lifecycle.get("owner_session_id") != session_id:
            raise MonitorWorkflowStateError("owner session identity mismatch")
        self._lifecycle = dict(lifecycle)
        raw_mailbox = current.get("monitor_mailbox")
        if raw_mailbox is None:
            mailbox: Mapping[str, object] = {}
        elif isinstance(raw_mailbox, Mapping):
            mailbox = raw_mailbox
        else:
            raise MonitorWorkflowStateError("monitor mailbox must be an object")
        pending = mailbox.get("pending_events", [])
        seen = mailbox.get("seen_event_ids", [])
        active_claim = mailbox.get("active_claim")
        if not isinstance(pending, list) or any(not isinstance(row, Mapping) for row in pending):
            raise MonitorWorkflowStateError("monitor mailbox pending events must be object array")
        if not isinstance(seen, list) or any(not isinstance(row, str) for row in seen):
            raise MonitorWorkflowStateError("monitor mailbox seen event ids must be string array")
        if active_claim is not None and not isinstance(active_claim, Mapping):
            raise MonitorWorkflowStateError("monitor mailbox active claim must be object or null")
        self._mailbox: dict[str, object] = {
            **mailbox,
            "pending_events": [dict(row) for row in pending],
            "seen_event_ids": list(seen),
            "active_claim": dict(active_claim) if isinstance(active_claim, Mapping) else None,
        }

    @property
    def lifecycle(self) -> dict[str, object]:
        """Detached lifecycle copy를 반환합니다.

        Returns:
            Mutation이 원본 mapping을 건드리지 않고 갱신할 lifecycle 복사본입니다.
        """
        return dict(self._lifecycle)

    @property
    def mailbox(self) -> dict[str, object]:
        """Detached mailbox copy를 반환합니다.

        Returns:
            Pending event, seen ID, active claim을 분리 복사한 mailbox입니다.
        """
        return {
            **self._mailbox,
            "pending_events": [
                dict(row)
                for row in self._list(self._mailbox.get("pending_events"))
                if isinstance(row, Mapping)
            ],
            "seen_event_ids": list(self._list(self._mailbox.get("seen_event_ids"))),
            "active_claim": (
                dict(self._mailbox["active_claim"])
                if isinstance(self._mailbox.get("active_claim"), Mapping)
                else None
            ),
        }

    def replace_lifecycle(self, lifecycle: Mapping[str, object]) -> None:
        """Transition이 계산한 lifecycle을 document에 교체합니다.

        Args:
            lifecycle: 이번 pure transition이 계산한 complete owner lifecycle입니다.
        """
        self._lifecycle = dict(lifecycle)

    def replace_mailbox(self, mailbox: Mapping[str, object]) -> None:
        """Transition이 계산한 mailbox를 document에 교체합니다.

        Args:
            mailbox: 이번 pure transition이 계산한 complete monitor mailbox입니다.
        """
        self._mailbox = dict(mailbox)

    def payload(self) -> Mapping[str, object]:
        """Unrelated key를 보존한 complete skill-state candidate를 반환합니다.

        Returns:
            새 lifecycle과 mailbox를 병합한 optimistic update candidate입니다.
        """
        return {
            **self._state,
            "owner_lifecycle": dict(self._lifecycle),
            "monitor_mailbox": self.mailbox,
        }

    def _list(self, value: object) -> list[object]:
        return list(value) if isinstance(value, list) else []


class StageMonitorEventMutation:
    """새 occurrence를 workflow FIFO mailbox에 exact-once 저장합니다."""

    def __init__(self, *, session_id: str, event: Mapping[str, object], now: float) -> None:
        """Retry 밖에서 고정된 event와 timestamp를 보관합니다.

        Args:
            session_id: Mailbox owner lifecycle과 일치해야 하는 exact session ID입니다.
            event: Stable ``event_id``를 포함한 stage 대상 occurrence입니다.
            now: 모든 CAS retry가 공유할 stage timestamp입니다.

        Raises:
            MonitorWorkflowStateError: Event에 non-empty ``event_id``가 없을 때 발생합니다.
        """
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise MonitorWorkflowStateError("monitor event requires event_id")
        self._session_id = session_id
        self._event = dict(event)
        self._event_id = event_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest mailbox에 unseen event만 append합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Event가 처음이면 append한 candidate, 이미 seen이면 original state입니다.

        Raises:
            MonitorWorkflowStateError: Latest mailbox가 normalized list shape가 아닐 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        seen = mailbox["seen_event_ids"]
        pending = mailbox["pending_events"]
        if not isinstance(seen, list) or not isinstance(pending, list):
            raise MonitorWorkflowStateError("monitor mailbox is not normalized")
        if self._event_id in seen:
            return current
        pending.append(dict(self._event))
        seen.append(self._event_id)
        mailbox["pending_events"] = pending
        mailbox["seen_event_ids"] = seen
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        return document.payload()


class ClaimMonitorEventMutation:
    """Idle owner와 FIFO head를 하나의 workflow-local CAS에서 claim합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        runtime_id: str,
        instance_id: str,
        claimant_pid: int,
        claim_id: str,
        now: float,
    ) -> None:
        """Claim identity와 clock을 retry 전에 한 번만 고정합니다.

        Args:
            session_id: Owner lifecycle과 claim에 기록할 exact session ID입니다.
            workflow_id: Claim이 속하는 exact active workflow identity입니다.
            runtime_id: Claim을 수행하는 monitor launch identity입니다.
            instance_id: 같은 runtime 안에서 claimant를 구분하는 instance identity입니다.
            claimant_pid: Claimant process 생존 검증에 사용할 PID입니다.
            claim_id: Retry 전체에서 유지할 새 claim identity입니다.
            now: Claim과 lifecycle transition이 공유할 timestamp입니다.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._runtime_id = runtime_id
        self._instance_id = instance_id
        self._claimant_pid = claimant_pid
        self._claim_id = claim_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Idle, no-active-claim, non-empty FIFO 조건에서만 claim을 생성합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            FIFO head를 claim한 candidate 또는 prerequisite가 없으면 original state입니다.

        Raises:
            MonitorWorkflowStateError: Pending event collection 또는 head shape가 invalid할 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        lifecycle = document.lifecycle
        mailbox = document.mailbox
        pending = mailbox["pending_events"]
        if not isinstance(pending, list):
            raise MonitorWorkflowStateError("monitor mailbox is not normalized")
        if (
            lifecycle.get("state") != "idle"
            or isinstance(mailbox.get("active_claim"), Mapping)
            or not pending
        ):
            return current
        event = pending.pop(0)
        if not isinstance(event, Mapping):
            raise MonitorWorkflowStateError("pending monitor event must be an object")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise MonitorWorkflowStateError("pending monitor event requires event_id")
        claim: dict[str, object] = {
            "claim_id": self._claim_id,
            "event_id": event_id,
            "owner_session_id": self._session_id,
            "session_id": self._session_id,
            "workflow_id": self._workflow_id,
            "claimant_runtime_id": self._runtime_id,
            "claimant_instance_id": self._instance_id,
            "claimant_pid": self._claimant_pid,
            "claimed_at_epoch": self._now,
            "event": dict(event),
        }
        mailbox["pending_events"] = pending
        mailbox["active_claim"] = claim
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        document.replace_lifecycle(
            {
                "state": "active",
                "owner_session_id": self._session_id,
                "source": "monitor-delivery",
                "transitioned_at_epoch": self._now,
                "activity": "claim",
                "claim_id": self._claim_id,
            }
        )
        return document.payload()


class BindMonitorTurnMutation:
    """Exact claim에 새 runtime turn identity를 immutable하게 결속합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        event_id: str,
        claim_id: str,
        turn_id: str,
        now: float,
    ) -> None:
        """Binding prerequisite와 clock을 고정합니다.

        Args:
            session_id: Active claim owner와 일치해야 하는 exact session ID입니다.
            event_id: Active claim이 참조해야 하는 staged event identity입니다.
            claim_id: Turn을 결속할 exact mailbox claim identity입니다.
            turn_id: Resume adapter가 생성한 immutable runtime turn identity입니다.
            now: 최초 binding에 기록할 timestamp입니다.

        Raises:
            MonitorWorkflowStateError: Exact turn identity가 비어 있을 때 발생합니다.
        """
        if not turn_id:
            raise MonitorWorkflowStateError("claimed delivery requires exact turn id")
        self._session_id = session_id
        self._event_id = event_id
        self._claim_id = claim_id
        self._turn_id = turn_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching active claim에만 turn을 bind합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Matching claim에 turn을 결속한 candidate 또는 불일치 시 original state입니다.

        Raises:
            MonitorWorkflowStateError: Claim에 다른 immutable turn이 이미 결속됐을 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if not isinstance(claim, Mapping):
            return current
        if claim.get("event_id") != self._event_id or claim.get("claim_id") != self._claim_id:
            return current
        existing = claim.get("turn_id")
        if isinstance(existing, str) and existing != self._turn_id:
            raise MonitorWorkflowStateError("monitor delivery turn identity is immutable")
        bound = dict(claim)
        bound["turn_id"] = self._turn_id
        bound.setdefault("turn_bound_at_epoch", self._now)
        mailbox["active_claim"] = bound
        mailbox["updated_at_epoch"] = self._now
        lifecycle = document.lifecycle
        lifecycle.update(
            {
                "turn_id": self._turn_id,
                "activity": "turn-started",
                "transitioned_at_epoch": self._now,
            }
        )
        document.replace_mailbox(mailbox)
        document.replace_lifecycle(lifecycle)
        return document.payload()


class CompleteMonitorTurnMutation:
    """Terminal read-back과 matching ACK를 claim completion으로 반영합니다."""

    def __init__(self, *, session_id: str, turn_id: str, acknowledged: bool, now: float) -> None:
        """Terminal observation을 retry 전에 고정합니다.

        Args:
            session_id: Active claim owner와 일치해야 하는 exact session ID입니다.
            turn_id: Terminal read-back이 증명한 exact runtime turn identity입니다.
            acknowledged: Matching durable ACK까지 확인됐는지 나타냅니다.
            now: Terminal lifecycle transition에 기록할 timestamp입니다.
        """
        self._session_id = session_id
        self._turn_id = turn_id
        self._acknowledged = acknowledged
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching turn을 recovering 또는 idle completion으로 전이합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            ACK 유무에 따라 recovering 또는 idle로 바꾼 candidate입니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if not isinstance(claim, Mapping) or claim.get("turn_id") != self._turn_id:
            return current
        saved_claim = dict(claim)
        saved_claim["terminal_observed_at_epoch"] = self._now
        if not self._acknowledged:
            saved_claim["delivery_state"] = "awaiting-ack"
            mailbox["active_claim"] = saved_claim
            lifecycle = {
                "state": "recovering",
                "owner_session_id": self._session_id,
                "source": "monitor-delivery",
                "transitioned_at_epoch": self._now,
                "activity": "terminal-without-ack",
                "claim_id": claim.get("claim_id"),
                "turn_id": self._turn_id,
            }
        else:
            mailbox["active_claim"] = None
            lifecycle = {
                "state": "idle",
                "owner_session_id": self._session_id,
                "source": "monitor-delivery",
                "transitioned_at_epoch": self._now,
                "activity": "turn-completed-and-acknowledged",
            }
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        document.replace_lifecycle(lifecycle)
        return document.payload()


class ReleaseMonitorClaimMutation:
    """Turn이 없는 exact claim만 FIFO head로 되돌립니다."""

    def __init__(self, *, session_id: str, claim_id: str, now: float) -> None:
        """Release identity와 clock을 고정합니다.

        Args:
            session_id: Active claim owner와 일치해야 하는 exact session ID입니다.
            claim_id: Delivery가 시작되지 않았음을 확인한 exact claim identity입니다.
            now: FIFO 복원과 lifecycle transition에 기록할 timestamp입니다.
        """
        self._session_id = session_id
        self._claim_id = claim_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching unbound claim을 안전하게 release합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Event를 FIFO head로 복원한 candidate 또는 불일치 시 original state입니다.

        Raises:
            MonitorWorkflowStateError: Claim event 또는 pending collection shape가 invalid할 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if not isinstance(claim, Mapping) or claim.get("claim_id") != self._claim_id:
            return current
        if isinstance(claim.get("turn_id"), str):
            return current
        event = claim.get("event")
        pending = mailbox["pending_events"]
        if not isinstance(event, Mapping) or not isinstance(pending, list):
            raise MonitorWorkflowStateError("monitor claim requires event payload")
        pending.insert(0, dict(event))
        mailbox["pending_events"] = pending
        mailbox["active_claim"] = None
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        document.replace_lifecycle(
            {
                "state": "idle",
                "owner_session_id": self._session_id,
                "source": "monitor-delivery",
                "transitioned_at_epoch": self._now,
                "activity": "delivery-not-started",
            }
        )
        return document.payload()


class ReleaseNativeOwnerMutation:
    """Runtime inspection이 terminal로 증명한 exact native turn을 idle로 해제합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_status: str,
        now: float,
    ) -> None:
        """Inspection evidence를 retry 전에 고정합니다.

        Args:
            session_id: Native lifecycle owner와 일치해야 하는 exact session ID입니다.
            turn_id: App-server가 terminal로 read-back한 native turn identity입니다.
            turn_status: Native turn의 허용된 terminal status입니다.
            now: Owner release lifecycle에 기록할 timestamp입니다.

        Raises:
            MonitorWorkflowStateError: ``turn_status``가 terminal set 밖일 때 발생합니다.
        """
        if turn_status not in NATIVE_TURN_TERMINAL_STATUSES:
            raise MonitorWorkflowStateError("native owner release requires terminal status")
        self._session_id = session_id
        self._turn_id = turn_id
        self._turn_status = turn_status
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current native lifecycle이 inspected turn과 같을 때만 해제합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Matching native owner를 idle로 해제한 candidate 또는 original state입니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        lifecycle = document.lifecycle
        mailbox = document.mailbox
        if (
            isinstance(mailbox.get("active_claim"), Mapping)
            or lifecycle.get("state") != "active"
            or lifecycle.get("source") != "native-hook"
            or lifecycle.get("turn_id") != self._turn_id
        ):
            return current
        document.replace_lifecycle(
            {
                "state": "idle",
                "owner_session_id": self._session_id,
                "source": "turn-inspection",
                "transitioned_at_epoch": self._now,
                "activity": "native-turn-release",
                "released_turn_id": self._turn_id,
                "released_turn_status": self._turn_status,
            }
        )
        return document.payload()


class MonitorWorkflowState:
    """Exact workflow mailbox를 pure optimistic transactions로 관리합니다."""

    _MAX_RETRIES = 64

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Runtime-bound handle과 exact active workflow에 adapter를 고정합니다.

        Args:
            handle: Vendor runtime identity에 attach된 canonical session handle입니다.
            workflow_id: Mailbox와 owner lifecycle을 소유하는 exact workflow입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._session_id = str(handle.session_id)
        self._store = SkillStateStore(handle, workflow_id)

    def runtime(self) -> dict[str, object]:
        """Validated lifecycle과 mailbox snapshot을 반환합니다.

        Returns:
            Current lifecycle, FIFO, seen IDs, active claim을 분리한 runtime view입니다.
        """
        snapshot = self._store.read()
        document = MonitorWorkflowDocument(snapshot.skill_state, self._session_id)
        mailbox = document.mailbox
        return {
            "lifecycle": document.lifecycle,
            "pending_events": mailbox["pending_events"],
            "seen_event_ids": mailbox["seen_event_ids"],
            "active_claim": mailbox["active_claim"],
        }

    def stage(self, event: Mapping[str, object]) -> bool:
        """새 event를 exact-once 저장하고 CAS 승자 여부를 반환합니다.

        Args:
            event: Stable ``event_id``를 포함한 workflow-local occurrence입니다.

        Returns:
            새 occurrence가 committed되면 ``True``, 이미 seen이면 ``False``입니다.
        """
        _, changed = self._commit(
            StageMonitorEventMutation(
                session_id=self._session_id,
                event=event,
                now=time.time(),
            )
        )
        return changed

    def claim(self, *, runtime_id: str, instance_id: str, claimant_pid: int) -> dict[str, object]:
        """Idle FIFO head를 claim하고 committed claim을 반환합니다.

        Args:
            runtime_id: Claimant monitor launch의 고유 runtime identity입니다.
            instance_id: 같은 launch 안에서 process instance를 구분하는 identity입니다.
            claimant_pid: Stale claim recovery에서 process 생존을 검증할 PID입니다.

        Returns:
            Committed active claim이며 claim할 event가 없으면 빈 object입니다.
        """
        snapshot, changed = self._commit(
            ClaimMonitorEventMutation(
                session_id=self._session_id,
                workflow_id=str(self._workflow_id),
                runtime_id=runtime_id,
                instance_id=instance_id,
                claimant_pid=claimant_pid,
                claim_id=uuid.uuid4().hex,
                now=time.time(),
            )
        )
        if not changed:
            return {}
        document = MonitorWorkflowDocument(snapshot.skill_state, self._session_id)
        claim = document.mailbox.get("active_claim")
        return dict(claim) if isinstance(claim, Mapping) else {}

    def bind_turn(self, *, event_id: str, claim_id: str, turn_id: str) -> bool:
        """Matching claim에 exact turn identity를 결속합니다.

        Args:
            event_id: Claim이 참조하는 staged event identity입니다.
            claim_id: Turn을 결속할 exact active claim identity입니다.
            turn_id: Resume adapter가 시작한 immutable runtime turn identity입니다.

        Returns:
            Matching claim이 committed되면 ``True``, 없으면 ``False``입니다.
        """
        _, changed = self._commit(
            BindMonitorTurnMutation(
                session_id=self._session_id,
                event_id=event_id,
                claim_id=claim_id,
                turn_id=turn_id,
                now=time.time(),
            )
        )
        return changed

    def complete_turn(self, *, turn_id: str, acknowledged: bool) -> bool:
        """Terminal observation을 기록하고 ACK가 있으면 claim을 완료합니다.

        Args:
            turn_id: Terminal read-back을 마친 exact runtime turn identity입니다.
            acknowledged: Matching durable monitor ACK를 확인했는지 나타냅니다.

        Returns:
            ACK와 terminal turn이 함께 committed되어 claim이 사라지면 ``True``입니다.
        """
        snapshot, changed = self._commit(
            CompleteMonitorTurnMutation(
                session_id=self._session_id,
                turn_id=turn_id,
                acknowledged=acknowledged,
                now=time.time(),
            )
        )
        if not changed or not acknowledged:
            return False
        document = MonitorWorkflowDocument(snapshot.skill_state, self._session_id)
        return document.mailbox.get("active_claim") is None

    def release_claim(self, claim_id: str) -> bool:
        """Matching unbound claim을 FIFO로 되돌립니다.

        Args:
            claim_id: Resume turn을 시작하지 못한 exact active claim identity입니다.

        Returns:
            Event가 FIFO head로 복원되어 commit되면 ``True``입니다.
        """
        _, changed = self._commit(
            ReleaseMonitorClaimMutation(
                session_id=self._session_id,
                claim_id=claim_id,
                now=time.time(),
            )
        )
        return changed

    def release_native_owner(self, *, turn_id: str, turn_status: str) -> dict[str, object]:
        """Exact terminal native turn을 idle로 해제하고 committed lifecycle을 반환합니다.

        Args:
            turn_id: Runtime inspection이 terminal로 증명한 native turn identity입니다.
            turn_status: Native runtime이 read-back한 terminal status입니다.

        Returns:
            해제가 committed되면 새 lifecycle, route가 달라지면 빈 object입니다.
        """
        snapshot, changed = self._commit(
            ReleaseNativeOwnerMutation(
                session_id=self._session_id,
                turn_id=turn_id,
                turn_status=turn_status,
                now=time.time(),
            )
        )
        if not changed:
            return {}
        return MonitorWorkflowDocument(snapshot.skill_state, self._session_id).lifecycle

    def acknowledgement(self) -> dict[str, object]:
        """Current workflow-local monitor ACK를 반환합니다.

        Returns:
            Exact workflow의 durable ACK이며 기록이 없거나 invalid하면 빈 object입니다.
        """
        value = self._store.read().skill_state.get("monitor_event_ack")
        return dict(value) if isinstance(value, Mapping) else {}

    def _commit(
        self,
        mutation: MonitorWorkflowMutation,
    ) -> tuple[SkillStateSnapshot, bool]:
        for _attempt in range(self._MAX_RETRIES):
            original = self._store.read()
            candidate = mutation(original.skill_state)
            if dict(candidate) == dict(original.skill_state):
                return original, False
            try:
                committed = self._store.compare_and_update(
                    original.workflow_revision,
                    mutation,
                )
            except SkillStateConflict:
                continue
            return committed, True
        raise SkillStateRetryExhausted(
            f"monitor workflow {self._workflow_id} did not converge after "
            f"{self._MAX_RETRIES} retries"
        )


class MonitorDelegationSnapshot:
    """Exact workflow child assignment과 optional result를 immutable하게 결합합니다."""

    __slots__ = ("claim", "result", "status")

    def __init__(
        self,
        *,
        claim: Mapping[str, object],
        result: Mapping[str, object] | None,
        status: DelegationStatus,
    ) -> None:
        """Canonical delegation projection을 고정합니다.

        Args:
            claim: Owner와 target identity를 포함한 normalized child assignment입니다.
            result: Reported child이면 immutable result receipt, pending이면 ``None``입니다.
            status: SessionKernel이 보존한 pending 또는 reported delegation 상태입니다.
        """
        object.__setattr__(self, "claim", dict(claim))
        object.__setattr__(self, "result", None if result is None else dict(result))
        object.__setattr__(self, "status", status)

    claim: dict[str, object]
    """Monitor가 delivery 판단에 사용할 normalized child assignment입니다."""
    result: dict[str, object] | None
    """Reported child의 digest-bound result이며 pending 상태에서는 없습니다."""
    status: DelegationStatus
    """Result delivery 여부를 결정하는 canonical delegation lifecycle 상태입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 delegation snapshot mutation을 거부합니다.

        Args:
            name: 변경을 시도한 snapshot attribute 이름입니다.
            value: Immutable projection에 새로 지정하려 한 값입니다.

        Raises:
            AttributeError: 생성 이후 snapshot field를 변경하려 할 때 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class MonitorDelegationReader:
    """SessionKernel delegation map에서 exact owner/workflow child만 선택합니다."""

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Canonical session actor와 workflow identity를 고정합니다.

        Args:
            handle: Exact owner actor와 delegation map을 제공하는 session handle입니다.
            workflow_id: Child assignment를 필터링할 exact workflow identity입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id

    def active(self) -> tuple[MonitorDelegationSnapshot, ...]:
        """Pending 또는 reported exact child assignment를 stable order로 반환합니다.

        Returns:
            Current owner와 workflow에 속한 active child projection의 stable tuple입니다.

        Raises:
            MonitorWorkflowStateError: Assignment JSON, identity, required field가 invalid할 때 발생합니다.
        """
        snapshots: list[MonitorDelegationSnapshot] = []
        state = self._handle.inspect()
        for delegation_id, delegation in sorted(
            state.delegations.items(),
            key=lambda item: str(item[0]),
        ):
            if delegation.owner_actor_id != self._handle.actor_id:
                continue
            # Terminal history can use another producer's assignment schema.
            if delegation.status not in {DelegationStatus.PENDING, DelegationStatus.REPORTED}:
                continue
            try:
                raw_assignment: object = json.loads(delegation.assignment)
            except json.JSONDecodeError:
                # Generic delegations carry free-form instructions. Without a
                # structured workflow identity they are not monitor assignments.
                continue
            if not isinstance(raw_assignment, Mapping):
                continue
            if raw_assignment.get("workflow_id") != str(self._workflow_id):
                continue
            required = ("kind", "scope", "started_at", "target", "workflow_id")
            if any(
                not isinstance(raw_assignment.get(field), str) or not raw_assignment.get(field)
                for field in required
            ):
                raise MonitorWorkflowStateError(
                    f"delegation assignment identity is incomplete: {delegation_id}"
                )
            claim: dict[str, object] = {
                "delegation_id": str(delegation.id),
                "kind": raw_assignment["kind"],
                "owner_actor_id": str(delegation.owner_actor_id),
                "scope": raw_assignment["scope"],
                "started_at": raw_assignment["started_at"],
                "target": raw_assignment["target"],
                "target_agent_id": str(delegation.target_actor_id),
                "workflow_id": raw_assignment["workflow_id"],
            }
            result_payload: dict[str, object] | None = None
            if delegation.status is DelegationStatus.REPORTED:
                result_payload = delegation.result.to_payload()
                result_payload.update(
                    {
                        "delegation_id": str(delegation.id),
                        "target_agent_id": str(delegation.target_actor_id),
                        "result_digest": hashlib.sha256(
                            json.dumps(
                                result_payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode()
                        ).hexdigest(),
                    }
                )
            snapshots.append(
                MonitorDelegationSnapshot(
                    claim=claim,
                    result=result_payload,
                    status=delegation.status,
                )
            )
        return tuple(snapshots)
