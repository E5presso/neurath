"""Exact-session state로 모든 foreground turn의 continuation 결정을 내립니다.

이 module은 vendor hook payload에서 runtime identity를 얻고 ``StateHandle``에
attach한 뒤, actor-scoped outer turn과 그 actor가 소유한 inner workflow를 처리합니다.
Run directory scan, global active pointer, caller-selected state path는 사용하지 않습니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TextIO

MONITOR_RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/monitor-pr/scripts"
if str(MONITOR_RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MONITOR_RUNTIME_SCRIPTS))

from monitor_runtime_resources import MonitorRuntimeResources

from scripts.agent_harness.adaptive_control import (
    ControlAction,
    EvidenceKind,
    GoalContract,
    render_socratic_question,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityError,
    AdaptiveControlAuthorityStatus,
    AdaptiveControlAuthorityVerifier,
)
from scripts.agent_harness.adaptive_control_store import AdaptiveControlStore
from scripts.agent_harness.adaptive_policy import requires_adaptive_control_for_workflow
from scripts.agent_harness.evaluation_admission import EvaluationAdmissionPolicy
from scripts.agent_harness.harness_incident import (
    HarnessIncidentValidationError,
    validate_harness_incidents,
)
from scripts.agent_harness.material_action import MaterialActionStatus
from scripts.agent_harness.monitor_liveness import (
    MonitorLease,
    MonitorLivenessError,
    MonitorLivenessValidator,
    read_monitor_observation,
)
from scripts.agent_harness.session_kernel import (
    ActorStatus,
    ActorStopped,
    DelegationStatus,
    ForegroundPromptAuthorityContext,
    ForegroundTurnClosed,
    ForegroundTurnInvalidated,
    ForegroundTurnOutcome,
    ForegroundTurnPrompted,
    ForegroundTurnStatus,
    ForegroundTurnToolObserved,
    MaterialActionAbandoned,
    MonitorWorkflowStopProjection,
    ProcessState,
    RevisionConflict,
    SessionKernel,
    SessionKernelError,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateRetryExhausted,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityBinding,
    RuntimeIdentityError,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import (
    WorktreeId,
    WorktreeIdentityResolver,
    WorktreeNotClaimed,
    WorktreeRegistry,
    WorktreeRegistryError,
)


class AgentContinuationHookError(RuntimeError):
    """Universal continuation hook이 fail-closed로 거부하는 contract violation입니다."""


class InvalidHookInput(AgentContinuationHookError):
    """Vendor hook input이 지원하는 JSON object가 아닐 때 발생합니다."""


class MonitorWorkflowInvalid(AgentContinuationHookError):
    """Workflow-local monitor state가 canonical shape를 어길 때 발생합니다."""


class AgentContinuationBlocked(AgentContinuationHookError):
    """현재 foreground turn을 안전하게 끝낼 수 없을 때 발생합니다."""


class MonitorRuntimeUnavailable(AgentContinuationHookError):
    """Registered monitor runtime을 확인하거나 재시작하지 못했을 때 발생합니다."""


class HookEvent(StrEnum):
    """Universal continuation integration이 처리하는 vendor hook event입니다."""

    SESSION_START = "SessionStart"
    """Session startup 또는 compact 이후 활성화를 관찰합니다."""
    USER_PROMPT = "UserPromptSubmit"
    """사용자 prompt가 새 owner activity를 시작했음을 나타냅니다."""
    PRE_TOOL = "PreToolUse"
    """Yield 이후의 추가 side effect가 terminal receipt를 무효화함을 나타냅니다."""
    PRE_COMPACT = "PreCompact"
    """Context compaction 직전 owner activity를 보존합니다."""
    STOP = "Stop"
    """Exact turn 종료 전에 continuation gate를 실행합니다."""
    SUBAGENT_STOP = "SubagentStop"
    """Persisted child 또는 state-free child 종료 lifecycle을 관찰합니다."""


class HookResult:
    """Hook process exit code와 protocol output을 immutable하게 묶습니다."""

    __slots__ = ("exit_code", "stderr", "stdout")

    def __init__(self, *, exit_code: int, stdout: str, stderr: str = "") -> None:
        """Hook process 결과를 생성 이후 변경할 수 없게 고정합니다.

        Args:
            exit_code: Vendor hook에 반환할 process status입니다.
            stdout: Vendor protocol이 읽을 JSON output입니다.
            stderr: Fail-closed 진단을 담는 optional text입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "stdout", stdout)
        object.__setattr__(self, "stderr", stderr)

    exit_code: int
    """Vendor hook process의 exit status입니다."""
    stdout: str
    """Vendor protocol에 전달할 JSON text입니다."""
    stderr: str
    """실패 원인을 설명하는 bounded diagnostic입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 뒤 result attribute 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Hook result는 immutable이므로 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class HookInvocation:
    """검증된 hook event와 optional turn/prompt를 보존합니다."""

    __slots__ = ("agent_id", "event", "prompt", "session_id", "turn_id")

    def __init__(
        self,
        *,
        event: HookEvent,
        session_id: str | None,
        turn_id: str | None,
        prompt: str | None,
        agent_id: str | None = None,
    ) -> None:
        """정규화된 hook invocation identity와 payload 일부를 고정합니다.

        Args:
            event: 처리할 지원 vendor hook event입니다.
            session_id: Payload가 제공한 optional session identity입니다.
            turn_id: Current native turn의 optional identity입니다.
            prompt: UserPrompt hook이 제공한 optional prompt입니다.
            agent_id: Claude subagent hook payload가 제공한 optional child identity입니다.
        """
        object.__setattr__(self, "event", event)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "turn_id", turn_id)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "agent_id", agent_id)

    event: HookEvent
    """정규화된 vendor hook event입니다."""
    session_id: str | None
    """Payload에서 읽은 optional session identity입니다."""
    turn_id: str | None
    """Vendor가 제공한 optional exact turn identity입니다."""
    prompt: str | None
    """UserPrompt hook이 제공한 optional prompt입니다."""
    agent_id: str | None
    """Claude runtime이 current subagent hook에 결속한 optional child identity입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 뒤 invocation attribute 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Hook invocation은 immutable이므로 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class GitPublicationPort(Protocol):
    """Stop gate가 worktree publication 상태를 읽는 외부 port입니다."""

    def validate_stoppable(self, worktree: Path) -> None:
        """Dirty 또는 unpublished work가 있으면 typed error를 냅니다.

        Args:
            worktree: Publication 상태를 검사할 canonical Git worktree입니다.
        """


