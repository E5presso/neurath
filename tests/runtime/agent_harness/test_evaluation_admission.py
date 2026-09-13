"""현재 evaluator 가용성 진단과 성공을 주장하지 않는 control return을 검증합니다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateAuthorityError,
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.agent_continuation_hook import HookEvent
from scripts.agent_harness.evaluation_admission import EvaluationAdmissionPolicy
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    ActorStatus,
    ActorStopped,
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    HarnessIncidentRecorded,
    IncidentId,
    SessionKernel,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.state_cli import StateCliApplication
from scripts.agent_harness.tests import test_agent_continuation_hook as hook_tests
from scripts.agent_harness.tests.test_adaptive_control_authority import AdaptiveAuthorityFixture
from scripts.agent_harness.tests.test_agent_continuation_hook import AgentContinuationHookFixture
from scripts.skill_harness.phase_runner import PhaseRunnerApplication


class EvaluationAdmissionTest(TestCase):
    """Repository declaration으로 host 권한을 만들지 않고 현재 session만 조회합니다."""

    def setUp(self) -> None:
        """각 검사에 독립된 실제 kernel과 hook fixture를 제공합니다."""
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = AgentContinuationHookFixture(Path(temporary.name))
        self.handle = self.fixture.open_session("admission")
        self.environment = {"CODEX_THREAD_ID": "admission"}

    def test_unregistered_and_unattested_evaluators_are_unavailable(self) -> None:
        """자식 관계가 증명되지 않으면 조회는 UNAVAILABLE이며 상태를 만들지 않습니다."""
        before = self.handle.inspect()
        receipt = EvaluationAdmissionPolicy().inspect(before, self.handle.actor_id)
        self.assertEqual("unavailable", receipt["status"])
        self.assertEqual(before.to_payload(), self.handle.inspect().to_payload())
        self.handle.apply(
            ActorStarted(
                session_id=self.handle.session_id,
                actor_id=ActorId("codex:unattested"),
                parent_actor_id=self.handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="admission:unattested",
            )
        )
        self.assertEqual(
            "unavailable",
            EvaluationAdmissionPolicy().inspect(
                self.handle.inspect(),
                self.handle.actor_id,
            )["status"],
        )

    def test_attested_child_and_pending_report_preserve_the_evaluation_path(self) -> None:
        """실제 direct child와 기존 report 작업은 repository 선언보다 우선합니다."""
        child = ActorId("codex:evaluator")
        self.handle.apply(
            ActorStarted(
                session_id=self.handle.session_id,
                actor_id=child,
                parent_actor_id=self.handle.actor_id,
                kind=ActorKind.SUBAGENT,
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
                idempotency_key="admission:child",
            )
        )
        policy = EvaluationAdmissionPolicy()
        self.assertEqual(
            "available", policy.inspect(self.handle.inspect(), self.handle.actor_id)["status"]
        )
        workflow = self.fixture.open_workflow(self.handle, "audit", kind="evaluate-harness")
        self.handle.apply(
            DelegationAssigned(
                session_id=self.handle.session_id,
                delegation_id=DelegationId("review"),
                owner_actor_id=self.handle.actor_id,
                target_actor_id=child,
                assignment=json.dumps({
                    "workflow_id": str(workflow),
                    "kind": "adaptive-goal-evaluation",
                }),
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
                idempotency_key="admission:assign",
            )
        )
        self.assertEqual(
            "in-progress",
            policy.inspect(
                self.handle.inspect(),
                self.handle.actor_id,
                workflow,
            )["status"],
        )

    def test_semantic_init_without_evaluator_creates_no_workflow(self) -> None:
        """실행 전 가용성 부족은 새 pending workflow를 만들지 않고 진단으로 반환합니다."""
        contracts = self.fixture.repository / ".agents/skills/contracts.json"
        contracts.parent.mkdir(parents=True)
        contracts.write_text(
            json.dumps({
                "skills": {
                    "evaluate-harness": {
                        "adaptive_control": "required",
                        "terminal_states": ["evaluated", "blocked"],
                        "phase_contracts": [
                            {
                                "id": 1,
                                "name": "audit",
                                "min_evidence_count": 1,
                                "required_evidence": ["source"],
                            }
                        ],
                    }
                }
            }),
            encoding="utf-8",
        )
        result = PhaseRunnerApplication(self.fixture.repository).run(
            [
                "init",
                "--workflow-id",
                "unavailable",
                "--skill",
                "evaluate-harness",
                "--run-id",
                "unavailable",
                "--north-star",
                "현재 source 평가",
            ],
            environment=self.environment,
        )
        self.assertNotEqual(0, result)
        self.assertEqual({}, dict(self.handle.inspect().workflows))

    def test_incomplete_return_preserves_the_existing_workflow(self) -> None:
        """현재 evaluator가 없으면 불완료 반환은 workflow를 성공·실패로 바꾸지 않습니다."""
        workflow = self.fixture.open_workflow(self.handle, "audit", kind="evaluate-harness")
        before = self.handle.inspect().workflows[workflow].to_payload()
        turn = self.handle.inspect().foreground_turns[self.handle.actor_id]
        yielded = StateCliApplication().run(
            (
                "turn",
                "yield",
                "--expected-revision",
                str(turn.revision),
                "--outcome",
                "incomplete",
                "--reason",
                "현재 직접 자식 평가 근거를 사용할 수 없습니다.",
            ),
            self.environment,
            self.fixture.repository,
        )
        self.assertEqual(0, yielded.exit_code, yielded.stdout)
        stopped = self.fixture.run(self.fixture.application(), "admission", HookEvent.STOP)
        self.assertEqual(0, stopped.exit_code, stopped.stderr)
        self.assertEqual(before, self.handle.inspect().workflows[workflow].to_payload())
        self.assertEqual(
            "closed", self.handle.inspect().foreground_turns[self.handle.actor_id].status.value
        )

    def test_stopped_child_keeps_consumed_report_path_without_completion(self) -> None:
        """종료된 evaluator의 consumed report는 기존 경로를 보존하고 성공을 주장하지 않습니다."""
        child = ActorId("codex:evaluator-stopped")
        self.handle.apply(
            ActorStarted(
                session_id=self.handle.session_id,
                actor_id=child,
                parent_actor_id=self.handle.actor_id,
                kind=ActorKind.SUBAGENT,
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
                idempotency_key="admission:stopped-child",
            )
        )
        workflow = self.fixture.open_workflow(self.handle, "audit", kind="evaluate-harness")
        delegation = DelegationId("consumed-report")
        self.handle.apply(
            DelegationAssigned(
                session_id=self.handle.session_id,
                delegation_id=delegation,
                owner_actor_id=self.handle.actor_id,
                target_actor_id=child,
                assignment=json.dumps({
                    "workflow_id": str(workflow),
                    "kind": "adaptive-goal-evaluation",
                }),
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
                idempotency_key="admission:assign-consumed",
            )
        )
        kernel = SessionKernel(self.fixture.locator)
        kernel.apply(
            DelegationReported(
                session_id=self.handle.session_id,
                delegation_id=delegation,
                reporter_actor_id=child,
                result=DelegationResult("pass", "report", "sha256:" + "a" * 64, ()),
                idempotency_key="admission:report",
            )
        )
        self.handle.apply(
            DelegationConsumed(
                session_id=self.handle.session_id,
                delegation_id=delegation,
                consumer_actor_id=self.handle.actor_id,
                idempotency_key="admission:consume",
            )
        )
        kernel.apply(
            ActorStopped(
                session_id=self.handle.session_id,
                actor_id=child,
                terminal_status=ActorStatus.STOPPED,
                idempotency_key="admission:stop-child",
            )
        )
        before = self.handle.inspect().to_payload()
        receipt = EvaluationAdmissionPolicy().inspect(
            self.handle.inspect(), self.handle.actor_id, workflow
        )
        self.assertEqual("in-progress", receipt["status"])
        self.assertEqual([], receipt["available_actor_ids"])
        self.assertEqual([str(delegation)], receipt["existing_delegation_ids"])
        self.assertFalse(receipt["semantic_completion"])
        self.assertEqual(before, self.handle.inspect().to_payload())

    def test_foreign_workflow_preflight_does_not_grant_candidate_authority(self) -> None:
        """조회에 다른 workflow ID를 넣어도 해당 owner의 candidate 쓰기 권한은 생기지 않습니다."""
        with AdaptiveAuthorityFixture() as fixture:
            foreign = WorkflowId("foreign-workflow")
            kernel = SessionKernel(fixture.locator)
            kernel.apply(
                WorkflowStarted(
                    session_id=fixture.owner.session_id,
                    workflow_id=foreign,
                    owner_actor_id=fixture.foreign_owner_id,
                    kind="plan-issues",
                    goal="Foreign workflow",
                    payload={},
                    idempotency_key="foreign:start",
                )
            )
            before = fixture.owner.inspect().to_payload()
            result = StateCliApplication().run(
                ("adaptive", "preflight", "--workflow-id", str(foreign)),
                {"CODEX_THREAD_ID": "adaptive-authority-session"},
                fixture.repository,
            )
            self.assertEqual(0, result.exit_code, result.stdout)
            diagnostic = json.loads(result.stdout)["result"]
            self.assertEqual(str(fixture.owner.actor_id), diagnostic["actor_id"])
            self.assertFalse(diagnostic["semantic_completion"])
            with self.assertRaises(AdaptiveEvaluationCandidateAuthorityError):
                AdaptiveEvaluationCandidateStore(fixture.owner, foreign).prepare(
                    fixture.same_context_snapshot().state
                )
            self.assertEqual(before, fixture.owner.inspect().to_payload())

    def test_incomplete_return_preserves_material_incident_and_delegation_vetoes(self) -> None:
        """Material 이력은 보존하고 incident·위임의 기존 반환 조건은 유지합니다."""
        for veto in ("material", "incident", "delegation"):
            with self.subTest(veto=veto), TemporaryDirectory() as directory:
                fixture = AgentContinuationHookFixture(Path(directory))
                handle = fixture.open_session("veto")
                workflow = fixture.open_workflow(handle, "audit", kind="evaluate-harness")
                if veto == "material":
                    helper = hook_tests.ForegroundTurnContinuationMatrixTest()
                    helper.fixture = fixture
                    helper._prepare_material_action(handle)
                elif veto == "incident":
                    handle.apply(
                        HarnessIncidentRecorded(
                            session_id=handle.session_id,
                            occurrence_id=IncidentId("veto-incident"),
                            rule_id="evaluation-incomplete-veto",
                            actor_id=handle.actor_id,
                            symptom="open incident",
                            recorded_at="2026-09-06T00:00:00+00:00",
                            idempotency_key="veto:incident",
                        )
                    )
                else:
                    child = ActorId("codex:unattested-veto")
                    handle.apply(
                        ActorStarted(
                            session_id=handle.session_id,
                            actor_id=child,
                            parent_actor_id=handle.actor_id,
                            kind=ActorKind.SUBAGENT,
                            idempotency_key="veto:child",
                        )
                    )
                    handle.apply(
                        DelegationAssigned(
                            session_id=handle.session_id,
                            delegation_id=DelegationId("unrelated-work"),
                            owner_actor_id=handle.actor_id,
                            target_actor_id=child,
                            assignment="other work",
                            topology_policy=DelegationTopologyPolicy.SAME_SESSION,
                            idempotency_key="veto:delegation",
                        )
                    )
                before = handle.inspect()
                self.assertEqual(
                    "unavailable",
                    EvaluationAdmissionPolicy().inspect(before, handle.actor_id, workflow)[
                        "status"
                    ],
                )
                yielded = StateCliApplication().run(
                    (
                        "turn",
                        "yield",
                        "--expected-revision",
                        str(before.foreground_turns[handle.actor_id].revision),
                        "--outcome",
                        "incomplete",
                        "--reason",
                        "현재 evaluator가 없습니다.",
                    ),
                    {"CODEX_THREAD_ID": "veto"},
                    fixture.repository,
                )
                if veto == "material":
                    self.assertEqual(0, yielded.exit_code, yielded.stdout)
                    self.assertEqual(before.material_actions[handle.actor_id],
                                     handle.inspect().material_actions[handle.actor_id])
                    continue
                self.assertEqual(0, yielded.exit_code, yielded.stdout)
                stopped = fixture.run(fixture.application(), "veto", HookEvent.STOP)
                self.assertEqual(2, stopped.exit_code, stopped.stderr)
                self.assertIn(
                    "incident" if veto == "incident" else "unresolved delegation", stopped.stderr
                )
                self.assertEqual(
                    before.workflows[workflow].to_payload(),
                    handle.inspect().workflows[workflow].to_payload(),
                )
