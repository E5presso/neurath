"""Pure workflow validation and prepared/completed handoff mutations."""

from __future__ import annotations

from collections.abc import Mapping


from monitor_handoff_plan import MonitorRuntimeIdentityMismatch, MonitorRuntimePaths


class MonitorWorkflowSnapshotValidator:
    """Runtime retirement 전에 persisted owner와 monitor route를 fail-closed 검증합니다."""

    _OWNER_STATES = frozenset({"active", "idle", "recovering", "terminal"})

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        paths: MonitorRuntimePaths,
    ) -> None:
        """Current runtime authority와 canonical local route를 고정합니다.

        Args:
            session_id: StateHandle이 검증한 exact root session identity입니다.
            workflow_id: Handoff가 속한 exact active workflow identity입니다.
            paths: Git identity에서 파생한 canonical monitor runtime paths입니다.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._paths = paths

    def validate(self, state: Mapping[str, object]) -> None:
        """Owner fence와 optional monitor runtime receipt의 exact identity를 확인합니다.

        Args:
            state: Exact workflow의 latest skill-state snapshot입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Owner, session, workflow 또는 local route가
                current authority와 다를 때 발생합니다.
        """
        self._validate_owner_lifecycle(state.get("owner_lifecycle"))
        subscription = state.get("monitor_event_subscription")
        started = state.get("monitor_started")
        if subscription is not None:
            self._validate_runtime_receipt(subscription, "monitor_event_subscription")
        if started is not None:
            self._validate_runtime_receipt(started, "monitor_started")
            if subscription is None:
                raise MonitorRuntimeIdentityMismatch(
                    "detached monitor subscription identity is missing"
                )

    def _validate_owner_lifecycle(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch(
                "workflow-local owner lifecycle identity is missing"
            )
        if value.get("state") not in self._OWNER_STATES:
            raise MonitorRuntimeIdentityMismatch("owner lifecycle state is invalid")
        if value.get("owner_session_id") != self._session_id:
            raise MonitorRuntimeIdentityMismatch("owner session identity mismatch")

    def _validate_runtime_receipt(self, value: object, field: str) -> None:
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch(f"{field} must be an object")
        if "process_state_path" in value:
            raise MonitorRuntimeIdentityMismatch(
                f"{field} cannot select worktree-local process state"
            )
        expected: dict[str, object] = {
            "provider": "local-pr-monitor",
            "session_id": self._session_id,
            "workflow_id": self._workflow_id,
        }
        if "worktree_id" in value or "observation_resource" in value:
            expected.update(
                {
                    "worktree_id": self._paths.worktree_id,
                    "observation_resource": self._paths.observation_resource(),
                }
            )
        else:
            expected.update(
                {
                    "worktree": str(self._paths.worktree.resolve()),
                    "state_path": str(self._paths.state_path.resolve()),
                }
            )
        for key, expected_value in expected.items():
            if value.get(key) != expected_value:
                identity_name = {
                    "session_id": "session",
                    "workflow_id": "workflow",
                }.get(key, key.replace("_", " "))
                raise MonitorRuntimeIdentityMismatch(f"{field} {identity_name} identity mismatch")
        thread_id = value.get("thread_id")
        if thread_id is not None and thread_id != self._session_id:
            raise MonitorRuntimeIdentityMismatch(f"{field} thread identity mismatch")


class MonitorHandoffPreparedMutation:
    """Legacy event migration과 prepared receipt를 pure optimistic transform으로 만듭니다."""

    _OWNER_STATES = frozenset({"active", "idle", "recovering", "terminal"})

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        worktree: str,
        prepared_at: str,
        mailbox_updated_at_epoch: float,
        receipt: Mapping[str, object],
        migrated_events: tuple[Mapping[str, object], ...],
    ) -> None:
        """Retry 사이에서 바뀌면 안 되는 identity, time, migration input을 고정합니다.

        Args:
            session_id: Workflow owner와 일치해야 하는 exact session identity입니다.
            workflow_id: Receipt에 결속할 exact workflow identity입니다.
            worktree: Git이 증명한 canonical worktree path입니다.
            prepared_at: I/O 전에 한 번 캡처한 UTC timestamp입니다.
            mailbox_updated_at_epoch: Mailbox mutation에 사용할 한 번 캡처한 epoch입니다.
            receipt: Retirement와 legacy inventory를 담은 immutable input receipt입니다.
            migrated_events: 안전하게 재큐잉할 수 있는 legacy event 후보입니다.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._worktree = worktree
        self._prepared_at = prepared_at
        self._mailbox_updated_at_epoch = mailbox_updated_at_epoch
        self._receipt = dict(receipt)
        self._migrated_events = tuple(dict(event) for event in migrated_events)

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest workflow state에 exact-once mailbox와 prepared lifecycle을 계산합니다.

        Args:
            current: SkillStateStore가 optimistic retry마다 제공하는 latest snapshot입니다.

        Returns:
            Concurrent sibling field와 owner lifecycle을 보존한 새 skill-state object입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Retry 중 owner identity 또는 mailbox shape가
                invariant를 벗어나면 발생합니다.
        """
        self._validate_owner(current.get("owner_lifecycle"))
        next_state = dict(current)
        mailbox = self._mailbox(current.get("monitor_mailbox"))
        acknowledged_event_id = self._event_id(current.get("monitor_event_ack"))
        pending = mailbox["pending_events"]
        seen = mailbox["seen_event_ids"]
        if not isinstance(pending, list) or not isinstance(seen, list):
            raise MonitorRuntimeIdentityMismatch("monitor mailbox is not normalized")
        migrated_event_ids: list[str] = []
        staged_event_ids: list[str] = []
        inserted = False
        for event in self._migrated_events:
            event_id = self._event_id(event)
            if not event_id or event_id == acknowledged_event_id:
                continue
            migrated_event_ids.append(event_id)
            if event_id in seen:
                continue
            pending.append(dict(event))
            seen.append(event_id)
            staged_event_ids.append(event_id)
            inserted = True
        if inserted or current.get("monitor_mailbox") is not None:
            mailbox["updated_at_epoch"] = self._mailbox_updated_at_epoch
            next_state["monitor_mailbox"] = mailbox
        prepared_receipt = dict(self._receipt)
        prepared_receipt.update(
            {
                "state": "prepared",
                "session_id": self._session_id,
                "workflow_id": self._workflow_id,
                "worktree": self._worktree,
                "prepared_at": self._prepared_at,
                "migrated_event_ids": list(dict.fromkeys(migrated_event_ids)),
                "staged_event_ids": staged_event_ids,
            }
        )
        next_state["monitor_runtime_handoff"] = prepared_receipt
        return next_state

    def _validate_owner(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("workflow-local owner lifecycle is missing")
        if value.get("state") not in self._OWNER_STATES:
            raise MonitorRuntimeIdentityMismatch("owner lifecycle state is invalid")
        if value.get("owner_session_id") != self._session_id:
            raise MonitorRuntimeIdentityMismatch("owner session identity mismatch")

    def _mailbox(self, value: object) -> dict[str, object]:
        if value is None:
            return {
                "pending_events": [],
                "seen_event_ids": [],
                "active_claim": None,
            }
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("monitor mailbox must be an object")
        pending = value.get("pending_events", [])
        seen = value.get("seen_event_ids", [])
        active_claim = value.get("active_claim")
        if not isinstance(pending, list) or any(
            not isinstance(event, Mapping) for event in pending
        ):
            raise MonitorRuntimeIdentityMismatch(
                "monitor mailbox pending events must be object array"
            )
        if not isinstance(seen, list) or any(not isinstance(event_id, str) for event_id in seen):
            raise MonitorRuntimeIdentityMismatch(
                "monitor mailbox seen event identities must be string array"
            )
        if active_claim is not None and not isinstance(active_claim, Mapping):
            raise MonitorRuntimeIdentityMismatch(
                "monitor mailbox active claim must be an object or null"
            )
        return {
            **value,
            "pending_events": [dict(event) for event in pending],
            "seen_event_ids": list(seen),
            "active_claim": dict(active_claim) if isinstance(active_claim, Mapping) else None,
        }

    def _event_id(self, value: object) -> str:
        if not isinstance(value, Mapping):
            return ""
        event_id = value.get("event_id")
        return event_id if isinstance(event_id, str) and event_id else ""


class MonitorHandoffCompletedMutation:
    """Prepared receipt와 exact handoff identity가 같은 경우에만 완료로 전이합니다."""

    def __init__(
        self,
        *,
        handoff_id: str,
        completed_at: str,
        retired_detached_pids: tuple[int, ...],
        retired_labels: tuple[str, ...],
        removed_state_paths: tuple[str, ...],
    ) -> None:
        """Deletion read-back 뒤 한 번 캡처한 completion evidence를 고정합니다.

        Args:
            handoff_id: Prepared transaction과 동일해야 하는 fencing identity입니다.
            completed_at: Retry 밖에서 한 번 캡처한 UTC timestamp입니다.
            retired_detached_pids: Exact plan상 종료가 read-back된 process IDs입니다.
            retired_labels: Exact plan상 unloaded가 read-back된 LaunchAgent labels입니다.
            removed_state_paths: 실제 unlink가 끝난 obsolete state paths입니다.
        """
        self._handoff_id = handoff_id
        self._completed_at = completed_at
        self._retired_detached_pids = retired_detached_pids
        self._retired_labels = retired_labels
        self._removed_state_paths = removed_state_paths

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Exact prepared lifecycle만 completed receipt로 바꿉니다.

        Args:
            current: SkillStateStore가 optimistic retry마다 제공하는 latest snapshot입니다.

        Returns:
            Unrelated workflow state를 보존한 completed handoff snapshot입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Prepared receipt가 없거나 다른 handoff이면
                발생합니다.
        """
        handoff = current.get("monitor_runtime_handoff")
        if not isinstance(handoff, Mapping):
            raise MonitorRuntimeIdentityMismatch("prepared monitor handoff is missing")
        if handoff.get("handoff_id") != self._handoff_id:
            raise MonitorRuntimeIdentityMismatch("monitor handoff fencing identity mismatch")
        if handoff.get("state") not in {"prepared", "completed"}:
            raise MonitorRuntimeIdentityMismatch("monitor handoff lifecycle is invalid")
        completed = dict(handoff)
        completed.update(
            {
                "state": "completed",
                "completed_at": self._completed_at,
                "retired_detached_pids": list(self._retired_detached_pids),
                "retired_labels": list(self._retired_labels),
                "removed_state_paths": list(self._removed_state_paths),
                "live_rescan_required": bool(self._removed_state_paths),
            }
        )
        return {**current, "monitor_runtime_handoff": completed}
