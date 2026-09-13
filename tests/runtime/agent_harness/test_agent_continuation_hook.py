"""Exact-session universal continuation hook의 canonical contract를 검증합니다."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    ClarificationGap,
    ControlAction,
    CriterionEvidence,
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapAuthority,
    GapInventory,
    GapResolution,
    GoalContract,
    GoalCoverage,
    OracleOwner,
    RequirementSection,
    approved_requirement_fingerprint,
    render_socratic_question,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    AdaptiveControlStore,
)
from scripts.agent_harness.agent_continuation_hook import (
    AgentContinuationBlocked,
    AgentContinuationHookApplication,
    GitPublicationInspector,
    HookEvent,
    HookResult,
    LocalMonitorRuntime,
    MonitorRuntimeUnavailable,
    render_user_acceptance_question,
)
from scripts.agent_harness.material_action import (
    MaterialActionKind,
    MaterialActionResolution,
    ObservableDeltaKind,
    ObservableExpectation,
    ObservableObservation,
    ToolReceipt,
    ToolReceiptOutcome,
)
from scripts.agent_harness.runtime_hook import RuntimeHookApplication
from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    ActorStatus,
    DelegationAssigned,
    DelegationCancelled,
    DelegationId,
    ForegroundTurnOutcome,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnReceipt,
    ForegroundTurnStatus,
    ForegroundTurnToolObserved,
    ForegroundTurnYielded,
    HarnessIncidentEscalated,
    HarnessIncidentRecorded,
    IncidentId,
    MaterialActionPrepared,
    MaterialActionResolved,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    ReservedSkillStateAdvanced,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    SessionStateStore,
    TransitionRejected,
    WorkflowFinalized,
    WorkflowId,
    WorkflowStarted,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_cli import StateCliApplication, StateCliResult
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle
from scripts.agent_harness.worktree_registry import (
    WorktreeClaim,
    WorktreeIdentityResolver,
    WorktreeRegistry,
)


def mapping(value: object, label: str) -> Mapping[str, object]:
    """Test assertion 뒤 type checker에도 object narrowing을 제공합니다."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


class FakeGitPublication:
    """Stop test가 Git 외부 상태와 application 결정을 분리하도록 합니다."""

    def __init__(self, error: str | None = None) -> None:
        """Optional 실패와 관찰된 worktree 목록을 초기화합니다.

        Args:
            error: Validation 호출에서 발생시킬 optional diagnostic입니다.
        """
        self.error = error
        self.paths: list[Path] = []

    def validate_stoppable(self, worktree: Path) -> None:
        """검사한 worktree를 기록하고 설정된 실패를 재현합니다.

        Args:
            worktree: Application이 선택한 canonical worktree입니다.

        Raises:
            AgentContinuationBlocked: Fixture에 실패가 설정된 경우 발생합니다.
        """
        self.paths.append(worktree)
        if self.error is not None:
            raise AgentContinuationBlocked(self.error)


