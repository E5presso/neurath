"""Live evidence로 exact workflow의 current monitor event를 ACK합니다."""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from monitor_observation_store import MonitorObservationStore
from monitor_runtime_resources import MonitorRuntimeResources

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_harness.session_kernel import SessionKernelError, SessionLocator, WorkflowId
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import WorktreeRegistryError


class MonitorAcknowledgementError(RuntimeError):
    """ACK input, identity, evidence 또는 optimistic precondition 위반입니다."""


class MonitorAcknowledgementConflict(MonitorAcknowledgementError):
    """Live read-back 중 workflow revision이 바뀌어 caller 재실행이 필요합니다."""


class ExpectedMonitorRoute:
    """Canonical workflow와 runtime resource에 결속된 monitor route입니다."""

    __slots__ = (
        "observation_resource",
        "pr_number",
        "repo",
        "runtime_id",
        "session_id",
        "workflow_id",
        "worktree_id",
    )

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        runtime_id: str,
        worktree_id: str,
        observation_resource: Mapping[str, object],
        repo: str,
        pr_number: int,
    ) -> None:
        """Validated route identity와 GitHub read-back target을 고정합니다.

        Args:
            session_id: Canonical workflow를 소유한 exact root session입니다.
            workflow_id: ACK가 갱신할 process-ticket workflow입니다.
            runtime_id: Observation을 발행한 monitor process identity입니다.
            worktree_id: Git topology로 검증한 opaque worktree resource입니다.
            observation_resource: Local cache를 path 없이 식별하는 resource receipt입니다.
            repo: Live read-back 대상 GitHub repository입니다.
            pr_number: Live read-back 대상 pull request 번호입니다.
        """
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "runtime_id", runtime_id)
        object.__setattr__(self, "worktree_id", worktree_id)
        object.__setattr__(self, "observation_resource", dict(observation_resource))
        object.__setattr__(self, "repo", repo)
        object.__setattr__(self, "pr_number", pr_number)

    session_id: str
    """Canonical ACK workflow를 소유한 root session identity입니다."""
    workflow_id: str
    """ACK mutation이 적용될 exact process-ticket workflow identity입니다."""
    runtime_id: str
    """Local observation을 발행한 monitor process identity입니다."""
    worktree_id: str
    """Raw path를 대신해 local resource를 결속하는 Git-derived identity입니다."""
    observation_resource: dict[str, object]
    """Resolved cache가 canonical subscription과 같음을 증명하는 resource receipt입니다."""
    repo: str
    """선택된 event를 live 검증할 GitHub repository입니다."""
    pr_number: int
    """선택된 event를 live 검증할 pull request 번호입니다."""

    @classmethod
    def from_skill_state(
        cls,
        current: Mapping[str, object],
        *,
        workflow_id: WorkflowId,
        resources: MonitorRuntimeResources,
    ) -> ExpectedMonitorRoute:
        """Current subscription을 exact runtime-derived resource에 대조합니다.

        Args:
            current: Event와 subscription을 함께 선택한 workflow skill state입니다.
            workflow_id: Caller가 명시한 exact workflow selector입니다.
            resources: Runtime identity와 Git cwd로 파생된 local resource handle입니다.

        Returns:
            Canonical route와 resolved observation resource가 일치하는 immutable route입니다.

        Raises:
            MonitorAcknowledgementError: Subscription이 없거나 route identity가 다를 때
                발생합니다.
        """
        value = current.get("monitor_event_subscription")
        if not isinstance(value, Mapping):
            raise MonitorAcknowledgementError(
                "monitor_event_subscription is missing from exact workflow"
            )
        runtime_id = value.get("runtime_id")
        repo = value.get("repo")
        pr_number = value.get("pr_number")
        if not isinstance(runtime_id, str) or not runtime_id:
            raise MonitorAcknowledgementError("monitor_event_subscription runtime_id is invalid")
        if not isinstance(repo, str) or not repo:
            raise MonitorAcknowledgementError("monitor_event_subscription repo is invalid")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise MonitorAcknowledgementError("monitor_event_subscription pr_number is invalid")
        expected: dict[str, object] = {
            "session_id": resources.session_id,
            "workflow_id": str(workflow_id),
            "worktree_id": resources.worktree_id,
            "observation_resource": resources.observation_resource(),
        }
        for field, expected_value in expected.items():
            if value.get(field) != expected_value:
                raise MonitorAcknowledgementError(
                    f"monitor_event_subscription {field} identity mismatch"
                )
        return cls(
            session_id=resources.session_id,
            workflow_id=str(workflow_id),
            runtime_id=runtime_id,
            worktree_id=resources.worktree_id,
            observation_resource=resources.observation_resource(),
            repo=repo,
            pr_number=pr_number,
        )

    def validate_observation(self, observation: Mapping[str, object]) -> None:
        """Resolved cache가 canonical expected route의 exact producer인지 검증합니다.

        Args:
            observation: `MonitorObservationStore`에서 읽은 process-local snapshot입니다.

        Raises:
            MonitorAcknowledgementError: Snapshot producer 또는 GitHub target이 route와
                다를 때 발생합니다.
        """
        expected: dict[str, object] = {
            "provider": "local-pr-monitor",
            "repo": self.repo,
            "pr_number": self.pr_number,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "runtime_id": self.runtime_id,
            "worktree_id": self.worktree_id,
        }
        for field, expected_value in expected.items():
            if observation.get(field) != expected_value:
                raise MonitorAcknowledgementError(
                    f"local monitor observation {field} identity mismatch"
                )

    def __setattr__(self, name: str, value: object) -> None:
        """생성 후 expected route mutation을 거부합니다.

        Args:
            name: 변경을 시도한 route attribute입니다.
            value: Attribute에 대입하려 한 값입니다.

        Raises:
            AttributeError: Expected route는 선택 뒤 변경할 수 없습니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class MonitorEventSelection:
    """External read-back 전에 고정한 event와 workflow revision입니다."""

    __slots__ = ("event", "monitor_state", "workflow_revision")

    def __init__(
        self,
        event: Mapping[str, object],
        monitor_state: Mapping[str, object],
        workflow_revision: int,
    ) -> None:
        """선택된 event, observation, revision을 하나의 snapshot으로 고정합니다.

        Args:
            event: Canonical mailbox에도 존재하는 exact occurrence입니다.
            monitor_state: Route validation을 통과한 process-local observation입니다.
            workflow_revision: External read-back 뒤 CAS에 사용할 selected revision입니다.
        """
        object.__setattr__(self, "event", dict(event))
        object.__setattr__(self, "monitor_state", dict(monitor_state))
        object.__setattr__(self, "workflow_revision", workflow_revision)

    event: dict[str, object]
    """Canonical mailbox와 local observation에서 일치한 exact event입니다."""
    monitor_state: dict[str, object]
    """Expected route의 producer identity를 통과한 observation snapshot입니다."""
    workflow_revision: int
    """External read-back 전에 선택해 ACK CAS에 그대로 제출할 revision입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """External read-back 중 selection mutation을 거부합니다.

        Args:
            name: 변경을 시도한 selection attribute입니다.
            value: Attribute에 대입하려 한 값입니다.

        Raises:
            AttributeError: Selection은 외부 I/O 전에 고정되어야 합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class MonitorAcknowledgementMutation:
    """선택된 event가 그대로일 때만 ACK와 mailbox 정리를 pure하게 계산합니다."""

    def __init__(
        self,
        *,
        event_id: str,
        acknowledgement: Mapping[str, object],
    ) -> None:
        """ACK가 소비할 exact occurrence와 검증된 receipt를 고정합니다.

        Args:
            event_id: Mailbox에서 제거할 exact occurrence identity입니다.
            acknowledgement: External read-back을 완료한 canonical ACK receipt입니다.
        """
        self._event_id = event_id
        self._acknowledgement = dict(acknowledgement)

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current mailbox를 확인하고 ACK transition을 pure하게 계산합니다.

        Args:
            current: Selected revision과 비교된 workflow skill state입니다.

        Returns:
            Exact pending occurrence를 소비하고 ACK를 기록한 다음 state입니다.

        Raises:
            MonitorAcknowledgementConflict: Selected occurrence가 더는 current가 아닐 때
                발생합니다.
            MonitorAcknowledgementError: Mailbox queue shape가 손상됐을 때 발생합니다.
        """
        existing = current.get("monitor_event_ack")
        if isinstance(existing, Mapping) and dict(existing) == self._acknowledgement:
            return current
        mailbox = _mailbox(current)
        if not _mailbox_contains(mailbox, self._event_id):
            raise MonitorAcknowledgementConflict(
                f"monitor event {self._event_id} is no longer current"
            )
        pending = mailbox["pending_events"]
        if not isinstance(pending, list):
            raise MonitorAcknowledgementError("monitor pending event queue is invalid")
        mailbox["pending_events"] = [
            item
            for item in pending
            if not isinstance(item, Mapping) or item.get("event_id") != self._event_id
        ]
        next_state = dict(current)
        next_state["monitor_event_ack"] = dict(self._acknowledgement)
        next_state.pop("monitor_event_wait", None)
        next_state["monitor_mailbox"] = mailbox
        return next_state


