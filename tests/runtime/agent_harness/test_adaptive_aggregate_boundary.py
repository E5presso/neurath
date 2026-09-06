"""Adaptive control public mutation이 aggregate invariant를 우회하지 못하는지 검증합니다."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    CriterionEvidence,
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapInventory,
    GoalContract,
    GoalCoverage,
    OracleOwner,
    RequirementSection,
    approved_requirement_fingerprint,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    AdaptiveControlStore,
)
from scripts.agent_harness.session_kernel import (
    ProcessState,
    ReservedSkillStateAdvanced,
    SessionKernel,
    SessionLocator,
    SessionStateReducer,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowId,
    WorkflowRecord,
    WorkflowStarted,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateReservedMutation,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    StateHandle,
)


class MalformedAdaptiveMutation(SkillStateReservedMutation):
    """Public reserved-mutation subclass가 malformed payload를 제출하는 공격 fixture입니다."""

    @property
    def reserved_namespaces(self) -> frozenset[str]:
        """Caller가 권한이 있다고 주장하는 adaptive namespace를 반환합니다."""
        return frozenset({"adaptive_control"})

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Canonical schema가 아닌 adaptive object를 sibling과 함께 반환합니다."""
        return {**current, "adaptive_control": {"fabricated": True}}


class AdaptiveAggregateBoundaryTest(TestCase):
    """Final aggregate가 event label 대신 adaptive 내용과 authority를 검증합니다."""

    _GOAL = "승인된 adaptive aggregate 계약을 완수한다"

    def setUp(self) -> None:
        """각 test에 exact session과 독립된 canonical state root를 준비합니다."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.locator = SessionLocator(Path(directory.name))
        binding = RuntimeEnvironmentResolver().resolve({
            "CODEX_THREAD_ID": "adaptive-aggregate-boundary"
        })
        self.handle = StateHandle.initialize(self.locator, binding)

    def _start_workflow(
        self,
        workflow_id: str,
        *,
        kind: str = "process-ticket",
        goal: str | None = _GOAL,
    ) -> tuple[WorkflowId, SkillStateStore, AdaptiveControlStore]:
        """Empty skill state를 가진 active workflow와 두 typed store를 반환합니다."""
        identity = WorkflowId(workflow_id)
        self.handle.apply(
            WorkflowStarted(
                session_id=self.handle.session_id,
                workflow_id=identity,
                owner_actor_id=self.handle.actor_id,
                kind=kind,
                goal=goal,
                payload={"skill_state": {"sibling": "preserved"}},
                idempotency_key=f"adaptive-boundary:start:{workflow_id}",
            )
        )
        skill_state = SkillStateStore(self.handle, identity)
        return identity, skill_state, AdaptiveControlStore(skill_state)

    def _contract(
        self,
        *,
        goal: str = _GOAL,
        intent_revision: int = 1,
    ) -> GoalContract:
        """External claim이 없어도 canonical한 최소 goal contract를 구성합니다."""
        constraints = ("aggregate boundary를 우회하지 않는다",)
        non_goals = ("새 agent runtime을 만들지 않는다",)
        source_revision = f"approved-plan:{intent_revision}"
        fingerprint = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            intent_revision,
            source_revision,
        )
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({"REQ-aggregate-boundary"}),
            criteria=(
                CriterionSpec(
                    criterion_id="aggregate-boundary",
                    description="Public mutation이 final aggregate invariant를 통과한다",
                    source_requirement_id="REQ-aggregate-boundary",
                    approved_requirement_fingerprint=fingerprint,
                    observer="test runner",
                    precondition="workflow가 active이다",
                    stimulus="public mutation을 제출한다",
                    expected_outcome="invalid candidate는 영속화되지 않는다",
                    oracle_owner=OracleOwner.EXECUTABLE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.PROPERTY_TEST}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )

    def _empty_state(
        self,
        *,
        goal: str = _GOAL,
        intent_revision: int = 1,
    ) -> AdaptiveControlState:
        """Authority claim이 없는 canonical incomplete adaptive state를 반환합니다."""
        contract = self._contract(goal=goal, intent_revision=intent_revision)
        return AdaptiveControlState.empty(
            contract,
            GapInventory(
                intent_revision=contract.intent_revision,
                source_revision="repo:current",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )

    def _complete_state(
        self,
        *,
        goal: str,
        intent_revision: int,
    ) -> AdaptiveControlState:
        """Reducer semantic completion을 충족한 already-admitted current state를 만듭니다."""
        contract = self._contract(goal=goal, intent_revision=intent_revision)
        execution_lineage = AuthorityReceipt(
            authority=EvidenceAuthority.EXECUTABLE,
            issuer_id="pytest:aggregate-current-goal",
            subject_id=str(self.handle.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=hashlib.sha256(b"aggregate current goal execution").hexdigest(),
        )
        coverage_lineage = AuthorityReceipt(
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            issuer_id="codex:aggregate-current-goal-evaluator",
            subject_id=str(self.handle.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=hashlib.sha256(b"aggregate current goal coverage").hexdigest(),
            delegation_id="aggregate-current-goal-evaluation",
        )
        criterion_id = contract.criteria[0].criterion_id
        return AdaptiveControlState(
            contract=contract,
            inventory=GapInventory(
                intent_revision=contract.intent_revision,
                source_revision="repo:current",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id=criterion_id,
                    kind=EvidenceKind.PROPERTY_TEST,
                    authority=EvidenceAuthority.EXECUTABLE,
                    status=EvidenceStatus.PASS,
                    reference="pytest:aggregate-current-goal",
                    lineage=execution_lineage,
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({criterion_id}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="independent:aggregate-current-goal",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=coverage_lineage,
                evaluation_revision=1,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )

    def _candidate_with_unverified_execution(self) -> AdaptiveControlState:
        """형식은 valid하지만 execution receipt가 없는 external claim을 추가합니다."""
        current = self._empty_state()
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.EXECUTABLE,
            issuer_id="caller-constructed-test-runner",
            subject_id=str(self.handle.actor_id),
            intent_revision=current.contract.intent_revision,
            source_revision=current.contract.source_revision,
            receipt_digest=hashlib.sha256(b"caller-constructed execution").hexdigest(),
        )
        evidence = CriterionEvidence(
            goal_fingerprint=current.contract.fingerprint,
            criterion_id=current.contract.criteria[0].criterion_id,
            kind=EvidenceKind.PROPERTY_TEST,
            authority=EvidenceAuthority.EXECUTABLE,
            status=EvidenceStatus.PASS,
            reference="pytest:caller-constructed",
            lineage=lineage,
        )
        return replace(current, evidence=(evidence,))

    def _payload_with_adaptive(
        self,
        workflow_id: WorkflowId,
        adaptive: Mapping[str, object],
    ) -> dict[str, object]:
        """Current sibling을 보존한 complete workflow payload를 구성합니다."""
        workflow = self.handle.inspect().workflows[workflow_id]
        payload = dict(workflow.payload)
        current_skill_state = payload["skill_state"]
        if not isinstance(current_skill_state, Mapping):
            self.fail("test workflow skill_state must be an object")
        skill_state = dict(current_skill_state)
        skill_state["adaptive_control"] = dict(adaptive)
        payload["skill_state"] = skill_state
        return payload

    def _assert_workflow_unchanged(
        self,
        workflow_id: WorkflowId,
        *,
        process_revision: int,
        workflow_revision: int,
        payload: Mapping[str, object],
    ) -> None:
        """Rejected mutation이 process와 workflow CAS 원본을 모두 보존했는지 확인합니다."""
        current = self.handle.inspect()
        workflow = current.workflows[workflow_id]
        self.assertEqual(process_revision, current.revision)
        self.assertEqual(workflow_revision, workflow.revision)
        self.assertEqual(payload, workflow.payload)

    def test_arbitrary_reserved_mutation_subclass_cannot_persist_invalid_adaptive_payload(
        self,
    ) -> None:
        """Caller-defined subclass와 namespace claim은 malformed state 권한이 아닙니다."""
        workflow_id, skill_state, _adaptive = self._start_workflow("malformed-subclass")
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]

        with self.assertRaises(TransitionRejected):
            skill_state.update(MalformedAdaptiveMutation())

        self._assert_workflow_unchanged(
            workflow_id,
            process_revision=before.revision,
            workflow_revision=workflow.revision,
            payload=workflow.payload,
        )

    def test_direct_reserved_event_rejects_invalid_schema_and_preserves_revision(self) -> None:
        """Direct reserved event도 canonical adaptive schema를 우회하지 못합니다."""
        workflow_id, _skill_state, _adaptive = self._start_workflow("invalid-schema")
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]

        with self.assertRaises(TransitionRejected):
            self.handle.apply(
                ReservedSkillStateAdvanced(
                    session_id=self.handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=self.handle.actor_id,
                    expected_workflow_revision=workflow.revision,
                    payload=self._payload_with_adaptive(
                        workflow_id,
                        {"fabricated": True},
                    ),
                    idempotency_key="adaptive-boundary:invalid-schema",
                    reserved_namespaces=frozenset({"adaptive_control"}),
                )
            )

        self._assert_workflow_unchanged(
            workflow_id,
            process_revision=before.revision,
            workflow_revision=workflow.revision,
            payload=workflow.payload,
        )

    def test_direct_reserved_event_rejects_invalid_transition_and_preserves_revision(self) -> None:
        """Direct reserved event는 terminal execution status rollback을 거부합니다."""
        workflow_id, _skill_state, adaptive = self._start_workflow("invalid-transition")
        terminal = replace(self._empty_state(), execution_status=ExecutionStatus.FAILED)
        current = adaptive.update(lambda _state: terminal)
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]
        invalid = replace(terminal, execution_status=ExecutionStatus.INCOMPLETE)

        with self.assertRaises(TransitionRejected):
            self.handle.apply(
                ReservedSkillStateAdvanced(
                    session_id=self.handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=self.handle.actor_id,
                    expected_workflow_revision=current.workflow_revision,
                    payload=self._payload_with_adaptive(workflow_id, invalid.to_payload()),
                    idempotency_key="adaptive-boundary:invalid-transition",
                    reserved_namespaces=frozenset({"adaptive_control"}),
                )
            )

        self._assert_workflow_unchanged(
            workflow_id,
            process_revision=before.revision,
            workflow_revision=workflow.revision,
            payload=workflow.payload,
        )

    def test_direct_reserved_event_rejects_unverified_external_authority(self) -> None:
        """Valid-looking execution lineage도 current runtime receipt 없이는 저장되지 않습니다."""
        workflow_id, _skill_state, adaptive = self._start_workflow("invalid-authority")
        current = adaptive.update(lambda _state: self._empty_state())
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]
        candidate = self._candidate_with_unverified_execution()

        with self.assertRaises(TransitionRejected):
            self.handle.apply(
                ReservedSkillStateAdvanced(
                    session_id=self.handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=self.handle.actor_id,
                    expected_workflow_revision=current.workflow_revision,
                    payload=self._payload_with_adaptive(workflow_id, candidate.to_payload()),
                    idempotency_key="adaptive-boundary:invalid-authority",
                    reserved_namespaces=frozenset({"adaptive_control"}),
                )
            )

        self._assert_workflow_unchanged(
            workflow_id,
            process_revision=before.revision,
            workflow_revision=workflow.revision,
            payload=workflow.payload,
        )

    def test_public_adaptive_control_store_cannot_bypass_external_admission(self) -> None:
        """Public typed store도 external claim을 aggregate admission 없이 저장하지 못합니다."""
        workflow_id, _skill_state, adaptive = self._start_workflow("store-authority")
        adaptive.update(lambda _state: self._empty_state())
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]

        with self.assertRaises(TransitionRejected):
            adaptive.update(lambda _state: self._candidate_with_unverified_execution())

        self._assert_workflow_unchanged(
            workflow_id,
            process_revision=before.revision,
            workflow_revision=workflow.revision,
            payload=workflow.payload,
        )

    def test_valid_adaptive_control_store_transition_is_admitted(self) -> None:
        """Canonical typed store의 claim-free transition은 aggregate seal 뒤에도 동작합니다."""
        workflow_id, skill_state, adaptive = self._start_workflow("valid-store")

        committed = adaptive.update(lambda _state: self._empty_state())

        self.assertEqual(1, committed.workflow_revision)
        self.assertEqual(self._empty_state(), committed.state)
        self.assertEqual("preserved", skill_state.read().skill_state["sibling"])
        self.assertEqual(
            committed.state.to_payload(),
            skill_state.read().skill_state["adaptive_control"],
        )
        self.assertEqual(workflow_id, committed.workflow_id)

    def test_initial_adaptive_admission_rejects_goal_outside_workflow_anchor(self) -> None:
        """Fresh adaptive admission은 immutable workflow goal과 다른 contract를 거절합니다."""
        scenarios = (
            ("mismatch", self._GOAL, "승인되지 않은 initial adaptive goal"),
            ("missing-anchor", None, self._GOAL),
        )
        for suffix, workflow_goal, contract_goal in scenarios:
            with self.subTest(suffix=suffix):
                workflow_id, _skill_state, adaptive = self._start_workflow(
                    f"initial-goal-{suffix}",
                    goal=workflow_goal,
                )
                before = self.handle.inspect()
                workflow = before.workflows[workflow_id]
                mismatched = self._empty_state(goal=contract_goal)

                with self.assertRaises(TransitionRejected):
                    adaptive.update(lambda _state, candidate=mismatched: candidate)

                self._assert_workflow_unchanged(
                    workflow_id,
                    process_revision=before.revision,
                    workflow_revision=workflow.revision,
                    payload=workflow.payload,
                )

    def test_direct_completed_finalization_rejects_semantic_and_unknown_without_adaptive(
        self,
    ) -> None:
        """Semantic kind와 unknown kind는 adaptive state 없이 completed가 될 수 없습니다."""
        for index, kind in enumerate(("process-ticket", "unknown-semantic-kind")):
            with self.subTest(kind=kind):
                workflow_id, _skill_state, _adaptive = self._start_workflow(
                    f"missing-adaptive-{index}",
                    kind=kind,
                )
                before = self.handle.inspect()
                workflow = before.workflows[workflow_id]
                with self.assertRaises(TransitionRejected):
                    self.handle.apply(
                        WorkflowFinalized(
                            session_id=self.handle.session_id,
                            workflow_id=workflow_id,
                            actor_id=self.handle.actor_id,
                            expected_workflow_revision=workflow.revision,
                            terminal_status=WorkflowStatus.COMPLETED,
                            payload=workflow.payload,
                            idempotency_key=f"adaptive-boundary:missing:{index}",
                        )
                    )
                self._assert_workflow_unchanged(
                    workflow_id,
                    process_revision=before.revision,
                    workflow_revision=workflow.revision,
                    payload=workflow.payload,
                )

    def test_persisted_legacy_policy_is_immutable_and_can_reach_terminal_state(self) -> None:
        """정책 도입 전 false로 시작한 run은 변조 없이 완료되어야 합니다."""
        workflow_id = WorkflowId("persisted-legacy-policy")
        legacy_payload = {
            "phase_run": {
                "schema_version": 1,
                "adaptive_control_required": False,
            },
            "skill_state": {},
        }
        self.handle.apply(
            WorkflowStarted(
                session_id=self.handle.session_id,
                workflow_id=workflow_id,
                owner_actor_id=self.handle.actor_id,
                kind="evaluate-harness",
                goal=self._GOAL,
                payload=legacy_payload,
                idempotency_key="adaptive-boundary:start-legacy-policy",
            )
        )
        legacy_workflow = self.handle.inspect().workflows[workflow_id]

        with self.assertRaises(TransitionRejected):
            self.handle.apply(
                WorkflowAdvanced(
                    session_id=self.handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=self.handle.actor_id,
                    expected_workflow_revision=legacy_workflow.revision,
                    payload={
                        **legacy_payload,
                        "phase_run": {
                            **legacy_payload["phase_run"],
                            "adaptive_control_required": True,
                        },
                    },
                    idempotency_key="adaptive-boundary:mutate-legacy-policy",
                )
            )

        current = self.handle.inspect().workflows[workflow_id]
        committed = self.handle.apply(
            WorkflowFinalized(
                session_id=self.handle.session_id,
                workflow_id=workflow_id,
                actor_id=self.handle.actor_id,
                expected_workflow_revision=current.revision,
                terminal_status=WorkflowStatus.COMPLETED,
                payload=current.payload,
                idempotency_key="adaptive-boundary:finalize-legacy-policy",
            )
        )

        self.assertIs(WorkflowStatus.COMPLETED, committed.workflows[workflow_id].status)

    def test_direct_completed_finalization_rejects_unachieved_adaptive_projection(self) -> None:
        """Canonical adaptive state라도 COMPLETE와 achieved가 아니면 완료 권한이 아닙니다."""
        workflow_id, _skill_state, adaptive = self._start_workflow("unachieved")
        adaptive.update(lambda _state: self._empty_state())
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]

        with self.assertRaises(TransitionRejected):
            self.handle.apply(
                WorkflowFinalized(
                    session_id=self.handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=self.handle.actor_id,
                    expected_workflow_revision=workflow.revision,
                    terminal_status=WorkflowStatus.COMPLETED,
                    payload=workflow.payload,
                    idempotency_key="adaptive-boundary:unachieved",
                )
            )

        self._assert_workflow_unchanged(
            workflow_id,
            process_revision=before.revision,
            workflow_revision=workflow.revision,
            payload=workflow.payload,
        )

    def test_kernel_completion_admission_delegates_to_shared_current_readback(self) -> None:
        """Kernel external admission은 reducer projection과 별개로 shared verifier를 사용합니다."""
        workflow_id, _skill_state, adaptive = self._start_workflow("shared-readback")
        adaptive.update(lambda _state: self._empty_state())
        current = self.handle.inspect()
        workflow = current.workflows[workflow_id]
        event = WorkflowFinalized(
            session_id=self.handle.session_id,
            workflow_id=workflow_id,
            actor_id=self.handle.actor_id,
            expected_workflow_revision=workflow.revision,
            terminal_status=WorkflowStatus.COMPLETED,
            payload=workflow.payload,
            idempotency_key="adaptive-boundary:shared-readback",
        )

        with patch(
            "scripts.agent_harness.adaptive_control_authority."
            "AdaptiveControlAuthorityVerifier.verify_completion"
        ) as verify_completion:
            SessionKernel(self.locator)._validate_adaptive_authority(current, event)

        verify_completion.assert_called_once_with(workflow.revision)

    def test_final_reducer_uses_already_admitted_current_goal_projection(self) -> None:
        """Final reducer는 initial anchor가 아니라 persisted current contract를 판정합니다."""
        workflow_id, _skill_state, _adaptive = self._start_workflow("amended-final-goal")
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]
        amended_goal = "사용자가 수정하고 이미 admission된 current adaptive goal"
        current_adaptive = self._complete_state(goal=amended_goal, intent_revision=2)
        payload = self._payload_with_adaptive(workflow_id, current_adaptive.to_payload())
        amended_workflow = WorkflowRecord(
            workflow.id,
            workflow.owner_actor_id,
            workflow.kind,
            workflow.goal,
            payload,
            workflow.revision,
            workflow.status,
            workflow.last_transition_idempotency_key,
        )
        amended_process = ProcessState(
            before.revision,
            before.session,
            before.actors,
            {**before.workflows, workflow_id: amended_workflow},
            before.delegations,
            before.resources,
            before.mailboxes,
            before.incidents,
            before.outbox,
            before.foreground_turns,
            before.material_actions,
        )

        finalized = SessionStateReducer().reduce(
            amended_process,
            WorkflowFinalized(
                session_id=self.handle.session_id,
                workflow_id=workflow_id,
                actor_id=self.handle.actor_id,
                expected_workflow_revision=amended_workflow.revision,
                terminal_status=WorkflowStatus.COMPLETED,
                payload=payload,
                idempotency_key="adaptive-boundary:finalize-amended-goal",
            ),
        )

        completed = finalized.workflows[workflow_id]
        self.assertEqual(self._GOAL, completed.goal)
        self.assertIs(WorkflowStatus.COMPLETED, completed.status)
        completed_skill_state = completed.payload["skill_state"]
        if not isinstance(completed_skill_state, Mapping):
            self.fail("completed workflow skill_state must be an object")
        completed_adaptive = completed_skill_state["adaptive_control"]
        if not isinstance(completed_adaptive, Mapping):
            self.fail("completed adaptive state must be an object")
        self.assertEqual(
            amended_goal,
            AdaptiveControlState.from_payload(completed_adaptive).contract.goal,
        )

    def test_exact_operational_workflow_can_complete_without_adaptive_state(self) -> None:
        """Narrow operational exemption은 adaptive namespace 없이 기존 완료를 유지합니다."""
        workflow_id, _skill_state, _adaptive = self._start_workflow(
            "operational",
            kind="commit",
            goal=None,
        )
        workflow = self.handle.inspect().workflows[workflow_id]

        committed = self.handle.apply(
            WorkflowFinalized(
                session_id=self.handle.session_id,
                workflow_id=workflow_id,
                actor_id=self.handle.actor_id,
                expected_workflow_revision=workflow.revision,
                terminal_status=WorkflowStatus.COMPLETED,
                payload=workflow.payload,
                idempotency_key="adaptive-boundary:operational",
            )
        )

        self.assertIs(WorkflowStatus.COMPLETED, committed.workflows[workflow_id].status)

    def test_failed_finalization_preserves_adaptive_state_without_completion_authority(
        self,
    ) -> None:
        """Failure는 completion을 요구하지 않지만 adaptive namespace를 그대로 보존합니다."""
        workflow_id, skill_state, adaptive = self._start_workflow("failed")
        adaptive.update(
            lambda _state: replace(self._empty_state(), execution_status=ExecutionStatus.FAILED)
        )
        before = self.handle.inspect()
        workflow = before.workflows[workflow_id]
        adaptive_payload = skill_state.read().skill_state["adaptive_control"]

        committed = self.handle.apply(
            WorkflowFinalized(
                session_id=self.handle.session_id,
                workflow_id=workflow_id,
                actor_id=self.handle.actor_id,
                expected_workflow_revision=workflow.revision,
                terminal_status=WorkflowStatus.FAILED,
                payload=workflow.payload,
                idempotency_key="adaptive-boundary:failed",
            )
        )

        finalized = committed.workflows[workflow_id]
        finalized_skill_state = finalized.payload["skill_state"]
        if not isinstance(finalized_skill_state, Mapping):
            self.fail("finalized workflow skill_state must be an object")
        self.assertIs(WorkflowStatus.FAILED, finalized.status)
        self.assertEqual(
            adaptive_payload,
            finalized_skill_state["adaptive_control"],
        )