class FakeMonitorRuntime:
    """Application이 선택한 exact workflow route를 기록합니다."""

    def __init__(
        self,
        *,
        liveness_error: str | None = None,
        recovery_error: str | None = None,
    ) -> None:
        """Optional 실패와 liveness/recovery 호출 목록을 초기화합니다.

        Args:
            liveness_error: Read-only liveness 검사에서 발생시킬 optional diagnostic입니다.
            recovery_error: Non-Stop recovery에서 발생시킬 optional diagnostic입니다.
        """
        self.liveness_error = liveness_error
        self.recovery_error = recovery_error
        self.liveness_calls: list[tuple[WorkflowId, dict[str, object], dict[str, str], Path]] = []
        self.recovery_calls: list[tuple[WorkflowId, dict[str, object], dict[str, str], Path]] = []

    def assert_live(
        self,
        *,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Read-only liveness 호출을 기록하고 설정된 실패를 재현합니다.

        Args:
            workflow_id: Application이 선택한 workflow identity입니다.
            subscription: Workflow-local opaque monitor route입니다.
            environment: Runtime-owned identity environment입니다.
            cwd: Current canonical Git worktree입니다.

        Raises:
            AgentContinuationBlocked: Fixture에 liveness 실패가 설정된 경우 발생합니다.
        """
        self.liveness_calls.append((
            workflow_id,
            dict(subscription),
            dict(environment),
            cwd.resolve(),
        ))
        if self.liveness_error is not None:
            raise AgentContinuationBlocked(self.liveness_error)

    def recover_if_needed(
        self,
        *,
        workflow_id: WorkflowId,
        subscription: Mapping[str, object],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        """Non-Stop recovery 호출을 기록하고 설정된 실패를 재현합니다.

        Args:
            workflow_id: Application이 선택한 workflow identity입니다.
            subscription: Workflow-local opaque monitor route입니다.
            environment: Runtime-owned identity environment입니다.
            cwd: Current canonical Git worktree입니다.

        Raises:
            AgentContinuationBlocked: Fixture에 recovery 실패가 설정된 경우 발생합니다.
        """
        self.recovery_calls.append((
            workflow_id,
            dict(subscription),
            dict(environment),
            cwd.resolve(),
        ))
        if self.recovery_error is not None:
            raise AgentContinuationBlocked(self.recovery_error)


class AgentContinuationHookFixture:
    """한 Git repository 안에 여러 isolated session/workflow를 구성합니다."""

    def __init__(self, root: Path) -> None:
        """격리된 Git repository와 session locator를 생성합니다.

        Args:
            root: Test repository를 생성할 temporary root입니다.
        """
        self.repository = root / "repository"
        self.repository.mkdir()
        subprocess.run(("git", "init", "-q"), cwd=self.repository, check=True)
        subprocess.run(
            ("git", "config", "user.email", "fixture@example.invalid"),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "config", "user.name", "Fixture"),
            cwd=self.repository,
            check=True,
        )
        tracked = self.repository / "tracked.txt"
        tracked.write_text("fixture\n", encoding="utf-8")
        subprocess.run(("git", "add", "tracked.txt"), cwd=self.repository, check=True)
        subprocess.run(("git", "commit", "-qm", "fixture"), cwd=self.repository, check=True)
        self.locator = SessionLocator.from_worktree(self.repository)

    def open_session(
        self,
        session_id: str,
        *,
        runtime: SessionRuntime = SessionRuntime.CODEX,
        provision_turn: bool = True,
    ) -> StateHandle:
        """Exact runtime session과 root actor를 열어 handle을 반환합니다.

        Args:
            session_id: Fixture 안에서 사용할 session identity입니다.
            runtime: 동일 application을 검증할 vendor runtime입니다.
            provision_turn: Fresh SessionStart와 같은 provisional turn을 만들지 여부입니다.

        Returns:
            생성한 session의 root actor에 attach된 state handle입니다.
        """
        actor_id = ActorId(f"{runtime.value}:session:{session_id}")
        kernel = SessionKernel(self.locator)
        kernel.apply(
            SessionStarted(
                session_id=SessionId(session_id),
                resume_id=ResumeId(session_id),
                runtime=runtime,
                root_actor_id=actor_id,
                idempotency_key=f"start:{runtime.value}:{session_id}",
            )
        )
        handle = StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=runtime,
                session_id=SessionId(session_id),
                actor_id=actor_id,
                root_actor_id=actor_id,
            ),
        )
        if provision_turn:
            handle.apply(
                ForegroundTurnProvisioned(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    idempotency_key=f"provision:{runtime.value}:{session_id}",
                )
            )
        return handle

    def open_workflow(
        self,
        handle: StateHandle,
        workflow_id: str,
        *,
        kind: str = "process-ticket",
        skill_state: Mapping[str, object] | None = None,
    ) -> WorkflowId:
        """Handle owner에게 귀속된 active workflow를 생성합니다.

        Args:
            handle: Workflow를 소유할 exact session/actor handle입니다.
            workflow_id: 생성할 workflow identity입니다.
            kind: Workflow를 분류할 skill kind입니다.
            skill_state: 초기 workflow-local state입니다.

        Returns:
            생성한 typed workflow identity입니다.
        """
        selected = WorkflowId(workflow_id)
        handle.apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=selected,
                owner_actor_id=handle.actor_id,
                kind=kind,
                goal=f"goal:{workflow_id}",
                payload={"skill_state": dict(skill_state or {})},
                idempotency_key=f"workflow:{handle.session_id}:{workflow_id}",
            )
        )
        return selected

    def monitor_subscription(
        self,
        *,
        session_id: str = "session",
        workflow_id: str = "workflow",
        heartbeat_at_epoch: float = 1234.5,
    ) -> dict[str, object]:
        """Current fixture worktree에 결속된 v4-compatible monitor route를 만듭니다.

        Args:
            session_id: Subscription을 소유하는 exact runtime session입니다.
            workflow_id: Subscription을 소유하는 exact workflow입니다.
            heartbeat_at_epoch: Canonical launch readback의 heartbeat baseline입니다.

        Returns:
            Exact process, route와 poll interval이 포함된 subscription입니다.
        """
        worktree_id = str(WorktreeIdentityResolver().resolve(self.repository).worktree_id)
        return {
            "provider": "local-pr-monitor",
            "repo": "E5presso/neurath",
            "pr_number": 42,
            "session_id": session_id,
            "workflow_id": workflow_id,
            "runtime_id": "runtime-42",
            "worktree_id": worktree_id,
            "observation_resource": {
                "kind": "monitor-observation-cache",
                "worktree_id": worktree_id,
            },
            "poll_interval_seconds": 30,
            "last_seen": {},
            "pid": os.getpid(),
            "heartbeat_at_epoch": heartbeat_at_epoch,
            "resume_adapter": "command",
        }

    def active_turn(self, handle: StateHandle) -> None:
        """Runtime Stop이 직접 닫을 active foreground turn을 구성합니다.

        Args:
            handle: Active foreground turn을 소유할 actor-bound handle입니다.
        """
        handle.apply(
            ForegroundTurnProvisioned(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                idempotency_key=f"fixture:turn:provision:{handle.actor_id}",
            )
        )
        handle.apply(
            ForegroundTurnPrompted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                vendor_turn_id=None,
                idempotency_key=f"fixture:turn:prompt:{handle.actor_id}",
            )
        )

    def ready_turn(self, handle: StateHandle) -> None:
        """Legacy receipt 호환성 test에 ready-to-stop turn을 구성합니다.

        Args:
            handle: Ready-to-stop foreground turn을 소유할 actor-bound handle입니다.
        """
        self.active_turn(handle)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        handle.apply(
            ForegroundTurnYielded(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                expected_turn_revision=turn.revision,
                receipt=ForegroundTurnReceipt(
                    ForegroundTurnOutcome.COMPLETED,
                    summary="fixture inner workflow reached terminal control return",
                ),
                idempotency_key=(
                    f"fixture:turn:yield:{handle.actor_id}:{turn.generation}:{turn.revision}"
                ),
            )
        )

    def application(
        self,
        *,
        git: FakeGitPublication | None = None,
        monitor: FakeMonitorRuntime | None = None,
        runtime: SessionRuntime = SessionRuntime.CODEX,
    ) -> AgentContinuationHookApplication:
        """Deterministic clock과 fake 외부 port를 가진 application을 만듭니다.

        Args:
            git: Optional Git publication fake입니다.
            monitor: Optional monitor runtime fake입니다.
            runtime: 동일 application contract를 실행할 vendor runtime입니다.

        Returns:
            Exact-session hook application입니다.
        """
        selected_monitor = monitor or FakeMonitorRuntime()
        return AgentContinuationHookApplication(
            runtime=runtime,
            git_publication=git or FakeGitPublication(),
            monitor_liveness=selected_monitor,
            monitor_recovery=selected_monitor,
            clock=lambda: 1234.5,
        )

    def run(
        self,
        application: AgentContinuationHookApplication,
        session_id: str,
        event: HookEvent,
        *,
        prompt: str | None = None,
        turn_id: str | None = None,
        runtime: SessionRuntime = SessionRuntime.CODEX,
    ) -> HookResult:
        """Codex hook payload와 runtime identity로 application을 실행합니다.

        Args:
            application: 실행할 hook application입니다.
            session_id: Payload와 runtime에 함께 제공할 exact session입니다.
            event: 실행할 normalized hook event입니다.
            prompt: UserPromptSubmit에서만 전달하는 optional user text입니다.
            turn_id: Optional native turn identity입니다.
            runtime: Payload를 전달하는 vendor runtime입니다.

        Returns:
            Vendor hook protocol result입니다.
        """
        payload: dict[str, object] = {
            "hook_event_name": event.value,
            "session_id": session_id,
        }
        if turn_id is not None:
            payload["turn_id"] = turn_id
        if prompt is not None:
            payload["prompt"] = prompt
        environment_key = (
            "CODEX_THREAD_ID" if runtime is SessionRuntime.CODEX else "CLAUDE_CODE_SESSION_ID"
        )
        return application.run(
            json.dumps(payload),
            {environment_key: session_id},
            self.repository,
        )


class AgentContinuationHookTest(TestCase):
    """Global scan 없이 exact session workflow만 mutation/gate하는지 검증합니다."""

    def setUp(self) -> None:
        """각 test에 독립 Git repository fixture를 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = AgentContinuationHookFixture(Path(self.temporary_directory.name))

    def test_session_start_before_kernel_initialization_is_a_noop(self) -> None:
        """초기화 전 startup hook은 다른 session을 탐색하지 않습니다."""
        result = self.fixture.run(
            self.fixture.application(),
            "not-open-yet",
            HookEvent.SESSION_START,
        )

        self.assertEqual(0, result.exit_code)
        self.assertEqual("{}", result.stdout)

    def test_non_start_event_without_exact_session_fails_closed(self) -> None:
        """SessionStart 외 lifecycle은 canonical session state가 없으면 모두 거부됩니다."""
        for event in (
            HookEvent.USER_PROMPT,
            HookEvent.PRE_TOOL,
            HookEvent.PRE_COMPACT,
            HookEvent.STOP,
        ):
            with self.subTest(event=event.value):
                result = self.fixture.run(
                    self.fixture.application(),
                    "not-open-yet",
                    event,
                )

                self.assertEqual(2, result.exit_code)
                self.assertIn("exact-session state is missing", result.stderr)

    def test_user_prompt_mutates_only_matching_session(self) -> None:
        """User prompt activity는 exact matching session만 변경합니다."""
        handle_a = self.fixture.open_session("session-a")
        handle_b = self.fixture.open_session("session-b")
        workflow_a = self.fixture.open_workflow(handle_a, "workflow-a")
        workflow_b = self.fixture.open_workflow(handle_b, "workflow-b")

        result = self.fixture.run(
            self.fixture.application(),
            "session-a",
            HookEvent.USER_PROMPT,
            turn_id="turn-a",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        state_a = SkillStateStore(handle_a, workflow_a).read().skill_state
        state_b = SkillStateStore(handle_b, workflow_b).read().skill_state
        self.assertEqual(
            "turn-a",
            mapping(state_a["owner_lifecycle"], "session A lifecycle")["turn_id"],
        )
        self.assertNotIn("owner_lifecycle", state_b)

    def test_one_session_can_activate_multiple_monitor_workflows(self) -> None:
        """한 session의 여러 monitor workflow를 동일 activity로 활성화합니다."""
        handle = self.fixture.open_session("session")
        workflow_a = self.fixture.open_workflow(handle, "workflow-a")
        workflow_b = self.fixture.open_workflow(handle, "workflow-b", kind="monitor-pr")

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.PRE_COMPACT,
            turn_id="turn-1",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        for workflow_id in (workflow_a, workflow_b):
            lifecycle = mapping(
                SkillStateStore(handle, workflow_id).read().skill_state["owner_lifecycle"],
                "owner lifecycle",
            )
            self.assertEqual("active", lifecycle["state"])
            self.assertEqual("PreCompact", lifecycle["activity"])

    def test_global_pointer_and_flat_legacy_state_are_never_consulted(self) -> None:
        """손상된 global pointer와 flat legacy state를 전혀 읽지 않습니다."""
        runs = self.fixture.locator.control_root / ".agents/runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / "active-north-star.json").write_text("{not-json", encoding="utf-8")
        (runs / "flat-run.json").write_text(
            json.dumps({"owner_lifecycle": {"state": "corrupt"}}),
            encoding="utf-8",
        )
        handle = self.fixture.open_session("exact-session")
        workflow = self.fixture.open_workflow(handle, "exact-workflow")

        result = self.fixture.run(
            self.fixture.application(),
            "exact-session",
            HookEvent.USER_PROMPT,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        lifecycle = mapping(
            SkillStateStore(handle, workflow).read().skill_state["owner_lifecycle"],
            "owner lifecycle",
        )
        self.assertEqual("session-turn:exact-session", lifecycle["turn_id"])

    def test_stop_blocks_unresolved_delegation_before_worktree_checks(self) -> None:
        """미소비 delegation은 Git 외부 검증 전에 Stop을 차단합니다."""
        handle = self.fixture.open_session("session")
        self.fixture.open_workflow(handle, "workflow")
        target = ActorId("codex:worker")
        handle.apply(
            ActorStarted(
                session_id=handle.session_id,
                actor_id=target,
                parent_actor_id=handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker",
            )
        )
        handle.apply(
            DelegationAssigned(
                session_id=handle.session_id,
                delegation_id=DelegationId("delegation"),
                owner_actor_id=handle.actor_id,
                target_actor_id=target,
                assignment="review",
                idempotency_key="delegation:review",
            )
        )
        self.fixture.ready_turn(handle)
        git = FakeGitPublication()

        result = self.fixture.run(
            self.fixture.application(git=git),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("unresolved delegation", result.stderr)
        self.assertEqual([], git.paths)

    def test_stop_blocks_active_claim_without_matching_ack(self) -> None:
        """Matching ACK가 없는 active mailbox claim은 Stop을 차단합니다."""
        handle = self.fixture.open_session("session")
        workflow = self.fixture.open_workflow(
            handle,
            "workflow",
            skill_state={
                "owner_lifecycle": {
                    "state": "active",
                    "owner_session_id": "session",
                    "source": "native-hook",
                    "activity": "UserPromptSubmit",
                    "transitioned_at_epoch": 1.0,
                    "turn_id": "turn",
                },
                "monitor_mailbox": {
                    "pending_events": [],
                    "seen_event_ids": ["event-1"],
                    "active_claim": {
                        "claim_id": "claim-1",
                        "event": {"event_id": "event-1", "reason": "ci-failed"},
                    },
                    "updated_at_epoch": 1.0,
                },
            },
        )
        self.fixture.ready_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
            turn_id="turn",
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("not acknowledged", result.stderr)
        lifecycle = mapping(
            SkillStateStore(handle, workflow).read().skill_state["owner_lifecycle"],
            "owner lifecycle",
        )
        self.assertEqual("active", lifecycle["state"])

    def test_stop_consumes_valid_claim_and_releases_owner(self) -> None:
        """Valid claim과 ACK는 turn 완료와 owner release로 전이됩니다."""
        handle = self.fixture.open_session("session")
        workflow = self.fixture.open_workflow(
            handle,
            "workflow",
            skill_state={
                "owner_lifecycle": {
                    "state": "active",
                    "owner_session_id": "session",
                    "source": "native-hook",
                    "activity": "UserPromptSubmit",
                    "transitioned_at_epoch": 1.0,
                    "turn_id": "turn",
                },
                "monitor_mailbox": {
                    "pending_events": [],
                    "seen_event_ids": ["event-1"],
                    "active_claim": {
                        "claim_id": "claim-1",
                        "event": {"event_id": "event-1", "reason": "ci-failed"},
                    },
                    "updated_at_epoch": 1.0,
                },
                "monitor_event_ack": {
                    "event_id": "event-1",
                    "reason": "ci-failed",
                    "evidence": ["ci_readback:failedChecks=0"],
                },
            },
        )
        self.fixture.ready_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
            turn_id="turn",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        saved = SkillStateStore(handle, workflow).read().skill_state
        lifecycle = mapping(saved["owner_lifecycle"], "owner lifecycle")
        mailbox = mapping(saved["monitor_mailbox"], "monitor mailbox")
        self.assertEqual("idle", lifecycle["state"])
        self.assertEqual("turn", lifecycle["released_turn_id"])
        self.assertIsNone(mailbox["active_claim"])

    def test_stop_blocks_open_harness_incident(self) -> None:
        """Open harness incident가 있으면 continuation을 fail-closed합니다."""
        handle = self.fixture.open_session("session")
        self.fixture.open_workflow(handle, "workflow")
        handle.apply(
            HarnessIncidentRecorded(
                session_id=handle.session_id,
                occurrence_id=IncidentId("incident-1"),
                rule_id="repeated-failure",
                actor_id=handle.actor_id,
                symptom="reproduction",
                recorded_at="2026-08-04T00:00:00+00:00",
                idempotency_key="incident:1",
            )
        )
        self.fixture.ready_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("unresolved harness incident", result.stderr)

    def test_registered_monitor_uses_exact_session_and_workflow_route(self) -> None:
        """Registered monitor가 exact session/workflow route만 사용합니다."""
        handle = self.fixture.open_session("session")
        worktree_id = str(WorktreeIdentityResolver().resolve(self.fixture.repository).worktree_id)
        subscription = {
            "provider": "local-pr-monitor",
            "repo": "E5presso/neurath",
            "pr_number": 42,
            "session_id": "session",
            "workflow_id": "workflow",
            "runtime_id": "runtime-42",
            "worktree_id": worktree_id,
            "observation_resource": {
                "kind": "monitor-observation-cache",
                "worktree_id": worktree_id,
            },
            "poll_interval_seconds": 30,
            "last_seen": {},
            "resume_adapter": "unavailable",
        }
        self.fixture.open_workflow(
            handle,
            "workflow",
            skill_state={"monitor_event_subscription": subscription},
        )
        monitor = FakeMonitorRuntime()

        result = self.fixture.run(
            self.fixture.application(monitor=monitor),
            "session",
            HookEvent.SESSION_START,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([], monitor.liveness_calls)
        self.assertEqual(1, len(monitor.recovery_calls))
        workflow_id, selected, environment, cwd = monitor.recovery_calls[0]
        self.assertEqual(WorkflowId("workflow"), workflow_id)
        self.assertEqual("session", selected["session_id"])
        self.assertEqual("session", environment["CODEX_THREAD_ID"])
        self.assertEqual(self.fixture.repository.resolve(), cwd)

    def test_local_runtime_reads_only_the_opaque_current_worktree_resource(self) -> None:
        """Local runtime은 current worktree의 opaque observation만 읽습니다."""
        observation_path = self.fixture.repository / ".monitor-pr/monitor-state.json"
        observation_path.parent.mkdir(parents=True)
        route = self.fixture.monitor_subscription(heartbeat_at_epoch=100.0)
        observation_path.write_text(
            json.dumps({
                "schema_version": 4,
                **{
                    key: value
                    for key, value in route.items()
                    if key
                    in {
                        "provider",
                        "repo",
                        "pr_number",
                        "session_id",
                        "workflow_id",
                        "runtime_id",
                        "worktree_id",
                        "resume_adapter",
                        "pid",
                        "heartbeat_at_epoch",
                        "poll_interval_seconds",
                    }
                },
            }),
            encoding="utf-8",
        )
        runtime = LocalMonitorRuntime(clock=lambda: 100.0)

        runtime.assert_live(
            workflow_id=WorkflowId("workflow"),
            subscription=route,
            environment={"CODEX_THREAD_ID": "session"},
            cwd=self.fixture.repository,
        )
        with self.assertRaisesRegex(MonitorRuntimeUnavailable, "worktree_id"):
            runtime.assert_live(
                workflow_id=WorkflowId("workflow"),
                subscription={**route, "worktree_id": "foreign"},
                environment={"CODEX_THREAD_ID": "session"},
                cwd=self.fixture.repository,
            )

    def test_local_runtime_liveness_does_not_create_missing_observation_resource(self) -> None:
        """Read-only liveness 실패는 Stop 경로에 directory나 lock file을 만들지 않습니다."""
        observation_directory = self.fixture.repository / ".monitor-pr"
        self.assertFalse(observation_directory.exists())
        route = self.fixture.monitor_subscription(heartbeat_at_epoch=100.0)
        runtime = LocalMonitorRuntime(clock=lambda: 100.0)

        with self.assertRaises(MonitorRuntimeUnavailable):
            runtime.assert_live(
                workflow_id=WorkflowId("workflow"),
                subscription=route,
                environment={"CODEX_THREAD_ID": "session"},
                cwd=self.fixture.repository,
            )

        self.assertFalse(observation_directory.exists())

    def test_local_runtime_recovery_requires_fresh_readback_after_starter_success(self) -> None:
        """Starter exit 0도 fresh exact-route observation 없이는 recovery 성공이 아닙니다."""
        observation_path = self.fixture.repository / ".monitor-pr/monitor-state.json"
        observation_path.parent.mkdir(parents=True)
        route = self.fixture.monitor_subscription(heartbeat_at_epoch=100.0)
        observation_path.write_text(
            json.dumps({
                "schema_version": 4,
                **{
                    key: value
                    for key, value in route.items()
                    if key
                    in {
                        "provider",
                        "repo",
                        "pr_number",
                        "session_id",
                        "workflow_id",
                        "runtime_id",
                        "worktree_id",
                        "resume_adapter",
                        "pid",
                        "heartbeat_at_epoch",
                        "poll_interval_seconds",
                    }
                },
            }),
            encoding="utf-8",
        )
        starter = (
            self.fixture.repository
            / ".agents/skills/monitor-pr/scripts/start_local_pr_monitor_locked.sh"
        )
        starter.parent.mkdir(parents=True)
        starter.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        runtime = LocalMonitorRuntime(clock=lambda: 200.0)
        completed = subprocess.CompletedProcess(
            args=("bash", str(starter)),
            returncode=0,
            stdout="{}\n",
            stderr="",
        )

        with (
            patch(
                "scripts.agent_harness.agent_continuation_hook.LocalMonitorRuntime._run_starter",
                return_value=completed,
            ),
            self.assertRaisesRegex(MonitorRuntimeUnavailable, "fresh live readback"),
        ):
            runtime.recover_if_needed(
                workflow_id=WorkflowId("workflow"),
                subscription=route,
                environment={"CODEX_THREAD_ID": "session"},
                cwd=self.fixture.repository,
            )

    def test_local_runtime_recovery_accepts_fresh_starter_readback(self) -> None:
        """Recovery는 starter의 새 route와 같은 fresh observation을 검증한 뒤 성공합니다."""
        from scripts.agent_harness.monitor_observation_store import MonitorObservationStore
        observation_path = self.fixture.repository / ".monitor-pr/monitor-state.json"
        observation_path.parent.mkdir(parents=True)
        route = self.fixture.monitor_subscription(heartbeat_at_epoch=100.0)
        MonitorObservationStore(observation_path).write({
                "schema_version": 4,
                **{
                    key: value
                    for key, value in route.items()
                    if key
                    in {
                        "provider",
                        "repo",
                        "pr_number",
                        "session_id",
                        "workflow_id",
                        "runtime_id",
                        "worktree_id",
                        "resume_adapter",
                        "pid",
                        "heartbeat_at_epoch",
                        "poll_interval_seconds",
                    }
                },
            })
        starter = (
            self.fixture.repository
            / ".agents/skills/monitor-pr/scripts/start_local_pr_monitor_locked.sh"
        )
        starter.parent.mkdir(parents=True)
        starter.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        fresh_route = {
            **route,
            "runtime_id": "runtime-fresh",
            "heartbeat_at_epoch": 200.0,
        }

        def start_with_fresh_readback(
            starter_path: Path,
            worktree: Path,
            environment: Mapping[str, str],
        ) -> subprocess.CompletedProcess[str]:
            """새 runtime observation을 쓴 뒤 starter receipt를 반환합니다."""
            self.assertEqual(starter.resolve(), starter_path)
            self.assertEqual(self.fixture.repository.resolve(), worktree)
            self.assertEqual("workflow", environment["WORKFLOW_ID"])
            MonitorObservationStore(observation_path).write({
                    "schema_version": 4,
                    **{
                        key: value
                        for key, value in fresh_route.items()
                        if key
                        in {
                            "provider",
                            "repo",
                            "pr_number",
                            "session_id",
                            "workflow_id",
                            "runtime_id",
                            "worktree_id",
                            "resume_adapter",
                            "pid",
                            "heartbeat_at_epoch",
                            "poll_interval_seconds",
                        }
                    },
                })
            return subprocess.CompletedProcess(
                args=("bash", str(starter_path)),
                returncode=0,
                stdout=json.dumps(fresh_route),
                stderr="",
            )

        runtime = LocalMonitorRuntime(clock=lambda: 200.0)
        with patch(
            "scripts.agent_harness.agent_continuation_hook.LocalMonitorRuntime._run_starter",
            side_effect=start_with_fresh_readback,
        ) as starter_run:
            runtime.recover_if_needed(
                workflow_id=WorkflowId("workflow"),
                subscription=route,
                environment={"CODEX_THREAD_ID": "session"},
                cwd=self.fixture.repository,
            )

        starter_run.assert_called_once()

    def test_local_runtime_recovery_rejects_fresh_receipt_for_different_pr_route(self) -> None:
        """Starter가 live observation을 만들더라도 canonical repo/PR을 바꿀 수 없습니다."""
        observation_path = self.fixture.repository / ".monitor-pr/monitor-state.json"
        observation_path.parent.mkdir(parents=True)
        route = self.fixture.monitor_subscription(heartbeat_at_epoch=100.0)
        observation_path.write_text(
            json.dumps({
                "schema_version": 4,
                **{
                    key: value
                    for key, value in route.items()
                    if key
                    in {
                        "provider",
                        "repo",
                        "pr_number",
                        "session_id",
                        "workflow_id",
                        "runtime_id",
                        "worktree_id",
                        "resume_adapter",
                        "pid",
                        "heartbeat_at_epoch",
                        "poll_interval_seconds",
                    }
                },
            }),
            encoding="utf-8",
        )
        starter = (
            self.fixture.repository
            / ".agents/skills/monitor-pr/scripts/start_local_pr_monitor_locked.sh"
        )
        starter.parent.mkdir(parents=True)
        starter.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        foreign_route = {
            **route,
            "repo": "other/repository",
            "pr_number": 999,
            "runtime_id": "runtime-foreign",
            "heartbeat_at_epoch": 200.0,
        }

        def start_foreign_route(
            _starter_path: Path,
            _worktree: Path,
            _environment: Mapping[str, str],
        ) -> subprocess.CompletedProcess[str]:
            """Starter 성공 뒤 foreign route를 기록한 process 결과를 반환합니다.

            Args:
                _starter_path: 이 fixture에서 사용하지 않는 starter 경로입니다.
                _worktree: 이 fixture에서 사용하지 않는 worktree 경로입니다.
                _environment: 이 fixture에서 사용하지 않는 runtime 환경입니다.

            Returns:
                성공 exit code와 foreign route stdout을 가진 process 결과입니다.
            """
            observation_path.write_text(
                json.dumps({
                    "schema_version": 4,
                    **{
                        key: value
                        for key, value in foreign_route.items()
                        if key
                        in {
                            "provider",
                            "repo",
                            "pr_number",
                            "session_id",
                            "workflow_id",
                            "runtime_id",
                            "worktree_id",
                            "resume_adapter",
                            "pid",
                            "heartbeat_at_epoch",
                            "poll_interval_seconds",
                        }
                    },
                }),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                args=("bash", str(starter)),
                returncode=0,
                stdout=json.dumps(foreign_route),
                stderr="",
            )

        runtime = LocalMonitorRuntime(clock=lambda: 200.0)
        with (
            patch(
                "scripts.agent_harness.agent_continuation_hook.LocalMonitorRuntime._run_starter",
                side_effect=start_foreign_route,
            ),
            self.assertRaisesRegex(MonitorRuntimeUnavailable, "fresh live readback"),
        ):
            runtime.recover_if_needed(
                workflow_id=WorkflowId("workflow"),
                subscription=route,
                environment={"CODEX_THREAD_ID": "session"},
                cwd=self.fixture.repository,
            )

    def test_runtime_and_payload_session_mismatch_fails_closed(self) -> None:
        """Runtime과 payload session 불일치는 typed failure로 닫힙니다."""
        self.fixture.open_session("session-a")
        result = self.fixture.application().run(
            json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-b",
            }),
            {"CODEX_THREAD_ID": "session-a"},
            self.fixture.repository,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("conflicts", result.stderr)

    def test_codex_payload_session_without_thread_environment_opens_turn(self) -> None:
        """Runtime-specific Codex adapter는 공식 payload session_id로 turn을 엽니다."""
        self.fixture.open_session("payload-only")

        result = self.fixture.application().run(
            json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "session_id": "payload-only",
            }),
            {},
            self.fixture.repository,
        )

        self.assertEqual(0, result.exit_code, result.stderr)

    def test_codex_overlay_without_vendor_identity_fails_closed(self) -> None:
        """Codex caller가 만든 Neurath overlay는 vendor thread authority를 대체하지 않습니다."""
        handle = self.fixture.open_session("overlay-only")

        result = self.fixture.application().run(
            json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "session_id": "overlay-only",
            }),
            {
                "NEURATH_AGENT_SESSION_ID": "overlay-only",
                "NEURATH_AGENT_ACTOR_ID": str(handle.actor_id),
                "NEURATH_AGENT_RUNTIME": "codex",
            },
            self.fixture.repository,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("vendor", result.stderr)

    def test_payload_actor_claim_cannot_inherit_root_vendor_identity(self) -> None:
        """Payload의 child actor claim을 무시하고 root로 실행하는 경로를 차단합니다."""
        handle = self.fixture.open_session("session")
        worker = ActorId("codex:worker")
        handle.apply(
            ActorStarted(
                session_id=handle.session_id,
                actor_id=worker,
                parent_actor_id=handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="payload-actor:worker",
            )
        )

        before = handle.inspect().foreground_turns[handle.actor_id].to_payload()
        result = self.fixture.application().run(
            json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session",
                "thread_id": "session",
                "actor_id": str(worker),
            }),
            {"CODEX_THREAD_ID": "session"},
            self.fixture.repository,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("actor identity", result.stderr)
        self.assertEqual(
            before,
            handle.inspect().foreground_turns[handle.actor_id].to_payload(),
        )

    def test_invalid_canonical_state_does_not_fallback_to_other_session(self) -> None:
        """손상된 canonical state가 다른 session fallback을 유발하지 않습니다."""
        handle = self.fixture.open_session("corrupt")
        self.fixture.open_workflow(handle, "workflow")
        self.fixture.open_session("fallback")
        with RuntimeDatabase(self.fixture.repository).connection() as db:
            changed = db.execute(
                "UPDATE runtime_records SET payload=? "
                "WHERE namespace='session' AND key='corrupt'",
                (b"{not-json",),
            )
            self.assertEqual(1, changed.rowcount)

        result = self.fixture.run(
            self.fixture.application(),
            "corrupt",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("Agent continuation blocked", result.stderr)



class StopTerminalReachabilityMatrixTest(TestCase):
    """Frozen exact-session Stop terminal-reachability matrix를 검증합니다."""

    def setUp(self) -> None:
        """각 matrix row에 독립 Git repository와 session fixture를 제공합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = AgentContinuationHookFixture(Path(self.temporary_directory.name))

    def _awaiting_input_turn(
        self,
        handle: StateHandle,
        *,
        question: str = "현재 사용자 결정을 선택해 주세요.",
    ) -> None:
        """Adaptive AWAIT_USER와 결속할 exact awaiting-input outer turn을 만듭니다."""
        current = handle.inspect().foreground_turns.get(handle.actor_id)
        if current is None or current.status is not ForegroundTurnStatus.ACTIVE:
            self.fixture.active_turn(handle)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        handle.apply(
            ForegroundTurnYielded(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                expected_turn_revision=turn.revision,
                receipt=ForegroundTurnReceipt(
                    ForegroundTurnOutcome.AWAITING_INPUT,
                    question=question,
                ),
                idempotency_key=f"fixture:turn:awaiting-input:{handle.actor_id}",
            )
        )

    def _adaptive_receipt(
        self,
        *,
        workflow_revision: int,
        action: ControlAction,
        achieved: bool = False,
        ambiguity_action: ControlAction = ControlAction.CONTINUE,
        ambiguity_ready: bool = True,
    ) -> SimpleNamespace:
        """Control-return gate가 읽는 receipt projection을 고정합니다."""
        return SimpleNamespace(
            workflow_revision=workflow_revision,
            ambiguity=SimpleNamespace(
                action=ambiguity_action,
                ready=ambiguity_ready,
                selected_gap_id=(
                    "fixture-gap"
                    if ambiguity_action is ControlAction.ASK_USER and not ambiguity_ready
                    else None
                ),
            ),
            decision=SimpleNamespace(action=action, achieved=achieved),
            attainment=SimpleNamespace(
                action=(
                    ControlAction.AWAIT_USER
                    if action is ControlAction.AWAIT_USER
                    else ControlAction.CONTINUE
                ),
                achieved=achieved,
            ),
        )

    def _seed_ask_user_state(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        *,
        gap_id: str = "scope-choice",
        question: str = "어느 스코프를 적용할까요?",
        gap_intent_revision: int | None = None,
    ) -> str:
        """Unresolved user-owned clarification gap으로 current ASK_USER를 저장합니다."""
        goal = handle.inspect().workflows[workflow_id].goal
        self.assertIsNotNone(goal)
        assert goal is not None
        constraints = ("질문 전에 선택을 추측하지 않는다",)
        non_goals = ("사용자 선택을 agent가 대신하지 않는다",)
        intent_revision = 1
        source_revision = "approved-plan:1"
        criterion = CriterionSpec(
            criterion_id="implementation-evidence",
            description="승인된 의도를 구현한다",
            source_requirement_id="REQ-implementation",
            approved_requirement_fingerprint=approved_requirement_fingerprint(
                goal,
                constraints,
                non_goals,
                intent_revision,
                source_revision,
            ),
            observer="executable verifier",
            precondition="사용자 의도가 확정되어 있다",
            stimulus="승인된 요구사항을 구현한다",
            expected_outcome="실행 가능한 검증이 통과한다",
            oracle_owner=OracleOwner.EXECUTABLE,
            hard=True,
            required_evidence=frozenset({EvidenceKind.EXAMPLE_TEST}),
        )
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            criteria=(criterion,),
            requirement_ids=frozenset({criterion.source_requirement_id}),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )
        gap = ClarificationGap(
            gap_id=gap_id,
            section=RequirementSection.SCOPE,
            authority=GapAuthority.USER,
            dependency_rank=0,
            weight=1.0,
            blocking=True,
            reversible=False,
            scope_local=False,
            context="두 스코프가 모두 현재 요청과 합치다",
            question=question,
            consequence="선택에 따라 구현 경계가 달라진다",
            recommendation="더 작은 스코프를 권장한다",
            recommendation_rationale="되돌릴 수 없는 범위를 최소화한다",
            intent_revision=(
                contract.intent_revision if gap_intent_revision is None else gap_intent_revision
            ),
            resolution=GapResolution.OPEN,
        )
        state = AdaptiveControlState.empty(
            contract,
            GapInventory(
                intent_revision=contract.intent_revision,
                source_revision="repo:current",
                assessed_sections=frozenset(RequirementSection),
                gaps=(gap,),
            ),
        )
        snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).update(
            lambda _current: state
        )
        receipt = snapshot.receipt()
        self.assertIs(ControlAction.ASK_USER, receipt.ambiguity.action)
        self.assertIs(ControlAction.ASK_USER, receipt.decision.action)
        return render_socratic_question(gap)

    def _seed_await_user_state(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        *,
        unverified_independent: bool = False,
    ) -> str:
        """User pending과 optional unverified independent claim을 저장합니다."""
        goal = handle.inspect().workflows[workflow_id].goal
        self.assertIsNotNone(goal)
        assert goal is not None
        constraints = ("질문 중 workflow를 active로 유지한다",)
        non_goals = ("AWAIT_USER를 completion으로 취급하지 않는다",)
        intent_revision = 1
        source_revision = "approved-plan:1"
        requirement_fingerprint = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            intent_revision,
            source_revision,
        )
        user_criterion = CriterionSpec(
            criterion_id="user-acceptance",
            description="사용자가 현재 결과를 최종 승인한다",
            source_requirement_id="REQ-user-acceptance",
            approved_requirement_fingerprint=requirement_fingerprint,
            observer="사용자",
            precondition="실행 결과가 사용자에게 제시되어 있다",
            stimulus="사용자에게 최종 승인을 요청한다",
            expected_outcome="사용자가 승인 또는 수정 요청을 반환한다",
            oracle_owner=OracleOwner.USER,
            hard=True,
            required_evidence=frozenset({EvidenceKind.USER_ACCEPTANCE}),
        )
        independent_criterion = CriterionSpec(
            criterion_id="independent-review",
            description="독립 evaluator가 current 결과를 검증한다",
            source_requirement_id="REQ-independent-review",
            approved_requirement_fingerprint=requirement_fingerprint,
            observer="독립 evaluator",
            precondition="Current 결과가 evaluator에게 전달되어 있다",
            stimulus="Independent semantic evaluation을 수행한다",
            expected_outcome="Consumed evaluator artifact가 결과를 승인한다",
            oracle_owner=OracleOwner.INDEPENDENT_EVALUATOR,
            hard=True,
            required_evidence=frozenset({EvidenceKind.INDEPENDENT_SEMANTIC}),
        )
        criteria = (
            (user_criterion, independent_criterion) if unverified_independent else (user_criterion,)
        )
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            criteria=criteria,
            requirement_ids=frozenset(criterion.source_requirement_id for criterion in criteria),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )
        inventory = GapInventory(
            intent_revision=contract.intent_revision,
            source_revision="repo:current",
            assessed_sections=frozenset(RequirementSection),
            gaps=(),
        )
        evidence: tuple[CriterionEvidence, ...] = ()
        coverage: GoalCoverage | None = None
        if unverified_independent:
            coverage_lineage = AuthorityReceipt(
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                issuer_id="codex:missing-adaptive-evaluator",
                subject_id=str(handle.actor_id),
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                receipt_digest="d" * 64,
                delegation_id="missing-adaptive-evaluation",
            )
            evidence = (
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id=independent_criterion.criterion_id,
                    kind=EvidenceKind.INDEPENDENT_SEMANTIC,
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    status=EvidenceStatus.PASS,
                    reference="independent:missing",
                    lineage=coverage_lineage,
                ),
            )
            coverage = GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset(item.criterion_id for item in criteria),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="independent:missing-coverage",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=coverage_lineage,
            )
        state = AdaptiveControlState(
            contract=contract,
            inventory=inventory,
            evidence=evidence,
            coverage=coverage,
            execution_status=ExecutionStatus.INCOMPLETE,
            observations=(),
        )
        store = AdaptiveControlStore(SkillStateStore(handle, workflow_id))
        if unverified_independent:
            workflow = handle.inspect().workflows[workflow_id]
            payload = dict(workflow.payload)
            skill_state = mapping(payload.get("skill_state"), "workflow skill_state")
            payload["skill_state"] = {
                **skill_state,
                "adaptive_control": state.to_payload(),
            }
            SessionStateStore(
                self.fixture.locator.locate(handle.session_id).process_state
            ).transact(
                ReservedSkillStateAdvanced(
                    session_id=handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=handle.actor_id,
                    expected_workflow_revision=workflow.revision,
                    payload=payload,
                    idempotency_key="continuation-fixture:seed-unverified-adaptive",
                    reserved_namespaces=frozenset({"adaptive_control"}),
                )
            )
            snapshot = store.read()
        else:
            snapshot = store.update(lambda _current: state)
        self.assertIs(ControlAction.AWAIT_USER, snapshot.receipt().decision.action)
        return render_user_acceptance_question(
            contract,
            (user_criterion.criterion_id,),
        )

    def test_root_active_generic_stop_denies(self) -> None:
        """Root가 소유한 active generic workflow는 Stop을 차단합니다."""
        handle = self.fixture.open_session("session")
        self.fixture.open_workflow(handle, "generic", kind="commit")
        self.fixture.active_turn(handle)
        git = FakeGitPublication()

        result = self.fixture.run(
            self.fixture.application(git=git),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("Agent continuation blocked", result.stderr)
        self.assertIn("generic", result.stderr)
        self.assertEqual([], git.paths)

    def test_root_active_unknown_stop_denies(self) -> None:
        """등록되지 않은 active workflow kind도 generic foreground로 Stop을 차단합니다."""
        handle = self.fixture.open_session("session")
        self.fixture.open_workflow(handle, "unknown", kind="future-workflow-kind")
        self.fixture.active_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("unknown", result.stderr)

    def test_root_active_monitor_stoppable_stop_allows(self) -> None:
        """기존 monitor-managed workflow의 검증된 stoppable 경로는 계속 허용합니다."""
        handle = self.fixture.open_session("session")
        subscription = self.fixture.monitor_subscription(workflow_id="monitor")
        workflow = self.fixture.open_workflow(
            handle,
            "monitor",
            skill_state={"monitor_event_subscription": subscription},
        )
        self.fixture.active_turn(handle)
        git = FakeGitPublication()
        monitor = FakeMonitorRuntime()

        result = self.fixture.run(
            self.fixture.application(git=git, monitor=monitor),
            "session",
            HookEvent.STOP,
            turn_id="turn",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([self.fixture.repository.resolve()], git.paths)
        self.assertEqual(1, len(monitor.liveness_calls))
        self.assertEqual([], monitor.recovery_calls)
        lifecycle = mapping(
            SkillStateStore(handle, workflow).read().skill_state["owner_lifecycle"],
            "owner lifecycle",
        )
        self.assertEqual("idle", lifecycle["state"])
        self.assertEqual("turn", lifecycle["released_turn_id"])

    def test_stop_closes_two_monitors_and_turn_with_one_canonical_cas(self) -> None:
        """두 monitor의 idle projection과 turn close는 process revision을 한 번만 올립니다."""
        handle = self.fixture.open_session("session")
        workflow_a = self.fixture.open_workflow(
            handle,
            "monitor-a",
            kind="monitor-pr",
            skill_state={
                "monitor_event_subscription": self.fixture.monitor_subscription(
                    workflow_id="monitor-a"
                )
            },
        )
        workflow_b = self.fixture.open_workflow(
            handle,
            "monitor-b",
            kind="monitor-pr",
            skill_state={
                "monitor_event_subscription": self.fixture.monitor_subscription(
                    workflow_id="monitor-b"
                )
            },
        )
        self.fixture.active_turn(handle)
        before = handle.inspect()
        git = FakeGitPublication()
        monitor = FakeMonitorRuntime()

        result = self.fixture.run(
            self.fixture.application(git=git, monitor=monitor),
            "session",
            HookEvent.STOP,
            turn_id="turn",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        after = handle.inspect()
        self.assertEqual(before.revision + 1, after.revision)
        self.assertIs(
            ForegroundTurnStatus.CLOSED,
            after.foreground_turns[handle.actor_id].status,
        )
        self.assertEqual([self.fixture.repository.resolve()] * 2, git.paths)
        self.assertEqual(
            [workflow_a, workflow_b],
            [call[0] for call in monitor.liveness_calls],
        )
        self.assertEqual([], monitor.recovery_calls)
        for workflow_id in (workflow_a, workflow_b):
            workflow = after.workflows[workflow_id]
            self.assertEqual(before.workflows[workflow_id].revision + 1, workflow.revision)
            skill_state = mapping(workflow.payload["skill_state"], "skill state")
            lifecycle = mapping(skill_state["owner_lifecycle"], "owner lifecycle")
            self.assertEqual("idle", lifecycle["state"])
            self.assertEqual("turn", lifecycle["released_turn_id"])

    def test_second_monitor_validation_failure_commits_no_workflow_projection(self) -> None:
        """뒤 monitor의 external failure는 앞 monitor의 idle 전이도 저장하지 않습니다."""
        handle = self.fixture.open_session("session")
        workflows = tuple(
            self.fixture.open_workflow(
                handle,
                f"monitor-{index}",
                kind="monitor-pr",
                skill_state={
                    "monitor_event_subscription": self.fixture.monitor_subscription(
                        workflow_id=f"monitor-{index}"
                    )
                },
            )
            for index in (1, 2)
        )
        self.fixture.active_turn(handle)
        before = handle.inspect()

        class FailSecondMonitor(FakeMonitorRuntime):
            """첫 monitor는 통과시키고 두 번째 exact route에서 실패합니다."""

            def assert_live(
                self,
                *,
                workflow_id: WorkflowId,
                subscription: Mapping[str, object],
                environment: Mapping[str, str],
                cwd: Path,
            ) -> None:
                """두 번째 liveness 호출에서 deterministic failure를 발생시킵니다."""
                super().assert_live(
                    workflow_id=workflow_id,
                    subscription=subscription,
                    environment=environment,
                    cwd=cwd,
                )
                if len(self.liveness_calls) == 2:
                    raise AgentContinuationBlocked("second monitor is stale")

        monitor = FailSecondMonitor()
        result = self.fixture.run(
            self.fixture.application(monitor=monitor),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("second monitor is stale", result.stderr)
        after = handle.inspect()
        self.assertEqual(before.revision, after.revision)
        self.assertEqual(before.to_payload(), after.to_payload())
        for workflow_id in workflows:
            self.assertEqual(
                before.workflows[workflow_id].to_payload(),
                after.workflows[workflow_id].to_payload(),
            )
        self.assertEqual(2, len(monitor.liveness_calls))
        self.assertEqual([], monitor.recovery_calls)

    def test_stop_cas_conflict_preserves_all_monitor_projections(self) -> None:
        """External validation 뒤 canonical mutation이 이기면 projected idle state는 전혀 남지 않습니다."""
        handle = self.fixture.open_session("session")
        workflow = self.fixture.open_workflow(
            handle,
            "monitor",
            kind="monitor-pr",
            skill_state={
                "monitor_event_subscription": self.fixture.monitor_subscription(
                    workflow_id="monitor"
                )
            },
        )
        self.fixture.active_turn(handle)
        before = handle.inspect()

        class ConcurrentTurnObservation(FakeGitPublication):
            """External validation window에서 foreground revision을 전진시킵니다."""

            def validate_stoppable(self, worktree: Path) -> None:
                """검증 대상 path를 기록한 뒤 competing canonical event를 commit합니다."""
                super().validate_stoppable(worktree)
                handle.apply(
                    ActorStarted(
                        session_id=handle.session_id,
                        actor_id=ActorId("codex:stop-conflict-child"),
                        parent_actor_id=handle.actor_id,
                        kind=ActorKind.SUBAGENT,
                        idempotency_key="stop-conflict:actor-started",
                    )
                )

        git = ConcurrentTurnObservation()
        monitor = FakeMonitorRuntime()
        result = self.fixture.run(
            self.fixture.application(git=git, monitor=monitor),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("state changed during external Stop validation", result.stderr)
        after = handle.inspect()
        self.assertEqual(
            before.workflows[workflow].to_payload(),
            after.workflows[workflow].to_payload(),
        )
        self.assertIs(
            ForegroundTurnStatus.ACTIVE,
            after.foreground_turns[handle.actor_id].status,
        )
        self.assertEqual(1, len(git.paths))
        self.assertEqual(1, len(monitor.liveness_calls))
        self.assertEqual([], monitor.recovery_calls)

    def test_stop_liveness_failure_never_recovers_monitor(self) -> None:
        """Stop은 dead monitor를 launch하지 않고 read-only liveness failure로 닫힙니다."""
        handle = self.fixture.open_session("session")
        subscription = self.fixture.monitor_subscription(workflow_id="monitor")
        self.fixture.open_workflow(
            handle,
            "monitor",
            skill_state={"monitor_event_subscription": subscription},
        )
        self.fixture.ready_turn(handle)
        monitor = FakeMonitorRuntime(liveness_error="monitor heartbeat is stale")

        result = self.fixture.run(
            self.fixture.application(monitor=monitor),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("heartbeat is stale", result.stderr)
        self.assertEqual(1, len(monitor.liveness_calls))
        self.assertEqual([], monitor.recovery_calls)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)

    def test_no_active_workflow_stop_allows(self) -> None:
        """Exact session에 active workflow가 없으면 Stop을 허용합니다."""
        handle = self.fixture.open_session("session")
        self.fixture.active_turn(handle)
        git = FakeGitPublication()
        monitor = FakeMonitorRuntime()

        result = self.fixture.run(
            self.fixture.application(git=git, monitor=monitor),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([], git.paths)
        self.assertEqual([], monitor.liveness_calls)
        self.assertEqual([], monitor.recovery_calls)

    def test_adaptive_await_user_stop_returns_control_and_leaves_workflow_active(self) -> None:
        """Current AWAIT_USER와 awaiting-input turn은 inner workflow를 종료하지 않습니다."""
        handle = self.fixture.open_session("adaptive-await")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        question = self._seed_await_user_state(handle, workflow_id)
        self._awaiting_input_turn(handle, question=question)

        result = self.fixture.run(
            self.fixture.application(),
            "adaptive-await",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIs(
            WorkflowStatus.ACTIVE,
            handle.inspect().workflows[workflow_id].status,
        )
        self.assertIs(
            ForegroundTurnStatus.CLOSED,
            handle.inspect().foreground_turns[handle.actor_id].status,
        )

    def test_replaced_awaiting_question_survives_pending_task_stop_gate(self) -> None:
        """Host replacement stays incomplete but retains the exact question for the response."""
        from scripts.agent_harness.session_kernel import ForegroundTurnClosed, ForegroundTurnReplaced, InvalidSessionState
        from scripts.agent_harness.session_state_codec import SessionStateCodec
        from scripts.agent_harness.task_service import TaskService

        session = "adaptive-replaced-question"
        handle = self.fixture.open_session(session)
        initial = self.fixture.run(self.fixture.application(), session, HookEvent.USER_PROMPT,
                                   prompt="Review the request", turn_id="old-native-turn")
        self.assertEqual(0, initial.exit_code, initial.stderr)
        workflow_id = self.fixture.open_workflow(handle, "adaptive", kind="evaluate-harness", skill_state={})
        question = self._seed_await_user_state(handle, workflow_id)
        tasks = TaskService(handle)
        tasks.define([{"key": "pending", "title": "Pending implementation", "goal": "Complete implementation",
                       "sources": [], "acceptance": ["Required behavior is verified"],
                       "evidence_contract": "pending-work", "dependencies": []}],
                     expected_revision=0, key="pending-task")
        with tasks.database.transaction() as tx:
            original_record = tx.get("task-ledger", str(handle.session_id))
            assert original_record is not None
            original_tasks = original_record.payload
        self._awaiting_input_turn(handle, question=question)
        before = handle.inspect().foreground_turns[handle.actor_id]
        with self.assertRaisesRegex(TransitionRejected, "task"):
            handle.apply(ForegroundTurnClosed(session_id=handle.session_id, actor_id=handle.actor_id,
                         expected_turn_revision=before.revision, idempotency_key="refuse-task-stop"))
        event = ForegroundTurnReplaced(session_id=handle.session_id, actor_id=handle.actor_id,
                    expected_turn_revision=before.revision, replacement_reference="codex-turn:next-native-turn",
                    idempotency_key="host-replaces-awaiting-question")
        replaced = handle.apply(event)
        closed = replaced.foreground_turns[handle.actor_id]
        assert closed.receipt is not None
        assert before.receipt is not None
        assert closed.replacement_question is not None
        self.assertIs(ForegroundTurnOutcome.INCOMPLETE, closed.receipt.outcome)
        self.assertEqual(before.receipt.to_payload(), closed.replacement_question.to_payload())
        self.assertEqual(replaced.to_payload(), handle.apply(event).to_payload())
        codec = SessionStateCodec()
        decoded = codec.decode(replaced.to_payload(), handle.session_id)
        decoded_question = decoded.foreground_turns[handle.actor_id].awaiting_input_receipt
        assert decoded_question is not None
        self.assertEqual(question, decoded_question.question)
        malformed = json.loads(json.dumps(replaced.to_payload()))
        malformed["foreground_turns"][str(handle.actor_id)]["replacement_question"]["outcome"] = "completed"
        with self.assertRaises(InvalidSessionState):
            codec.decode(malformed, handle.session_id)
        legacy = json.loads(json.dumps(replaced.to_payload()))
        legacy["foreground_turns"][str(handle.actor_id)].pop("replacement_question")
        self.assertIsNone(codec.decode(legacy, handle.session_id).foreground_turns[handle.actor_id].awaiting_input_receipt)
        prompted = self.fixture.run(self.fixture.application(), session, HookEvent.USER_PROMPT,
                                     prompt="Proceed as proposed", turn_id="next-native-turn")
        self.assertEqual(0, prompted.exit_code, prompted.stderr)
        next_turn = handle.inspect().foreground_turns[handle.actor_id]
        assert next_turn.user_prompt_receipt is not None
        context = next_turn.user_prompt_receipt.authority_context
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(workflow_id, context.workflow_id)
        self.assertEqual(hashlib.sha256(question.encode()).hexdigest(), context.question_digest)
        self.assertEqual(closed.generation, context.question_generation)
        self.assertEqual(closed.revision, context.question_turn_revision)
        self.assertIsNone(next_turn.replacement_question)
        with tasks.database.transaction() as tx:
            retained = tx.get("task-ledger", str(handle.session_id))
            assert retained is not None
            self.assertEqual(original_tasks, retained.payload)
        with self.assertRaisesRegex(TransitionRejected, "task"):
            handle.apply(ForegroundTurnClosed(session_id=handle.session_id, actor_id=handle.actor_id,
                         expected_turn_revision=next_turn.revision, idempotency_key="refuse-next-task-stop"))

    def test_adaptive_await_user_response_binds_exact_goal_question_and_claims(self) -> None:
        """AWAIT_USER 다음 prompt는 exact workflow/goal/criteria/question digest만 보존합니다."""
        handle = self.fixture.open_session("adaptive-user-response")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        question = self._seed_await_user_state(handle, workflow_id)
        self._awaiting_input_turn(handle, question=question)
        stopped = self.fixture.run(
            self.fixture.application(),
            "adaptive-user-response",
            HookEvent.STOP,
        )
        self.assertEqual(0, stopped.exit_code, stopped.stderr)

        prompted = self.fixture.run(
            self.fixture.application(),
            "adaptive-user-response",
            HookEvent.USER_PROMPT,
            prompt="승인합니다.",
            turn_id="vendor-user-response",
        )

        self.assertEqual(0, prompted.exit_code, prompted.stderr)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        user_receipt = turn.user_prompt_receipt
        self.assertIsNotNone(user_receipt)
        assert user_receipt is not None
        context = user_receipt.authority_context
        self.assertIsNotNone(context)
        assert context is not None
        snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
        self.assertEqual(workflow_id, context.workflow_id)
        self.assertEqual(snapshot.state.contract.fingerprint, context.goal_fingerprint)
        self.assertEqual(("user-acceptance",), context.criterion_ids)
        self.assertEqual(("criterion:user-acceptance",), context.claim_ids)
        self.assertEqual(ControlAction.AWAIT_USER.value, context.control_action)
        self.assertEqual(
            hashlib.sha256(question.encode("utf-8")).hexdigest(),
            context.question_digest,
        )

        before_retry = handle.inspect().to_payload()
        retried = self.fixture.run(
            self.fixture.application(),
            "adaptive-user-response",
            HookEvent.USER_PROMPT,
            prompt="승인합니다.",
            turn_id="vendor-user-response",
        )
        self.assertEqual(0, retried.exit_code, retried.stderr)
        self.assertEqual(before_retry, handle.inspect().to_payload())

        with self.assertRaises(TransitionRejected):
            handle.apply(
                ForegroundTurnPrompted(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    vendor_turn_id="vendor-user-response",
                    prompt_digest="f" * 64,
                    authority_context=context,
                    idempotency_key="forged-steering-authority",
                )
            )
        self.assertEqual(before_retry, handle.inspect().to_payload())

        steered = self.fixture.run(
            self.fixture.application(),
            "adaptive-user-response",
            HookEvent.USER_PROMPT,
            prompt="추가 오류도 확인해주세요.",
            turn_id="vendor-user-response",
        )
        self.assertEqual(0, steered.exit_code, steered.stderr)
        latest = handle.inspect().foreground_turns[handle.actor_id].user_prompt_receipt
        assert latest is not None
        self.assertIsNone(latest.authority_context)
        self.assertNotEqual(user_receipt.authority_reference, latest.authority_reference)

    def test_adaptive_await_user_rejects_an_unrelated_acceptance_question(self) -> None:
        """같은 workflow의 awaiting-input이라도 canonical acceptance question만 허용합니다."""
        handle = self.fixture.open_session("adaptive-unrelated-acceptance")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        self._seed_await_user_state(handle, workflow_id)
        self._awaiting_input_turn(handle, question="다음 작업도 바로 시작할까요?")

        stopped = self.fixture.run(
            self.fixture.application(),
            "adaptive-unrelated-acceptance",
            HookEvent.STOP,
        )

        self.assertEqual(2, stopped.exit_code)
        self.assertIn("current control request", stopped.stderr)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
        self.assertIsNone(turn.user_prompt_receipt)

    def test_adaptive_ask_user_stop_returns_question_and_leaves_workflow_active(self) -> None:
        """Current ambiguity ASK_USER는 exact awaiting-input turn을 통해 질문을 반환합니다."""
        handle = self.fixture.open_session("adaptive-ask")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        question = "어느 스코프를 적용할까요?"
        rendered = self._seed_ask_user_state(handle, workflow_id, question=question)
        self._awaiting_input_turn(handle, question=rendered)

        result = self.fixture.run(
            self.fixture.application(),
            "adaptive-ask",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIs(WorkflowStatus.ACTIVE, handle.inspect().workflows[workflow_id].status)
        self.assertIs(
            ForegroundTurnStatus.CLOSED,
            handle.inspect().foreground_turns[handle.actor_id].status,
        )

    def test_adaptive_ask_user_rejects_unrelated_foreground_question(self) -> None:
        """Current selected gap과 다른 awaiting-input 질문은 provenance가 없습니다."""
        handle = self.fixture.open_session("adaptive-unrelated-question")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        self._seed_ask_user_state(
            handle,
            workflow_id,
            question="어느 스코프를 적용할까요?",
        )
        self._awaiting_input_turn(handle, question="배포를 진행할까요?")

        result = self.fixture.run(
            self.fixture.application(),
            "adaptive-unrelated-question",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("question", result.stderr)
        self.assertIs(WorkflowStatus.ACTIVE, handle.inspect().workflows[workflow_id].status)

    def test_adaptive_ask_user_cannot_persist_gap_from_another_intent_revision(self) -> None:
        """Selected gap은 hook 이전 domain boundary에서 current intent 소속이어야 합니다."""
        handle = self.fixture.open_session("adaptive-stale-gap-intent")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        question = "어느 스코프를 적용할까요?"
        with self.assertRaisesRegex(
            ValueError,
            "gap must belong to the inventory intent revision",
        ):
            self._seed_ask_user_state(
                handle,
                workflow_id,
                question=question,
                gap_intent_revision=2,
            )

    def test_multiple_adaptive_questions_cannot_share_one_foreground_receipt(self) -> None:
        """한 outer turn은 복수 active workflow의 서로 다른 질문을 증명하지 못합니다."""
        handle = self.fixture.open_session("adaptive-multiple-questions")
        first = self.fixture.open_workflow(
            handle,
            "adaptive-first",
            kind="evaluate-harness",
            skill_state={},
        )
        second = self.fixture.open_workflow(
            handle,
            "adaptive-second",
            kind="evaluate-harness",
            skill_state={},
        )
        first_question = "첫 번째 스코프를 선택할까요?"
        first_rendered = self._seed_ask_user_state(
            handle,
            first,
            gap_id="first-scope",
            question=first_question,
        )
        self._seed_ask_user_state(
            handle,
            second,
            gap_id="second-scope",
            question="두 번째 스코프를 선택할까요?",
        )
        self._awaiting_input_turn(handle, question=first_rendered)

        result = self.fixture.run(
            self.fixture.application(),
            "adaptive-multiple-questions",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("multiple adaptive", result.stderr)
        self.assertIs(WorkflowStatus.ACTIVE, handle.inspect().workflows[first].status)
        self.assertIs(WorkflowStatus.ACTIVE, handle.inspect().workflows[second].status)

    def test_adaptive_await_user_bypasses_monitor_terminal_checks(self) -> None:
        """질문을 위한 control return은 process-ticket publication 완료를 요구하지 않습니다."""
        handle = self.fixture.open_session("adaptive-monitor-await")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive-monitor",
            kind="process-ticket",
            skill_state={},
        )
        question = self._seed_await_user_state(handle, workflow_id)
        self._awaiting_input_turn(handle, question=question)
        git = FakeGitPublication("publication must not be consulted for AWAIT_USER")

        result = self.fixture.run(
            self.fixture.application(git=git),
            "adaptive-monitor-await",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([], git.paths)
        self.assertIs(
            WorkflowStatus.ACTIVE,
            handle.inspect().workflows[workflow_id].status,
        )

    def test_adaptive_await_user_with_unverified_independent_claim_denies(self) -> None:
        """AWAIT_USER여도 missing independent delegation이 있으면 fail closed입니다."""
        handle = self.fixture.open_session("adaptive-unverified-independent")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        question = self._seed_await_user_state(
            handle,
            workflow_id,
            unverified_independent=True,
        )
        self._awaiting_input_turn(handle, question=question)

        result = self.fixture.run(
            self.fixture.application(),
            "adaptive-unverified-independent",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("adaptive", result.stderr)
        self.assertIs(
            WorkflowStatus.ACTIVE,
            handle.inspect().workflows[workflow_id].status,
        )
        self.assertIs(
            ForegroundTurnStatus.ACTIVE,
            handle.inspect().foreground_turns[handle.actor_id].status,
        )

    def test_adaptive_nonawait_or_stale_receipt_stop_denies(self) -> None:
        """CONTINUE, 회고 action, COMPLETE와 stale AWAIT_USER는 control return이 아닙니다."""
        cases = (
            ("continue", ControlAction.CONTINUE, 0, False),
            ("change-approach", ControlAction.CHANGE_APPROACH, 0, False),
            ("promote-harness", ControlAction.PROMOTE_HARNESS, 0, False),
            ("complete", ControlAction.COMPLETE, 0, True),
            ("forged-ask", ControlAction.ASK_USER, 0, False),
            ("forged-await", ControlAction.AWAIT_USER, 0, True),
            ("stale-await", ControlAction.AWAIT_USER, 1, False),
        )
        for suffix, action, receipt_revision, achieved in cases:
            with self.subTest(case=suffix):
                session_id = f"adaptive-deny-{suffix}"
                handle = self.fixture.open_session(session_id)
                workflow_id = self.fixture.open_workflow(
                    handle,
                    "adaptive",
                    kind="evaluate-harness",
                    skill_state={},
                )
                self._seed_await_user_state(handle, workflow_id)
                self._awaiting_input_turn(handle)
                workflow = handle.inspect().workflows[workflow_id]
                receipt = self._adaptive_receipt(
                    workflow_revision=workflow.revision + receipt_revision,
                    action=action,
                    achieved=achieved,
                    ambiguity_action=ControlAction.CONTINUE,
                    ambiguity_ready=True,
                )

                with patch(
                    "scripts.agent_harness.agent_continuation_hook.AdaptiveControlStore.read",
                    return_value=SimpleNamespace(receipt=lambda receipt=receipt: receipt),
                ):
                    result = self.fixture.run(
                        self.fixture.application(),
                        session_id,
                        HookEvent.STOP,
                    )

                self.assertEqual(2, result.exit_code)
                self.assertIn("adaptive", result.stderr)
                self.assertIs(
                    WorkflowStatus.ACTIVE,
                    handle.inspect().workflows[workflow_id].status,
                )
                turn = handle.inspect().foreground_turns[handle.actor_id]
                self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
                self.assertIsNone(turn.receipt)

    def test_adaptive_await_user_requires_matching_awaiting_input_turn(self) -> None:
        """Adaptive AWAIT_USER를 completed outer receipt와 조합해 질문 반환으로 위조할 수 없습니다."""
        handle = self.fixture.open_session("adaptive-wrong-turn")
        workflow_id = self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={},
        )
        self._seed_await_user_state(handle, workflow_id)
        self.fixture.ready_turn(handle)
        workflow = handle.inspect().workflows[workflow_id]
        receipt = self._adaptive_receipt(
            workflow_revision=workflow.revision,
            action=ControlAction.AWAIT_USER,
        )

        with patch(
            "scripts.agent_harness.agent_continuation_hook.AdaptiveControlStore.read",
            return_value=SimpleNamespace(receipt=lambda: receipt),
        ):
            result = self.fixture.run(
                self.fixture.application(),
                "adaptive-wrong-turn",
                HookEvent.STOP,
            )

        self.assertEqual(2, result.exit_code)
        self.assertIn("awaiting-input", result.stderr)

    def test_adaptive_receipt_label_without_adaptive_state_stop_denies(self) -> None:
        """Agent가 쓴 receipt label은 canonical adaptive state readback을 대신하지 못합니다."""
        handle = self.fixture.open_session("adaptive-forged-label")
        self.fixture.open_workflow(
            handle,
            "adaptive",
            kind="evaluate-harness",
            skill_state={
                "adaptive_control_receipt": {
                    "action": "await-user",
                    "workflow_revision": 0,
                }
            },
        )
        self._awaiting_input_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "adaptive-forged-label",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("adaptive", result.stderr)


class ForegroundTurnContinuationMatrixTest(TestCase):
    """Universal foreground-turn의 executable lifecycle matrix를 검증합니다."""

    def setUp(self) -> None:
        """각 matrix row에 독립 exact-session repository를 제공합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = AgentContinuationHookFixture(Path(self.temporary_directory.name))

    def _run_event(
        self,
        handle: StateHandle,
        event: str,
        *,
        prompt: str | None = None,
        turn_id: str | None = None,
    ) -> HookResult:
        """Current handle actor로 raw universal continuation event를 실행합니다."""
        payload: dict[str, object] = {
            "hook_event_name": event,
            "session_id": str(handle.session_id),
        }
        if turn_id is not None:
            payload["turn_id"] = turn_id
        if prompt is not None:
            payload["prompt"] = prompt
        return self.fixture.application().run(
            json.dumps(payload),
            self._environment(handle),
            self.fixture.repository,
        )

    def _environment(self, handle: StateHandle) -> dict[str, str]:
        """StateHandle의 exact actor authority를 public runtime environment로 표현합니다."""
        state = handle.inspect()
        return {
            "CODEX_THREAD_ID": str(handle.session_id),
            "NEURATH_AGENT_SESSION_ID": str(handle.session_id),
            "NEURATH_AGENT_ACTOR_ID": str(handle.actor_id),
            "NEURATH_AGENT_RUNTIME": "codex",
        } | {
            "NEURATH_AGENT_ROOT_ACTOR_ID": str(state.session.root_actor_id),
        }

    def _turns(self, handle: StateHandle) -> Mapping[str, object]:
        """Canonical payload의 typed foreground-turn map을 반환합니다."""
        turns = handle.inspect().to_payload().get("foreground_turns")
        self.assertIsInstance(turns, Mapping)
        assert isinstance(turns, Mapping)
        return turns

    def _turn(self, handle: StateHandle) -> Mapping[str, object]:
        """Current actor의 latest foreground turn payload를 반환합니다."""
        turn = self._turns(handle).get(str(handle.actor_id))
        self.assertIsInstance(turn, Mapping)
        assert isinstance(turn, Mapping)
        return turn

    def _run_cli(self, handle: StateHandle, arguments: tuple[str, ...]) -> StateCliResult:
        """Exact actor identity로 public state CLI를 실행합니다."""
        return StateCliApplication().run(
            arguments,
            self._environment(handle),
            self.fixture.repository,
        )

    def _yield(
        self,
        handle: StateHandle,
        *,
        outcome: str,
        expected_revision: int | None = None,
    ) -> StateCliResult:
        """Current turn을 outcome별 required evidence와 함께 yield합니다."""
        revision = self._turn(handle).get("revision")
        self.assertIsInstance(revision, int)
        selected_revision = revision if expected_revision is None else expected_revision
        evidence = {
            "completed": ("--summary", "요청을 완료했습니다."),
            "awaiting-input": ("--question", "어떤 선택을 원하시나요?"),
            "failed": ("--reason", "더 진행할 수 없습니다."),
        }[outcome]
        return self._run_cli(
            handle,
            (
                "turn",
                "yield",
                "--expected-revision",
                str(selected_revision),
                "--outcome",
                outcome,
                *evidence,
            ),
        )

    def _prepare_material_action(
        self,
        handle: StateHandle,
        *,
        batch_id: str = "batch-1",
        sequence: int = 1,
    ) -> tuple[str, str]:
        """Current active turn에 raw-free local mutation intent를 준비합니다."""
        target = str((self.fixture.repository / "tracked.txt").resolve())
        digest = hashlib.sha256(Path(target).read_bytes()).hexdigest()
        turn = handle.inspect().foreground_turns[handle.actor_id]
        handle.apply(
            MaterialActionPrepared(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                sequence=sequence,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=(target,),
                expectations=(
                    ObservableExpectation(
                        observable_id=target,
                        baseline_digest=digest,
                        expected_delta=ObservableDeltaKind.UNCHANGED,
                        expected_digest=digest,
                    ),
                ),
                adaptive_binding=None,
                idempotency_key=f"material-action:prepare:{batch_id}",
            )
        )
        return target, digest

    def _resolve_material_action(
        self,
        handle: StateHandle,
        *,
        target: str,
        digest: str,
        batch_id: str = "batch-1",
    ) -> None:
        """Prepared batch에 matching PostTool receipt를 결속하고 완료합니다."""
        request_digest = hashlib.sha256(b"request").hexdigest()
        handle.apply(
            MaterialActionToolStarted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                expected_batch_revision=0,
                invocation_id="tool-use-1",
                tool_name="apply_patch",
                request_digest=request_digest,
                targets=(target,),
                idempotency_key=f"material-action:start:{batch_id}",
            )
        )
        handle.apply(
            MaterialActionToolObserved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                expected_batch_revision=1,
                invocation_id="tool-use-1",
                receipt=ToolReceipt(
                    receipt_id="post-tool:tool-use-1",
                    request_digest=request_digest,
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=hashlib.sha256(b"output").hexdigest(),
                    observations=(
                        ObservableObservation(
                            observable_id=target,
                            current_digest=digest,
                        ),
                    ),
                ),
                idempotency_key=f"material-action:observe:{batch_id}",
            )
        )
        handle.apply(
            MaterialActionResolved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                expected_batch_revision=2,
                resolution=MaterialActionResolution.COMPLETED,
                idempotency_key=f"material-action:resolve:{batch_id}",
            )
        )

    def test_user_prompt_binds_existing_provisional_turn(self) -> None:
        """UserPromptSubmit은 provisional generation을 보존하며 실제 provenance만 결합합니다."""
        handle = self.fixture.open_session("session")
        handle.apply(
            ForegroundTurnProvisioned(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                idempotency_key="fixture:provisional-turn",
            )
        )
        before = handle.inspect().foreground_turns[handle.actor_id]

        result = self._run_event(
            handle,
            "UserPromptSubmit",
            prompt="실제 사용자 요청",
            turn_id="vendor-turn-1",
        )
        turn = handle.inspect().foreground_turns[handle.actor_id]

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual(before.generation, turn.generation)
        self.assertEqual(before.revision + 1, turn.revision)
        self.assertEqual("vendor-turn-1", turn.vendor_turn_id)
        self.assertIsNotNone(turn.user_prompt_receipt)

    def test_root_prompt_binds_provisional_turn(self) -> None:
        """일반 UserPromptSubmit은 exact root actor의 provisional turn을 결합합니다."""
        handle = self.fixture.open_session("session")

        result = self._run_event(handle, "UserPromptSubmit")

        self.assertEqual(0, result.exit_code, result.stderr)
        turn = self._turn(handle)
        self.assertEqual("active", turn["status"])
        self.assertEqual(1, turn["generation"])

    def test_root_prompt_without_provisional_turn_requires_exact_recovery(self) -> None:
        """Legacy missing turn은 UserPromptSubmit이 암묵 생성하지 않고 복구를 요구합니다."""
        handle = self.fixture.open_session("legacy-missing", provision_turn=False)

        result = self._run_event(
            handle,
            "UserPromptSubmit",
            prompt="복구 전 요청",
            turn_id="vendor-turn-missing",
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("recover the exact session", result.stderr)
        self.assertNotIn(handle.actor_id, handle.inspect().foreground_turns)

    def test_root_prompt_preserves_only_canonical_digest_and_runtime_metadata(self) -> None:
        """UserPromptSubmit은 원문 대신 canonical digest와 exact turn provenance만 보존합니다."""
        handle = self.fixture.open_session("session")
        prompt = "  현재 결과를 승인합니다.  "

        result = self._run_event(
            handle,
            "UserPromptSubmit",
            prompt=prompt,
            turn_id="vendor-turn-7",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        turn = self._turn(handle)
        receipt = turn["user_prompt_receipt"]
        self.assertIsInstance(receipt, Mapping)
        assert isinstance(receipt, Mapping)
        self.assertEqual(
            hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest(),
            receipt["prompt_digest"],
        )
        self.assertEqual(1, receipt["generation"])
        self.assertEqual(1, receipt["turn_revision"])
        self.assertEqual("vendor-turn-7", receipt["vendor_turn_id"])
        self.assertIsNone(receipt["authority_context"])
        self.assertNotIn(prompt.strip(), json.dumps(handle.inspect().to_payload()))

    def test_root_prompt_without_text_keeps_normal_turn_without_user_authority(self) -> None:
        """Prompt field가 없는 vendor hook도 turn을 열되 USER authority source를 만들지 않습니다."""
        handle = self.fixture.open_session("session")

        result = self._run_event(handle, "UserPromptSubmit", turn_id="vendor-turn-8")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIsNone(self._turn(handle)["user_prompt_receipt"])

    def test_root_prompt_retry_reuses_active_turn(self) -> None:
        """Stable turn id가 없는 prompt retry도 active singleton을 중복 생성하지 않습니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        before = dict(self._turn(handle))

        result = self._run_event(handle, "UserPromptSubmit")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual(before, self._turn(handle))

    def test_active_user_steering_preserves_turn_and_refreshes_prompt(self) -> None:
        """두 runtime의 추가 사용자 입력은 같은 턴에서 출처만 갱신하고 재전송은 보존합니다."""
        for runtime in SessionRuntime:
            for first_id, next_id in (
                (None, None),
                ("turn-1", "turn-1"),
                ("turn-1", None),
                (None, "turn-1"),
            ):
                with self.subTest(runtime=runtime, first_id=first_id, next_id=next_id):
                    session_id = f"steer-{runtime.value}-{first_id}-{next_id}"
                    handle = self.fixture.open_session(session_id, runtime=runtime)
                    application = self.fixture.application(runtime=runtime)
                    initial = self.fixture.run(
                        application,
                        session_id,
                        HookEvent.USER_PROMPT,
                        prompt="현재 하네스를 평가해주세요.",
                        turn_id=first_id,
                        runtime=runtime,
                    )
                    self.assertEqual(0, initial.exit_code, initial.stderr)
                    before = handle.inspect().foreground_turns[handle.actor_id]

                    steered = self.fixture.run(
                        application,
                        session_id,
                        HookEvent.USER_PROMPT,
                        prompt="스티어링 오류도 수정해주세요.",
                        turn_id=next_id,
                        runtime=runtime,
                    )

                    self.assertEqual(0, steered.exit_code, steered.stderr)
                    state = handle.inspect()
                    turn = state.foreground_turns[handle.actor_id]
                    self.assertEqual(before.generation, turn.generation)
                    self.assertEqual(before.revision + 1, turn.revision)
                    self.assertEqual(next_id or first_id, turn.vendor_turn_id)
                    self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
                    self.assertIsNone(turn.receipt)
                    receipt = turn.user_prompt_receipt
                    assert receipt is not None
                    self.assertEqual(
                        hashlib.sha256("스티어링 오류도 수정해주세요.".encode()).hexdigest(),
                        receipt.prompt_digest,
                    )
                    self.assertIsNone(receipt.authority_context)
                    self.assertNotIn("스티어링 오류도", json.dumps(state.to_payload()))

                    retried = self.fixture.run(
                        application,
                        session_id,
                        HookEvent.USER_PROMPT,
                        prompt="스티어링 오류도 수정해주세요.",
                        turn_id=next_id,
                        runtime=runtime,
                    )

                    self.assertEqual(0, retried.exit_code, retried.stderr)
                    self.assertEqual(state.to_payload(), handle.inspect().to_payload())

    def test_active_prompt_rejects_conflicting_turn_or_missing_text(self) -> None:
        """활성 턴의 명시적 다른 ID와 내용 없는 출처 덮어쓰기는 상태 변경 없이 거부합니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit", prompt="처음 요청", turn_id="turn-1")
        before = handle.inspect().to_payload()
        for prompt, turn_id in (("추가 요청", "turn-2"), (None, "turn-1"), (None, None)):
            with self.subTest(prompt=prompt, turn_id=turn_id):
                result = self._run_event(
                    handle,
                    "UserPromptSubmit",
                    prompt=prompt,
                    turn_id=turn_id,
                )
                self.assertEqual(2, result.exit_code)
                self.assertEqual(before, handle.inspect().to_payload())

    def test_active_steering_rejects_stale_turn_yield(self) -> None:
        """추가 입력 전 revision으로 제출한 완료 판정은 새 사용자 요청을 닫을 수 없습니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit", prompt="처음 요청", turn_id="turn-1")
        previous = handle.inspect().foreground_turns[handle.actor_id]

        steered = self._run_event(
            handle,
            "UserPromptSubmit",
            prompt="추가 요청",
            turn_id="turn-1",
        )
        yielded = self._yield(handle, outcome="completed", expected_revision=previous.revision)

        self.assertEqual(0, steered.exit_code, steered.stderr)
        self.assertNotEqual(0, yielded.exit_code)
        self.assertIs(
            ForegroundTurnStatus.ACTIVE,
            handle.inspect().foreground_turns[handle.actor_id].status,
        )

    def test_active_steering_preserves_inflight_material_action_and_workflow(self) -> None:
        """추가 입력은 진행 중인 도구의 의도와 응답 결속을 보존하며 현재 턴에 원자적으로 연결합니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit", prompt="처음 요청", turn_id="turn-1")
        workflow_id = self.fixture.open_workflow(handle, "work", kind="investigate")
        target, digest = self._prepare_material_action(handle)
        request_digest = hashlib.sha256(b"request").hexdigest()
        handle.apply(
            MaterialActionToolStarted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id="batch-1",
                expected_batch_revision=0,
                invocation_id="tool-use-1",
                tool_name="apply_patch",
                request_digest=request_digest,
                targets=(target,),
                idempotency_key="start:inflight",
            )
        )
        before = handle.inspect()

        result = self._run_event(
            handle,
            "UserPromptSubmit",
            prompt="추가 요청",
            turn_id="turn-1",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        after = handle.inspect()
        batch = after.material_actions[handle.actor_id]
        previous = before.material_actions[handle.actor_id]
        self.assertEqual(
            before.workflows[workflow_id].to_payload(), after.workflows[workflow_id].to_payload()
        )
        self.assertEqual(previous.invocations, batch.invocations)
        self.assertEqual(previous.targets, batch.targets)
        self.assertEqual(previous.expectations, batch.expectations)
        self.assertEqual(previous.adaptive_binding, batch.adaptive_binding)
        self.assertEqual(previous.revision + 1, batch.revision)
        self.assertEqual(after.foreground_turns[handle.actor_id].revision, batch.turn_revision)
        handle.apply(
            MaterialActionToolObserved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id="batch-1",
                expected_batch_revision=batch.revision,
                invocation_id="tool-use-1",
                receipt=ToolReceipt(
                    receipt_id="post-tool:tool-use-1",
                    request_digest=request_digest,
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=hashlib.sha256(b"output").hexdigest(),
                    observations=(
                        ObservableObservation(observable_id=target, current_digest=digest),
                    ),
                ),
                idempotency_key="observe:inflight",
            )
        )
        observed = handle.inspect().material_actions[handle.actor_id]
        handle.apply(
            MaterialActionResolved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id="batch-1",
                expected_batch_revision=observed.revision,
                resolution=MaterialActionResolution.COMPLETED,
                idempotency_key="resolve:inflight",
            )
        )
        self.assertIs(
            MaterialActionResolution.COMPLETED,
            handle.inspect().material_actions[handle.actor_id].resolution,
        )

    def test_root_ready_prompt_reactivates_turn(self) -> None:
        """Yield 뒤 새 prompt는 stale terminal receipt를 제거하고 같은 turn을 재활성화합니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        yielded = self._yield(handle, outcome="completed")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)

        result = self._run_event(handle, "UserPromptSubmit")

        self.assertEqual(0, result.exit_code, result.stderr)
        turn = self._turn(handle)
        self.assertEqual("active", turn["status"])
        self.assertIsNone(turn["receipt"])

    def test_root_pretool_invalidates_ready_turn(self) -> None:
        """Yield 이후의 모든 tool call은 receipt를 무효화해 fresh acknowledgement를 요구합니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        yielded = self._yield(handle, outcome="completed")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)

        result = self._run_event(handle, "PreToolUse")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual("active", self._turn(handle)["status"])
        self.assertIsNone(self._turn(handle)["receipt"])

    def test_root_active_pretool_is_a_noop(self) -> None:
        """Tool history는 active turn의 runtime Stop 종료 가능성을 바꾸지 않습니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        before_state_revision = handle.inspect().revision
        before_turn = dict(self._turn(handle))

        result = self._run_event(handle, "PreToolUse")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual(before_state_revision, handle.inspect().revision)
        self.assertEqual(before_turn, self._turn(handle))

        stopped = self._run_event(handle, "Stop")

        self.assertEqual(0, stopped.exit_code, stopped.stderr)
        self.assertEqual("closed", self._turn(handle)["status"])

    def test_root_stop_without_turn_denies(self) -> None:
        """Exact active actor의 Stop은 foreground turn이 없으면 fail-closed합니다."""
        handle = self.fixture.open_session("session", provision_turn=False)

        result = self._run_event(handle, "Stop")

        self.assertEqual(2, result.exit_code)
        self.assertIn("foreground turn", result.stderr)

    def test_claude_subagent_stop_closes_only_the_exact_registered_child_turn(self) -> None:
        """Claude ``SubagentStop``는 payload agent_id의 child turn만 검증하고 닫습니다."""
        root = self.fixture.open_session(
            "claude-child-stop",
            runtime=SessionRuntime.CLAUDE_CODE,
        )
        child_actor_id = ActorId("claude-code:worker-7")
        root.apply(
            ActorStarted(
                session_id=root.session_id,
                actor_id=child_actor_id,
                parent_actor_id=root.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker-7",
            )
        )
        child = StateHandle.attach(
            self.fixture.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CLAUDE_CODE,
                session_id=root.session_id,
                actor_id=child_actor_id,
                root_actor_id=root.actor_id,
            ),
        )
        self.fixture.active_turn(child)
        payload = json.dumps({
            "hook_event_name": "SubagentStop",
            "session_id": str(root.session_id),
            "agent_id": "worker-7",
        })

        result = self.fixture.application(runtime=SessionRuntime.CLAUDE_CODE).run(
            payload,
            {"CLAUDE_CODE_SESSION_ID": str(root.session_id)},
            self.fixture.repository,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIs(
            ForegroundTurnStatus.CLOSED,
            child.inspect().foreground_turns[child_actor_id].status,
        )
        root_turn = root.inspect().foreground_turns[root.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, root_turn.status)
        self.assertIsNone(root_turn.vendor_turn_id)

    def test_state_free_child_precompact_and_stop_are_idempotent_for_both_runtimes(
        self,
    ) -> None:
        """Unregistered child lifecycle은 exact root를 읽되 state와 authority를 바꾸지 않습니다."""
        for runtime in (SessionRuntime.CODEX, SessionRuntime.CLAUDE_CODE):
            with self.subTest(runtime=runtime.value):
                session_id = f"{runtime.value}-state-free-child"
                root = self.fixture.open_session(session_id, runtime=runtime)
                before = root.inspect().to_payload()
                environment_key = (
                    "CODEX_THREAD_ID"
                    if runtime is SessionRuntime.CODEX
                    else "CLAUDE_CODE_SESSION_ID"
                )
                application = self.fixture.application(runtime=runtime)

                results = []
                for event in ("PreCompact", "PreCompact", "SubagentStop", "SubagentStop"):
                    results.append(
                        application.run(
                            json.dumps({
                                "hook_event_name": event,
                                "session_id": session_id,
                                "agent_id": "state-free-worker",
                            }),
                            {environment_key: session_id},
                            self.fixture.repository,
                        )
                    )

                self.assertTrue(
                    all(result.exit_code == 0 for result in results),
                    [result.stderr for result in results],
                )
                self.assertTrue(all(result.stdout == "{}" for result in results))
                self.assertEqual(before, root.inspect().to_payload())
                self.assertNotIn(
                    ActorId(f"{runtime.value}:state-free-worker"),
                    root.inspect().actors,
                )

    def test_runtime_subagent_start_stop_fences_actor_and_late_child_tool(self) -> None:
        """Production Start→Stop wiring은 child turn을 닫고 actor를 terminal fence합니다."""
        root = self.fixture.open_session(
            "claude-runtime-child",
            runtime=SessionRuntime.CLAUDE_CODE,
        )
        runtime = RuntimeHookApplication(
            self.fixture.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=2048,
        )
        with patch.object(
            RuntimeHookApplication,
            "_lineage_assurance",
            return_value=ActorLineageAssurance.HOST_ATTESTED,
        ):
            start = runtime.run(
                json.dumps({
                    "hook_event_name": "SubagentStart",
                    "session_id": str(root.session_id),
                    "agent_id": "runtime-worker",
                    "parent_agent_id": f"session:{root.session_id}",
                    "agent_type": "general-purpose",
                    "cwd": str(self.fixture.repository),
                    "transcript_path": str(self.fixture.repository / "child.jsonl"),
                }),
                {"CLAUDE_PROJECT_DIR": str(self.fixture.repository)},
            )
        runtime.acknowledge(start)
        application = self.fixture.application(runtime=SessionRuntime.CLAUDE_CODE)
        stop_payload = json.dumps({
            "hook_event_name": "SubagentStop",
            "session_id": str(root.session_id),
            "agent_id": "runtime-worker",
        })

        stopped = application.run(
            stop_payload,
            {"CLAUDE_CODE_SESSION_ID": str(root.session_id)},
            self.fixture.repository,
        )
        repeated = application.run(
            stop_payload,
            {"CLAUDE_CODE_SESSION_ID": str(root.session_id)},
            self.fixture.repository,
        )
        late_tool = application.run(
            json.dumps({
                "hook_event_name": "PreToolUse",
                "session_id": str(root.session_id),
                "agent_id": "runtime-worker",
            }),
            {"CLAUDE_CODE_SESSION_ID": str(root.session_id)},
            self.fixture.repository,
        )
        state = root.inspect()
        actor_id = ActorId("claude-code:runtime-worker")

        self.assertEqual(0, start.exit_code)
        self.assertEqual(0, stopped.exit_code, stopped.stderr)
        self.assertEqual(0, repeated.exit_code, repeated.stderr)
        self.assertIs(ActorStatus.STOPPED, state.actors[actor_id].status)
        self.assertIs(ForegroundTurnStatus.CLOSED, state.foreground_turns[actor_id].status)
        self.assertEqual(2, late_tool.exit_code)
        self.assertIn("terminal", late_tool.stderr)

    def test_subagent_stop_requires_owned_worktree_release_or_handoff(self) -> None:
        """Child actor는 exact worktree lease를 남긴 채 terminal authority가 되지 않습니다."""
        root = self.fixture.open_session(
            "claude-child-lease",
            runtime=SessionRuntime.CLAUDE_CODE,
        )
        runtime = RuntimeHookApplication(
            self.fixture.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=2048,
        )
        with patch.object(
            RuntimeHookApplication,
            "_lineage_assurance",
            return_value=ActorLineageAssurance.HOST_ATTESTED,
        ):
            start = runtime.run(
                json.dumps({
                    "hook_event_name": "SubagentStart",
                    "session_id": str(root.session_id),
                    "agent_id": "lease-worker",
                    "parent_agent_id": f"session:{root.session_id}",
                    "agent_type": "general-purpose",
                    "cwd": str(self.fixture.repository),
                    "transcript_path": str(self.fixture.repository / "lease-worker.jsonl"),
                }),
                {"CLAUDE_PROJECT_DIR": str(self.fixture.repository)},
            )
        runtime.acknowledge(start)
        actor_id = ActorId("claude-code:lease-worker")
        identity = WorktreeIdentityResolver().resolve(self.fixture.repository)
        registry = WorktreeRegistry(self.fixture.locator)
        claim = registry.claim(
            WorktreeClaim(
                worktree_id=identity.worktree_id,
                path=identity.path,
                session_id=root.session_id,
                actor_id=actor_id,
            )
        )
        payload = json.dumps({
            "hook_event_name": "SubagentStop",
            "session_id": str(root.session_id),
            "agent_id": "lease-worker",
        })
        application = self.fixture.application(runtime=SessionRuntime.CLAUDE_CODE)

        blocked = application.run(
            payload,
            {"CLAUDE_CODE_SESSION_ID": str(root.session_id)},
            self.fixture.repository,
        )
        registry.release(claim)
        stopped = application.run(
            payload,
            {"CLAUDE_CODE_SESSION_ID": str(root.session_id)},
            self.fixture.repository,
        )

        self.assertEqual(2, blocked.exit_code)
        self.assertIn("claim", blocked.stderr)
        self.assertEqual(0, stopped.exit_code, stopped.stderr)
        self.assertIs(ActorStatus.STOPPED, root.inspect().actors[actor_id].status)

    def test_root_stop_active_turn_closes_without_agent_receipt(self) -> None:
        """Runtime Stop 자체가 terminal intent이므로 plain turn은 별도 yield 없이 닫힙니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")

        result = self._run_event(handle, "Stop")

        self.assertEqual(0, result.exit_code, result.stderr)
        turn = self._turn(handle)
        self.assertEqual("closed", turn["status"])
        self.assertIsNone(turn["receipt"])

    def test_root_stop_ignores_legacy_open_material_action(self) -> None:
        """Legacy edit bookkeeping is not a separate completion gate."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        self._prepare_material_action(handle)

        result = self._run_event(handle, "Stop")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual("closed", self._turn(handle)["status"])

    def test_stop_preserves_unobserved_material_history_without_fabricating_result(self) -> None:
        """Stop neither repeats an edit nor invents its missing result."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        target, _digest = self._prepare_material_action(handle)
        handle.apply(
            MaterialActionToolStarted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id="batch-1",
                expected_batch_revision=0,
                invocation_id="tool-use-without-post",
                tool_name="apply_patch",
                request_digest=hashlib.sha256(b"request-without-post").hexdigest(),
                targets=(target,),
                idempotency_key="material-action:start:without-post",
            )
        )

        result = self._run_event(handle, "Stop")
        batch = handle.inspect().material_actions[handle.actor_id]
        receipt = batch.invocations[0].receipt

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIsNone(batch.resolution)
        self.assertIsNone(receipt)
        self.assertEqual("closed", self._turn(handle)["status"])

        retried = self._run_event(handle, "Stop")

        self.assertEqual(0, retried.exit_code, retried.stderr)
        self.assertEqual("closed", self._turn(handle)["status"])

    def test_root_stop_allows_resolved_material_action_without_workflow(self) -> None:
        """Current actor의 latest batch가 resolved이면 plain Stop을 허용합니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        target, digest = self._prepare_material_action(handle)
        self._resolve_material_action(handle, target=target, digest=digest)

        result = self._run_event(handle, "Stop")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual("closed", self._turn(handle)["status"])

    def test_root_stop_ignores_foreign_actor_open_material_action(self) -> None:
        """같은 session의 다른 actor batch는 current actor Stop authority가 아닙니다."""
        root = self.fixture.open_session("session")
        worker_id = ActorId("codex:worker")
        root.apply(
            ActorStarted(
                session_id=root.session_id,
                actor_id=worker_id,
                parent_actor_id=root.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker",
            )
        )
        worker = StateHandle.attach(
            self.fixture.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=root.session_id,
                actor_id=worker_id,
                root_actor_id=root.actor_id,
            ),
        )
        self.fixture.active_turn(worker)
        self._run_event(worker, "UserPromptSubmit")
        self._prepare_material_action(worker)
        self._run_event(root, "UserPromptSubmit")

        result = self._run_event(root, "Stop")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual("closed", self._turn(root)["status"])

    def test_root_completed_yield_stop_closes(self) -> None:
        """Completed receipt와 공통 gate를 통과한 Stop은 outer turn을 닫습니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        yielded = self._yield(handle, outcome="completed")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)

        result = self._run_event(handle, "Stop")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual("closed", self._turn(handle)["status"])
        receipt = self._turn(handle)["receipt"]
        self.assertIsInstance(receipt, Mapping)
        assert isinstance(receipt, Mapping)
        self.assertEqual("completed", receipt["outcome"])

    def test_root_awaiting_input_yield_stop_closes(self) -> None:
        """Awaiting-input question receipt도 검증된 control-return terminal outcome입니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        yielded = self._yield(handle, outcome="awaiting-input")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)

        result = self._run_event(handle, "Stop")

        self.assertEqual(0, result.exit_code, result.stderr)
        receipt = self._turn(handle)["receipt"]
        self.assertIsInstance(receipt, Mapping)
        assert isinstance(receipt, Mapping)
        self.assertEqual("awaiting-input", receipt["outcome"])

    def test_root_stale_yield_revision_denies(self) -> None:
        """Caller가 읽은 turn revision이 stale이면 yield는 typed CAS conflict로 거부됩니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")

        result = self._yield(handle, outcome="completed", expected_revision=99)

        self.assertEqual(2, result.exit_code)
        payload = json.loads(result.stdout)
        self.assertEqual("revision-conflict", payload["error"]["code"])
        self.assertEqual("active", self._turn(handle)["status"])

    def test_root_inner_failure_invalidates_ready(self) -> None:
        """Ready outer turn에 active generic inner workflow가 남으면 Stop은 receipt를 무효화합니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        yielded = self._yield(handle, outcome="completed")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)
        self.fixture.open_workflow(handle, "inner", kind="commit")

        result = self._run_event(handle, "Stop")

        self.assertEqual(2, result.exit_code)
        self.assertEqual("active", self._turn(handle)["status"])
        self.assertIsNone(self._turn(handle)["receipt"])

    def test_root_skill_workflow_coexists(self) -> None:
        """Foreground turn은 phase-run skill workflow와 별도 outer aggregate로 공존합니다."""
        handle = self.fixture.open_session("session")
        workflow_id = self.fixture.open_workflow(handle, "skill", kind="evaluate-harness")

        result = self._run_event(handle, "UserPromptSubmit")

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual("active", self._turn(handle)["status"])
        self.assertIn(workflow_id, handle.inspect().workflows)

    def test_root_next_prompt_opens_next_generation(self) -> None:
        """Closed outer turn 뒤의 다음 prompt는 같은 actor의 다음 generation을 엽니다."""
        handle = self.fixture.open_session("session")
        self._run_event(handle, "UserPromptSubmit")
        yielded = self._yield(handle, outcome="completed")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)
        stopped = self._run_event(handle, "Stop")
        self.assertEqual(0, stopped.exit_code, stopped.stderr)

        result = self._run_event(handle, "UserPromptSubmit")

        self.assertEqual(0, result.exit_code, result.stderr)
        turn = self._turn(handle)
        self.assertEqual(2, turn["generation"])
        self.assertEqual("active", turn["status"])

    def test_foreign_actor_turn_cannot_authorize_root(self) -> None:
        """Foreign subagent의 ready turn은 root actor의 missing turn Stop을 승인하지 않습니다."""
        root = self.fixture.open_session("session", provision_turn=False)
        worker_id = ActorId("codex:worker")
        root.apply(
            ActorStarted(
                session_id=root.session_id,
                actor_id=worker_id,
                parent_actor_id=root.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="worker:start",
            )
        )
        worker = StateHandle.attach(
            self.fixture.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=root.session_id,
                actor_id=worker_id,
                root_actor_id=root.actor_id,
            ),
        )
        self.fixture.active_turn(worker)
        self._run_event(worker, "UserPromptSubmit")
        yielded = self._yield(worker, outcome="completed")
        self.assertEqual(0, yielded.exit_code, yielded.stdout)

        result = self._run_event(root, "Stop")

        self.assertEqual(2, result.exit_code)
        self.assertIn("foreground turn", result.stderr)



class StopTerminalReachabilityRemainingMatrixTest(TestCase):
    """기존 exact-session Stop matrix의 나머지 actor 및 prerequisite 행을 검증합니다."""

    def setUp(self) -> None:
        """각 matrix row에 독립 Git repository와 session fixture를 제공합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = AgentContinuationHookFixture(Path(self.temporary_directory.name))

    def test_root_terminal_generic_stop_allows(self) -> None:
        """Root의 terminal generic workflow는 더 이상 Stop을 차단하지 않습니다."""
        handle = self.fixture.open_session("session")
        workflow_id = self.fixture.open_workflow(handle, "generic", kind="commit")
        workflow = handle.inspect().workflows[workflow_id]
        handle.apply(
            WorkflowFinalized(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                actor_id=handle.actor_id,
                expected_workflow_revision=workflow.revision,
                terminal_status=WorkflowStatus.COMPLETED,
                payload=workflow.payload,
                idempotency_key="workflow:generic:completed",
            )
        )
        self.fixture.active_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIs(WorkflowStatus.COMPLETED, handle.inspect().workflows[workflow_id].status)

    def test_foreign_actor_active_stop_allows(self) -> None:
        """같은 session의 foreign actor가 소유한 active workflow는 root Stop을 막지 않습니다."""
        root_handle = self.fixture.open_session("session")
        worker_id = ActorId("codex:worker")
        root_handle.apply(
            ActorStarted(
                session_id=root_handle.session_id,
                actor_id=worker_id,
                parent_actor_id=root_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker",
            )
        )
        worker_handle = StateHandle.attach(
            self.fixture.locator,
            RuntimeIdentityBinding(
                runtime=SessionRuntime.CODEX,
                session_id=root_handle.session_id,
                actor_id=worker_id,
                root_actor_id=root_handle.actor_id,
            ),
        )
        self.fixture.open_workflow(worker_handle, "worker-generic", kind="commit")
        self.fixture.active_turn(root_handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIs(
            WorkflowStatus.ACTIVE,
            root_handle.inspect().workflows[WorkflowId("worker-generic")].status,
        )

    def test_foreign_session_active_stop_allows(self) -> None:
        """다른 exact session의 active workflow는 현재 session Stop에 영향을 주지 않습니다."""
        current = self.fixture.open_session("session-a")
        foreign = self.fixture.open_session("session-b")
        self.fixture.open_workflow(foreign, "foreign-generic", kind="commit")
        self.fixture.active_turn(current)

        result = self.fixture.run(
            self.fixture.application(),
            "session-a",
            HookEvent.STOP,
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertIs(
            WorkflowStatus.ACTIVE,
            foreign.inspect().workflows[WorkflowId("foreign-generic")].status,
        )

    def test_open_incident_without_monitor_stop_denies(self) -> None:
        """Monitor workflow가 없어도 exact-session open incident는 Stop을 차단합니다."""
        handle = self.fixture.open_session("session")
        handle.apply(
            HarnessIncidentRecorded(
                session_id=handle.session_id,
                occurrence_id=IncidentId("incident-1"),
                rule_id="exact-session-stop-terminal-reachability",
                actor_id=handle.actor_id,
                symptom="generic Stop bypass",
                recorded_at="2026-08-07T00:00:00+00:00",
                idempotency_key="incident:1",
            )
        )
        self.fixture.active_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("unresolved harness incident", result.stderr)

    def test_unresolved_delegation_without_monitor_stop_denies(self) -> None:
        """Monitor workflow가 없어도 current actor의 unresolved delegation은 Stop을 차단합니다."""
        handle = self.fixture.open_session("session")
        target = ActorId("codex:worker")
        handle.apply(
            ActorStarted(
                session_id=handle.session_id,
                actor_id=target,
                parent_actor_id=handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor:worker",
            )
        )
        handle.apply(
            DelegationAssigned(
                session_id=handle.session_id,
                delegation_id=DelegationId("delegation"),
                owner_actor_id=handle.actor_id,
                target_actor_id=target,
                assignment="review",
                idempotency_key="delegation:review",
            )
        )
        self.fixture.active_turn(handle)

        result = self.fixture.run(
            self.fixture.application(),
            "session",
            HookEvent.STOP,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIn("unresolved delegation", result.stderr)

    def test_root_generic_nonstop_event_allows(self) -> None:
        """Non-Stop hook은 generic workflow를 monitor mutation 경로로 보내지 않습니다."""
        handle = self.fixture.open_session("session")
        workflow_id = self.fixture.open_workflow(handle, "generic", kind="commit")
        before = handle.inspect().workflows[workflow_id]
        git = FakeGitPublication()
        monitor = FakeMonitorRuntime()

        result = self.fixture.run(
            self.fixture.application(git=git, monitor=monitor),
            "session",
            HookEvent.USER_PROMPT,
            turn_id="turn",
        )

        self.assertEqual(0, result.exit_code, result.stderr)
        after = handle.inspect().workflows[workflow_id]
        self.assertEqual(before.revision, after.revision)
        self.assertEqual(before.payload, after.payload)
        self.assertEqual([], git.paths)
        self.assertEqual([], monitor.liveness_calls)
        self.assertEqual([], monitor.recovery_calls)


class ForegroundTurnGenerationCasTest(TestCase):
    """Latest-only turn aggregate가 generation 사이 ABA를 허용하지 않는지 검증합니다."""

    def _transient_state_during_stop(
        self,
        mutation: Callable[[AgentContinuationHookFixture, StateHandle], None],
    ) -> tuple[HookResult, StateHandle]:
        """External validation 중 transient canonical mutation을 한 번 주입합니다."""
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        fixture = AgentContinuationHookFixture(Path(temporary_directory.name))
        handle = fixture.open_session("session")
        fixture.open_workflow(handle, "monitor")
        fixture.active_turn(handle)

        class TransientMutationDuringValidation(FakeGitPublication):
            """외부 검증 중 canonical state를 한 번 변경하는 publication test double입니다."""

            mutated = False
            """첫 external validation mutation이 이미 실행됐는지 나타냅니다."""

            def validate_stoppable(self, worktree: Path) -> None:
                """검증 대상 경로를 기록하고 첫 호출에서 transient mutation을 주입합니다.

                Args:
                    worktree: Stop 가능 여부를 검증하는 checkout 경로입니다.
                """
                self.paths.append(worktree)
                if not self.mutated:
                    self.mutated = True
                    mutation(fixture, handle)

        result = fixture.run(
            fixture.application(git=TransientMutationDuringValidation()),
            "session",
            HookEvent.STOP,
        )
        return result, handle

    def test_stop_rejects_workflow_aba_during_external_validation(self) -> None:
        """검증 중 생겼다가 terminal이 된 workflow도 Stop snapshot을 무효화합니다."""

        def mutation(fixture: AgentContinuationHookFixture, handle: StateHandle) -> None:
            """Workflow를 열고 같은 검증 구간 안에서 완료 상태로 전이합니다.

            Args:
                fixture: Continuation hook test fixture입니다.
                handle: Canonical session state handle입니다.
            """
            workflow_id = fixture.open_workflow(handle, "transient", kind="commit")
            workflow = handle.inspect().workflows[workflow_id]
            handle.apply(
                WorkflowFinalized(
                    session_id=handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=handle.actor_id,
                    expected_workflow_revision=workflow.revision,
                    terminal_status=WorkflowStatus.COMPLETED,
                    payload=workflow.payload,
                    idempotency_key="transient:workflow:completed",
                )
            )

        result, handle = self._transient_state_during_stop(mutation)

        self.assertEqual(2, result.exit_code)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
        self.assertIsNone(turn.receipt)

    def test_stop_rejects_material_action_aba_during_external_validation(self) -> None:
        """검증 중 open 뒤 resolved가 된 batch도 initial Stop snapshot을 무효화합니다."""

        def mutation(fixture: AgentContinuationHookFixture, handle: StateHandle) -> None:
            """No-open predicate를 transient batch lifecycle로 ABA 전이합니다."""
            target = str((fixture.repository / "tracked.txt").resolve())
            digest = hashlib.sha256(Path(target).read_bytes()).hexdigest()
            request_digest = hashlib.sha256(b"transient-request").hexdigest()
            turn = handle.inspect().foreground_turns[handle.actor_id]
            handle.apply(
                MaterialActionPrepared(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    batch_id="transient-batch",
                    sequence=1,
                    expected_turn_generation=turn.generation,
                    expected_turn_revision=turn.revision,
                    kind=MaterialActionKind.LOCAL_MUTATION,
                    targets=(target,),
                    expectations=(
                        ObservableExpectation(
                            observable_id=target,
                            baseline_digest=digest,
                            expected_delta=ObservableDeltaKind.UNCHANGED,
                            expected_digest=digest,
                        ),
                    ),
                    adaptive_binding=None,
                    idempotency_key="transient:material:prepare",
                )
            )
            handle.apply(
                MaterialActionToolStarted(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    batch_id="transient-batch",
                    expected_batch_revision=0,
                    invocation_id="transient-tool",
                    tool_name="apply_patch",
                    request_digest=request_digest,
                    targets=(target,),
                    idempotency_key="transient:material:start",
                )
            )
            handle.apply(
                MaterialActionToolObserved(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    batch_id="transient-batch",
                    expected_batch_revision=1,
                    invocation_id="transient-tool",
                    receipt=ToolReceipt(
                        receipt_id="post-tool:transient-tool",
                        request_digest=request_digest,
                        outcome=ToolReceiptOutcome.SUCCEEDED,
                        output_digest=hashlib.sha256(b"transient-output").hexdigest(),
                        observations=(
                            ObservableObservation(
                                observable_id=target,
                                current_digest=digest,
                            ),
                        ),
                    ),
                    idempotency_key="transient:material:observe",
                )
            )
            handle.apply(
                MaterialActionResolved(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    batch_id="transient-batch",
                    expected_batch_revision=2,
                    resolution=MaterialActionResolution.COMPLETED,
                    idempotency_key="transient:material:resolve",
                )
            )

        result, handle = self._transient_state_during_stop(mutation)

        self.assertEqual(2, result.exit_code)
        self.assertIn("state changed during external Stop validation", result.stderr)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
        self.assertIsNone(turn.receipt)

    def test_stop_rejects_incident_aba_during_external_validation(self) -> None:
        """검증 중 open에서 escalated로 바뀐 incident도 Stop snapshot을 무효화합니다."""

        def mutation(fixture: AgentContinuationHookFixture, handle: StateHandle) -> None:
            """Incident를 기록하고 같은 검증 구간 안에서 escalated 상태로 전이합니다.

            Args:
                fixture: Continuation hook test fixture입니다.
                handle: Canonical session state handle입니다.
            """
            del fixture
            occurrence_id = IncidentId("transient-incident")
            handle.apply(
                HarnessIncidentRecorded(
                    session_id=handle.session_id,
                    occurrence_id=occurrence_id,
                    rule_id="stop-aba",
                    actor_id=handle.actor_id,
                    symptom="transient incident",
                    recorded_at="2026-08-09T00:00:00+00:00",
                    idempotency_key="transient:incident:recorded",
                )
            )
            handle.apply(
                HarnessIncidentEscalated(
                    session_id=handle.session_id,
                    occurrence_id=occurrence_id,
                    actor_id=handle.actor_id,
                    summary="handoff complete",
                    reproduction_commands=("python3 -V",),
                    escalated_at="2026-08-09T00:00:01+00:00",
                    idempotency_key="transient:incident:escalated",
                )
            )

        result, handle = self._transient_state_during_stop(mutation)

        self.assertEqual(2, result.exit_code)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
        self.assertIsNone(turn.receipt)

    def test_stop_rejects_delegation_aba_during_external_validation(self) -> None:
        """검증 중 assigned에서 cancelled가 된 delegation도 snapshot을 무효화합니다."""

        def mutation(fixture: AgentContinuationHookFixture, handle: StateHandle) -> None:
            """Delegation을 할당하고 같은 검증 구간 안에서 취소합니다.

            Args:
                fixture: Continuation hook test fixture입니다.
                handle: Canonical session state handle입니다.
            """
            del fixture
            worker = ActorId("codex:transient-worker")
            delegation_id = DelegationId("transient-delegation")
            handle.apply(
                ActorStarted(
                    session_id=handle.session_id,
                    actor_id=worker,
                    parent_actor_id=handle.actor_id,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key="transient:actor:started",
                )
            )
            handle.apply(
                DelegationAssigned(
                    session_id=handle.session_id,
                    delegation_id=delegation_id,
                    owner_actor_id=handle.actor_id,
                    target_actor_id=worker,
                    assignment="transient review",
                    idempotency_key="transient:delegation:assigned",
                )
            )
            handle.apply(
                DelegationCancelled(
                    session_id=handle.session_id,
                    delegation_id=delegation_id,
                    owner_actor_id=handle.actor_id,
                    reason="transient review cancelled",
                    idempotency_key="transient:delegation:cancelled",
                )
            )

        result, handle = self._transient_state_during_stop(mutation)

        self.assertEqual(2, result.exit_code)
        turn = handle.inspect().foreground_turns[handle.actor_id]
        self.assertIs(ForegroundTurnStatus.ACTIVE, turn.status)
        self.assertIsNone(turn.receipt)

    def test_previous_generation_revision_cannot_yield_next_generation(self) -> None:
        """Closed turn에서 읽은 revision은 다음 generation의 CAS 원본이 될 수 없습니다."""
        with TemporaryDirectory() as temporary_directory:
            fixture = AgentContinuationHookFixture(Path(temporary_directory))
            handle = fixture.open_session("session")
            application = fixture.application()
            prompted = fixture.run(application, "session", HookEvent.USER_PROMPT)
            self.assertEqual(0, prompted.exit_code, prompted.stderr)
            first_revision = handle.inspect().foreground_turns[handle.actor_id].revision
            environment = {
                "CODEX_THREAD_ID": "session",
                "NEURATH_AGENT_SESSION_ID": "session",
                "NEURATH_AGENT_ACTOR_ID": str(handle.actor_id),
                "NEURATH_AGENT_RUNTIME": "codex",
                "NEURATH_AGENT_ROOT_ACTOR_ID": str(handle.actor_id),
            }
            yielded = StateCliApplication().run(
                (
                    "turn",
                    "yield",
                    "--expected-revision",
                    str(first_revision),
                    "--outcome",
                    "completed",
                    "--summary",
                    "first generation completed",
                ),
                environment,
                fixture.repository,
            )
            self.assertEqual(0, yielded.exit_code, yielded.stdout)
            stopped = fixture.run(application, "session", HookEvent.STOP)
            self.assertEqual(0, stopped.exit_code, stopped.stderr)
            reprompted = fixture.run(application, "session", HookEvent.USER_PROMPT)
            self.assertEqual(0, reprompted.exit_code, reprompted.stderr)

            stale = StateCliApplication().run(
                (
                    "turn",
                    "yield",
                    "--expected-revision",
                    str(first_revision),
                    "--outcome",
                    "completed",
                    "--summary",
                    "stale first generation retry",
                ),
                environment,
                fixture.repository,
            )

            self.assertEqual(2, stale.exit_code)
            self.assertEqual("revision-conflict", json.loads(stale.stdout)["error"]["code"])
            current = handle.inspect().foreground_turns[handle.actor_id]
            self.assertEqual(2, current.generation)
            self.assertGreater(current.revision, first_revision)
            self.assertEqual("active", current.status.value)

    def test_old_stop_failure_preserves_newer_ready_receipt(self) -> None:
        """Old Stop validation failure는 같은 generation의 newer READY를 무효화하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            fixture = AgentContinuationHookFixture(Path(temporary_directory))
            handle = fixture.open_session("session")
            fixture.open_workflow(handle, "monitor")
            fixture.ready_turn(handle)
            old_ready = handle.inspect().foreground_turns[handle.actor_id]

            class NewerReadyDuringValidation(FakeGitPublication):
                """Git validation 사이에 같은 actor가 새 receipt를 제출하는 race를 재현합니다."""

                def validate_stoppable(self, worktree: Path) -> None:
                    """Current READY를 갱신한 뒤 old Stop validation을 실패시킵니다."""
                    self.paths.append(worktree)
                    handle.apply(
                        ForegroundTurnToolObserved(
                            session_id=handle.session_id,
                            actor_id=handle.actor_id,
                            idempotency_key="concurrent:tool",
                        )
                    )
                    active = handle.inspect().foreground_turns[handle.actor_id]
                    handle.apply(
                        ForegroundTurnYielded(
                            session_id=handle.session_id,
                            actor_id=handle.actor_id,
                            expected_turn_revision=active.revision,
                            receipt=ForegroundTurnReceipt(
                                ForegroundTurnOutcome.COMPLETED,
                                summary="newer ready receipt",
                            ),
                            idempotency_key="concurrent:yield",
                        )
                    )
                    raise AgentContinuationBlocked("old Stop validation failed")

            result = fixture.run(
                fixture.application(git=NewerReadyDuringValidation()),
                "session",
                HookEvent.STOP,
            )

            self.assertEqual(2, result.exit_code)
            current = handle.inspect().foreground_turns[handle.actor_id]
            self.assertEqual(old_ready.generation, current.generation)
            self.assertEqual(old_ready.revision + 2, current.revision)
            self.assertEqual("ready-to-stop", current.status.value)
            self.assertIsNotNone(current.receipt)
            assert current.receipt is not None
            self.assertEqual("newer ready receipt", current.receipt.summary)

    def test_stop_close_revalidates_concurrent_inner_workflow(self) -> None:
        """Monitor 검증 뒤 생긴 active inner workflow는 final close CAS 전에 차단됩니다."""
        with TemporaryDirectory() as temporary_directory:
            fixture = AgentContinuationHookFixture(Path(temporary_directory))
            handle = fixture.open_session("session")
            fixture.open_workflow(handle, "monitor")
            fixture.ready_turn(handle)

            class LateGenericDuringValidation(FakeGitPublication):
                """External monitor validation 중 새 inner workflow가 생기는 race를 재현합니다."""

                def validate_stoppable(self, worktree: Path) -> None:
                    """검증한 path를 기록하고 current actor의 late generic work를 엽니다."""
                    self.paths.append(worktree)
                    fixture.open_workflow(handle, "late-generic", kind="commit")

            result = fixture.run(
                fixture.application(git=LateGenericDuringValidation()),
                "session",
                HookEvent.STOP,
            )

            self.assertEqual(2, result.exit_code)
            self.assertIn("state changed during external Stop validation", result.stderr)
            turn = handle.inspect().foreground_turns[handle.actor_id]
            self.assertEqual("active", turn.status.value)
            self.assertIsNone(turn.receipt)
            self.assertIs(
                WorkflowStatus.ACTIVE,
                handle.inspect().workflows[WorkflowId("late-generic")].status,
            )


class GitPublicationInspectorTest(TestCase):
    """Actual Git read-back port가 dirty work를 차단하는지 검증합니다."""

    def test_dirty_worktree_is_blocked(self) -> None:
        """Actual Git inspector는 dirty worktree의 Stop을 차단합니다."""
        with TemporaryDirectory() as temporary_directory:
            fixture = AgentContinuationHookFixture(Path(temporary_directory))
            (fixture.repository / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            with self.assertRaisesRegex(
                AgentContinuationBlocked,
                "unpublished changes",
            ):
                GitPublicationInspector().validate_stoppable(fixture.repository)
