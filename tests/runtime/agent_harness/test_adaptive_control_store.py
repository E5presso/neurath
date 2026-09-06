"""적응형 제어 snapshot과 phase-runner evidence readback 계약을 검증합니다."""

import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

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
    IterationObservation,
    OracleOwner,
    ReflectionPolicy,
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionTarget,
    UserDeferral,
    adaptive_output_fingerprint,
    approved_requirement_fingerprint,
    assess_goal_attainment,
    user_decision_value_summary_digest,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    AdaptiveControlStateMissing,
    AdaptiveControlStore,
    InvalidAdaptiveControlEvidence,
    InvalidAdaptiveControlState,
    validate_adaptive_control_transition,
    validate_efficiency_resource_admission,
)
from scripts.agent_harness.efficiency_assessment import (
    EfficiencyAssessor,
    EfficiencyStatus,
    ResourceMetricDelta,
    ResourceTelemetryStatus,
)
from scripts.agent_harness.material_action import (
    AdaptiveActionBinding,
    MaterialActionKind,
    MaterialActionResolution,
    ObservableDeltaKind,
    ObservableExpectation,
    ObservableObservation,
    ToolReceipt,
    ToolReceiptOutcome,
)
from scripts.agent_harness.session_kernel import (
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    KernelEvent,
    MaterialActionPrepared,
    MaterialActionResolved,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    ProcessState,
    SessionKernel,
    SessionLocator,
    SessionStateStore,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateReservedNamespaceError,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle


class TransitionOnlySessionKernel(SessionKernel):
    """Pure store tests가 external authority fixture 없이 reducer transition만 실행합니다."""

    def apply(
        self,
        event: KernelEvent,
        expected_revision: int | None = None,
    ) -> ProcessState:
        """Production reducer와 CAS를 유지하고 external aggregate admission만 분리합니다."""
        paths = self._session_paths(event.session_id)
        return SessionStateStore(paths.process_state).transact(event, expected_revision)


class AdaptiveControlStoreTest(TestCase):
    """Pure adaptive state와 receipt가 exact workflow에서만 신뢰되는지 검증합니다."""

    def setUp(self) -> None:
        """각 test에 격리된 canonical session directory를 준비합니다."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.locator = SessionLocator(Path(directory.name))

    def _handle(self, session_id: str) -> StateHandle:
        """지정한 session에서 pure store transition만 실행하는 test handle을 만듭니다."""
        binding = RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID": session_id})
        handle = StateHandle(TransitionOnlySessionKernel(self.locator), binding)
        StateHandle.initialize(self.locator, binding)
        handle.apply(
            ForegroundTurnProvisioned(
                session_id=binding.session_id,
                actor_id=binding.actor_id,
                idempotency_key="adaptive-store:turn:provision",
            )
        )
        return handle

    def _store(
        self,
        handle: StateHandle,
        workflow_id: str,
        *,
        ticket: int,
    ) -> tuple[SkillStateStore, AdaptiveControlStore]:
        """Sibling skill state를 가진 exact active workflow store를 만듭니다."""
        identity = WorkflowId(workflow_id)
        handle.apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=identity,
                owner_actor_id=handle.actor_id,
                kind="process-ticket",
                goal="승인된 작업을 완수한다",
                payload={"skill_state": {"ticket": ticket}},
                idempotency_key=f"workflow-started:{workflow_id}",
            )
        )
        skill_state = SkillStateStore(handle, identity)
        return skill_state, AdaptiveControlStore(skill_state)

    def _lineage(
        self,
        authority: EvidenceAuthority,
        *,
        intent_revision: int = 1,
        source_revision: str = "approved-plan:1",
        issuer_id: str | None = None,
        subject_id: str = "implementation-agent",
    ) -> AuthorityReceipt:
        """Authority, issuer, subject, revision을 하나의 provenance receipt로 묶습니다."""
        issuer = (
            issuer_id
            or {
                EvidenceAuthority.EXECUTABLE: "test-runner",
                EvidenceAuthority.INDEPENDENT_EVALUATOR: "independent-reviewer",
                EvidenceAuthority.USER: "user",
                EvidenceAuthority.PRIMARY_SOURCE: "repository",
                EvidenceAuthority.SAME_CONTEXT: subject_id,
            }[authority]
        )
        receipt_body = f"{authority}:{issuer}:{subject_id}:{intent_revision}:{source_revision}"
        return AuthorityReceipt(
            authority=authority,
            issuer_id=issuer,
            subject_id=subject_id,
            intent_revision=intent_revision,
            source_revision=source_revision,
            receipt_digest=hashlib.sha256(receipt_body.encode()).hexdigest(),
            delegation_id=(
                "delegation-independent-review"
                if authority is EvidenceAuthority.INDEPENDENT_EVALUATOR
                else None
            ),
        )

    def _contract(
        self,
        suffix: str = "current",
        *,
        intent_revision: int = 1,
    ) -> GoalContract:
        """Approved requirement lineage와 executable oracle을 가진 goal contract를 만듭니다."""
        criterion_id = f"{suffix}-behavior"
        goal = f"{suffix} 목표를 완수한다"
        constraints = ("기존 SessionKernel을 재사용한다",)
        non_goals = ("별도 Agent OS를 만들지 않는다",)
        source_revision = f"approved-plan:{intent_revision}"
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({f"REQ-{criterion_id}"}),
            criteria=(
                CriterionSpec(
                    criterion_id=criterion_id,
                    description="요청한 behavior가 실제 경계에서 검증된다",
                    source_requirement_id=f"REQ-{criterion_id}",
                    approved_requirement_fingerprint=approved_requirement_fingerprint(
                        goal,
                        constraints,
                        non_goals,
                        intent_revision,
                        source_revision,
                    ),
                    observer="사용자",
                    precondition="승인된 requirement가 current intent에 고정되어 있다",
                    stimulus="요청한 동작을 실행한다",
                    expected_outcome="실제 behavior가 acceptance 경계에서 관찰된다",
                    oracle_owner=OracleOwner.EXECUTABLE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.PROPERTY_TEST}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )

    def _goal_override_decision(
        self,
        previous: GoalContract,
        result: GoalContract,
        *,
        workflow_id: str,
    ) -> UserDecision:
        """Old criterion을 target으로 삼는 raw-free USER goal override를 만듭니다."""
        target_id = previous.criteria[0].criterion_id
        disposition = UserDecisionDisposition.ACCEPTED
        claim = UserDecisionClaim(
            workflow_id=workflow_id,
            question_workflow_revision=1,
            source_goal_fingerprint=previous.fingerprint,
            source_intent_revision=previous.intent_revision,
            source_revision=previous.source_revision,
            question_digest=hashlib.sha256(b"goal override question").hexdigest(),
            question_generation=1,
            question_turn_revision=2,
            prompt_digest=hashlib.sha256(b"goal override response").hexdigest(),
            prompt_reference="user-prompt:goal-override",
            prompt_generation=2,
            prompt_turn_revision=3,
            target_kind=UserDecisionTarget.CRITERION,
            target_id=target_id,
            disposition=disposition,
            value_summary_digest=user_decision_value_summary_digest(
                UserDecisionTarget.CRITERION,
                target_id,
                disposition,
                result.fingerprint,
                result.intent_revision,
                result.source_revision,
            ),
            result_goal_fingerprint=result.fingerprint,
            result_intent_revision=result.intent_revision,
            result_source_revision=result.source_revision,
        )
        return UserDecision(
            claim=claim,
            interpretation_lineage=AuthorityReceipt(
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                issuer_id="codex:goal-override-evaluator",
                subject_id="codex:goal-override-owner",
                intent_revision=result.intent_revision,
                source_revision=result.source_revision,
                receipt_digest="d" * 64,
                delegation_id="goal-override-evaluation",
            ),
        )

    def _inventory(
        self,
        contract: GoalContract,
        *,
        gaps: tuple[ClarificationGap, ...] | None = None,
        assessed: bool = True,
    ) -> GapInventory:
        """Current intent와 repository basis에 결속된 clarification inventory를 만듭니다."""
        source_revision = f"repo:head-{contract.intent_revision}"
        return GapInventory(
            intent_revision=contract.intent_revision,
            source_revision=source_revision,
            assessed_sections=(frozenset(RequirementSection) if assessed else frozenset()),
            gaps=(
                self._resolved_gap(contract, source_revision),
                self._deferred_gap(contract),
            )
            if gaps is None
            else gaps,
        )

    def _resolved_gap(
        self,
        contract: GoalContract,
        source_revision: str,
    ) -> ClarificationGap:
        """Repository primary-source lineage로 닫힌 clarification gap을 만듭니다."""
        return ClarificationGap(
            gap_id="repository-contract",
            section=RequirementSection.VERIFICATION,
            authority=GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=0.8,
            blocking=True,
            reversible=False,
            scope_local=False,
            context="기존 state contract를 확인해야 한다",
            question="어느 state store가 SSOT인가?",
            consequence="잘못된 persistence 경계가 생긴다",
            recommendation="SkillStateStore를 재사용한다",
            recommendation_rationale="이미 workflow-local CAS와 session 격리를 소유한다",
            intent_revision=contract.intent_revision,
            resolution=GapResolution.REPOSITORY_FACT,
            evidence_reference="scripts/agent_harness/skill_state_store.py",
            resolution_lineage=self._lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                intent_revision=contract.intent_revision,
                source_revision=source_revision,
            ),
        )

    def _deferred_gap(self, contract: GoalContract) -> ClarificationGap:
        """User lineage가 current intent에서 명시적으로 유예한 non-blocking gap을 만듭니다."""
        deferral = UserDeferral(
            gap_id="future-preference",
            intent_revision=contract.intent_revision,
            reason="사용자가 현재 workflow에서는 후속 선택으로 유예했다",
            lineage=self._lineage(
                EvidenceAuthority.USER,
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
            ),
        )
        return ClarificationGap(
            gap_id="future-preference",
            section=RequirementSection.OWNERSHIP,
            authority=GapAuthority.USER,
            dependency_rank=1,
            weight=0.2,
            blocking=False,
            reversible=False,
            scope_local=False,
            context="후속 product preference가 남아 있다",
            question="후속 preference를 지금 결정할까요?",
            consequence="현재 acceptance에는 영향을 주지 않는다",
            recommendation="명시적으로 후속 결정으로 유예한다",
            recommendation_rationale="현재 목표를 넓히지 않고 user ownership을 보존한다",
            intent_revision=contract.intent_revision,
            deferral=deferral,
        )

    def _complete_state(self, contract: GoalContract | None = None) -> AdaptiveControlState:
        """모든 authority가 current intent/source lineage에 결속된 state를 만듭니다."""
        selected = contract or self._contract()
        criterion_id = selected.criteria[0].criterion_id
        state = AdaptiveControlState(
            contract=selected,
            inventory=self._inventory(selected),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=selected.fingerprint,
                    criterion_id=criterion_id,
                    kind=EvidenceKind.PROPERTY_TEST,
                    authority=EvidenceAuthority.EXECUTABLE,
                    status=EvidenceStatus.PASS,
                    reference="pytest:property-contract",
                    lineage=self._lineage(
                        EvidenceAuthority.EXECUTABLE,
                        intent_revision=selected.intent_revision,
                        source_revision=selected.source_revision,
                    ),
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=selected.fingerprint,
                criterion_ids=frozenset({criterion_id}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="review:independent-evaluator",
                goal_alignment=0.95,
                semantic_drift=0.02,
                uncertainty=0.03,
                reward_hacking_risk=0.01,
                lineage=self._lineage(
                    EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    intent_revision=selected.intent_revision,
                    source_revision=selected.source_revision,
                ),
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        return replace(state, observations=(self._derived_observation(state),))

    def _derived_observation(
        self,
        state: AdaptiveControlState,
        *,
        generation: int = 1,
        recovery_epoch: int = 0,
        previous: IterationObservation | None = None,
        root_causes: tuple[str, ...] = (),
    ) -> IterationObservation:
        """Canonical adaptive state에서만 iteration observation 값을 파생합니다."""
        fingerprint = adaptive_output_fingerprint(
            state.contract,
            state.inventory,
            state.evidence,
            state.coverage,
            state.execution_status,
        )
        return IterationObservation(
            goal_fingerprint=state.contract.fingerprint,
            generation=generation,
            output_fingerprint=fingerprint,
            active_criteria=tuple(item.criterion_id for item in state.contract.criteria),
            root_causes=root_causes,
            progress=assess_goal_attainment(
                state.contract,
                state.evidence,
                state.coverage,
                state.execution_status,
            ).progress,
            material_change=previous is None or previous.output_fingerprint != fingerprint,
            recovery_epoch=recovery_epoch,
        )

    def _require_state(self, state: AdaptiveControlState | None) -> AdaptiveControlState:
        """Existing-state mutation fixture에서 missing initialization을 명시적으로 거부합니다."""
        if state is None:
            raise AssertionError("adaptive state must already exist")
        return state

    def _redigest(self, evidence: dict[str, object]) -> dict[str, object]:
        """공개 canonical 형식대로 forged body의 내부 digest까지 다시 계산합니다."""
        body = {key: value for key, value in evidence.items() if key != "evidence_digest"}
        encoded = json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return {**body, "evidence_digest": hashlib.sha256(encoded).hexdigest()}

    def _initialize_incomplete_generation(
        self,
        session_id: str,
    ) -> tuple[AdaptiveControlStore, AdaptiveControlSnapshot]:
        """Incomplete goal을 저장하고 아직 generation이 없는 snapshot을 반환합니다.

        Args:
            session_id: 격리된 test session identity입니다.

        Returns:
            Exact workflow store와 observation이 없는 current snapshot입니다.
        """
        handle = self._handle(session_id)
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        contract = self._contract()
        snapshot = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: AdaptiveControlState.empty(
                contract,
                self._inventory(contract),
            ),
        )
        return store, snapshot

    def _initialize_resource_generation(
        self,
        session_id: str,
    ) -> tuple[StateHandle, SkillStateStore, AdaptiveControlStore, AdaptiveControlSnapshot]:
        """Resource receipt fixture용 handle과 exact adaptive pre-generation을 반환합니다."""
        handle = self._handle(session_id)
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        contract = self._contract()
        snapshot = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: AdaptiveControlState.empty(contract, self._inventory(contract)),
        )
        return handle, skill_state, store, snapshot

    def _resolve_attributable_material_batch(
        self,
        handle: StateHandle,
        snapshot: AdaptiveControlSnapshot,
        *,
        duration_milliseconds: int | None,
        batch_id: str = "resource-batch",
    ) -> None:
        """Exact workflow binding과 successful receipt를 가진 latest batch를 commit합니다."""
        target = "/repo/resource.py"
        before = hashlib.sha256(b"before").hexdigest()
        after = hashlib.sha256(b"after").hexdigest()
        request = hashlib.sha256(b"request").hexdigest()
        handle.apply(
            ForegroundTurnPrompted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                vendor_turn_id="resource-turn",
                idempotency_key=f"turn:{batch_id}",
            )
        )
        turn = handle.inspect().foreground_turns[handle.actor_id]
        handle.apply(
            MaterialActionPrepared(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                sequence=1,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=(target,),
                expectations=(
                    ObservableExpectation(
                        observable_id=target,
                        baseline_digest=before,
                        expected_delta=ObservableDeltaKind.CHANGED,
                        expected_digest=after,
                    ),
                ),
                adaptive_binding=AdaptiveActionBinding(
                    workflow_id=str(snapshot.workflow_id),
                    workflow_revision=snapshot.workflow_revision,
                    goal_fingerprint=snapshot.state.contract.fingerprint,
                ),
                idempotency_key=f"prepare:{batch_id}",
            )
        )
        batch = handle.inspect().material_actions[handle.actor_id]
        handle.apply(
            MaterialActionToolStarted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                invocation_id="tool-resource",
                tool_name="apply_patch",
                request_digest=request,
                targets=(target,),
                idempotency_key=f"start:{batch_id}",
            )
        )
        batch = handle.inspect().material_actions[handle.actor_id]
        handle.apply(
            MaterialActionToolObserved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                invocation_id="tool-resource",
                receipt=ToolReceipt(
                    receipt_id="post-tool:tool-resource",
                    request_digest=request,
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=hashlib.sha256(b"output").hexdigest(),
                    observations=(
                        ObservableObservation(observable_id=target, current_digest=after),
                    ),
                    duration_milliseconds=duration_milliseconds,
                ),
                idempotency_key=f"observe:{batch_id}",
            )
        )
        batch = handle.inspect().material_actions[handle.actor_id]
        handle.apply(
            MaterialActionResolved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                resolution=MaterialActionResolution.COMPLETED,
                idempotency_key=f"resolve:{batch_id}",
            )
        )

    def _append_generation(
        self,
        store: AdaptiveControlStore,
        snapshot: AdaptiveControlSnapshot,
        *,
        settle_evidence: bool,
    ) -> AdaptiveControlSnapshot:
        """Caller admission 없이 canonical state와 observation 한 generation을 CAS합니다.

        Args:
            store: Exact workflow에 결속된 adaptive store입니다.
            snapshot: Generation 전 canonical workflow snapshot입니다.
            settle_evidence: Current criterion의 executable evidence를 PASS로 추가할지 여부입니다.

        Returns:
            Observation과 store-admitted efficiency가 결속된 next snapshot입니다.
        """
        workflow_revision = snapshot.workflow_revision

        def generation(state: AdaptiveControlState | None) -> AdaptiveControlState:
            """Current state에서 evidence와 canonical observation을 한 번 전진시킵니다.

            Args:
                state: Exact workflow revision의 current adaptive state입니다.

            Returns:
                Caller efficiency 없이 observation 하나를 추가한 candidate state입니다.
            """
            current = self._require_state(state)
            evidence = current.evidence
            if settle_evidence:
                evidence = self._complete_state(current.contract).evidence
            candidate = replace(current, evidence=evidence)
            observation = self._derived_observation(
                candidate,
                generation=len(current.observations) + 1,
                previous=current.observations[-1] if current.observations else None,
            )
            return replace(
                candidate,
                observations=(*current.observations, observation),
            )

        return store.compare_and_update(workflow_revision, generation)

    def test_unadmitted_efficiency_shape_cannot_control_reflection(self) -> None:
        """Structurally valid raw assessment도 public reflection input 권한을 얻지 못합니다."""
        store, initial = self._initialize_incomplete_generation("adaptive-efficiency-forgery")
        generated = self._append_generation(store, initial, settle_evidence=False)
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)

        receipt = generated.receipt()
        self.assertNotIn(
            "efficiency",
            inspect.signature(ReflectionPolicy.decide).parameters,
        )
        unadmitted = ReflectionPolicy().decide(
            receipt.ambiguity,
            receipt.attainment,
            generated.state.observations,
        )
        self.assertEqual(ControlAction.CONTINUE, unadmitted.action)
        self.assertEqual(ControlAction.CHANGE_APPROACH, receipt.decision.action)
        forged_observation = replace(
            self._derived_observation(
                generated.state,
                generation=2,
                previous=generated.state.observations[-1],
            ),
            efficiency_assessment=assessment,
        )
        with self.assertRaisesRegex(
            InvalidAdaptiveControlState,
            "caller-provided efficiency assessment is not store-admitted",
        ):
            store.compare_and_update(
                generated.workflow_revision,
                lambda state: replace(
                    self._require_state(state),
                    observations=(*generated.state.observations, forged_observation),
                ),
            )

    def test_post_first_generation_reflection_requires_current_store_admitted_goal_resource_readback(
        self,
    ) -> None:
        """첫 generation 뒤 reflection은 store가 만든 current goal-resource delta만 사용합니다."""
        store, initial = self._initialize_incomplete_generation("adaptive-efficiency-required")
        generated = self._append_generation(store, initial, settle_evidence=False)

        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        self.assertEqual(
            generated.state.contract.fingerprint,
            assessment.goal_delta.goal_fingerprint,
        )
        self.assertEqual(1, assessment.goal_delta.before.evaluation_revision)
        self.assertEqual(2, assessment.goal_delta.after.evaluation_revision)
        self.assertEqual(EfficiencyStatus.ZERO_PROGRESS, assessment.status)
        self.assertEqual(ControlAction.CHANGE_APPROACH, generated.receipt().decision.action)

    def test_efficiency_admission_derives_goal_delta_from_consecutive_adaptive_snapshots(
        self,
    ) -> None:
        """Goal delta의 exact evidence 집합은 caller count가 아닌 연속 snapshot에서 파생됩니다."""
        store, initial = self._initialize_incomplete_generation("adaptive-efficiency-goal-delta")
        generated = self._append_generation(store, initial, settle_evidence=True)

        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        criterion = generated.state.contract.criteria[0]
        unit = f"{criterion.criterion_id}:{EvidenceKind.PROPERTY_TEST.value}"
        self.assertEqual(frozenset(), assessment.goal_delta.before.settled_evidence_units)
        self.assertEqual(
            frozenset({unit}),
            assessment.goal_delta.after.settled_evidence_units,
        )
        self.assertEqual(frozenset({f"evidence:{unit}"}), assessment.goal_delta.progress_units)
        self.assertFalse(assessment.requires_approach_change)

    def test_missing_runtime_telemetry_is_admitted_as_unavailable_not_zero(self) -> None:
        """Generation 경계에 귀속할 runtime receipt가 없으면 모든 dimension은 unavailable입니다."""
        store, initial = self._initialize_incomplete_generation("adaptive-efficiency-telemetry")
        generated = self._append_generation(store, initial, settle_evidence=True)

        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        self.assertEqual(EfficiencyStatus.UNPROVEN, assessment.status)
        for metric in assessment.resource_delta.metrics:
            self.assertEqual(ResourceTelemetryStatus.UNAVAILABLE, metric.status)
            self.assertIsNone(metric.value)

    def test_material_batch_does_not_claim_total_tool_invocation_resource_authority(
        self,
    ) -> None:
        """Material/evaluator 부분 관측을 전체 generation resource authority로 승격하지 않습니다."""
        handle, _skill_state, store, initial = self._initialize_resource_generation(
            "adaptive-efficiency-resources"
        )
        self._resolve_attributable_material_batch(
            handle,
            initial,
            duration_milliseconds=37,
        )

        generated = self._append_generation(store, initial, settle_evidence=True)
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        assert assessment is not None

        resources = assessment.resource_delta
        self.assertEqual(EfficiencyStatus.UNPROVEN, assessment.status)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.wall_clock_milliseconds.status)
        self.assertIsNone(resources.wall_clock_milliseconds.value)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.tool_invocations.status)
        self.assertIsNone(resources.tool_invocations.value)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.evaluator_generations.status)
        self.assertIsNone(resources.evaluator_generations.value)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.input_tokens.status)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.output_tokens.status)
        for metric in resources.metrics:
            self.assertIsNone(metric.receipt_reference)
            self.assertIsNone(metric.receipt_digest)

    def test_tool_duration_is_not_promoted_to_generation_wall_clock_or_provider_tokens(
        self,
    ) -> None:
        """Per-tool duration 유무와 무관하게 generation wall-clock/token은 unavailable입니다."""
        handle, _skill_state, store, initial = self._initialize_resource_generation(
            "adaptive-efficiency-partial-duration"
        )
        self._resolve_attributable_material_batch(
            handle,
            initial,
            duration_milliseconds=37,
        )

        generated = self._append_generation(store, initial, settle_evidence=True)
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        assert assessment is not None

        resources = assessment.resource_delta
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.wall_clock_milliseconds.status)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.tool_invocations.status)
        self.assertIs(ResourceTelemetryStatus.UNAVAILABLE, resources.evaluator_generations.status)
        self.assertIsNone(resources.wall_clock_milliseconds.value)
        self.assertIsNone(resources.input_tokens.value)
        self.assertIsNone(resources.output_tokens.value)

    def test_stale_material_binding_is_not_admitted_as_current_resource_telemetry(self) -> None:
        """Batch binding 뒤 workflow revision이 바뀌면 current generation 비용을 위조하지 않습니다."""
        handle, skill_state, store, initial = self._initialize_resource_generation(
            "adaptive-efficiency-stale-material"
        )
        self._resolve_attributable_material_batch(handle, initial, duration_milliseconds=37)
        skill_state.update({"sibling": "advanced"})
        current = store.read()

        generated = self._append_generation(store, current, settle_evidence=True)
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        assert assessment is not None

        self.assertEqual(EfficiencyStatus.UNPROVEN, assessment.status)
        self.assertTrue(
            all(
                metric.status is ResourceTelemetryStatus.UNAVAILABLE
                for metric in assessment.resource_delta.metrics
            )
        )

    def test_final_aggregate_rejects_forged_total_resource_authority(
        self,
    ) -> None:
        """Material 부분 receipt가 있어도 total tool authority를 주입하면 final CAS가 거부됩니다."""
        handle, _skill_state, store, initial = self._initialize_resource_generation(
            "adaptive-efficiency-toctou"
        )
        self._resolve_attributable_material_batch(handle, initial, duration_milliseconds=37)
        admitted_batch = handle.inspect().material_actions[handle.actor_id]
        generated = self._append_generation(store, initial, settle_evidence=True)

        validate_efficiency_resource_admission(
            initial.state,
            generated.state,
            session_id=str(handle.session_id),
            actor_id=str(handle.actor_id),
            workflow_id=str(initial.workflow_id),
            workflow_revision=initial.workflow_revision,
            material_batch=admitted_batch,
        )
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        assert assessment is not None
        forged_metric = ResourceMetricDelta(
            status=ResourceTelemetryStatus.VERIFIED,
            value=1,
            source_id="forged-total-tool-counter",
            receipt_reference="forged:tool-count",
            receipt_digest="f" * 64,
        )
        forged_resources = replace(
            assessment.resource_delta,
            tool_invocations=forged_metric,
        )
        forged_assessment = EfficiencyAssessor().assess(
            assessment.goal_delta,
            forged_resources,
        )
        forged_state = replace(
            generated.state,
            observations=(
                *generated.state.observations[:-1],
                replace(
                    generated.state.observations[-1],
                    efficiency_assessment=forged_assessment,
                ),
            ),
        )

        with self.assertRaisesRegex(
            InvalidAdaptiveControlState,
            "current process aggregate",
        ):
            validate_efficiency_resource_admission(
                initial.state,
                forged_state,
                session_id=str(handle.session_id),
                actor_id=str(handle.actor_id),
                workflow_id=str(initial.workflow_id),
                workflow_revision=initial.workflow_revision,
                material_batch=admitted_batch,
            )

    def test_efficiency_admission_uses_non_compensating_current_evidence(self) -> None:
        """같은 latest revision의 PASS는 FAIL receipt를 가려 goal progress를 만들지 못합니다."""
        store, initial = self._initialize_incomplete_generation(
            "adaptive-efficiency-non-compensating"
        )
        passed = self._complete_state(initial.state.contract).evidence[0]
        failed = replace(
            passed,
            status=EvidenceStatus.FAIL,
            reference="pytest:contradictory-latest-failure",
        )

        def contradict(state: AdaptiveControlState | None) -> AdaptiveControlState:
            """같은 revision의 PASS와 FAIL을 함께 가진 generation candidate를 만듭니다.

            Args:
                state: Exact pre-generation adaptive state입니다.

            Returns:
                Contradictory latest evidence와 canonical observation을 가진 candidate입니다.
            """
            current = self._require_state(state)
            candidate = replace(current, evidence=(passed, failed))
            observation = self._derived_observation(candidate)
            return replace(candidate, observations=(observation,))

        generated = store.compare_and_update(initial.workflow_revision, contradict)
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        unit = f"{passed.criterion_id}:{passed.kind.value}"
        self.assertNotIn(unit, assessment.goal_delta.after.settled_evidence_units)
        self.assertIn(unit, assessment.goal_delta.after.failed_evidence_units)
        self.assertEqual(EfficiencyStatus.ZERO_PROGRESS, assessment.status)

    def test_efficiency_admission_tracks_coverage_and_execution_as_exact_goal_surfaces(
        self,
    ) -> None:
        """Coverage threshold와 execution completion은 criterion count와 분리된 progress입니다."""
        store, initial = self._initialize_incomplete_generation("adaptive-efficiency-goal-surfaces")
        complete = self._complete_state(initial.state.contract)
        if complete.coverage is None:
            self.fail("fixture must provide goal coverage")

        def complete_surfaces(state: AdaptiveControlState | None) -> AdaptiveControlState:
            """Coverage와 execution만 전진한 canonical generation candidate를 만듭니다.

            Args:
                state: Exact pre-generation adaptive state입니다.

            Returns:
                Coverage authority와 COMPLETED execution을 가진 candidate state입니다.
            """
            current = self._require_state(state)
            candidate = replace(
                current,
                coverage=complete.coverage,
                execution_status=ExecutionStatus.COMPLETED,
            )
            observation = self._derived_observation(candidate)
            return replace(candidate, observations=(observation,))

        generated = store.compare_and_update(initial.workflow_revision, complete_surfaces)
        assessment = generated.latest_efficiency
        self.assertIsNotNone(assessment)
        self.assertIn("execution:completed", assessment.goal_delta.after.settled_evidence_units)
        self.assertIn(
            "goal-coverage:authority",
            assessment.goal_delta.after.settled_evidence_units,
        )
        self.assertTrue(assessment.goal_delta.has_material_progress)

    def test_efficiency_readback_reference_is_bound_to_exact_snapshot_content(self) -> None:
        """같은 goal/generation이라도 divergent state는 같은 readback reference를 공유하지 않습니다."""
        zero_store, zero_initial = self._initialize_incomplete_generation(
            "adaptive-efficiency-reference-zero"
        )
        progress_store, progress_initial = self._initialize_incomplete_generation(
            "adaptive-efficiency-reference-progress"
        )
        zero = self._append_generation(zero_store, zero_initial, settle_evidence=False)
        progress = self._append_generation(
            progress_store,
            progress_initial,
            settle_evidence=True,
        )
        zero_assessment = zero.latest_efficiency
        progress_assessment = progress.latest_efficiency
        self.assertIsNotNone(zero_assessment)
        self.assertIsNotNone(progress_assessment)

        self.assertNotEqual(
            zero_assessment.goal_delta.after.readback_reference,
            progress_assessment.goal_delta.after.readback_reference,
        )

    def test_coverage_risk_regression_vetoes_other_goal_progress(self) -> None:
        """Coverage risk threshold 회귀는 같은 generation의 새 PASS로 상쇄되지 않습니다."""
        store, initial = self._initialize_incomplete_generation(
            "adaptive-efficiency-coverage-regression"
        )
        complete = self._complete_state(initial.state.contract)
        if complete.coverage is None:
            self.fail("fixture must provide goal coverage")

        def establish_coverage(state: AdaptiveControlState | None) -> AdaptiveControlState:
            """Threshold를 통과한 coverage baseline generation을 만듭니다.

            Args:
                state: Exact pre-generation adaptive state입니다.

            Returns:
                Current coverage와 first observation을 가진 candidate입니다.
            """
            current = self._require_state(state)
            candidate = replace(current, coverage=complete.coverage)
            return replace(candidate, observations=(self._derived_observation(candidate),))

        established = store.compare_and_update(initial.workflow_revision, establish_coverage)
        regressed_coverage = replace(
            complete.coverage,
            reference="review:reward-hacking-regression",
            reward_hacking_risk=0.80,
            evaluation_revision=2,
        )
        passed = complete.evidence[0]

        def regress(state: AdaptiveControlState | None) -> AdaptiveControlState:
            """새 criterion PASS와 coverage risk regression을 같은 generation에 추가합니다.

            Args:
                state: Coverage baseline이 admitted된 current state입니다.

            Returns:
                PASS와 threshold regression을 함께 가진 next candidate입니다.
            """
            current = self._require_state(state)
            candidate = replace(
                current,
                evidence=(passed,),
                coverage=regressed_coverage,
            )
            observation = self._derived_observation(
                candidate,
                generation=2,
                previous=current.observations[-1],
            )
            return replace(candidate, observations=(*current.observations, observation))

        regressed = store.compare_and_update(established.workflow_revision, regress)
        assessment = regressed.latest_efficiency
        self.assertIsNotNone(assessment)
        self.assertIn(
            "goal-coverage:reward-hacking-risk",
            assessment.goal_delta.newly_failed_evidence_units,
        )
        self.assertEqual(EfficiencyStatus.ZERO_PROGRESS, assessment.status)

    def test_json_round_trip_preserves_inventory_authority_and_requirement_lineage(self) -> None:
        """새 domain 전체가 JSON을 거쳐 동일하고 current authority만 COMPLETE를 만듭니다."""
        handle = self._handle("adaptive-round-trip")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        expected = self._complete_state()

        committed = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: expected,
        )
        reopened = AdaptiveControlStore(SkillStateStore(handle, WorkflowId("workflow-a"))).read()
        receipt = reopened.receipt()

        self.assertEqual(expected, committed.state)
        self.assertEqual(expected, reopened.state)
        self.assertEqual(
            expected.contract.criteria[0].approved_requirement_fingerprint,
            reopened.state.contract.criteria[0].approved_requirement_fingerprint,
        )
        self.assertEqual(
            expected.inventory.gaps[0].resolution_lineage,
            reopened.state.inventory.gaps[0].resolution_lineage,
        )
        self.assertEqual(
            expected.inventory.gaps[1].deferral,
            reopened.state.inventory.gaps[1].deferral,
        )
        self.assertTrue(receipt.ambiguity.ready)
        self.assertEqual(0.0, receipt.ambiguity.score)
        self.assertEqual(1.0, receipt.progress)
        self.assertTrue(receipt.decision.achieved)
        self.assertIs(ControlAction.COMPLETE, receipt.decision.action)
        self.assertEqual(42, skill_state.read().skill_state["ticket"])

    def test_public_state_payload_round_trip_uses_the_canonical_store_codec(self) -> None:
        """CLI adapter용 public payload 경계는 private codec을 복제하지 않고 완전 왕복합니다."""
        expected = self._complete_state()

        payload = expected.to_payload()
        restored = AdaptiveControlState.from_payload(payload)

        self.assertEqual(expected, restored)
        self.assertEqual(5, payload["schema_version"])

    def test_schema_v4_without_efficiency_admission_remains_readable(self) -> None:
        """Pre-admission v4 payload는 missing telemetry를 위조하지 않고 legacy state로 읽힙니다."""
        expected = self._complete_state()
        payload = json.loads(json.dumps(expected.to_payload()))
        payload["schema_version"] = 4
        observations = payload["observations"]
        if not isinstance(observations, list):
            self.fail("fixture observations must be a list")
        for observation in observations:
            if not isinstance(observation, dict):
                self.fail("fixture observation must be an object")
            observation.pop("efficiency_assessment")

        restored = AdaptiveControlState.from_payload(payload)

        self.assertEqual(expected, restored)
        self.assertIsNone(restored.observations[-1].efficiency_assessment)

    def test_schema_v2_is_explicitly_rejected_instead_of_silently_defaulted(self) -> None:
        """Authority revision과 recovery epoch가 없는 legacy payload는 명시적 migration 대상입니다."""
        payload = dict(self._complete_state().to_payload())
        payload["schema_version"] = 2

        with self.assertRaisesRegex(
            InvalidAdaptiveControlState,
            "unsupported adaptive control schema version",
        ):
            AdaptiveControlState.from_payload(payload)

    def test_compare_and_replace_payload_uses_canonical_codec_and_exact_cas(self) -> None:
        """Public replace는 typed payload를 decode한 뒤 sibling을 보존하는 exact CAS입니다."""
        handle = self._handle("adaptive-payload-cas")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        expected = self._complete_state()

        committed = store.compare_and_replace_payload(
            skill_state.read().workflow_revision,
            expected.to_payload(),
        )
        skill_state.update({"monitoring": True})

        self.assertEqual(expected, committed.state)
        self.assertEqual(42, skill_state.read().skill_state["ticket"])
        self.assertEqual(True, skill_state.read().skill_state["monitoring"])
        with self.assertRaises(SkillStateConflict):
            store.compare_and_replace_payload(
                committed.workflow_revision,
                expected.to_payload(),
            )

    def test_receipt_evidence_is_deterministic_and_bound_to_exact_snapshot(self) -> None:
        """Phase evidence digest는 exact workflow revision과 decision 필드에서 결정됩니다."""
        handle = self._handle("adaptive-evidence")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        snapshot = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: self._complete_state(),
        )

        first = snapshot.receipt()
        second = store.receipt()
        evidence = first.to_evidence()

        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertEqual(evidence, second.to_evidence())
        self.assertEqual("workflow-a", evidence["workflow_id"])
        self.assertEqual(snapshot.workflow_revision, evidence["workflow_revision"])
        self.assertEqual(snapshot.state.contract.fingerprint, evidence["goal_fingerprint"])
        self.assertEqual(ControlAction.COMPLETE.value, evidence["action"])
        self.assertIs(True, evidence["achieved"])
        self.assertIs(True, evidence["ambiguity_ready"])
        self.assertEqual(1.0, evidence["progress"])
        self.assertEqual(first, store.verify_evidence(evidence))

    def test_forged_or_stale_evidence_is_never_trusted_by_nominal_fields_or_digest(self) -> None:
        """재계산된 digest와 valid enum 모양도 current snapshot readback을 대신하지 못합니다."""
        handle = self._handle("adaptive-forgery")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: AdaptiveControlState.empty(
                self._contract(),
                self._inventory(self._contract()),
            ),
        )
        actual = dict(current.receipt().to_evidence())
        forged = self._redigest({
            **actual,
            "action": ControlAction.COMPLETE.value,
            "achieved": True,
            "progress": 1.0,
        })

        with self.assertRaises(InvalidAdaptiveControlEvidence):
            store.verify_evidence(forged)

        valid_before_update = current.receipt().to_evidence()
        store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                execution_status=ExecutionStatus.FAILED,
            ),
        )
        with self.assertRaises(InvalidAdaptiveControlEvidence):
            store.verify_evidence(valid_before_update)

    def test_generic_skill_state_mutation_cannot_tamper_adaptive_provenance(self) -> None:
        """Typed adaptive store 밖의 generic mutation은 persisted lineage를 바꾸지 못합니다."""
        handle = self._handle("adaptive-lineage-tamper")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        store.update(lambda _current: self._complete_state())

        def tamper(current: dict[str, object] | object) -> dict[str, object]:
            """Fixture의 adaptive lineage를 generic mutation처럼 위조합니다.

            Args:
                current: Test lambda가 store의 read-only current를 복사한 mutable object입니다.

            Returns:
                Coverage issuer, subject, delegation을 위조한 replacement object입니다.

            Raises:
                TypeError: Fixture 입력이 mutable dictionary가 아니면 발생합니다.
            """
            if not isinstance(current, dict):
                raise TypeError("fixture requires a mutable JSON copy")
            copied = json.loads(json.dumps(current))
            coverage = copied["adaptive_control"]["coverage"]
            coverage["lineage"]["issuer_id"] = "implementation-agent"
            coverage["lineage"]["subject_id"] = "implementation-agent"
            coverage["lineage"]["delegation_id"] = None
            return copied

        with self.assertRaises(SkillStateReservedNamespaceError):
            skill_state.update(lambda current: tamper(dict(current)))

        self.assertEqual(self._complete_state(), store.read().state)

    def test_compare_and_update_rejects_stale_workflow_revision(self) -> None:
        """Explicit adaptive CAS는 sibling commit 뒤 stale 원본을 재시도하지 않습니다."""
        handle = self._handle("adaptive-cas")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        initial = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: self._complete_state(),
        )
        skill_state.update({"monitoring": True})

        with self.assertRaises(SkillStateConflict):
            store.compare_and_update(
                initial.workflow_revision,
                lambda current: replace(
                    self._require_state(current),
                    execution_status=ExecutionStatus.FAILED,
                ),
            )

        self.assertIs(ExecutionStatus.COMPLETED, store.read().state.execution_status)

    def test_same_namespace_is_isolated_by_current_workflow_and_session(self) -> None:
        """동일 namespace와 workflow ID는 bound workflow/session 밖으로 fallback하지 않습니다."""
        first_handle = self._handle("adaptive-session-a")
        _first_skill, first = self._store(first_handle, "shared-workflow", ticket=1)
        _second_skill, second = self._store(first_handle, "workflow-b", ticket=2)
        other_handle = self._handle("adaptive-session-b")
        _other_skill, other = self._store(other_handle, "shared-workflow", ticket=3)
        first_contract = self._contract("first")
        second_contract = self._contract("second")
        other_contract = self._contract("other")

        first.update(
            lambda _current: AdaptiveControlState.empty(
                first_contract,
                self._inventory(first_contract),
            )
        )
        second.update(
            lambda _current: AdaptiveControlState.empty(
                second_contract,
                self._inventory(second_contract),
            )
        )
        other.update(
            lambda _current: AdaptiveControlState.empty(
                other_contract,
                self._inventory(other_contract),
            )
        )

        self.assertEqual("first 목표를 완수한다", first.read().state.contract.goal)
        self.assertEqual("second 목표를 완수한다", second.read().state.contract.goal)
        self.assertEqual("other 목표를 완수한다", other.read().state.contract.goal)

    def test_goal_override_discards_old_authority_observations_and_completion(self) -> None:
        """Intent revision 변경은 이전 goal authority와 실행 완료를 원자적으로 폐기합니다."""
        handle = self._handle("adaptive-override")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        previous = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: self._complete_state(),
        )
        replacement = self._contract("replacement", intent_revision=2)
        inventory = self._inventory(replacement)
        decision = self._goal_override_decision(
            previous.state.contract,
            replacement,
            workflow_id="workflow-a",
        )

        overridden = store.override_goal(
            previous.workflow_revision,
            replacement,
            inventory=inventory,
            user_decisions=(decision,),
        )

        self.assertEqual(replacement, overridden.state.contract)
        self.assertEqual(inventory, overridden.state.inventory)
        self.assertEqual((), overridden.state.evidence)
        self.assertIsNone(overridden.state.coverage)
        self.assertEqual((), overridden.state.observations)
        self.assertEqual((decision,), overridden.state.user_decisions)
        self.assertIs(ExecutionStatus.INCOMPLETE, overridden.state.execution_status)
        self.assertFalse(overridden.receipt().decision.achieved)
        self.assertIs(ControlAction.CONTINUE, overridden.receipt().decision.action)

    def test_goal_changing_general_mutation_cannot_carry_authority_forward(self) -> None:
        """Goal 변경과 authority 폐기는 명시적 override_goal 경계에서만 가능합니다."""
        handle = self._handle("adaptive-normalize")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        previous = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _current: self._complete_state(),
        )
        replacement = self._complete_state(self._contract("replacement", intent_revision=2))

        with self.assertRaises(InvalidAdaptiveControlState):
            store.compare_and_update(
                previous.workflow_revision,
                lambda _state: replacement,
            )

        self.assertEqual(previous.state, store.read().state)

    def test_same_goal_cannot_delete_evidence_coverage_or_observation_history(self) -> None:
        """Complete replacement도 same-goal authority와 reflection history를 삭제하지 못합니다."""
        handle = self._handle("adaptive-no-silent-delete")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: self._complete_state(),
        )
        candidates = (
            replace(current.state, evidence=()),
            replace(current.state, coverage=None),
            replace(current.state, observations=()),
        )

        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(InvalidAdaptiveControlState):
                store.compare_and_update(
                    current.workflow_revision,
                    lambda _state, selected=candidate: selected,
                )

        self.assertEqual(current.state, store.read().state)

    def test_blocking_user_gap_can_transition_to_explicit_deferral(self) -> None:
        """USER deferral은 같은 gap의 blocking policy만 원자적으로 낮출 수 있습니다."""
        contract = self._contract()
        deferred = self._deferred_gap(contract)
        open_gap = replace(deferred, blocking=True, deferral=None)
        previous = AdaptiveControlState.empty(
            contract,
            self._inventory(contract, gaps=(open_gap,)),
        )
        candidate = replace(
            previous,
            inventory=replace(previous.inventory, gaps=(deferred,)),
        )

        validate_adaptive_control_transition(previous, candidate)
        with self.assertRaisesRegex(
            InvalidAdaptiveControlState,
            "blocking policy is immutable",
        ):
            validate_adaptive_control_transition(candidate, previous)

    def test_evidence_supersession_is_append_only_and_revision_monotonic(self) -> None:
        """기존 FAIL은 보존하고 정확히 다음 evaluation revision의 PASS만 effective합니다."""
        handle = self._handle("adaptive-evidence-revision")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        complete = self._complete_state()
        failed = replace(
            complete.evidence[0],
            status=EvidenceStatus.FAIL,
            evaluation_revision=1,
        )
        initial_state = replace(complete, evidence=(failed,), observations=())
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: initial_state,
        )
        passed = replace(
            failed,
            status=EvidenceStatus.PASS,
            reference="pytest:property-contract:rerun",
            evaluation_revision=2,
        )

        superseded = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                evidence=self._require_state(state).evidence + (passed,),
            ),
        )

        self.assertEqual((failed, passed), superseded.state.evidence)
        self.assertTrue(superseded.receipt().attainment.achieved)
        for invalid in (
            (passed,),
            superseded.state.evidence
            + (replace(passed, reference="same-revision", evaluation_revision=2),),
            superseded.state.evidence
            + (replace(passed, reference="skipped-revision", evaluation_revision=4),),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InvalidAdaptiveControlState):
                store.compare_and_update(
                    superseded.workflow_revision,
                    lambda state, selected=invalid: replace(
                        self._require_state(state),
                        evidence=selected,
                    ),
                )

    def test_coverage_supersession_requires_exact_next_revision(self) -> None:
        """Goal coverage는 None/same/lower/jump replacement가 아니라 +1 재평가만 허용합니다."""
        handle = self._handle("adaptive-coverage-revision")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: replace(self._complete_state(), observations=()),
        )
        assert current.state.coverage is not None
        next_coverage = replace(
            current.state.coverage,
            reference="review:independent-evaluator:2",
            evaluation_revision=2,
        )
        updated = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(self._require_state(state), coverage=next_coverage),
        )

        updated_coverage = updated.state.coverage
        self.assertIsNotNone(updated_coverage)
        assert updated_coverage is not None
        self.assertEqual(2, updated_coverage.evaluation_revision)
        for replacement_coverage in (
            None,
            replace(next_coverage, reference="same-revision"),
            replace(next_coverage, reference="skipped-revision", evaluation_revision=4),
        ):
            with (
                self.subTest(coverage=replacement_coverage),
                self.assertRaises(InvalidAdaptiveControlState),
            ):
                store.compare_and_update(
                    updated.workflow_revision,
                    lambda state, selected=replacement_coverage: replace(
                        self._require_state(state),
                        coverage=selected,
                    ),
                )

    def test_gap_inventory_cannot_shrink_or_reopen_a_settled_gap(self) -> None:
        """Same intent ledger는 section/gap을 잃지 않고 OPEN에서 resolution으로만 전진합니다."""
        handle = self._handle("adaptive-gap-monotonic")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        contract = self._contract()
        source_revision = f"repo:head-{contract.intent_revision}"
        open_gap = replace(
            self._resolved_gap(contract, source_revision),
            resolution=GapResolution.OPEN,
            evidence_reference=None,
            resolution_lineage=None,
        )
        initial = AdaptiveControlState.empty(
            contract,
            self._inventory(contract, gaps=(open_gap,)),
        )
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: initial,
        )
        resolved = open_gap.resolve(
            GapResolution.REPOSITORY_FACT,
            "scripts/agent_harness/skill_state_store.py",
            self._lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source_revision,
            ),
        )
        advanced = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                inventory=replace(self._require_state(state).inventory, gaps=(resolved,)),
            ),
        )

        invalid_inventories = (
            replace(advanced.state.inventory, gaps=()),
            replace(
                advanced.state.inventory,
                assessed_sections=frozenset({RequirementSection.VERIFICATION}),
            ),
            replace(advanced.state.inventory, gaps=(open_gap,)),
        )
        for inventory in invalid_inventories:
            with self.subTest(inventory=inventory), self.assertRaises(InvalidAdaptiveControlState):
                store.compare_and_update(
                    advanced.workflow_revision,
                    lambda state, selected=inventory: replace(
                        self._require_state(state),
                        inventory=selected,
                    ),
                )

    def test_authoritative_blocker_is_terminal_and_cannot_reopen_or_become_fact(self) -> None:
        """OPEN→BLOCKER는 허용하지만 같은 goal에서 OPEN/fact로 되돌리는 mutation은 거부합니다."""
        handle = self._handle("adaptive-gap-blocker")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        contract = self._contract()
        source_revision = f"repo:head-{contract.intent_revision}"
        open_gap = replace(
            self._resolved_gap(contract, source_revision),
            resolution=GapResolution.OPEN,
            evidence_reference=None,
            resolution_lineage=None,
        )
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: AdaptiveControlState.empty(
                contract,
                self._inventory(contract, gaps=(open_gap,)),
            ),
        )
        blocker = open_gap.mark_blocked(
            "repository:terminal-blocker",
            self._lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source_revision,
            ),
        )
        blocked = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                inventory=replace(self._require_state(state).inventory, gaps=(blocker,)),
            ),
        )

        self.assertIs(ControlAction.BLOCKED, blocked.receipt().decision.action)
        resolved = open_gap.resolve(
            GapResolution.REPOSITORY_FACT,
            "repository:later-fact",
            self._lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source_revision,
            ),
        )
        for next_gap in (open_gap, resolved):
            with self.subTest(next_gap=next_gap), self.assertRaises(InvalidAdaptiveControlState):
                store.compare_and_update(
                    blocked.workflow_revision,
                    lambda state, selected=next_gap: replace(
                        self._require_state(state),
                        inventory=replace(
                            self._require_state(state).inventory,
                            gaps=(selected,),
                        ),
                    ),
                )

    def test_blocker_requires_an_existing_open_gap_and_current_source_basis(self) -> None:
        """Fresh blocker import와 stale-source terminalization은 typed transition을 우회합니다."""
        handle = self._handle("adaptive-gap-blocker-provenance")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        contract = self._contract()
        source_revision = f"repo:head-{contract.intent_revision}"
        open_gap = replace(
            self._resolved_gap(contract, source_revision),
            resolution=GapResolution.OPEN,
            evidence_reference=None,
            resolution_lineage=None,
        )
        current_blocker = open_gap.mark_blocked(
            "repository:terminal-blocker",
            self._lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision=source_revision,
            ),
        )
        with self.assertRaises(InvalidAdaptiveControlState):
            store.compare_and_update(
                skill_state.read().workflow_revision,
                lambda _state: AdaptiveControlState.empty(
                    contract,
                    self._inventory(contract, gaps=(current_blocker,)),
                ),
            )

        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: AdaptiveControlState.empty(
                contract,
                self._inventory(contract, gaps=(open_gap,)),
            ),
        )
        stale_blocker = open_gap.mark_blocked(
            "repository:stale-terminal-blocker",
            self._lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision="repo:old-head",
            ),
        )
        with self.assertRaises(InvalidAdaptiveControlState):
            store.compare_and_update(
                current.workflow_revision,
                lambda state: replace(
                    self._require_state(state),
                    inventory=replace(
                        self._require_state(state).inventory,
                        gaps=(stale_blocker,),
                    ),
                ),
            )

    def test_observation_is_single_append_with_canonical_derived_fields(self) -> None:
        """Caller가 generation, progress, output 또는 material_change를 자가 증명할 수 없습니다."""
        handle = self._handle("adaptive-observation-derived")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        initial = replace(self._complete_state(), observations=())
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: initial,
        )
        observation = self._derived_observation(current.state)
        appended = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                observations=(observation,),
            ),
        )
        second = self._derived_observation(
            appended.state,
            generation=2,
            previous=observation,
        )
        invalid_histories = (
            (),
            (observation, replace(second, generation=3)),
            (observation, replace(second, progress=0.123)),
            (observation, replace(second, output_fingerprint="forged")),
            (observation, replace(second, material_change=True)),
            (observation, second, replace(second, generation=3)),
        )

        for observations in invalid_histories:
            with (
                self.subTest(observations=observations),
                self.assertRaises(InvalidAdaptiveControlState),
            ):
                store.compare_and_update(
                    appended.workflow_revision,
                    lambda state, selected=observations: replace(
                        self._require_state(state),
                        observations=selected,
                    ),
                )

    def test_terminal_execution_status_cannot_toggle_or_rollback(self) -> None:
        """FAILED/COMPLETED lifecycle은 같은 goal에서 INCOMPLETE나 서로로 되돌릴 수 없습니다."""
        for terminal in (ExecutionStatus.FAILED, ExecutionStatus.COMPLETED):
            with self.subTest(terminal=terminal):
                handle = self._handle(f"adaptive-terminal-{terminal.value}")
                skill_state, store = self._store(handle, "workflow-a", ticket=42)
                initial = AdaptiveControlState.empty(
                    self._contract(),
                    self._inventory(self._contract()),
                )
                current = store.compare_and_update(
                    skill_state.read().workflow_revision,
                    lambda _state, selected=initial: selected,
                )
                terminal_snapshot = store.compare_and_update(
                    current.workflow_revision,
                    lambda state, selected=terminal: replace(
                        self._require_state(state),
                        execution_status=selected,
                    ),
                )
                for rollback in (
                    ExecutionStatus.INCOMPLETE,
                    ExecutionStatus.COMPLETED
                    if terminal is ExecutionStatus.FAILED
                    else ExecutionStatus.FAILED,
                ):
                    with (
                        self.subTest(terminal=terminal, rollback=rollback),
                        self.assertRaises(InvalidAdaptiveControlState),
                    ):
                        store.compare_and_update(
                            terminal_snapshot.workflow_revision,
                            lambda state, selected=rollback: replace(
                                self._require_state(state),
                                execution_status=selected,
                            ),
                        )

    def test_recovery_epoch_requires_a_prior_recovery_decision(self) -> None:
        """Canonical output 변화만으로 CONTINUE 상태에서 recovery epoch를 만들 수 없습니다."""
        handle = self._handle("adaptive-unapproved-recovery-epoch")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        initial = AdaptiveControlState.empty(self._contract(), self._inventory(self._contract()))
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: initial,
        )
        first = self._derived_observation(current.state)
        first_snapshot = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(self._require_state(state), observations=(first,)),
        )
        evidence = self._complete_state(first_snapshot.state.contract).evidence[0]
        changed_state = replace(first_snapshot.state, evidence=(evidence,))
        unapproved = self._derived_observation(
            changed_state,
            generation=2,
            recovery_epoch=1,
            previous=first,
        )
        with self.assertRaises(InvalidAdaptiveControlState):
            store.compare_and_update(
                first_snapshot.workflow_revision,
                lambda state: replace(
                    self._require_state(state),
                    evidence=(evidence,),
                    observations=(first, unapproved),
                ),
            )

    def test_recovery_epoch_advances_once_after_recovery_decision_and_material_transition(
        self,
    ) -> None:
        """반복 원인이 만든 CHANGE_APPROACH 뒤 실제 authority 변화 한 번만 새 epoch를 엽니다."""
        handle = self._handle("adaptive-authorized-recovery-epoch")
        skill_state, store = self._store(handle, "workflow-a", ticket=42)
        contract = self._contract()
        initial = AdaptiveControlState.empty(contract, self._inventory(contract))
        current = store.compare_and_update(
            skill_state.read().workflow_revision,
            lambda _state: initial,
        )
        first = self._derived_observation(
            current.state,
            root_causes=("introduced-state-bypass",),
        )
        first_snapshot = store.compare_and_update(
            current.workflow_revision,
            lambda state: replace(self._require_state(state), observations=(first,)),
        )
        admitted_first = first_snapshot.state.observations[0]
        evidence = self._complete_state(contract).evidence[0]
        changed_state = replace(first_snapshot.state, evidence=(evidence,))
        repeated = self._derived_observation(
            changed_state,
            generation=2,
            previous=admitted_first,
            root_causes=("introduced-state-bypass",),
        )
        repeated_snapshot = store.compare_and_update(
            first_snapshot.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                evidence=(evidence,),
                observations=(admitted_first, repeated),
            ),
        )
        admitted_repeated = repeated_snapshot.state.observations[1]
        self.assertIs(ControlAction.CHANGE_APPROACH, repeated_snapshot.receipt().decision.action)

        coverage = self._complete_state(contract).coverage
        if coverage is None:
            self.fail("fixture must provide goal coverage")
        recovered_state = replace(repeated_snapshot.state, coverage=coverage)
        recovered = self._derived_observation(
            recovered_state,
            generation=3,
            recovery_epoch=1,
            previous=admitted_repeated,
        )
        recovered_snapshot = store.compare_and_update(
            repeated_snapshot.workflow_revision,
            lambda state: replace(
                self._require_state(state),
                coverage=coverage,
                observations=(admitted_first, admitted_repeated, recovered),
            ),
        )

        self.assertTrue(recovered.material_change)
        self.assertEqual(1, recovered_snapshot.state.observations[-1].recovery_epoch)
        self.assertIs(ControlAction.CONTINUE, recovered_snapshot.receipt().decision.action)

    def test_state_rejects_evidence_kind_not_declared_by_criterion(self) -> None:
        """Acceptance 밖의 stray negative receipt는 COMPLETE state에 공존할 수 없습니다."""
        state = self._complete_state()
        stray = CriterionEvidence(
            goal_fingerprint=state.contract.fingerprint,
            criterion_id=state.contract.criteria[0].criterion_id,
            kind=EvidenceKind.EXAMPLE_TEST,
            authority=EvidenceAuthority.EXECUTABLE,
            status=EvidenceStatus.FAIL,
            reference="pytest:undeclared-surface",
            lineage=self._lineage(EvidenceAuthority.EXECUTABLE),
        )

        with self.assertRaisesRegex(ValueError, "undeclared evidence kind"):
            replace(state, evidence=state.evidence + (stray,))

    def test_unready_inventory_never_issues_false_complete_receipt(self) -> None:
        """Goal evidence가 완전해도 unassessed inventory는 COMPLETE receipt를 금지합니다."""
        handle = self._handle("adaptive-false-complete")
        _skill_state, store = self._store(handle, "workflow-a", ticket=42)
        state = self._complete_state()
        unassessed = replace(
            state.inventory,
            assessed_sections=frozenset(gap.section for gap in state.inventory.gaps),
        )

        committed = store.update(
            lambda _current: replace(
                state,
                inventory=unassessed,
                observations=(),
            )
        )
        receipt = committed.receipt()

        self.assertTrue(receipt.attainment.achieved)
        self.assertFalse(receipt.decision.achieved)
        self.assertFalse(receipt.ambiguity.ready)
        self.assertIs(ControlAction.BLOCKED, receipt.decision.action)
        self.assertIsNot(ControlAction.COMPLETE, receipt.decision.action)

    def test_missing_adaptive_namespace_fails_without_cross_workflow_fallback(self) -> None:
        """현재 workflow에 adaptive snapshot이 없으면 다른 workflow를 검색하지 않습니다."""
        handle = self._handle("adaptive-missing")
        _source_skill, source = self._store(handle, "workflow-a", ticket=1)
        _empty_skill, empty = self._store(handle, "workflow-b", ticket=2)
        contract = self._contract()
        source.update(
            lambda _current: AdaptiveControlState.empty(contract, self._inventory(contract))
        )

        with self.assertRaises(AdaptiveControlStateMissing):
            empty.read()
