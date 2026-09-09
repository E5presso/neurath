"""Phase runner state를 exact session workflow에 보존하는 store 계약입니다."""

import unittest
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.adaptive_control import (
    CriterionSpec,
    EvidenceKind,
    GapInventory,
    GoalContract,
    OracleOwner,
    RequirementSection,
    approved_requirement_fingerprint,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityInvalid,
    AdaptiveControlAuthorityStatus,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    AdaptiveControlStore,
)
from scripts.agent_harness.session_kernel import (
    ProcessState,
    SessionId,
    SessionLocator,
    SessionStateStore,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
from scripts.skill_harness.phase_runner import (
    PhaseContract,
    PhaseRunState,
    SkillContract,
)
from scripts.skill_harness.session_phase_store import (
    PhaseStateIdentityError,
    PhaseStateTerminalError,
    PhaseWorkflowConflict,
    SessionPhaseRunnerStore,
    SessionPhaseStateStore,
)


class SessionPhaseStateStoreTest(TestCase):
    """Workflow-local CAS, identity fencing, session 격리를 검증합니다."""

    def setUp(self) -> None:
        """각 test에 독립적인 canonical control root와 root handle을 준비합니다."""
        self._temporary_directory = TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.locator = SessionLocator(Path(self._temporary_directory.name))
        self.resolver = RuntimeEnvironmentResolver()
        self.handle = self._open_handle("session-a")

    def _open_handle(self, session_id: str) -> StateHandle:
        """Codex root identity로 exact session handle을 엽니다.

        Args:
            session_id: 다른 fixture와 격리할 runtime-owned session identity입니다.

        Returns:
            Exact session과 root actor에 bound된 state handle입니다.
        """
        binding = self.resolver.resolve({"CODEX_THREAD_ID": session_id})
        return StateHandle.initialize(self.locator, binding)

    def _contract(self, skill: str = "process-ticket") -> SkillContract:
        """두 단계 phase state를 만들 최소 skill contract를 반환합니다.

        Args:
            skill: Phase state의 skill identity로 사용할 이름입니다.

        Returns:
            성공과 실패 terminal state를 허용하는 deterministic contract입니다.
        """
        return SkillContract(
            name=skill,
            terminal_states=("completed", "failed"),
            phases=(
                PhaseContract(
                    id=1,
                    name="prepare",
                    min_evidence_count=0,
                    required_evidence=(),
                ),
                PhaseContract(
                    id=2,
                    name="verify",
                    min_evidence_count=0,
                    required_evidence=(),
                ),
            ),
        )

    def _state(
        self,
        run_id: str,
        *,
        skill: str = "process-ticket",
        north_star: str = "승인된 작업을 검증까지 완료한다",
    ) -> PhaseRunState:
        """Store test용 valid initial phase state를 생성합니다.

        Args:
            run_id: Workflow 안에서 검증할 legacy-compatible run identity입니다.
            skill: Persisted payload와 workflow kind가 공유할 skill identity입니다.
            north_star: Workflow goal과 phase payload가 공유할 실행 목표입니다.

        Returns:
            첫 phase가 active인 초기 phase state입니다.
        """
        return PhaseRunState.initialize(self._contract(skill), run_id, north_star)

    def _store(
        self,
        handle: StateHandle,
        workflow_id: str,
        run_id: str,
        skill: str = "process-ticket",
    ) -> SessionPhaseStateStore:
        """Explicit identity에 고정된 session phase store를 생성합니다.

        Args:
            handle: Exact session과 actor authority를 제공하는 facade입니다.
            workflow_id: 같은 session 안 workflow aggregate identity입니다.
            run_id: Payload가 반드시 일치해야 하는 phase-run identity입니다.
            skill: Workflow kind와 payload가 반드시 일치해야 하는 skill입니다.

        Returns:
            File path를 노출하지 않는 session-scoped store입니다.
        """
        return SessionPhaseStateStore(
            handle=handle,
            workflow_id=WorkflowId(workflow_id),
            skill=skill,
            run_id=run_id,
        )

    def test_initialize_and_read_round_trip_one_exact_workflow(self) -> None:
        """Initialize는 WorkflowStarted로 goal과 PhaseRunState payload를 보존합니다."""
        state = self._state("run-a")
        store = self._store(self.handle, "workflow-a", "run-a")

        initialized = store.initialize(state)
        read_back = store.read()
        workflow = self.handle.inspect().workflows[WorkflowId("workflow-a")]

        self.assertEqual(state.as_payload(), initialized.state.as_payload())
        self.assertEqual(state.as_payload(), read_back.state.as_payload())
        self.assertEqual(0, initialized.workflow_revision)
        self.assertEqual(WorkflowStatus.ACTIVE, initialized.workflow_status)
        self.assertEqual(state.north_star, workflow.goal)
        self.assertEqual(state.skill, workflow.kind)
        self.assertEqual(self.handle.actor_id, workflow.owner_actor_id)
        self.assertEqual(state.as_payload(), workflow.payload["phase_run"])
        self.assertEqual({}, workflow.payload["skill_state"])

    def test_adaptive_transition_readback_binds_authority_and_criteria_to_one_revision(
        self,
    ) -> None:
        """Transition read-back은 한 snapshot의 exact authority와 criterion metadata를 반환합니다."""
        goal = "승인된 adaptive goal을 exact authority로 진행한다"
        state = self._state("adaptive-run", skill="plan-issues", north_star=goal)
        store = self._store(
            self.handle,
            "adaptive-workflow",
            "adaptive-run",
            skill="plan-issues",
        )
        store.initialize(state)
        constraints = ("external authority를 runtime에서 확인한다",)
        non_goals = ("self-authored authority를 허용하지 않는다",)
        intent_revision = 1
        source_revision = "session-phase-store:1"
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({"REQ-adaptive-transition"}),
            criteria=(
                CriterionSpec(
                    criterion_id="adaptive-transition",
                    description="current authority가 phase transition을 허용한다",
                    source_requirement_id="REQ-adaptive-transition",
                    approved_requirement_fingerprint=approved_requirement_fingerprint(
                        goal,
                        constraints,
                        non_goals,
                        intent_revision,
                        source_revision,
                    ),
                    observer="phase runner",
                    precondition="adaptive workflow가 active다",
                    stimulus="phase transition read-back을 요청한다",
                    expected_outcome="same revision authority와 criterion을 반환한다",
                    oracle_owner=OracleOwner.EXECUTABLE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.EXAMPLE_TEST}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )
        inventory = GapInventory(
            intent_revision=intent_revision,
            source_revision=source_revision,
            assessed_sections=frozenset(RequirementSection),
            gaps=(),
        )
        snapshot = AdaptiveControlStore(
            SkillStateStore(self.handle, WorkflowId("adaptive-workflow"))
        ).update(lambda _current: AdaptiveControlState.empty(contract, inventory))

        readback = store.read_adaptive_control_transition()

        self.assertEqual(snapshot.workflow_revision, readback.receipt.workflow_revision)
        self.assertEqual(snapshot.workflow_revision, readback.authority.workflow_revision)
        self.assertEqual(snapshot.state.contract.fingerprint, readback.receipt.goal_fingerprint)
        self.assertEqual(
            snapshot.state.contract.fingerprint,
            readback.authority.goal_fingerprint,
        )
        self.assertIs(
            AdaptiveControlAuthorityStatus.VERIFIED,
            readback.authority.status,
        )
        self.assertEqual(contract.criteria, readback.criteria)

    def test_finalize_delegates_current_revision_to_shared_completion_readback(self) -> None:
        """Phase store는 amended goal을 재해석하지 않고 shared current readback에 맡깁니다."""
        state = self._state(
            "amended-finalize-run",
            skill="plan-issues",
            north_star="immutable initial phase goal",
        )
        store = self._store(
            self.handle,
            "amended-finalize-workflow",
            "amended-finalize-run",
            skill="plan-issues",
        )
        initialized = store.initialize(state)
        workflow = self.handle.inspect().workflows[WorkflowId("amended-finalize-workflow")]
        workflow = WorkflowRecord(
            workflow.id,
            workflow.owner_actor_id,
            workflow.kind,
            workflow.goal,
            {
                **workflow.payload,
                "skill_state": {"adaptive_control": {"current": "amended"}},
            },
            workflow.revision,
            workflow.status,
            workflow.last_transition_idempotency_key,
        )
        with (
            patch.object(SessionPhaseStateStore, "_active_workflow", return_value=workflow),
            patch.object(
                SessionPhaseStateStore,
                "_apply_transition",
                return_value=initialized,
            ) as apply_transition,
            patch(
                "scripts.skill_harness.session_phase_store.AdaptiveControlAuthorityVerifier"
            ) as verifier_type,
        ):
            finalized = store.finalize(
                state.with_terminal_state("completed"),
                expected_workflow_revision=workflow.revision,
            )

            verifier_type.return_value.verify_completion.side_effect = (
                AdaptiveControlAuthorityInvalid("stale current authority")
            )
            with self.assertRaises(PhaseStateTerminalError):
                store.finalize(
                    state.with_terminal_state("completed"),
                    expected_workflow_revision=workflow.revision,
                )

        self.assertEqual(initialized, finalized)
        apply_transition.assert_called_once()
        self.assertEqual(
            [
                ((workflow.revision,), {}),
                ((workflow.revision,), {}),
            ],
            [
                (entry.args, entry.kwargs)
                for entry in verifier_type.return_value.verify_completion.call_args_list
            ],
        )

    def test_reads_pre_policy_phase_state_and_canonicalizes_it_on_next_transition(self) -> None:
        """Adaptive policy field 이전 run은 읽히고 다음 write부터 canonical marker를 가집니다."""
        state = self._state("legacy-run")
        store = self._store(self.handle, "legacy-workflow", "legacy-run")
        initialized = store.initialize(state)
        workflow = self.handle.inspect().workflows[WorkflowId("legacy-workflow")]
        legacy_phase = dict(state.as_payload())
        legacy_phase.pop("adaptive_control_required")
        before_seed = self.handle.inspect()
        legacy_workflow = WorkflowRecord(
            workflow.id,
            workflow.owner_actor_id,
            workflow.kind,
            workflow.goal,
            {"phase_run": legacy_phase, "skill_state": {}},
            workflow.revision,
            workflow.status,
            workflow.last_transition_idempotency_key,
        )
        legacy_state = ProcessState(
            before_seed.revision,
            before_seed.session,
            before_seed.actors,
            {**before_seed.workflows, workflow.id: legacy_workflow},
            before_seed.delegations,
            before_seed.resources,
            before_seed.mailboxes,
            before_seed.incidents,
            before_seed.outbox,
            before_seed.foreground_turns,
        )
        import hashlib
        from scripts.agent_harness.runtime_database import RuntimeDatabase
        from scripts.agent_harness.session_state_codec import SessionStateCodec
        encoded = SessionStateCodec().encode(legacy_state)
        with RuntimeDatabase(self.locator.control_root).connection() as db:
            db.execute("UPDATE runtime_records SET payload=?,digest=? WHERE namespace='session' AND key=?",
                       (encoded, hashlib.sha256(encoded).hexdigest(), str(self.handle.session_id)))

        self.assertEqual(initialized.workflow_revision, legacy_workflow.revision)

        with self.assertRaises(TransitionRejected):
            self.handle.apply(
                WorkflowAdvanced(
                    session_id=self.handle.session_id,
                    workflow_id=workflow.id,
                    actor_id=self.handle.actor_id,
                    expected_workflow_revision=legacy_workflow.revision,
                    payload={
                        "phase_run": {
                            **legacy_phase,
                            "adaptive_control_required": True,
                        },
                        "skill_state": {},
                    },
                    idempotency_key="test:legacy-phase-policy:upgrade-to-true",
                )
            )

        legacy = store.read()
        advanced = legacy.state.with_completed_phase(
            self._contract(),
            1,
            "completed",
            (),
            "legacy phase migrated",
            None,
        )
        committed = store.advance(
            advanced,
            expected_workflow_revision=legacy.workflow_revision,
        )

        self.assertFalse(legacy.state.adaptive_control_required)
        self.assertFalse(committed.state.adaptive_control_required)
        current_payload = self.handle.inspect().workflows[workflow.id].payload["phase_run"]
        self.assertIsInstance(current_payload, dict)
        assert isinstance(current_payload, dict)
        self.assertIs(False, current_payload["adaptive_control_required"])

    def test_advance_uses_workflow_local_revision_and_exposes_stale_conflict(self) -> None:
        """동일 workflow의 stale writer는 덮어쓰지 않고 typed conflict를 반환합니다."""
        state = self._state("run-a")
        store = self._store(self.handle, "workflow-a", "run-a")
        initialized = store.initialize(state)
        advanced_state = state.with_completed_phase(
            self._contract(),
            1,
            "completed",
            ("first-writer",),
            "첫 writer가 phase를 완료함",
            None,
        )
        stale_state = state.with_completed_phase(
            self._contract(),
            1,
            "completed",
            ("stale-writer",),
            "stale writer가 다른 결과를 만듦",
            None,
        )

        committed = store.advance(
            advanced_state,
            expected_workflow_revision=initialized.workflow_revision,
        )

        with self.assertRaises(PhaseWorkflowConflict):
            store.advance(
                stale_state,
                expected_workflow_revision=initialized.workflow_revision,
            )

        current = store.read()
        self.assertEqual(1, committed.workflow_revision)
        self.assertEqual(("first-writer",), current.state.phase(1).evidence)

    def test_unrelated_workflow_update_does_not_invalidate_local_revision(self) -> None:
        """같은 session의 다른 workflow mutation은 aggregate-local CAS와 독립적입니다."""
        store_a = self._store(self.handle, "workflow-a", "run-a")
        store_b = self._store(self.handle, "workflow-b", "run-b", skill="investigate")
        snapshot_a = store_a.initialize(self._state("run-a"))
        snapshot_b = store_b.initialize(self._state("run-b", skill="investigate"))
        advanced_b = snapshot_b.state.with_completed_phase(
            self._contract("investigate"),
            1,
            "completed",
            (),
            "독립 workflow 완료",
            None,
        )
        store_b.advance(
            advanced_b,
            expected_workflow_revision=snapshot_b.workflow_revision,
        )
        advanced_a = snapshot_a.state.with_completed_phase(
            self._contract(),
            1,
            "completed",
            (),
            "원래 revision으로 완료",
            None,
        )

        committed_a = store_a.advance(
            advanced_a,
            expected_workflow_revision=snapshot_a.workflow_revision,
        )

        self.assertEqual(1, committed_a.workflow_revision)
        self.assertEqual(1, store_b.read().workflow_revision)

    def test_advance_preserves_unrelated_workflow_payload_namespaces(self) -> None:
        """Phase transition은 같은 workflow의 skill-specific payload를 덮어쓰지 않습니다."""
        store = self._store(self.handle, "workflow-a", "run-a")
        store.initialize(self._state("run-a"))
        workflow = self.handle.inspect().workflows[WorkflowId("workflow-a")]
        self.handle.apply(
            WorkflowAdvanced(
                session_id=self.handle.session_id,
                workflow_id=workflow.id,
                actor_id=self.handle.actor_id,
                expected_workflow_revision=workflow.revision,
                payload={
                    **workflow.payload,
                    "skill_state": {"issue_number": 42, "stage": "implementation"},
                },
                idempotency_key="test:skill-state:workflow-a",
            )
        )
        phase_snapshot = store.read()
        advanced_phase = phase_snapshot.state.with_completed_phase(
            self._contract(),
            1,
            "completed",
            (),
            "phase namespace만 갱신",
            None,
        )

        store.advance(
            advanced_phase,
            expected_workflow_revision=phase_snapshot.workflow_revision,
        )

        current_payload = self.handle.inspect().workflows[workflow.id].payload
        self.assertEqual(
            {"issue_number": 42, "stage": "implementation"},
            current_payload["skill_state"],
        )
        self.assertEqual(advanced_phase.as_payload(), current_payload["phase_run"])

    def test_same_workflow_identity_isolated_between_sessions(self) -> None:
        """같은 workflow/run identity도 다른 session snapshot과 절대 섞이지 않습니다."""
        handle_b = self._open_handle("session-b")
        store_a = self._store(self.handle, "shared-workflow", "shared-run")
        store_b = self._store(handle_b, "shared-workflow", "shared-run")
        state_a = self._state("shared-run", north_star="session A 목표")
        state_b = self._state("shared-run", north_star="session B 목표")

        store_a.initialize(state_a)
        store_b.initialize(state_b)

        self.assertEqual(SessionId("session-a"), self.handle.session_id)
        self.assertEqual(SessionId("session-b"), handle_b.session_id)
        self.assertEqual("session A 목표", store_a.read().state.north_star)
        self.assertEqual("session B 목표", store_b.read().state.north_star)

    def test_wrong_skill_or_run_identity_fails_closed_without_mutation(self) -> None:
        """Store selector와 persisted PhaseRunState의 skill/run 불일치는 모두 거부합니다."""
        correct = self._store(self.handle, "workflow-a", "run-a")
        correct.initialize(self._state("run-a"))
        revision_before = self.handle.inspect().revision
        mismatched_stores = (
            self._store(self.handle, "workflow-a", "run-a", skill="investigate"),
            self._store(self.handle, "workflow-a", "run-b"),
        )

        for store in mismatched_stores:
            with (
                self.subTest(skill=store.skill, run_id=store.run_id),
                self.assertRaises(PhaseStateIdentityError),
            ):
                store.read()

        new_store = self._store(self.handle, "workflow-b", "run-b")
        with self.assertRaises(PhaseStateIdentityError):
            new_store.initialize(self._state("different-run"))

        self.assertEqual(revision_before, self.handle.inspect().revision)
        self.assertNotIn(WorkflowId("workflow-b"), self.handle.inspect().workflows)

    def test_finalize_maps_terminal_state_and_blocks_further_advance(self) -> None:
        """WorkflowFinalized는 phase terminal 결과를 보존하고 이후 advance를 거부합니다."""
        state = self._state("run-a", skill="checkpoint")
        store = self._store(self.handle, "workflow-a", "run-a", skill="checkpoint")
        store.initialize(state)
        workflow = self.handle.inspect().workflows[WorkflowId("workflow-a")]
        self.handle.apply(
            WorkflowAdvanced(
                session_id=self.handle.session_id,
                workflow_id=workflow.id,
                actor_id=self.handle.actor_id,
                expected_workflow_revision=workflow.revision,
                payload={**workflow.payload, "skill_state": {"receipt": "kept"}},
                idempotency_key="test:skill-state-before-finalize:workflow-a",
            )
        )
        before_finalize = store.read()
        terminal_state = state
        contract = self._contract("checkpoint")
        for phase in contract.phases:
            terminal_state = terminal_state.with_completed_phase(
                contract,
                phase.id,
                "completed",
                (),
                "phase complete",
                None,
            )
            before_finalize = store.advance(
                terminal_state,
                expected_workflow_revision=before_finalize.workflow_revision,
            )
        terminal_state = terminal_state.with_terminal_state("completed")

        finalized = store.finalize(
            terminal_state,
            expected_workflow_revision=before_finalize.workflow_revision,
        )

        self.assertEqual(WorkflowStatus.COMPLETED, finalized.workflow_status)
        self.assertEqual(2 + len(contract.phases), finalized.workflow_revision)
        self.assertEqual("completed", store.read().state.terminal_state)
        self.assertEqual(
            {"receipt": "kept"},
            self.handle.inspect().workflows[workflow.id].payload["skill_state"],
        )
        with self.assertRaises(PhaseStateTerminalError):
            store.advance(
                state,
                expected_workflow_revision=finalized.workflow_revision,
            )

    def test_failed_phase_terminal_maps_to_failed_workflow(self) -> None:
        """Phase runner의 실패 terminal은 성공 완료와 구분된 workflow status를 남깁니다."""
        state = self._state("run-failed")
        store = self._store(self.handle, "workflow-failed", "run-failed")
        initial = store.initialize(state)

        finalized = store.finalize(
            state.with_completed_phase(
                self._contract(),
                1,
                "failed",
                (),
                "phase failed",
                "execution failed",
            ).with_terminal_state("failed"),
            expected_workflow_revision=initial.workflow_revision,
        )

        self.assertEqual(WorkflowStatus.FAILED, finalized.workflow_status)
        self.assertEqual("failed", finalized.state.terminal_state)

    def test_public_surface_requires_no_path_or_implicit_retry(self) -> None:
        """DX는 StateHandle/WorkflowId를 받고 caller-visible expected revision을 요구합니다."""
        store = self._store(self.handle, "workflow-a", "run-a")

        self.assertEqual(
            ("handle", "workflow_id", "skill", "run_id"),
            tuple(signature(SessionPhaseStateStore).parameters),
        )
        self.assertEqual(("state",), tuple(signature(store.initialize).parameters))
        self.assertEqual((), tuple(signature(store.read).parameters))
        self.assertEqual(
            ("state", "expected_workflow_revision"),
            tuple(signature(store.advance).parameters),
        )
        self.assertEqual(
            ("state", "expected_workflow_revision"),
            tuple(signature(store.finalize).parameters),
        )
        self.assertFalse(hasattr(store, "path"))
        self.assertFalse(hasattr(store, "state_path"))

    def test_runner_adapter_derives_existing_identity_and_uses_cached_cas(self) -> None:
        """Runner adapter는 workflow identity를 재개하고 직전 read revision으로 씁니다."""
        state = self._state("run-a")
        exact_store = self._store(self.handle, "workflow-a", "run-a")
        runner_store = SessionPhaseRunnerStore(exact_store)

        runner_store.write(state)
        current = runner_store.read()
        advanced = current.with_completed_phase(
            self._contract(),
            1,
            "completed",
            (),
            "runner adapter transition",
            None,
        )
        runner_store.write(advanced)
        reopened = SessionPhaseRunnerStore.open_existing(
            self.handle,
            WorkflowId("workflow-a"),
        )

        self.assertEqual(advanced.as_payload(), reopened.read().as_payload())


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
