"""Workflow와 delegation이 session aggregate 안에서 독립적으로 공존하는지 검증합니다."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    ActorStatus,
    ActorStopped,
    DelegationAssigned,
    DelegationCancelled,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationStatus,
    ResumeId,
    SessionEnded,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    SessionStatus,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowId,
    WorkflowStarted,
    WorkflowStatus,
)


class WorkflowKernelAcceptanceTest(TestCase):
    """H04, H05, H06, H11의 identity-keyed aggregate transition을 검증합니다."""

    def setUp(self) -> None:
        """Root와 두 subagent가 있는 exact session을 준비합니다."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.locator = SessionLocator(Path(self.directory.name))
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("workflow-session")
        self.root_actor_id = ActorId("codex:root")
        self.worker_a = ActorId("codex:worker-a")
        self.worker_b = ActorId("codex:worker-b")
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume:workflow-session"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.root_actor_id,
                idempotency_key="session-started:workflow-session",
            )
        )
        for actor_id in (self.worker_a, self.worker_b):
            self.kernel.apply(
                ActorStarted(
                    session_id=self.session_id,
                    actor_id=actor_id,
                    parent_actor_id=self.root_actor_id,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"actor-started:{actor_id}",
                )
            )

    def test_multiple_workflows_preserve_optional_goal_and_independent_payload(self) -> None:
        """Session은 goal 없는 workflow와 명시적 goal이 있는 workflow를 함께 보존합니다."""
        self.kernel.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=WorkflowId("workflow-a"),
                owner_actor_id=self.root_actor_id,
                kind="process-ticket",
                goal="Issue #42를 완료한다",
                payload={"phase": 1},
                idempotency_key="workflow-started:a",
            )
        )
        self.kernel.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=WorkflowId("workflow-b"),
                owner_actor_id=self.worker_a,
                kind="investigate",
                goal=None,
                payload={"phase": "evidence"},
                idempotency_key="workflow-started:b",
            )
        )

        state = self.kernel.inspect(self.session_id)

        self.assertEqual(
            {WorkflowId("workflow-a"), WorkflowId("workflow-b")},
            set(state.workflows),
        )
        self.assertEqual("Issue #42를 완료한다", state.workflows[WorkflowId("workflow-a")].goal)
        self.assertIsNone(state.workflows[WorkflowId("workflow-b")].goal)

    def test_workflow_advance_uses_aggregate_revision_and_rejects_stale_update(self) -> None:
        """다른 aggregate 변경과 무관하게 workflow 자체 expected revision을 CAS합니다."""
        workflow_id = WorkflowId("workflow-a")
        started = self.kernel.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=workflow_id,
                owner_actor_id=self.root_actor_id,
                kind="process-ticket",
                goal="Issue #42",
                payload={"phase": 1},
                idempotency_key="workflow-started:a",
            )
        ).workflows[workflow_id]
        self.kernel.apply(
            WorkflowAdvanced(
                session_id=self.session_id,
                workflow_id=workflow_id,
                actor_id=self.root_actor_id,
                expected_workflow_revision=started.revision,
                payload={"phase": 2},
                idempotency_key="workflow-advanced:a:2",
            )
        )

        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                WorkflowAdvanced(
                    session_id=self.session_id,
                    workflow_id=workflow_id,
                    actor_id=self.root_actor_id,
                    expected_workflow_revision=started.revision,
                    payload={"phase": 3},
                    idempotency_key="workflow-advanced:a:stale",
                )
            )

        current = self.kernel.inspect(self.session_id).workflows[workflow_id]
        self.assertEqual(1, current.revision)
        self.assertEqual(2, current.payload["phase"])

    def test_parallel_delegation_results_remain_bound_to_target_identity(self) -> None:
        """서로 다른 target의 result와 consume lifecycle이 singleton slot 없이 공존합니다."""
        pairs = (
            (DelegationId("delegate-a"), self.worker_a),
            (DelegationId("delegate-b"), self.worker_b),
        )
        for delegation_id, target_actor_id in pairs:
            self.kernel.apply(
                DelegationAssigned(
                    session_id=self.session_id,
                    delegation_id=delegation_id,
                    owner_actor_id=self.root_actor_id,
                    target_actor_id=target_actor_id,
                    assignment=f"inspect {target_actor_id}",
                    idempotency_key=f"delegation-assigned:{delegation_id}",
                )
            )
            self.kernel.apply(
                DelegationReported(
                    session_id=self.session_id,
                    delegation_id=delegation_id,
                    reporter_actor_id=target_actor_id,
                    result=DelegationResult(
                        verdict="pass",
                        summary=f"result from {target_actor_id}",
                        outcome_ref=f"sha256:{delegation_id!s:0<64}"[:71],
                        blocking_findings=(),
                    ),
                    idempotency_key=f"delegation-reported:{delegation_id}",
                )
            )
        self.kernel.apply(
            DelegationConsumed(
                session_id=self.session_id,
                delegation_id=DelegationId("delegate-a"),
                consumer_actor_id=self.root_actor_id,
                idempotency_key="delegation-consumed:delegate-a",
            )
        )

        state = self.kernel.inspect(self.session_id)

        self.assertEqual(
            DelegationStatus.CONSUMED, state.delegations[DelegationId("delegate-a")].status
        )
        self.assertEqual(
            DelegationStatus.REPORTED, state.delegations[DelegationId("delegate-b")].status
        )
        self.assertIn("worker-b", state.delegations[DelegationId("delegate-b")].result.summary)

    def test_owner_can_cancel_only_a_pending_delegation_with_idempotent_reason(self) -> None:
        """Spawn 실패 같은 pre-report abort는 singleton slot 삭제가 아닌 typed terminal 상태입니다."""
        delegation_id = DelegationId("delegate-cancelled")
        self.kernel.apply(
            DelegationAssigned(
                session_id=self.session_id,
                delegation_id=delegation_id,
                owner_actor_id=self.root_actor_id,
                target_actor_id=self.worker_a,
                assignment="review the exact head",
                idempotency_key="delegation-assigned:cancelled",
            )
        )
        event = DelegationCancelled(
            session_id=self.session_id,
            delegation_id=delegation_id,
            owner_actor_id=self.root_actor_id,
            reason="subagent spawn failed before execution",
            idempotency_key="delegation-cancelled:spawn-failed",
        )

        first = self.kernel.apply(event)
        repeated = self.kernel.apply(event)

        cancelled = repeated.delegations[delegation_id]
        self.assertEqual(first.revision, repeated.revision)
        self.assertEqual(DelegationStatus.CANCELLED, cancelled.status)
        self.assertEqual("cancelled", cancelled.result.verdict)
        self.assertEqual("subagent spawn failed before execution", cancelled.result.summary)
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                DelegationReported(
                    session_id=self.session_id,
                    delegation_id=delegation_id,
                    reporter_actor_id=self.worker_a,
                    result=DelegationResult(
                        verdict="pass",
                        summary="too late",
                        outcome_ref="sha256:" + "0" * 64,
                        blocking_findings=(),
                    ),
                    idempotency_key="delegation-reported:after-cancel",
                )
            )

    def test_retired_actor_cannot_mutate_and_session_end_is_terminal(self) -> None:
        """Actor retirement fencing과 explicit session end가 이후 mutation을 차단합니다."""
        self.kernel.apply(
            ActorStopped(
                session_id=self.session_id,
                actor_id=self.worker_a,
                terminal_status=ActorStatus.RETIRED,
                idempotency_key="actor-retired:worker-a",
            )
        )
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                WorkflowStarted(
                    session_id=self.session_id,
                    workflow_id=WorkflowId("retired-workflow"),
                    owner_actor_id=self.worker_a,
                    kind="investigate",
                    goal=None,
                    payload={},
                    idempotency_key="workflow-started:retired",
                )
            )

        self.kernel.apply(
            SessionEnded(
                session_id=self.session_id,
                actor_id=self.root_actor_id,
                idempotency_key="session-ended:workflow-session",
            )
        )
        state = self.kernel.inspect(self.session_id)

        self.assertEqual(SessionStatus.ENDED, state.session.status)
        self.assertTrue(all(actor.status is ActorStatus.RETIRED for actor in state.actors.values()))
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                WorkflowFinalized(
                    session_id=self.session_id,
                    workflow_id=WorkflowId("missing"),
                    actor_id=self.root_actor_id,
                    expected_workflow_revision=0,
                    terminal_status=WorkflowStatus.FAILED,
                    payload={},
                    idempotency_key="workflow-finalized:after-end",
                )
            )


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    import unittest

    unittest.main()