class MonitorLivenessPort(Protocol):
    """Stop이 exact workflow monitor의 live 상태만 읽는 외부 port입니다."""

    def assert_live(
        self,
        *,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Subscription의 exact route, PID와 heartbeat freshness를 read-only 검증합니다.

        Args:
            workflow_id: Monitor가 귀속된 exact workflow identity입니다.
            subscription: Canonical workflow에 저장된 opaque monitor route입니다.
            environment: Runtime-owned session identity environment입니다.
            cwd: Hook이 실행된 current Git worktree입니다.
        """


class MonitorRecoveryPort(Protocol):
    """Non-Stop lifecycle이 dead monitor를 복구하고 fresh readback을 요구하는 port입니다."""

    def recover_if_needed(
        self,
        *,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Dead runtime만 시작하고 같은 판정의 fresh observation을 다시 검증합니다.

        Args:
            workflow_id: Monitor가 귀속된 exact workflow identity입니다.
            subscription: Canonical workflow에 저장된 opaque monitor route입니다.
            environment: Runtime-owned session identity environment입니다.
            cwd: Hook이 실행된 current Git worktree입니다.
        """


class GitPublicationInspector:
    """Git read-back으로 unpublished owner work를 fail-closed 검증합니다."""

    def validate_stoppable(self, worktree: Path) -> None:
        """Dirty files와 upstream보다 앞선 commit이 있으면 Stop을 거부합니다.

        Args:
            worktree: Git status와 upstream을 읽을 canonical worktree입니다.

        Raises:
            AgentContinuationBlocked: Worktree가 없거나 unpublished mutation이 있으면
                발생합니다.
        """
        if not worktree.is_dir():
            raise AgentContinuationBlocked(
                f"registered process-ticket worktree is missing: {worktree}"
            )
        status = self._run(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            worktree,
            allow_failure=False,
        )
        if status.strip():
            raise AgentContinuationBlocked("owner worktree has unpublished changes")
        upstream = self._run(
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
            worktree,
            allow_failure=True,
        ).strip()
        if not upstream:
            return
        ahead = self._run(
            ("git", "rev-list", "--count", f"{upstream}..HEAD"),
            worktree,
            allow_failure=False,
        ).strip()
        try:
            unpublished = int(ahead)
        except ValueError as error:
            raise AgentContinuationBlocked(
                "unpublished commit read-back was not an integer"
            ) from error
        if unpublished > 0:
            raise AgentContinuationBlocked(f"owner HEAD has {unpublished} unpublished commit(s)")

    def _run(
        self,
        command: tuple[str, ...],
        cwd: Path,
        *,
        allow_failure: bool,
    ) -> str:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and not allow_failure:
            detail = result.stderr.strip() or "git read-back failed"
            raise AgentContinuationBlocked(detail)
        return result.stdout if result.returncode == 0 else ""


class LocalMonitorRuntime:
    """Shared liveness 판정과 non-Stop local monitor recovery를 제공합니다."""

    _PROVIDER = "local-pr-monitor"

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        liveness: MonitorLivenessValidator | None = None,
    ) -> None:
        """Freshness clock과 shared liveness validator를 고정합니다.

        Args:
            clock: Heartbeat age를 계산할 caller-owned clock입니다.
            liveness: Test 또는 alternate process probe가 제공하는 optional validator입니다.
        """
        self._clock = clock
        self._liveness = liveness or MonitorLivenessValidator()

    def assert_live(
        self,
        *,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Exact session/workflow route와 process freshness를 mutation 없이 검증합니다.

        Args:
            workflow_id: Liveness를 요구하는 exact workflow identity입니다.
            subscription: Opaque resource identity가 포함된 canonical route입니다.
            environment: Vendor runtime이 제공한 session identity입니다.
            cwd: Observation resource를 Git identity로 파생할 current worktree입니다.

        Raises:
            MonitorRuntimeUnavailable: Route, PID 또는 heartbeat가 live proof를 만들지 못하면
                발생합니다.
        """
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        route = self._validated_route(workflow_id, subscription, resources)
        self._assert_live_route(route, resources)

    def recover_if_needed(
        self,
        *,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Non-Stop lifecycle에서 dead runtime을 시작하고 fresh receipt를 다시 검증합니다.

        Args:
            workflow_id: Recovery가 허용된 exact workflow identity입니다.
            subscription: Opaque resource identity가 포함된 canonical route입니다.
            environment: Vendor runtime이 제공한 session identity입니다.
            cwd: Runtime resource를 Git identity로 파생할 current worktree입니다.

        Raises:
            MonitorRuntimeUnavailable: Route, starter 또는 post-start fresh readback이 invalid하면
                발생합니다.
        """
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        route = self._validated_route(workflow_id, subscription, resources)
        try:
            self._assert_live_route(route, resources)
        except MonitorRuntimeUnavailable:
            pass
        else:
            return
        worktree = resources.worktree
        starter = __import__("scripts._neurath_paths", fromlist=["asset_path"]).asset_path(worktree, ".agents/skills/monitor-pr/scripts/start_local_pr_monitor_locked.sh")
        if not starter.is_file():
            raise MonitorRuntimeUnavailable(f"monitor starter is missing: {starter}")
        process_environment = dict(environment)
        process_environment.update({
            "REPO": str(route["repo"]),
            "PR_NUMBER": str(route["pr_number"]),
            "WORKFLOW_ID": str(workflow_id),
            "MONITOR_POLL_INTERVAL_SECONDS": str(route["poll_interval_seconds"]),
        })
        result = self._run_starter(starter, worktree, process_environment)
        if result.returncode != 0:
            detail = result.stderr.strip() or "monitor starter failed"
            raise MonitorRuntimeUnavailable(detail)
        try:
            fresh_receipt = json.loads(result.stdout)
            if not isinstance(fresh_receipt, Mapping):
                raise TypeError("monitor starter receipt must be an object")
            fresh_route = self._validated_route(workflow_id, fresh_receipt, resources)
            self._assert_same_monitor_target(route, fresh_route)
            self._assert_live_route(fresh_route, resources)
        except (
            json.JSONDecodeError,
            MonitorRuntimeUnavailable,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            raise MonitorRuntimeUnavailable(
                f"monitor starter completed without fresh live readback: {error}"
            ) from error

    def _assert_same_monitor_target(
        self,
        expected: Mapping[str, object],
        actual: Mapping[str, object],
    ) -> None:
        """Recovery가 새 process identity를 만들되 canonical PR target은 바꾸지 못하게 합니다."""
        for field in (
            "provider",
            "repo",
            "pr_number",
            "session_id",
            "workflow_id",
            "worktree_id",
            "observation_resource",
        ):
            if actual.get(field) != expected.get(field):
                raise MonitorRuntimeUnavailable(f"monitor starter changed canonical {field} target")

    def _run_starter(
        self,
        starter: Path,
        worktree: Path,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Recovery-only subprocess boundary에서 starter를 실행합니다.

        Args:
            starter: Exact worktree에서 발견한 monitor starter script입니다.
            worktree: Starter가 실행될 canonical Git worktree입니다.
            environment: Runtime identity와 exact monitor route를 포함한 environment입니다.

        Returns:
            Starter exit, fresh receipt stdout와 diagnostic stderr입니다.
        """
        return subprocess.run(
            ("bash", str(starter)),
            cwd=worktree,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
        )

    def _validated_route(
        self,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        resources: MonitorRuntimeResources,
    ) -> Mapping[str, object]:
        required = {
            "provider": self._PROVIDER,
            "session_id": resources.session_id,
            "workflow_id": str(workflow_id),
            "worktree_id": resources.worktree_id,
            "observation_resource": resources.observation_resource(),
        }
        for field, expected in required.items():
            if subscription.get(field) != expected:
                raise MonitorRuntimeUnavailable(f"monitor subscription {field} identity mismatch")
        repo = subscription.get("repo")
        pr_number = subscription.get("pr_number")
        poll_interval = subscription.get("poll_interval_seconds")
        runtime_id = subscription.get("runtime_id")
        resume_adapter = subscription.get("resume_adapter")
        if not isinstance(repo, str) or not repo.strip():
            raise MonitorRuntimeUnavailable("monitor subscription repo is missing")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise MonitorRuntimeUnavailable("monitor subscription PR number is invalid")
        if (
            not isinstance(poll_interval, int)
            or isinstance(poll_interval, bool)
            or poll_interval <= 0
        ):
            raise MonitorRuntimeUnavailable("monitor poll interval is invalid")
        if not isinstance(runtime_id, str) or not runtime_id.strip():
            raise MonitorRuntimeUnavailable("monitor runtime identity is missing")
        if resume_adapter not in {"app-server", "command", "unavailable"}:
            raise MonitorRuntimeUnavailable("monitor resume adapter is invalid")
        return dict(subscription)

    def _assert_live_route(
        self,
        subscription: Mapping[str, object],
        resources: MonitorRuntimeResources,
    ) -> None:
        try:
            raw_state = read_monitor_observation(resources.observation_path)
            self._liveness.validate(
                self._lease(subscription),
                raw_state,
                now_epoch=self._clock(),
            )
        except (
            json.JSONDecodeError,
            MonitorLivenessError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            raise MonitorRuntimeUnavailable(str(error)) from error

    def _lease(self, subscription: Mapping[str, object]) -> MonitorLease:
        try:
            return MonitorLease(
                provider=self._required_text(subscription, "provider"),
                repo=self._required_text(subscription, "repo"),
                pr_number=self._required_integer(subscription, "pr_number"),
                session_id=self._required_text(subscription, "session_id"),
                workflow_id=self._required_text(subscription, "workflow_id"),
                runtime_id=self._required_text(subscription, "runtime_id"),
                worktree_id=self._required_text(subscription, "worktree_id"),
                resume_adapter=self._required_text(subscription, "resume_adapter"),
                pid=self._required_integer(subscription, "pid"),
                manager_pid=self._optional_integer(subscription, "manager_pid"),
                poll_interval_seconds=self._required_integer(
                    subscription,
                    "poll_interval_seconds",
                ),
                minimum_heartbeat_at_epoch=self._required_number(
                    subscription,
                    "heartbeat_at_epoch",
                ),
            )
        except MonitorLivenessError as error:
            raise MonitorRuntimeUnavailable(str(error)) from error

    def _required_text(self, payload: Mapping[str, object], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise MonitorRuntimeUnavailable(f"monitor subscription {field} is missing")
        return value.strip()

    def _required_integer(self, payload: Mapping[str, object], field: str) -> int:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MonitorRuntimeUnavailable(f"monitor subscription {field} is invalid")
        return value

    def _optional_integer(self, payload: Mapping[str, object], field: str) -> int | None:
        value = payload.get(field)
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MonitorRuntimeUnavailable(f"monitor subscription {field} is invalid")
        return value

    def _required_number(self, payload: Mapping[str, object], field: str) -> float:
        value = payload.get(field)
        if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
            raise MonitorRuntimeUnavailable(f"monitor subscription {field} is invalid")
        return float(value)


class MonitorWorkflowDocument:
    """Workflow-local owner lifecycle과 mailbox shape를 엄격하게 좁힙니다."""

    def __init__(self, payload: Mapping[str, object], session_id: str) -> None:
        """Workflow-local payload를 exact session identity에 결속합니다.

        Args:
            payload: SkillStateStore에서 읽은 immutable current state입니다.
            session_id: Owner lifecycle이 귀속되어야 하는 exact session입니다.
        """
        self._payload = dict(payload)
        self._session_id = session_id

    @property
    def lifecycle(self) -> dict[str, object]:
        """Validated owner lifecycle projection을 반환합니다.

        Returns:
            Existing lifecycle 또는 deterministic idle default입니다.

        Raises:
            MonitorWorkflowInvalid: Persisted lifecycle shape나 session이 잘못되면
                발생합니다.
        """
        value = self._payload.get("owner_lifecycle")
        if value is None:
            return {
                "state": "idle",
                "owner_session_id": self._session_id,
                "source": "session-kernel",
                "activity": "workflow-open",
                "transitioned_at_epoch": 0.0,
            }
        if not isinstance(value, Mapping):
            raise MonitorWorkflowInvalid("owner_lifecycle must be an object")
        lifecycle = dict(value)
        if lifecycle.get("owner_session_id") != self._session_id:
            raise MonitorWorkflowInvalid("owner_lifecycle session identity mismatch")
        if lifecycle.get("state") not in {"active", "idle", "recovering", "terminal"}:
            raise MonitorWorkflowInvalid("owner_lifecycle state is invalid")
        return lifecycle

    @property
    def mailbox(self) -> dict[str, object]:
        """Validated monitor mailbox projection을 반환합니다.

        Returns:
            Existing mailbox 또는 empty deterministic mailbox입니다.

        Raises:
            MonitorWorkflowInvalid: Queue, claim 또는 seen identity shape가 잘못되면
                발생합니다.
        """
        value = self._payload.get("monitor_mailbox")
        if value is None:
            return {
                "pending_events": [],
                "seen_event_ids": [],
                "active_claim": None,
                "updated_at_epoch": 0.0,
            }
        if not isinstance(value, Mapping):
            raise MonitorWorkflowInvalid("monitor_mailbox must be an object")
        mailbox = dict(value)
        pending = mailbox.get("pending_events")
        seen = mailbox.get("seen_event_ids")
        claim = mailbox.get("active_claim")
        if not isinstance(pending, list) or not isinstance(seen, list):
            raise MonitorWorkflowInvalid("monitor_mailbox queues must be arrays")
        if claim is not None and not isinstance(claim, Mapping):
            raise MonitorWorkflowInvalid("monitor_mailbox active_claim must be object or null")
        if any(not isinstance(item, Mapping) for item in pending):
            raise MonitorWorkflowInvalid("monitor pending event must be an object")
        if any(not isinstance(item, str) or not item for item in seen):
            raise MonitorWorkflowInvalid("monitor seen event id must be non-empty")
        mailbox.setdefault("updated_at_epoch", 0.0)
        return mailbox

    def replace_lifecycle(self, lifecycle: Mapping[str, object]) -> None:
        """다음 owner lifecycle을 detached object로 교체합니다.

        Args:
            lifecycle: Pure mutation이 계산한 complete lifecycle object입니다.
        """
        self._payload["owner_lifecycle"] = dict(lifecycle)

    def replace_mailbox(self, mailbox: Mapping[str, object]) -> None:
        """다음 monitor mailbox를 detached object로 교체합니다.

        Args:
            mailbox: Pure mutation이 계산한 complete mailbox object입니다.
        """
        self._payload["monitor_mailbox"] = dict(mailbox)

    def payload(self) -> Mapping[str, object]:
        """Unrelated key를 보존한 detached next payload를 반환합니다.

        Returns:
            SkillStateStore CAS에 전달할 새 workflow-local object입니다.
        """
        return dict(self._payload)


class OwnerActivityMutation:
    """Current hook activity를 conflict-safe pure transform으로 계산합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        event: HookEvent,
        turn_id: str | None,
        now: float,
    ) -> None:
        """Owner activity pure transform에 필요한 immutable input을 고정합니다.

        Args:
            session_id: Mutation authority가 귀속된 exact session입니다.
            event: Owner activity를 발생시킨 native hook event입니다.
            turn_id: Vendor가 제공한 optional turn identity입니다.
            now: Transform 밖에서 한 번 읽은 transition timestamp입니다.
        """
        self._session_id = session_id
        self._event = event
        self._turn_id = turn_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current state에서 active owner lifecycle을 순수 계산합니다.

        Args:
            current: Optimistic retry가 제공한 latest workflow skill state입니다.

        Returns:
            Unrelated state를 보존한 next workflow skill state입니다.

        Raises:
            MonitorWorkflowInvalid: Current lifecycle shape가 유효하지 않으면
                발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        previous = document.lifecycle
        if previous.get("state") == "terminal":
            return current
        lifecycle: dict[str, object] = {
            "state": "active",
            "owner_session_id": self._session_id,
            "source": "native-hook",
            "transitioned_at_epoch": self._now,
            "activity": self._event.value,
        }
        selected_turn = self._turn_id
        if selected_turn is None and self._event is HookEvent.USER_PROMPT:
            selected_turn = f"session-turn:{self._session_id}"
        if selected_turn is None:
            existing_turn = previous.get("turn_id")
            if isinstance(existing_turn, str) and existing_turn:
                selected_turn = existing_turn
        if selected_turn is not None:
            lifecycle["turn_id"] = selected_turn
        if lifecycle == previous:
            return current
        document.replace_lifecycle(lifecycle)
        return document.payload()


class StopTransitionMutation:
    """Validated Stop에서 matching ACK claim을 소비하고 owner를 idle로 만듭니다."""

    def __init__(self, *, session_id: str, turn_id: str | None, now: float) -> None:
        """Stop transition pure transform input을 고정합니다.

        Args:
            session_id: Stop authority가 귀속된 exact session입니다.
            turn_id: 종료하는 optional native turn identity입니다.
            now: Transform 밖에서 한 번 읽은 transition timestamp입니다.
        """
        self._session_id = session_id
        self._turn_id = turn_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching ACK claim을 소비하고 owner를 idle로 전이합니다.

        Args:
            current: Optimistic retry가 제공한 latest workflow skill state입니다.

        Returns:
            Claim과 lifecycle을 원자적으로 바꿀 next skill state입니다.

        Raises:
            AgentContinuationBlocked: Active claim의 ACK가 불완전하면 발생합니다.
            MonitorWorkflowInvalid: Current lifecycle 또는 mailbox가 잘못되면 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        lifecycle = document.lifecycle
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if isinstance(claim, Mapping):
            self._validate_ack(current, claim)
            mailbox["active_claim"] = None
            mailbox["updated_at_epoch"] = self._now
            document.replace_mailbox(mailbox)
        released_turn = self._turn_id
        if released_turn is None:
            current_turn = lifecycle.get("turn_id")
            released_turn = current_turn if isinstance(current_turn, str) else None
        idle: dict[str, object] = {
            "state": "idle",
            "owner_session_id": self._session_id,
            "source": "native-hook",
            "transitioned_at_epoch": self._now,
            "activity": HookEvent.STOP.value,
        }
        if released_turn:
            idle["released_turn_id"] = released_turn
        document.replace_lifecycle(idle)
        return document.payload()

    def _validate_ack(
        self,
        current: Mapping[str, object],
        claim: Mapping[str, object],
    ) -> None:
        event = claim.get("event")
        acknowledgement = current.get("monitor_event_ack")
        if not isinstance(event, Mapping) or not isinstance(acknowledgement, Mapping):
            raise AgentContinuationBlocked("active monitor claim is not acknowledged")
        event_id = event.get("event_id")
        reason = event.get("reason")
        evidence = acknowledgement.get("evidence")
        if (
            not isinstance(event_id, str)
            or not event_id
            or acknowledgement.get("event_id") != event_id
            or acknowledgement.get("reason") != reason
            or not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(item, str) or not item for item in evidence)
        ):
            raise AgentContinuationBlocked("active monitor claim ACK is incomplete")
        _validate_reason_evidence(reason, evidence)


def _validate_reason_evidence(reason: object, evidence: list[object]) -> None:
    values = tuple(str(item) for item in evidence)

    def contains(prefix: str) -> bool:
        """Evidence tuple에 required prefix가 존재하는지 판정합니다.

        Args:
            prefix: Reason contract가 요구하는 stable evidence prefix입니다.

        Returns:
            하나 이상의 evidence가 prefix로 시작하면 참입니다.
        """
        return any(value.startswith(prefix) for value in values)

    required: dict[str, tuple[str, ...]] = {
        "ci-failed": ("ci_readback:failedChecks=0",),
        "merge-dirty": ("merge_readback:mergeState=",),
        "comments-changed": (
            "collect_comments:TOTAL=0",
            "collect_comments:UNRESOLVED_THREADS_COUNT=0",
        ),
        "review-blocked": (
            "collect_comments:TOTAL=0",
            "collect_comments:UNRESOLVED_THREADS_COUNT=0",
            "review_readback:reviewDecision=APPROVED",
        ),
        "mergeable-clean": (
            "terminal_readback:state=OPEN",
            "terminal_readback:mergeState=CLEAN",
            "terminal_readback:reviewDecision=APPROVED",
            "terminal_readback:failedChecks=0",
            "terminal_readback:pendingChecks=0",
            "terminal_readback:headRefOid=",
            "collect_comments:TOTAL=0",
            "collect_comments:UNRESOLVED_THREADS_COUNT=0",
        ),
    }
    if not isinstance(reason, str) or reason not in required:
        raise AgentContinuationBlocked(f"unsupported monitor event reason: {reason!r}")
    missing = tuple(prefix for prefix in required[reason] if not contains(prefix))
    if missing:
        raise AgentContinuationBlocked(
            f"monitor event {reason} lacks required evidence: {', '.join(missing)}"
        )


def render_user_acceptance_question(
    contract: GoalContract,
    criterion_ids: tuple[str, ...],
) -> str:
    """Current goal의 pending USER_ACCEPTANCE criteria를 canonical question으로 렌더링합니다.

    Args:
        contract: 사용자 승인 대상인 immutable current goal contract입니다.
        criterion_ids: 이번 질문이 답변할 pending user criterion identity입니다.

    Returns:
        Goal과 sorted requirement/criterion descriptions를 포함한 exact acceptance question입니다.

    Raises:
        AgentContinuationBlocked: Criterion 집합이 비었거나 current contract와 다르면
            발생합니다.
    """
    selected_ids = tuple(sorted(criterion_ids))
    selected = tuple(
        sorted(
            (
                criterion
                for criterion in contract.criteria
                if criterion.criterion_id in selected_ids
                and EvidenceKind.USER_ACCEPTANCE in criterion.required_evidence
            ),
            key=lambda criterion: criterion.criterion_id,
        )
    )
    if not selected or tuple(criterion.criterion_id for criterion in selected) != selected_ids:
        raise AgentContinuationBlocked(
            "adaptive AWAIT_USER acceptance criteria are empty or foreign"
        )
    criteria = "\n".join(
        f"- {criterion.criterion_id} ({criterion.source_requirement_id}): "
        f"{criterion.description.strip()}"
        for criterion in selected
    )
    return "\n".join((
        f"[목표] {contract.goal.strip()}",
        "[승인 기준]",
        criteria,
        "[질문] 위 목표와 승인 기준에 대한 현재 결과를 승인하시나요?",
    ))


class AgentContinuationHookApplication:
    """Exact runtime session의 universal outer turn과 inner workflow를 처리합니다."""

    _MONITORED_KINDS = frozenset({"process-ticket", "autopilot", "monitor-pr"})
    _MAX_RETRIES = 64

    def __init__(
        self,
        *,
        runtime: SessionRuntime,
        git_publication: GitPublicationPort | None = None,
        monitor_liveness: MonitorLivenessPort | None = None,
        monitor_recovery: MonitorRecoveryPort | None = None,
        clock: Callable[[], float] = time.time,
        stop_guard: Callable[[ProcessState, StateHandle], AbstractContextManager[None]] | None = None,
    ) -> None:
        """Runtime-neutral hook application과 외부 read-back port를 구성합니다.

        Args:
            runtime: 이 wiring이 처리하는 exact vendor runtime입니다.
            git_publication: Optional Git publication inspection port입니다.
            monitor_liveness: Stop에서 사용하는 optional read-only liveness port입니다.
            monitor_recovery: Non-Stop에서 사용하는 optional recovery port입니다.
            clock: Pure mutation input timestamp를 생성하는 clock입니다.
            stop_guard: Host adapter가 캡처한 Stop 진입 상태를 검사하는 내부 guard입니다.
        """
        local_monitor = LocalMonitorRuntime(clock=clock)
        self._runtime = runtime
        self._git_publication = git_publication or GitPublicationInspector()
        self._monitor_liveness = monitor_liveness or local_monitor
        self._monitor_recovery = monitor_recovery or local_monitor
        self._clock = clock
        self._identity_resolver = RuntimeEnvironmentResolver()
        self._stop_guard = stop_guard or (lambda *_: nullcontext())

    def run(
        self,
        raw_input: str,
        environment: Mapping[str, str],
        cwd: Path,
    ) -> HookResult:
        """Hook input을 current session의 canonical workflow state에 적용합니다.

        Args:
            raw_input: Vendor가 stdin으로 제공한 hook JSON 원문입니다.
            environment: Runtime-owned session/actor identity environment입니다.
            cwd: SessionLocator와 Git resource를 파생할 current worktree입니다.

        Returns:
            성공 또는 fail-closed protocol output을 담은 immutable result입니다.

        Raises:
            AttributeError: 반환된 immutable value를 caller가 변경하려 하면 발생합니다.
        """
        try:
            invocation = self._parse_invocation(raw_input)
            effective_environment = self._effective_environment(invocation, environment)
            binding = self._identity_resolver.resolve_hook_actor(
                effective_environment,
                invocation.agent_id,
                invocation.session_id,
                hook_runtime=self._runtime,
            )
            if binding.runtime is not self._runtime:
                raise InvalidHookInput("hook runtime argument conflicts with runtime identity")
            locator = SessionLocator.from_worktree(cwd)
            if self._is_state_free_child_lifecycle(invocation, binding, locator):
                return HookResult(exit_code=0, stdout="{}")
            try:
                handle = StateHandle.attach(locator, binding)
            except SessionNotFound:
                if invocation.event is HookEvent.SESSION_START:
                    return HookResult(exit_code=0, stdout="{}")
                raise AgentContinuationBlocked(
                    f"exact-session state is missing for {invocation.event.value}"
                ) from None
            state = handle.inspect()
            actor = state.actors.get(handle.actor_id)
            if actor is None or actor.status in {ActorStatus.STOPPED, ActorStatus.RETIRED}:
                if invocation.event is HookEvent.SUBAGENT_STOP and actor is not None:
                    return HookResult(exit_code=0, stdout="{}")
                raise AgentContinuationBlocked("current actor is terminal")
            if invocation.event is HookEvent.USER_PROMPT:
                authority_context = (
                    None
                    if invocation.prompt is None
                    else self._prompt_authority_context(state, handle)
                )
                handle.apply(
                    ForegroundTurnPrompted(
                        session_id=handle.session_id,
                        actor_id=handle.actor_id,
                        vendor_turn_id=invocation.turn_id,
                        idempotency_key=self._turn_event_key(
                            handle,
                            "prompt",
                            invocation.turn_id,
                        ),
                        prompt_digest=(
                            None
                            if invocation.prompt is None
                            else hashlib.sha256(invocation.prompt.encode("utf-8")).hexdigest()
                        ),
                        authority_context=authority_context,
                    )
                )
                state = handle.inspect()
            elif invocation.event is HookEvent.PRE_TOOL:
                handle.apply(
                    ForegroundTurnToolObserved(
                        session_id=handle.session_id,
                        actor_id=handle.actor_id,
                        idempotency_key=self._turn_event_key(
                            handle,
                            "tool",
                            invocation.turn_id,
                        ),
                    )
                )
                return HookResult(exit_code=0, stdout="{}")
            elif invocation.event in {HookEvent.STOP, HookEvent.SUBAGENT_STOP}:
                self._stop_foreground_turn(
                    state,
                    handle,
                    invocation,
                    effective_environment,
                    cwd,
                )
                if invocation.event is HookEvent.SUBAGENT_STOP:
                    self._stop_subagent_actor(handle, cwd)
                return HookResult(exit_code=0, stdout="{}")

            workflows = self._selected_workflows(state, handle)
            if workflows:
                self._activate(handle, workflows, invocation)
                self._ensure_registered_monitors(
                    handle,
                    workflows,
                    effective_environment,
                    cwd,
                )
            return HookResult(exit_code=0, stdout="{}")
        except (
            HarnessIncidentValidationError,
            InvalidHookInput,
            AgentContinuationBlocked,
            MonitorRuntimeUnavailable,
            MonitorWorkflowInvalid,
            RuntimeIdentityError,
            SessionKernelError,
            SkillStateRetryExhausted,
            WorktreeRegistryError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            return HookResult(
                exit_code=2,
                stdout="{}",
                stderr=f"Agent continuation blocked: {error}",
            )

    def _parse_invocation(self, raw_input: str) -> HookInvocation:
        try:
            payload: object = json.loads(raw_input)
        except json.JSONDecodeError as error:
            raise InvalidHookInput("hook input must be valid JSON") from error
        if not isinstance(payload, Mapping):
            raise InvalidHookInput("hook input must be an object")
        raw_event = payload.get("hook_event_name")
        try:
            event = HookEvent(raw_event)
        except (TypeError, ValueError) as error:
            raise InvalidHookInput(f"unsupported hook event: {raw_event!r}") from error
        if payload.get("actor_id") is not None:
            raise InvalidHookInput("actor identity must come from the runtime-owned environment")
        agent_id = self._optional_text(payload.get("agent_id"))
        if event is HookEvent.SUBAGENT_STOP and agent_id is None:
            raise InvalidHookInput("SubagentStop requires exact agent_id")
        if event is HookEvent.STOP and agent_id is not None:
            raise InvalidHookInput("child completion must use SubagentStop")
        session_id = self._optional_text(payload.get("session_id"))
        thread_id = self._optional_text(payload.get("thread_id"))
        if session_id and thread_id and session_id != thread_id:
            raise InvalidHookInput("hook payload thread conflicts with payload session")
        return HookInvocation(
            event=event,
            session_id=session_id or thread_id,
            turn_id=self._optional_text(payload.get("turn_id")),
            prompt=self._optional_text(payload.get("prompt")),
            agent_id=agent_id,
        )

    def _is_state_free_child_lifecycle(
        self,
        invocation: HookInvocation,
        binding: RuntimeIdentityBinding,
        locator: SessionLocator,
    ) -> bool:
        """Unregistered child의 read-only lifecycle을 exact session no-op으로 판정합니다.

        Repository wiring은 child event가 선언됐다는 사실만 제공합니다. Parent lineage나
        delivery attestation이 없는 child를 root에 attach하거나 actor로 persist하지 않고,
        exact session/runtime/root identity를 read-back한 뒤 PreCompact/SubagentStop만
        state-free success로 처리합니다.
        """
        if binding.is_root or invocation.event not in {
            HookEvent.PRE_COMPACT,
            HookEvent.SUBAGENT_STOP,
        }:
            return False
        state = SessionKernel(locator).inspect(binding.session_id)
        if (
            state.session.runtime is not binding.runtime
            or state.session.root_actor_id != binding.root_actor_id
        ):
            raise AgentContinuationBlocked(
                "state-free child lifecycle conflicts with exact root session"
            )
        return binding.actor_id not in state.actors

    def _effective_environment(
        self,
        invocation: HookInvocation,
        environment: Mapping[str, str],
    ) -> dict[str, str]:
        """Runtime-owned identity만 resolver input으로 정규화합니다.

        Vendor session variable이 없는 Claude Code process에서는 SessionStart hook이
        ``CLAUDE_ENV_FILE``에 보존한 complete Neurath overlay를 사용할 수 있습니다.
        Codex는 runtime-specific adapter가 공식 hook JSON의 필수 ``session_id``를
        resolver에 직접 결속하므로 비공식 ``CODEX_THREAD_ID``를 요구하지 않습니다.
        """
        selected = dict(environment)
        vendor_key = (
            "CODEX_THREAD_ID" if self._runtime is SessionRuntime.CODEX else "CLAUDE_CODE_SESSION_ID"
        )
        other_key = (
            "CLAUDE_CODE_SESSION_ID" if self._runtime is SessionRuntime.CODEX else "CODEX_THREAD_ID"
        )
        if selected.get(other_key):
            raise InvalidHookInput("hook environment contains the other runtime identity")
        persisted = selected.get(vendor_key)
        overlay_session = selected.get("NEURATH_AGENT_SESSION_ID")
        overlay_actor = selected.get("NEURATH_AGENT_ACTOR_ID")
        overlay_runtime = selected.get("NEURATH_AGENT_RUNTIME")
        overlay_presence = tuple(
            value is not None for value in (overlay_session, overlay_actor, overlay_runtime)
        )
        if not persisted and any(overlay_presence):
            if self._runtime is SessionRuntime.CODEX:
                raise InvalidHookInput(
                    "Codex continuation cannot replace vendor hook payload authority with an Neurath overlay"
                )
            if not all(overlay_presence):
                raise InvalidHookInput("Neurath runtime identity overlay must be all-or-none")
            if overlay_runtime != self._runtime.value:
                raise InvalidHookInput("Neurath runtime identity overlay conflicts with hook runtime")
            assert overlay_session is not None
            persisted = overlay_session
            selected[vendor_key] = overlay_session
        if persisted and invocation.session_id and persisted != invocation.session_id:
            raise InvalidHookInput("hook payload session conflicts with runtime environment")
        return selected

    def _selected_workflows(
        self,
        state: ProcessState,
        handle: StateHandle,
    ) -> tuple[WorkflowRecord, ...]:
        selected: list[WorkflowRecord] = []
        for workflow in state.workflows.values():
            if (
                workflow.status is not WorkflowStatus.ACTIVE
                or workflow.owner_actor_id != handle.actor_id
            ):
                continue
            skill_state = workflow.payload.get("skill_state")
            has_monitor_state = isinstance(skill_state, Mapping) and any(
                field in skill_state
                for field in (
                    "monitor_event_subscription",
                    "monitor_mailbox",
                    "owner_lifecycle",
                )
            )
            if workflow.kind in self._MONITORED_KINDS or has_monitor_state:
                selected.append(workflow)
        return tuple(sorted(selected, key=lambda item: str(item.id)))

    def _prompt_authority_context(
        self,
        state: ProcessState,
        handle: StateHandle,
    ) -> ForegroundPromptAuthorityContext | None:
        """직전 exact adaptive question과 current user response를 결속할 context를 찾습니다.

        Args:
            state: UserPromptSubmit 적용 직전 exact-session snapshot입니다.
            handle: Current foreground actor에 bound된 runtime authority입니다.

        Returns:
            Canonical ASK_USER 또는 AWAIT_USER question 하나와 일치하는 bounded context이며,
            일반 prompt나 prompt provenance가 부족하면 None입니다.

        Raises:
            AgentContinuationBlocked: 둘 이상의 adaptive workflow가 같은 user response를
                소비할 수 있어 authority source가 모호하면 발생합니다.
        """
        turn = state.foreground_turns.get(handle.actor_id)
        if (
            turn is None
            or turn.status not in {ForegroundTurnStatus.READY_TO_STOP, ForegroundTurnStatus.CLOSED}
            or turn.receipt is None
            or turn.receipt.outcome is not ForegroundTurnOutcome.AWAITING_INPUT
            or turn.receipt.question is None
        ):
            return None
        contexts: list[ForegroundPromptAuthorityContext] = []
        for workflow in state.workflows.values():
            if (
                workflow.status is not WorkflowStatus.ACTIVE
                or workflow.owner_actor_id != handle.actor_id
            ):
                continue
            skill_state = workflow.payload.get("skill_state")
            if not isinstance(skill_state, Mapping) or "adaptive_control" not in skill_state:
                continue
            snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow.id)).read()
            receipt = snapshot.receipt()
            if receipt.workflow_revision != workflow.revision:
                raise AgentContinuationBlocked(
                    f"workflow {workflow.id} has a stale adaptive prompt receipt"
                )
            claim_ids: tuple[str, ...] = ()
            if (
                receipt.decision.action is ControlAction.ASK_USER
                and receipt.ambiguity.selected_gap_id is not None
            ):
                selected = tuple(
                    gap
                    for gap in snapshot.state.inventory.gaps
                    if gap.gap_id == receipt.ambiguity.selected_gap_id
                )
                if (
                    len(selected) != 1
                    or render_socratic_question(selected[0]) != turn.receipt.question
                ):
                    continue
                claim_ids = (f"gap:{selected[0].gap_id}",)
            elif receipt.decision.action is ControlAction.AWAIT_USER:
                pending = frozenset(receipt.attainment.pending)
                claim_ids = tuple(
                    sorted(
                        f"criterion:{criterion.criterion_id}"
                        for criterion in snapshot.state.contract.criteria
                        if criterion.criterion_id in pending
                        and EvidenceKind.USER_ACCEPTANCE in criterion.required_evidence
                    )
                )
                if not claim_ids:
                    continue
                expected_question = render_user_acceptance_question(
                    snapshot.state.contract,
                    tuple(claim.removeprefix("criterion:") for claim in claim_ids),
                )
                if turn.receipt.question != expected_question:
                    continue
            else:
                continue
            contract = snapshot.state.contract
            contexts.append(
                ForegroundPromptAuthorityContext(
                    workflow_id=workflow.id,
                    workflow_revision=workflow.revision,
                    goal_fingerprint=contract.fingerprint,
                    intent_revision=contract.intent_revision,
                    source_revision=contract.source_revision,
                    criterion_ids=tuple(
                        sorted(criterion.criterion_id for criterion in contract.criteria)
                    ),
                    claim_ids=claim_ids,
                    control_action=receipt.decision.action.value,
                    question_digest=hashlib.sha256(
                        turn.receipt.question.strip().encode("utf-8")
                    ).hexdigest(),
                    question_generation=turn.generation,
                    question_turn_revision=turn.revision,
                )
            )
        if len(contexts) > 1:
            identities = ", ".join(sorted(str(item.workflow_id) for item in contexts))
            raise AgentContinuationBlocked(
                f"multiple adaptive workflows cannot consume one user prompt receipt: {identities}"
            )
        return contexts[0] if contexts else None

    def _validated_stop_workflows(
        self,
        state: ProcessState,
        handle: StateHandle,
        cwd: Path,
    ) -> tuple[WorkflowRecord, ...]:
        """Stop 전 exact-session prerequisite와 foreground reachability를 검증합니다.

        Args:
            state: Runtime-bound handle이 읽은 exact-session snapshot입니다.
            handle: Current actor identity와 workflow authority입니다.
            cwd: Incident resolution evidence를 검증할 current worktree입니다.

        Returns:
            기존 monitor-specific Stop 검증을 실행할 active workflow입니다.

        Raises:
            HarnessIncidentValidationError: Session incident가 terminal 조건을 못 갖췄을 때
                발생합니다.
            AgentContinuationBlocked: Current actor의 material action, delegation 또는
                generic foreground workflow가 미완료일 때 발생합니다.
        """
        material_action = state.material_actions.get(handle.actor_id)
        if material_action is not None and material_action.status is MaterialActionStatus.OPEN:
            raise AgentContinuationBlocked(
                "current actor open material action must resolve before Stop: "
                f"{material_action.batch_id}@{material_action.revision}"
            )
        validate_harness_incidents(state, cwd.resolve())
        self._validate_delegations(state, handle)
        adaptive_control_returns: dict[WorkflowId, tuple[ControlAction, str | None]] = {}
        for workflow in state.workflows.values():
            if (
                workflow.status is not WorkflowStatus.ACTIVE
                or workflow.owner_actor_id != handle.actor_id
            ):
                continue
            control_return = self._validate_adaptive_control_return(state, handle, workflow)
            if control_return is not None:
                adaptive_control_returns[workflow.id] = control_return
        if len(adaptive_control_returns) > 1 and any(
            question is not None for _action, question in adaptive_control_returns.values()
        ):
            identities = ", ".join(sorted(str(item) for item in adaptive_control_returns))
            raise AgentContinuationBlocked(
                "multiple adaptive workflows cannot share one foreground question receipt: "
                f"{identities}"
            )
        if adaptive_control_returns:
            _action, expected_question = next(iter(adaptive_control_returns.values()))
            turn = state.foreground_turns.get(handle.actor_id)
            if expected_question is not None and (
                turn is None or turn.receipt is None or turn.receipt.question != expected_question
            ):
                raise AgentContinuationBlocked(
                    "adaptive foreground question does not match the current control request"
                )
        adaptive_control_return_ids = frozenset(adaptive_control_returns)
        monitored = tuple(
            workflow
            for workflow in self._selected_workflows(state, handle)
            if workflow.id not in adaptive_control_return_ids
        )
        monitored_ids = frozenset(workflow.id for workflow in monitored)
        generic = tuple(
            sorted(
                (
                    workflow
                    for workflow in state.workflows.values()
                    if workflow.status is WorkflowStatus.ACTIVE
                    and workflow.owner_actor_id == handle.actor_id
                    and workflow.id not in monitored_ids
                    and workflow.id not in adaptive_control_return_ids
                ),
                key=lambda item: str(item.id),
            )
        )
        if generic:
            identities = ", ".join(str(workflow.id) for workflow in generic)
            raise AgentContinuationBlocked(
                "active foreground workflow(s) must reach a terminal state before Stop: "
                f"{identities}"
            )
        return monitored

    def _validate_adaptive_control_return(
        self,
        state: ProcessState,
        handle: StateHandle,
        workflow: WorkflowRecord,
    ) -> tuple[ControlAction, str | None] | None:
        """Active adaptive workflow가 current user question에만 control을 반환하게 합니다.

        Persisted label은 사용하지 않습니다. Exact workflow의 adaptive state에서 receipt를
        재계산하고, caller snapshot과 같은 workflow revision인지 확인합니다.
        Clarification을 위한 ASK_USER와 goal acceptance를 위한 AWAIT_USER를 각각
        그 source assessment와 대조한 뒤 foreground AWAITING_INPUT과의 conjunction만
        허용합니다.

        Args:
            state: Stop 검증이 사용하는 exact-session snapshot입니다.
            handle: Workflow owner actor에 bound된 state handle입니다.
            workflow: 현재 검토하는 active owned workflow입니다.

        Returns:
            Adaptive namespace가 없으면 None입니다. 검증된 control return은
            action과 ASK_USER일 때 current selected-gap 질문을 반환합니다.

        Raises:
            AgentContinuationBlocked: Adaptive state가 있지만 current control-return authority가
                없으면 발생합니다.
            SessionKernelError: Persisted adaptive state가 invalid하면 fail closed로 전파됩니다.
        """
        turn = state.foreground_turns.get(handle.actor_id)
        if (
            turn is not None
            and turn.status is ForegroundTurnStatus.READY_TO_STOP
            and turn.receipt is not None
            and turn.receipt.outcome is ForegroundTurnOutcome.INCOMPLETE
            and requires_adaptive_control_for_workflow(workflow.kind, workflow.payload)
            and EvaluationAdmissionPolicy().inspect(state, handle.actor_id, workflow.id)["status"]
            == "unavailable"
        ):
            return ControlAction.CONTINUE, None
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, Mapping) or "adaptive_control" not in skill_state:
            return None
        snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow.id)).read()
        receipt = snapshot.receipt()
        if receipt.workflow_revision != workflow.revision:
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} has a stale adaptive control receipt"
            )
        clarification_question = (
            receipt.decision.action is ControlAction.ASK_USER
            and not receipt.ambiguity.ready
            and receipt.ambiguity.action is ControlAction.ASK_USER
            and receipt.ambiguity.selected_gap_id is not None
        )
        acceptance_question = (
            receipt.decision.action is ControlAction.AWAIT_USER
            and receipt.ambiguity.ready
            and receipt.ambiguity.action is ControlAction.CONTINUE
            and receipt.attainment.action is ControlAction.AWAIT_USER
        )
        if (
            not (clarification_question or acceptance_question)
            or receipt.decision.achieved
            or receipt.attainment.achieved
        ):
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} adaptive action {receipt.decision.action.value} "
                "cannot return control"
            )
        turn = state.foreground_turns.get(handle.actor_id)
        if (
            turn is None
            or turn.status is not ForegroundTurnStatus.READY_TO_STOP
            or turn.receipt is None
            or turn.receipt.outcome is not ForegroundTurnOutcome.AWAITING_INPUT
        ):
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} AWAIT_USER requires an exact awaiting-input foreground turn"
            )
        expected_question: str | None = None
        if clarification_question:
            selected_gap_id = receipt.ambiguity.selected_gap_id
            selected = tuple(
                gap for gap in snapshot.state.inventory.gaps if gap.gap_id == selected_gap_id
            )
            if len(selected) != 1:
                raise AgentContinuationBlocked(
                    f"workflow {workflow.id} ASK_USER selected gap is not unique"
                )
            gap = selected[0]
            if (
                gap.intent_revision != snapshot.state.inventory.intent_revision
                or gap.intent_revision != snapshot.state.contract.intent_revision
            ):
                raise AgentContinuationBlocked(
                    f"workflow {workflow.id} ASK_USER selected gap intent revision is stale"
                )
            expected_question = render_socratic_question(gap)
        elif acceptance_question:
            pending = frozenset(receipt.attainment.pending)
            criterion_ids = tuple(
                sorted(
                    criterion.criterion_id
                    for criterion in snapshot.state.contract.criteria
                    if criterion.criterion_id in pending
                    and EvidenceKind.USER_ACCEPTANCE in criterion.required_evidence
                )
            )
            expected_question = render_user_acceptance_question(
                snapshot.state.contract,
                criterion_ids,
            )
        try:
            verification = AdaptiveControlAuthorityVerifier(handle, workflow.id).verify()
        except AdaptiveControlAuthorityError as error:
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} adaptive external authority is invalid: {error}"
            ) from error
        if (
            verification.workflow_revision != workflow.revision
            or verification.goal_fingerprint != receipt.goal_fingerprint
        ):
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} adaptive external authority is stale"
            )
        if verification.status not in {
            AdaptiveControlAuthorityStatus.VERIFIED,
            AdaptiveControlAuthorityStatus.PENDING_UNVERIFIABLE,
        }:
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} adaptive external authority cannot return control"
            )
        return receipt.decision.action, expected_question

    def _stop_foreground_turn(
        self,
        state: ProcessState,
        handle: StateHandle,
        invocation: HookInvocation,
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Runtime Stop과 공통 prerequisite를 검증한 뒤 outer turn을 CAS로 닫습니다.

        Args:
            state: Stop hook 진입 시점의 exact-session snapshot입니다.
            handle: Current actor에 bound된 mutation authority입니다.
            invocation: Optional vendor turn identity를 포함한 Stop invocation입니다.
            environment: Monitor runtime에 전달할 runtime-owned identity입니다.
            cwd: Incident, worktree, publication evidence를 읽을 current worktree입니다.

        Raises:
            AgentContinuationBlocked: Current actor turn이 없거나 inner prerequisite가
                미완료일 때 발생합니다.
            SessionKernelError: Close CAS가 충돌하면 발생합니다.
        """
        turn = state.foreground_turns.get(handle.actor_id)
        if turn is None:
            raise AgentContinuationBlocked("current actor foreground turn is missing")
        if turn.status is ForegroundTurnStatus.CLOSED:
            return
        close_revision = turn.revision
        try:
            with self._stop_guard(state, handle):
                state, abandoned = self._abandon_unobserved_material_action(
                    state,
                    handle,
                    turn.generation,
                )
            if abandoned:
                raise AgentContinuationBlocked(
                    "unobserved material invocation was blocked as UNKNOWN; "
                    "inspect and reconcile current observables before retrying Stop"
                )
            workflows = self._validated_stop_workflows(state, handle, cwd)
            stop_timestamp = self._clock()
            monitor_transitions = self._monitor_stop_transitions(
                workflows,
                invocation,
                stop_timestamp,
                session_id=str(handle.session_id),
            )
            self._validate_monitor_workflows(workflows, environment, cwd)
            try:
                # External Git/monitor readbacks above must not hold the host
                # lifecycle journal. Recheck only for the short canonical CAS.
                with self._stop_guard(state, handle):
                    handle.apply(
                        ForegroundTurnClosed(
                            session_id=handle.session_id,
                            actor_id=handle.actor_id,
                            expected_turn_revision=close_revision,
                            idempotency_key=(
                                f"foreground-turn:close:{handle.actor_id}:{turn.generation}:"
                                f"{close_revision}"
                            ),
                            monitor_transitions=monitor_transitions,
                        ),
                        expected_revision=state.revision,
                    )
            except RevisionConflict as error:
                raise AgentContinuationBlocked(
                    "canonical session state changed during external Stop validation"
                ) from error
        except (
            HarnessIncidentValidationError,
            InvalidHookInput,
            AgentContinuationBlocked,
            MonitorRuntimeUnavailable,
            MonitorWorkflowInvalid,
            SessionKernelError,
            SkillStateRetryExhausted,
            WorktreeRegistryError,
            OSError,
            subprocess.SubprocessError,
        ):
            self._invalidate_ready_turn(handle, turn.generation, close_revision)
            raise

    def _stop_subagent_actor(self, handle: StateHandle, cwd: Path) -> None:
        """Closed child turn의 durable work를 확인한 뒤 actor authority를 terminalize합니다.

        Args:
            handle: Exact Claude child actor에 bound된 state authority입니다.
            cwd: Child hook이 실행된 canonical Git worktree입니다.

        Raises:
            AgentContinuationBlocked: Child가 pending work나 current worktree lease를
                남겼으면 발생합니다.
            SessionKernelError: ActorStopped CAS가 current snapshot과 충돌하면 발생합니다.
        """
        state = handle.inspect()
        turn = state.foreground_turns.get(handle.actor_id)
        if turn is None or turn.status is not ForegroundTurnStatus.CLOSED:
            raise AgentContinuationBlocked("subagent terminalization requires a closed turn")
        batch = state.material_actions.get(handle.actor_id)
        if batch is not None and batch.status is MaterialActionStatus.OPEN:
            raise AgentContinuationBlocked("subagent has an open material action")
        if any(
            workflow.owner_actor_id == handle.actor_id and workflow.status is WorkflowStatus.ACTIVE
            for workflow in state.workflows.values()
        ):
            raise AgentContinuationBlocked("subagent owns an active workflow")
        if any(
            (
                delegation.target_actor_id == handle.actor_id
                and delegation.status is DelegationStatus.PENDING
            )
            or (
                delegation.owner_actor_id == handle.actor_id
                and delegation.status in {DelegationStatus.PENDING, DelegationStatus.REPORTED}
            )
            for delegation in state.delegations.values()
        ):
            raise AgentContinuationBlocked("subagent has an unterminated delegation")
        identity = WorktreeIdentityResolver().resolve(cwd)
        registry = WorktreeRegistry(SessionLocator.from_worktree(cwd))
        try:
            claim = registry.get(identity.worktree_id)
        except WorktreeNotClaimed:
            claim = None
        if (
            claim is not None
            and claim.session_id == handle.session_id
            and claim.actor_id == handle.actor_id
        ):
            raise AgentContinuationBlocked("subagent worktree claim must be released or handed off")
        handle.apply(
            ActorStopped(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                terminal_status=ActorStatus.STOPPED,
                idempotency_key=f"subagent-stop:{handle.actor_id}",
            ),
            expected_revision=state.revision,
        )

    def _abandon_unobserved_material_action(
        self,
        state: ProcessState,
        handle: StateHandle,
        turn_generation: int,
    ) -> tuple[ProcessState, bool]:
        """Stop이 증명한 no-PostTool invocation을 UNKNOWN/BLOCKED로 원자 terminalize합니다.

        Args:
            state: Stop 진입에서 읽은 exact-session snapshot입니다.
            handle: Current actor의 typed state mutation authority입니다.
            turn_generation: Runtime Stop이 닫으려는 foreground turn generation입니다.

        Returns:
            Current snapshot과 새 abandonment가 발생했는지 나타내는 flag입니다.
        """
        batch = state.material_actions.get(handle.actor_id)
        if batch is None or batch.in_flight is None:
            return state, False
        invocation = batch.in_flight
        handle.apply(
            MaterialActionAbandoned(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                expected_turn_generation=turn_generation,
                invocation_id=invocation.invocation_id,
                idempotency_key=(
                    f"material-action:abandon:{batch.batch_id}:"
                    f"{invocation.invocation_id}:{turn_generation}"
                ),
            ),
            expected_revision=state.revision,
        )
        return handle.inspect(), True

    def _invalidate_ready_turn(
        self,
        handle: StateHandle,
        generation: int,
        ready_revision: int,
    ) -> None:
        """Stop prerequisite failure 뒤 아직 ready인 같은 turn receipt를 제거합니다."""
        current = handle.inspect().foreground_turns.get(handle.actor_id)
        if (
            current is None
            or current.generation != generation
            or current.revision != ready_revision
            or current.status is not ForegroundTurnStatus.READY_TO_STOP
        ):
            return
        handle.apply(
            ForegroundTurnInvalidated(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                expected_turn_revision=current.revision,
                idempotency_key=(
                    f"foreground-turn:invalidate:{handle.actor_id}:{generation}:{ready_revision}"
                ),
            )
        )

    def _turn_event_key(
        self,
        handle: StateHandle,
        event: str,
        vendor_turn_id: str | None,
    ) -> str:
        """Optional vendor turn identity 없이도 deterministic event key를 만듭니다."""
        identity = "unidentified" if vendor_turn_id is None else vendor_turn_id
        return f"foreground-turn:{event}:{handle.actor_id}:{identity}"

    def _activate(
        self,
        handle: StateHandle,
        workflows: tuple[WorkflowRecord, ...],
        invocation: HookInvocation,
    ) -> None:
        now = self._clock()
        for workflow in workflows:
            store = SkillStateStore(handle, workflow.id)
            store.update(
                OwnerActivityMutation(
                    session_id=str(handle.session_id),
                    event=invocation.event,
                    turn_id=invocation.turn_id,
                    now=now,
                )
            )

    def _monitor_stop_transitions(
        self,
        workflows: tuple[WorkflowRecord, ...],
        invocation: HookInvocation,
        now: float,
        *,
        session_id: str,
    ) -> tuple[MonitorWorkflowStopProjection, ...]:
        """Captured workflow payload에서 pure Stop 후보를 계산합니다.

        Args:
            workflows: 한 ProcessState에서 캡처한 canonical monitor workflows입니다.
            invocation: Optional vendor turn identity를 가진 exact Stop invocation입니다.
            now: 모든 lifecycle/mailbox projection이 공유할 단일 timestamp입니다.
            session_id: Runtime-bound handle이 증명한 exact session identity입니다.

        Returns:
            ForegroundTurnClosed와 같은 process CAS에 포함할 canonical projection입니다.

        Raises:
            MonitorWorkflowInvalid: Captured workflow에 object skill-state가 없으면 발생합니다.
            AgentContinuationBlocked: Active claim의 ACK가 불완전하면 발생합니다.
        """
        projections: list[MonitorWorkflowStopProjection] = []
        for workflow in workflows:
            skill_state = workflow.payload.get("skill_state")
            if not isinstance(skill_state, Mapping):
                raise MonitorWorkflowInvalid(
                    f"workflow {workflow.id} payload is missing object skill_state"
                )
            projections.append(
                MonitorWorkflowStopProjection(
                    workflow_id=workflow.id,
                    expected_workflow_revision=workflow.revision,
                    skill_state=StopTransitionMutation(
                        session_id=session_id,
                        turn_id=invocation.turn_id,
                        now=now,
                    )(skill_state),
                )
            )
        return tuple(projections)

    def _validate_monitor_workflows(
        self,
        workflows: tuple[WorkflowRecord, ...],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Monitor policy를 workflow snapshot마다 read-back해 side effect 없이 검증합니다."""
        for workflow in workflows:
            skill_state = workflow.payload.get("skill_state")
            if not isinstance(skill_state, Mapping):
                raise MonitorWorkflowInvalid(
                    f"workflow {workflow.id} payload is missing object skill_state"
                )
            self._validate_stop_snapshot(workflow, skill_state, environment, cwd)

    def _validate_delegations(self, state: ProcessState, handle: StateHandle) -> None:
        unresolved = tuple(
            delegation
            for delegation in state.delegations.values()
            if delegation.owner_actor_id == handle.actor_id
            and delegation.status in {DelegationStatus.PENDING, DelegationStatus.REPORTED}
        )
        if unresolved:
            identities = ", ".join(str(item.id) for item in unresolved)
            raise AgentContinuationBlocked(
                f"unresolved delegation(s) must be consumed before Stop: {identities}"
            )

    def _validate_stop_snapshot(
        self,
        workflow: WorkflowRecord,
        skill_state: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        document = MonitorWorkflowDocument(skill_state, self._session_id(environment))
        mailbox = document.mailbox
        pending = mailbox.get("pending_events")
        if isinstance(pending, list) and pending:
            raise AgentContinuationBlocked(
                f"workflow {workflow.id} has unprocessed monitor event(s)"
            )
        merged = skill_state.get("merged")
        subscription = skill_state.get("monitor_event_subscription")
        if merged:
            self._validate_released_worktree(subscription, cwd)
            return
        worktree = self._worktree(subscription, cwd, environment)
        self._git_publication.validate_stoppable(worktree)
        if isinstance(subscription, Mapping):
            self._monitor_liveness.assert_live(
                workflow_id=workflow.id,
                subscription=subscription,
                environment=environment,
                cwd=cwd,
            )

    def _ensure_registered_monitors(
        self,
        handle: StateHandle,
        workflows: tuple[WorkflowRecord, ...],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        for workflow in workflows:
            snapshot = SkillStateStore(handle, workflow.id).read()
            subscription = snapshot.skill_state.get("monitor_event_subscription")
            if isinstance(subscription, Mapping) and not snapshot.skill_state.get("merged"):
                self._monitor_recovery.recover_if_needed(
                    workflow_id=workflow.id,
                    subscription=subscription,
                    environment=environment,
                    cwd=cwd,
                )

    def _worktree(
        self,
        subscription: object,
        cwd: Path,
        environment: Mapping[str, str],
    ) -> Path:
        resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
        if isinstance(subscription, Mapping):
            if subscription.get("worktree_id") != resources.worktree_id:
                raise AgentContinuationBlocked(
                    "monitor subscription worktree identity does not match current cwd"
                )
            if subscription.get("observation_resource") != resources.observation_resource():
                raise AgentContinuationBlocked(
                    "monitor subscription observation resource does not match current cwd"
                )
        return resources.worktree

    def _validate_released_worktree(self, subscription: object, cwd: Path) -> None:
        """Merged workflow는 opaque worktree claim이 이미 release된 경우만 종료합니다.

        Args:
            subscription: Merge 전에 등록된 monitor route입니다.
            cwd: Shared repository registry를 파생할 current Git worktree입니다.

        Raises:
            AgentContinuationBlocked: Worktree identity가 없거나 claim이 남아 있으면
                발생합니다.
        """
        if not isinstance(subscription, Mapping):
            raise AgentContinuationBlocked(
                "merged workflow is missing its monitor worktree identity"
            )
        raw_worktree_id = subscription.get("worktree_id")
        if not isinstance(raw_worktree_id, str) or not raw_worktree_id:
            raise AgentContinuationBlocked("merged workflow monitor worktree identity is invalid")
        registry = WorktreeRegistry(SessionLocator.from_worktree(cwd))
        try:
            claim = registry.get(WorktreeId(raw_worktree_id))
        except WorktreeNotClaimed:
            return
        raise AgentContinuationBlocked(
            f"merged workflow worktree claim is still active: {claim.session_id}/{claim.actor_id}"
        )

    def _session_id(self, environment: Mapping[str, str]) -> str:
        key = (
            "CODEX_THREAD_ID" if self._runtime is SessionRuntime.CODEX else "CLAUDE_CODE_SESSION_ID"
        )
        value = environment.get(key)
        if value is None or not value.strip():
            raise InvalidHookInput("runtime session identity is unavailable")
        return value.strip()

    def _optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise InvalidHookInput("optional hook text must be non-empty when present")
        return value.strip()


class AgentContinuationHookCli:
    """Vendor hook process streams를 canonical application에 연결합니다."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: TextIO = sys.stdin,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        environment: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> int:
        """CLI 입력을 읽어 exact-session continuation hook을 실행합니다.

        Args:
            arguments: Runtime selector를 포함한 command-line arguments입니다.
            stdin: Vendor hook JSON payload를 읽을 stream입니다.
            stdout: Vendor protocol JSON을 기록할 stream입니다.
            stderr: Fail-closed diagnostic을 기록할 stream입니다.
            environment: Test 또는 caller가 제공하는 optional runtime environment입니다.
            cwd: Canonical Git identity를 파생할 optional current directory입니다.

        Returns:
            Vendor hook process에 반환할 exit status입니다.
        """
        parser = argparse.ArgumentParser(description="Run exact-session agent continuation hook.")
        parser.add_argument(
            "--runtime",
            required=True,
            choices=tuple(runtime.value for runtime in SessionRuntime),
        )
        namespace = parser.parse_args(tuple(arguments))
        application = AgentContinuationHookApplication(runtime=SessionRuntime(namespace.runtime))
        result = application.run(
            stdin.read(),
            dict(os.environ) if environment is None else environment,
            Path.cwd() if cwd is None else cwd,
        )
        stdout.write(f"{result.stdout}\n")
        if result.stderr:
            stderr.write(f"{result.stderr}\n")
        return result.exit_code


if __name__ == "__main__":
    raise SystemExit(AgentContinuationHookCli().run(sys.argv[1:]))
