"""Foreground Stop의 monitor workflow/turn aggregate commit 계약을 검증합니다."""

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.session_kernel import (
    ActorId,
    ForegroundTurnClosed,
    ForegroundTurnProvisioned,
    ForegroundTurnStatus,
    MonitorWorkflowStopProjection,
    ProcessState,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    SessionStateReducer,
    TransitionRejected,
    WorkflowId,
    WorkflowRecord,
    WorkflowStarted,
    WorkflowStatus,
)


class ForegroundStopAggregateTest(TestCase):
    """Monitor workflow와 foreground turn이 한 process CAS로 닫히는지 검증합니다."""

    def setUp(self) -> None:
        """각 test에 독립 exact-session kernel과 열린 foreground turn을 구성합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.kernel = SessionKernel(SessionLocator(Path(self.temporary_directory.name)))
        self.session_id = SessionId("stop-aggregate")
        self.actor_id = ActorId("codex:stop-aggregate")
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume:stop-aggregate"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.actor_id,
                idempotency_key="stop-aggregate:session-started",
            )
        )
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=self.session_id,
                actor_id=self.actor_id,
                idempotency_key="stop-aggregate:turn-provisioned",
            )
        )

    def _start_monitor(
        self,
        workflow_id: str,
        *,
        skill_state: dict[str, object] | None = None,
        payload_extra: dict[str, object] | None = None,
    ) -> WorkflowId:
        """Monitor-compatible active workflow를 구성하고 identity를 반환합니다."""
        selected = WorkflowId(workflow_id)
        self.kernel.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=selected,
                owner_actor_id=self.actor_id,
                kind="monitor-pr",
                goal=f"monitor {workflow_id}",
                payload={
                    **(payload_extra or {}),
                    "skill_state": dict(skill_state or {}),
                },
                idempotency_key=f"stop-aggregate:workflow-started:{workflow_id}",
            )
        )
        return selected

    def _projection(
        self,
        workflow_id: WorkflowId,
        *,
        expected_revision: int = 0,
        skill_state: dict[str, object] | None = None,
    ) -> MonitorWorkflowStopProjection:
        """Test용 immutable monitor Stop projection을 생성합니다."""
        return MonitorWorkflowStopProjection(
            workflow_id=workflow_id,
            expected_workflow_revision=expected_revision,
            skill_state=skill_state
            or {
                "owner_lifecycle": {
                    "state": "idle",
                    "owner_session_id": str(self.session_id),
                }
            },
        )

    def _close_event(
        self,
        *transitions: MonitorWorkflowStopProjection,
        expected_turn_revision: int | None = None,
    ) -> ForegroundTurnClosed:
        """Current turn revision과 supplied workflow projection을 한 close event로 묶습니다."""
        turn = self.kernel.inspect(self.session_id).foreground_turns[self.actor_id]
        return ForegroundTurnClosed(
            session_id=self.session_id,
            actor_id=self.actor_id,
            expected_turn_revision=(
                turn.revision if expected_turn_revision is None else expected_turn_revision
            ),
            idempotency_key="stop-aggregate:close",
            monitor_transitions=tuple(transitions),
        )

    def test_close_commits_two_monitor_advances_and_turn_with_one_process_revision(self) -> None:
        """두 workflow와 turn close가 canonical process revision을 정확히 한 번 올립니다."""
        workflow_a = self._start_monitor("monitor-a")
        workflow_b = self._start_monitor("monitor-b")
        before = self.kernel.inspect(self.session_id)
        event = self._close_event(
            self._projection(workflow_b),
            self._projection(workflow_a),
        )

        committed = self.kernel.apply(event, expected_revision=before.revision)

        self.assertEqual(before.revision + 1, committed.revision)
        self.assertEqual(
            (workflow_a, workflow_b),
            tuple(item.workflow_id for item in event.monitor_transitions),
        )
        for workflow_id in (workflow_a, workflow_b):
            workflow = committed.workflows[workflow_id]
            self.assertEqual(1, workflow.revision)
            skill_state = workflow.payload["skill_state"]
            self.assertIsInstance(skill_state, dict)
            assert isinstance(skill_state, dict)
            lifecycle = skill_state["owner_lifecycle"]
            self.assertIsInstance(lifecycle, dict)
            assert isinstance(lifecycle, dict)
            self.assertEqual("idle", lifecycle["state"])
        self.assertIs(
            ForegroundTurnStatus.CLOSED,
            committed.foreground_turns[self.actor_id].status,
        )

    def test_stale_workflow_or_turn_rejects_without_partial_monitor_commit(self) -> None:
        """두 번째 workflow 또는 turn CAS가 stale이면 첫 projection도 저장되지 않습니다."""
        workflow_a = self._start_monitor("monitor-a")
        workflow_b = self._start_monitor("monitor-b")
        before = self.kernel.inspect(self.session_id)
        stale_events = (
            self._close_event(
                self._projection(workflow_a),
                self._projection(workflow_b, expected_revision=1),
            ),
            self._close_event(
                self._projection(workflow_a),
                self._projection(workflow_b),
                expected_turn_revision=1,
            ),
        )

        for event in stale_events:
            with self.subTest(expected_turn_revision=event.expected_turn_revision):
                with self.assertRaises(TransitionRejected):
                    self.kernel.apply(event, expected_revision=before.revision)
                current = self.kernel.inspect(self.session_id)
                self.assertEqual(before.revision, current.revision)
                self.assertEqual(before.to_payload(), current.to_payload())

    def test_close_replay_is_idempotent_after_monitor_projections(self) -> None:
        """동일 aggregate close retry는 workflow와 process revision을 다시 올리지 않습니다."""
        workflow = self._start_monitor("monitor")
        event = self._close_event(self._projection(workflow))
        first = self.kernel.apply(event)

        replayed = self.kernel.apply(event)

        self.assertEqual(first.revision, replayed.revision)
        self.assertEqual(first.to_payload(), replayed.to_payload())

    def test_legacy_close_without_monitor_transitions_remains_supported(self) -> None:
        """기존 caller의 empty projection close는 foreground turn만 닫습니다."""
        before = self.kernel.inspect(self.session_id)

        committed = self.kernel.apply(self._close_event(), expected_revision=before.revision)

        self.assertEqual(before.revision + 1, committed.revision)
        self.assertEqual({}, committed.workflows)
        self.assertIs(
            ForegroundTurnStatus.CLOSED,
            committed.foreground_turns[self.actor_id].status,
        )

    def test_monitor_projection_preserves_unrelated_payload_and_adaptive_namespace(self) -> None:
        """Stop projection은 workflow의 non-skill payload와 adaptive namespace를 보존합니다."""
        adaptive = {"contract": {"fingerprint": "stable"}}
        workflow_id = self._start_monitor(
            "monitor",
            skill_state={
                "monitor_event_subscription": {"provider": "fixture"},
            },
            payload_extra={"phase_run": {"phase": "verify"}},
        )
        persisted = self.kernel.inspect(self.session_id)
        workflow = persisted.workflows[workflow_id]
        raw_skill_state = workflow.payload["skill_state"]
        self.assertIsInstance(raw_skill_state, Mapping)
        assert isinstance(raw_skill_state, Mapping)
        skill_state = dict(raw_skill_state)
        skill_state["adaptive_control"] = adaptive
        payload = dict(workflow.payload)
        payload["skill_state"] = skill_state
        workflows = dict(persisted.workflows)
        workflows[workflow_id] = WorkflowRecord(
            workflow_id=workflow.id,
            owner_actor_id=workflow.owner_actor_id,
            kind=workflow.kind,
            goal=workflow.goal,
            payload=payload,
            revision=workflow.revision,
            status=workflow.status,
            last_transition_idempotency_key=workflow.last_transition_idempotency_key,
        )
        state = ProcessState(
            persisted.revision,
            persisted.session,
            persisted.actors,
            workflows,
            persisted.delegations,
            persisted.resources,
            persisted.mailboxes,
            persisted.incidents,
            persisted.outbox,
            persisted.foreground_turns,
            persisted.material_actions,
        )
        projection = self._projection(
            workflow_id,
            skill_state={
                "adaptive_control": adaptive,
                "monitor_event_subscription": {"provider": "fixture"},
                "owner_lifecycle": {"state": "idle"},
            },
        )

        committed = SessionStateReducer().reduce(state, self._close_event(projection))
        committed_payload = committed.workflows[workflow_id].payload
        committed_skill_state = committed_payload["skill_state"]
        self.assertIsInstance(committed_skill_state, dict)
        assert isinstance(committed_skill_state, dict)

        self.assertEqual({"phase": "verify"}, committed_payload["phase_run"])
        self.assertEqual(adaptive, committed_skill_state["adaptive_control"])
        self.assertIs(WorkflowStatus.ACTIVE, committed.workflows[workflow_id].status)

    def test_monitor_projections_reject_duplicates_and_detach_skill_state(self) -> None:
        """Close input은 중복 workflow를 거부하고 caller mapping 변경을 관찰하지 않습니다."""
        workflow = self._start_monitor("monitor")
        mutable: dict[str, object] = {"owner_lifecycle": {"state": "idle"}}
        projection = self._projection(workflow, skill_state=mutable)
        mutable["late"] = True

        self.assertNotIn("late", projection.skill_state)
        with self.assertRaisesRegex(TransitionRejected, "unique"):
            self._close_event(projection, projection)