class MonitorWaitMutation:
    """Matching current event에만 reviewer-owned external wait를 기록합니다."""

    def __init__(self, *, event_id: str, wait: Mapping[str, object]) -> None:
        """External wait를 결속할 exact occurrence와 receipt를 고정합니다.

        Args:
            event_id: 소비하지 않고 wait 상태로 전이할 occurrence identity입니다.
            wait: Reviewer-owned unresolved state를 live 검증한 typed receipt입니다.
        """
        self._event_id = event_id
        self._wait = dict(wait)

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current occurrence를 보존하며 external wait transition을 계산합니다.

        Args:
            current: Selected revision과 비교된 workflow skill state입니다.

        Returns:
            Mailbox event는 유지하고 typed wait만 기록한 다음 state입니다.

        Raises:
            MonitorAcknowledgementConflict: Selected occurrence가 더는 current가 아닐 때
                발생합니다.
        """
        mailbox = _mailbox(current)
        if not _mailbox_contains(mailbox, self._event_id):
            raise MonitorAcknowledgementConflict(
                f"monitor event {self._event_id} is no longer current"
            )
        next_state = dict(current)
        next_state["monitor_event_wait"] = dict(self._wait)
        return next_state


def _mailbox(current: Mapping[str, object]) -> dict[str, object]:
    value = current.get("monitor_mailbox")
    if not isinstance(value, Mapping):
        raise MonitorAcknowledgementError("monitor mailbox is missing")
    mailbox = dict(value)
    if not isinstance(mailbox.get("pending_events"), list):
        raise MonitorAcknowledgementError("monitor pending event queue is invalid")
    claim = mailbox.get("active_claim")
    if claim is not None and not isinstance(claim, Mapping):
        raise MonitorAcknowledgementError("monitor active claim is invalid")
    return mailbox


def _mailbox_contains(mailbox: Mapping[str, object], event_id: str) -> bool:
    claim = mailbox.get("active_claim")
    if isinstance(claim, Mapping):
        event = claim.get("event")
        if isinstance(event, Mapping) and event.get("event_id") == event_id:
            return True
    pending = mailbox.get("pending_events")
    return isinstance(pending, list) and any(
        isinstance(item, Mapping) and item.get("event_id") == event_id for item in pending
    )


class MonitorEventAcknowledger:
    """External read-back과 canonical workflow CAS를 분리해 ACK합니다."""

    def __init__(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        resources: MonitorRuntimeResources,
        *,
        event_id: str | None = None,
    ) -> None:
        """Runtime-bound handle, exact workflow와 derived resource를 고정합니다.

        Args:
            handle: Current actor authority에 attach된 canonical session handle입니다.
            workflow_id: ACK mutation을 받을 exact process-ticket workflow입니다.
            resources: Runtime identity와 Git cwd로 파생한 monitor resource handle입니다.
            event_id: 명시하면 해당 mailbox occurrence만 선택하는 stable identity입니다.

        Raises:
            MonitorAcknowledgementError: Handle session과 resource session이 다를 때
                발생합니다.
        """
        if str(handle.session_id) != resources.session_id:
            raise MonitorAcknowledgementError(
                "state handle and monitor resource session_id identity mismatch"
            )
        self._workflow_id = workflow_id
        self._store = SkillStateStore(handle, workflow_id)
        self._resources = resources
        self._observations = MonitorObservationStore(resources.observation_path)
        self._event_id = event_id

    def acknowledge(self) -> dict[str, object]:
        """최신 처리 대상 event를 evidence와 함께 process-state에 기록합니다.

        Returns:
            저장된 event id, reason, evidence, 시각을 담은 ACK입니다.

        Raises:
            ValueError: 최신 event가 ACK 대상이 아니거나 evidence가 비었을 때 발생합니다."""
        selected = self._select_event()
        monitor_state = selected.monitor_state
        event = selected.event
        if not isinstance(event, dict) or event.get("monitor_event") not in {"event", "terminal"}:
            raise ValueError("latest monitor event must be an ACK-supported event")
        if event.get("monitor_event") == "terminal" and event.get("reason") not in {
            "mergeable-clean",
            "merged",
            "closed-without-merge",
        }:
            raise ValueError("terminal event is not ACK-supported")
        event_id = event.get("event_id")
        reason = event.get("reason")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("latest work event must include event_id")
        if not isinstance(reason, str) or not reason:
            raise ValueError("latest work event must include reason")
        evidence = MonitorEventEvidenceCollector(self._resources.worktree).collect(
            monitor_state,
            event,
        )
        acknowledgement: dict[str, object] = {
            "event_id": event_id,
            "reason": reason,
            "evidence": evidence,
            "acknowledged_at": datetime.now(UTC).isoformat(),
        }

        try:
            self._store.compare_and_update(
                selected.workflow_revision,
                MonitorAcknowledgementMutation(
                    event_id=event_id,
                    acknowledgement=acknowledgement,
                ),
            )
        except SkillStateConflict as error:
            raise MonitorAcknowledgementConflict(
                "workflow changed during live ACK read-back; rerun the command"
            ) from error
        return acknowledgement

    def _select_event(self) -> MonitorEventSelection:
        """한 workflow revision에서 route, observation, current event를 선택합니다."""
        snapshot = self._store.read()
        expected_route = ExpectedMonitorRoute.from_skill_state(
            snapshot.skill_state,
            workflow_id=self._workflow_id,
            resources=self._resources,
        )
        monitor_state = self._monitor_state(expected_route)
        mailbox = _mailbox(snapshot.skill_state)
        candidates: list[Mapping[str, object]] = []
        claim = mailbox.get("active_claim")
        if isinstance(claim, Mapping) and isinstance(claim.get("event"), Mapping):
            candidates.append(claim["event"])
        pending = mailbox.get("pending_events")
        if isinstance(pending, list):
            candidates.extend(item for item in pending if isinstance(item, Mapping))
        local_event = monitor_state.get("last_event")
        if isinstance(local_event, Mapping):
            candidates.append(local_event)
        event_id = self._event_id
        if event_id is None and candidates:
            raw_id = candidates[0].get("event_id")
            event_id = raw_id if isinstance(raw_id, str) else None
        for event in candidates:
            if event_id and event.get("event_id") == event_id:
                if not _mailbox_contains(mailbox, event_id):
                    break
                return MonitorEventSelection(
                    event,
                    monitor_state,
                    snapshot.workflow_revision,
                )
        raise MonitorAcknowledgementError(
            f"monitor event {event_id or '<latest>'} is not current in exact workflow"
        )

    def _monitor_state(self, expected_route: ExpectedMonitorRoute) -> dict[str, object]:
        """Resolved observation resource를 selected canonical route에 대조합니다."""
        state = self._observations.read()
        expected_route.validate_observation(state)
        return state


class MonitorEventWaitRecorder:
    """Reviewer-owned resolution만 남은 event를 소비하지 않고 typed wait로 기록합니다."""

    def __init__(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        resources: MonitorRuntimeResources,
        *,
        event_id: str | None = None,
    ) -> None:
        """Exact route selector와 external-wait mutation port를 결합합니다.

        Args:
            handle: Current actor authority에 attach된 canonical session handle입니다.
            workflow_id: Wait receipt를 기록할 exact process-ticket workflow입니다.
            resources: Observation과 command cwd를 제공하는 derived resource handle입니다.
            event_id: 명시하면 해당 review event만 wait 대상으로 선택합니다.

        Raises:
            MonitorAcknowledgementError: Handle과 resource session identity가 다를 때
                발생합니다.
        """
        self._acknowledger = MonitorEventAcknowledger(
            handle,
            workflow_id,
            resources,
            event_id=event_id,
        )
        self._store = SkillStateStore(handle, workflow_id)
        self._resources = resources

    def record(self) -> dict[str, object]:
        """Live unresolved-thread evidence를 matching occurrence wait로 저장합니다.

        Returns:
            Event id, reason, wait reason, live evidence를 담은 typed wait입니다.

        Raises:
            ValueError: Event가 review-owned wait 대상이 아니거나 identity가 없을 때 발생합니다.
            subprocess.CalledProcessError: Live comment read-back 실행이 실패할 때 발생합니다.
        """
        selected = self._acknowledger._select_event()
        monitor_state = selected.monitor_state
        event = selected.event
        if not isinstance(event, dict) or event.get("monitor_event") != "event":
            raise ValueError("external wait requires a monitor work event")
        event_id = event.get("event_id")
        reason = event.get("reason")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("external wait event must include event_id")
        if reason not in {
            "comments-changed",
            "review-blocked",
        }:
            raise ValueError("external wait is only valid for review-owned events")
        evidence = MonitorEventEvidenceCollector(
            self._resources.worktree
        ).collect_external_review_wait(monitor_state, event)
        observed_snapshot = self._observed_snapshot(evidence)
        observed_fingerprint = {
            "comments": {"ch1": {}, "ch2": {}, "ch3": {}},
        }
        wait: dict[str, object] = {
            "event_id": event_id,
            "reason": reason,
            "wait_reason": "unresolved-review-threads",
            "evidence": evidence,
            "observed_snapshot": observed_snapshot,
            "observed_fingerprint": observed_fingerprint,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        try:
            self._store.compare_and_update(
                selected.workflow_revision,
                MonitorWaitMutation(event_id=event_id, wait=wait),
            )
        except SkillStateConflict as error:
            raise MonitorAcknowledgementConflict(
                "workflow changed during live wait read-back; rerun the command"
            ) from error
        return wait

    def _observed_snapshot(self, evidence: list[str]) -> dict[str, object]:
        """Typed wait evidence에서 monitor 비교용 live snapshot을 복원합니다.

        Args:
            evidence: Live collector가 발급한 typed evidence입니다.

        Returns:
            Monitor summary와 같은 key를 가진 observed snapshot입니다.

        Raises:
            ValueError: 필수 snapshot evidence가 없거나 정수가 잘못됐을 때 발생합니다.
        """
        values: dict[str, str] = {}
        for item in evidence:
            if not item.startswith("wait_readback:"):
                continue
            key, separator, value = item.removeprefix("wait_readback:").partition("=")
            if separator:
                values[key] = value
        required = {
            "mergeState",
            "reviewDecision",
            "failedChecks",
            "pendingChecks",
            "headRefOid",
            "unresolvedReviewThreads",
        }
        if not required.issubset(values):
            raise ValueError("external wait evidence is missing observed snapshot fields")
        try:
            failed_checks = int(values["failedChecks"])
            pending_checks = int(values["pendingChecks"])
            unresolved_threads = int(values["unresolvedReviewThreads"])
        except ValueError as exc:
            raise ValueError("external wait snapshot counts must be integers") from exc
        return {
            "mergeState": values["mergeState"],
            "reviewDecision": values["reviewDecision"],
            "failedChecks": failed_checks,
            "pendingChecks": pending_checks,
            "headRefOid": values["headRefOid"],
            "unresolvedReviewThreads": unresolved_threads,
        }


class MonitorEventEvidenceCollector:
    """Event reason별 live GitHub/read-back evidence를 직접 수집합니다."""

    def __init__(self, worktree: Path) -> None:
        """검증 command를 실행할 ticket worktree를 고정합니다.

        Args:
            worktree: PR branch와 monitor scripts가 있는 ticket worktree입니다."""
        self._worktree = worktree

    def collect(
        self,
        monitor_state: dict[str, object],
        event: dict[str, object],
    ) -> list[str]:
        """Event reason에 맞는 외부 read-back을 실행합니다.

        Args:
            monitor_state: repository와 PR 번호를 담은 monitor state입니다.
            event: ACK 대상 최신 work event입니다.

        Returns:
            Stop hook과 monitor가 소비할 검증된 evidence 목록입니다.

        Raises:
            ValueError: 지원하지 않는 reason이거나 live state가 미처리 상태일 때 발생합니다.
            subprocess.CalledProcessError: GitHub 또는 comment collector 실행이 실패할 때 발생합니다."""
        reason = event.get("reason")
        repo = monitor_state.get("repo")
        pr_number = monitor_state.get("pr_number")
        if not isinstance(repo, str) or not repo or not isinstance(pr_number, int):
            raise ValueError("monitor state must include repo and numeric pr_number")
        if reason == "ci-failed":
            return self._collect_ci_readback(repo, pr_number)
        if reason == "merge-dirty":
            return self._collect_merge_readback(repo, pr_number)
        if reason == "comments-changed":
            return self._collect_comment_readback(repo, pr_number)
        if reason == "review-blocked":
            return [
                *self._collect_comment_readback(repo, pr_number),
                *self._collect_review_readback(repo, pr_number),
            ]
        if reason == "mergeable-clean":
            return self._collect_mergeable_terminal_readback(repo, pr_number, event)
        if reason in {"merged", "closed-without-merge"}:
            return self._collect_external_terminal_readback(repo, pr_number, event)
        raise ValueError(f"unsupported monitor work event reason: {reason}")

    def _collect_external_terminal_readback(
        self,
        repo: str,
        pr_number: int,
        event: dict[str, object],
    ) -> list[str]:
        """Active owner가 처리한 merged/closed terminal의 exact live 상태를 검증합니다."""
        payload = self._gh_pr_view(repo, pr_number, "state,headRefOid")
        state = payload.get("state")
        head_oid = payload.get("headRefOid")
        event_snapshot = event.get("snapshot")
        expected_head = (
            event_snapshot.get("headRefOid") if isinstance(event_snapshot, dict) else None
        )
        expected_state = "MERGED" if event.get("reason") == "merged" else "CLOSED"
        if state != expected_state:
            raise ValueError(f"terminal live PR state is not {expected_state}")
        if not isinstance(head_oid, str) or not head_oid or head_oid != expected_head:
            raise ValueError("terminal head no longer matches the delivered event")
        return [
            f"terminal_readback:state={expected_state}",
            f"terminal_readback:headRefOid={head_oid}",
        ]

    def _collect_mergeable_terminal_readback(
        self,
        repo: str,
        pr_number: int,
        event: dict[str, object],
    ) -> list[str]:
        comments = self._collect_comment_readback(repo, pr_number)
        payload = self._gh_pr_view(
            repo,
            pr_number,
            "state,mergeStateStatus,reviewDecision,headRefOid,statusCheckRollup",
        )
        state = payload.get("state")
        merge_state = payload.get("mergeStateStatus")
        review_decision = payload.get("reviewDecision")
        head_oid = payload.get("headRefOid")
        checks = payload.get("statusCheckRollup")
        event_snapshot = event.get("snapshot")
        expected_head = (
            event_snapshot.get("headRefOid") if isinstance(event_snapshot, dict) else None
        )
        if not isinstance(head_oid, str) or not head_oid or head_oid != expected_head:
            raise ValueError("mergeable terminal head no longer matches the delivered event")
        if state == "MERGED":
            return [
                *comments,
                "terminal_readback:state=MERGED",
                f"terminal_readback:headRefOid={head_oid}",
            ]
        if state != "OPEN" or merge_state != "CLEAN" or review_decision != "APPROVED":
            raise ValueError("mergeable terminal live PR state is not clean and approved")
        if not isinstance(checks, list):
            raise TypeError("mergeable terminal read-back did not return statusCheckRollup")
        failed, pending = self._check_counts(checks)
        if failed or pending:
            raise ValueError(
                f"mergeable terminal checks are not settled failed={failed} pending={pending}"
            )
        return [
            *comments,
            "terminal_readback:state=OPEN",
            "terminal_readback:mergeState=CLEAN",
            "terminal_readback:reviewDecision=APPROVED",
            "terminal_readback:failedChecks=0",
            "terminal_readback:pendingChecks=0",
            f"terminal_readback:headRefOid={head_oid}",
        ]

    def _collect_comment_readback(self, repo: str, pr_number: int) -> list[str]:
        total, unresolved = self._comment_readback_counts(repo, pr_number)
        if total != 0:
            raise ValueError("comment event still has pending human comments")
        if unresolved != 0:
            raise ValueError("comment event still has unresolved review threads")
        return [
            "collect_comments:TOTAL=0",
            "collect_comments:UNRESOLVED_THREADS_COUNT=0",
        ]

    def collect_external_review_wait(
        self,
        monitor_state: dict[str, object],
        event: dict[str, object],
    ) -> list[str]:
        """처리할 댓글은 없고 reviewer resolution만 남았음을 live 검증합니다.

        Args:
            monitor_state: Repository와 PR 번호를 담은 monitor state입니다.
            event: External wait를 기록할 최신 monitor event입니다.

        Returns:
            Pending comment 0개와 unresolved thread 수를 담은 typed evidence입니다.

        Raises:
            ValueError: Event reason 또는 live comment/thread 상태가 wait 조건과 다를 때 발생합니다.
            subprocess.CalledProcessError: Live comment collector 실행이 실패할 때 발생합니다.
        """
        repo = monitor_state.get("repo")
        pr_number = monitor_state.get("pr_number")
        if not isinstance(repo, str) or not repo or not isinstance(pr_number, int):
            raise ValueError("monitor state must include repo and numeric pr_number")
        if event.get("reason") not in {
            "comments-changed",
            "review-blocked",
        }:
            raise ValueError("external wait is only valid for review-owned events")
        total, unresolved = self._comment_readback_counts(repo, pr_number)
        if total != 0:
            raise ValueError("external wait still has pending human comments")
        if unresolved <= 0:
            raise ValueError("external wait requires unresolved review threads")
        payload = self._gh_pr_view(
            repo,
            pr_number,
            "mergeStateStatus,reviewDecision,headRefOid,statusCheckRollup",
        )
        checks = payload.get("statusCheckRollup")
        if not isinstance(checks, list):
            raise TypeError("external wait read-back did not return statusCheckRollup")
        failed, pending = self._check_counts(checks)
        return [
            "collect_comments:TOTAL=0",
            f"collect_comments:UNRESOLVED_THREADS_COUNT={unresolved}",
            f"wait_readback:mergeState={payload.get('mergeStateStatus', '')}",
            f"wait_readback:reviewDecision={payload.get('reviewDecision', '')}",
            f"wait_readback:failedChecks={failed}",
            f"wait_readback:pendingChecks={pending}",
            f"wait_readback:headRefOid={payload.get('headRefOid', '')}",
            f"wait_readback:unresolvedReviewThreads={unresolved}",
        ]

    def _comment_readback_counts(self, repo: str, pr_number: int) -> tuple[int, int]:
        script = __import__("scripts._neurath_paths", fromlist=["asset_path"]).asset_path(self._worktree, ".agents/skills/monitor-pr/scripts/collect_comments.sh")
        environment = {**os.environ, "REPO": repo, "PR_NUMBER": str(pr_number)}
        result = subprocess.run(
            ["bash", str(script)],
            cwd=self._worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        match = re.search(r"(?m)^TOTAL=(\d+)$", result.stdout)
        if match is None:
            raise ValueError("comment collector did not report TOTAL")
        unresolved = re.search(r"(?m)^UNRESOLVED_THREADS_COUNT=(\d+)$", result.stdout)
        if unresolved is None:
            raise ValueError("comment collector did not report unresolved review threads")
        return int(match.group(1)), int(unresolved.group(1))

    def _collect_review_readback(self, repo: str, pr_number: int) -> list[str]:
        payload = self._gh_pr_view(repo, pr_number, "reviewDecision")
        review_decision = payload.get("reviewDecision")
        if review_decision != "APPROVED":
            raise ValueError(f"review event is still {review_decision or 'unapproved'}")
        return ["review_readback:reviewDecision=APPROVED"]

    def _collect_ci_readback(self, repo: str, pr_number: int) -> list[str]:
        payload = self._gh_pr_view(repo, pr_number, "statusCheckRollup")
        checks = payload.get("statusCheckRollup")
        if not isinstance(checks, list):
            raise TypeError("CI read-back did not return statusCheckRollup")
        failed, _ = self._check_counts(checks)
        if failed:
            raise ValueError(f"CI event still has {failed} failed checks")
        return ["ci_readback:failedChecks=0"]

    def _check_counts(self, checks: list[object]) -> tuple[int, int]:
        latest: dict[str, Mapping[str, object]] = {}
        for index, raw_check in enumerate(checks):
            if not isinstance(raw_check, Mapping):
                continue
            name = (
                self._text(raw_check.get("name"))
                or self._text(raw_check.get("context"))
                or f"__anonymous_{index}"
            )
            previous = latest.get(name)
            if previous is None or self._check_timestamp(raw_check) >= self._check_timestamp(
                previous
            ):
                latest[name] = raw_check
        blocking_conclusions = {
            "ACTION_REQUIRED",
            "TIMED_OUT",
            "CANCELLED",
            "FAILURE",
            "STARTUP_FAILURE",
            "STALE",
        }
        nonblocking_workflows = {"Auto PR Code Review", "AI Review Auto Approve"}
        failed = 0
        pending = 0
        for check in latest.values():
            workflow = self._text(check.get("workflowName"))
            conclusion = self._text(check.get("conclusion"))
            state = self._text(check.get("state"))
            status = self._text(check.get("status"))
            if workflow not in nonblocking_workflows and (
                conclusion in blocking_conclusions or state in {"FAILURE", "ERROR"}
            ):
                failed += 1
            if (status and status != "COMPLETED") or state in {"EXPECTED", "PENDING"}:
                pending += 1
        return failed, pending

    def _check_timestamp(self, check: Mapping[str, object]) -> str:
        return (
            self._text(check.get("startedAt"))
            or self._text(check.get("createdAt"))
            or self._text(check.get("completedAt"))
        )

    def _text(self, value: object) -> str:
        return value if isinstance(value, str) else ""

    def _collect_merge_readback(self, repo: str, pr_number: int) -> list[str]:
        payload = self._gh_pr_view(repo, pr_number, "mergeStateStatus")
        merge_state = payload.get("mergeStateStatus")
        if not isinstance(merge_state, str) or merge_state == "DIRTY":
            raise ValueError("merge event is still DIRTY")
        return [f"merge_readback:mergeState={merge_state}"]

    def _gh_pr_view(self, repo: str, pr_number: int, field: str) -> dict[str, object]:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", field],
            cwd=self._worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise TypeError("GitHub PR read-back must be a JSON object")
        return payload


def main(arguments: Sequence[str] | None = None) -> int:
    """Runtime identity와 workflow selector로 exact monitor event를 ACK합니다.

    Args:
        arguments: Process argv 대신 주입할 optional public CLI arguments입니다.

    Returns:
        ACK 또는 wait commit 성공은 0, typed input·identity·conflict 실패는 2입니다.
    """
    parser = argparse.ArgumentParser(description="Acknowledge a processed monitor work event.")
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument(
        "--event-id",
        help="ACK an exact current occurrence instead of implicit latest.",
    )
    parser.add_argument(
        "--external-wait",
        action="store_true",
        help="Record a live-verified reviewer-owned wait without consuming the event.",
    )
    args = parser.parse_args(arguments)
    try:
        resources = MonitorRuntimeResources.resolve(
            cwd=Path.cwd(),
            environment=os.environ,
        )
        locator = SessionLocator.from_worktree(resources.worktree)
        binding = RuntimeEnvironmentResolver().resolve(os.environ)
        handle = StateHandle.attach(locator, binding)
        workflow_id = WorkflowId(args.workflow_id)
        acknowledgement = (
            MonitorEventWaitRecorder(
                handle,
                workflow_id,
                resources,
                event_id=args.event_id,
            ).record()
            if args.external_wait
            else MonitorEventAcknowledger(
                handle,
                workflow_id,
                resources,
                event_id=args.event_id,
            ).acknowledge()
        )
    except (
        json.JSONDecodeError,
        MonitorAcknowledgementError,
        OSError,
        RuntimeIdentityError,
        SessionKernelError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        WorktreeRegistryError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(acknowledgement, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
