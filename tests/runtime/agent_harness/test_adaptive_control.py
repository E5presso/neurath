"""적응형 제어 계약이 질문, 목표 판정, 반성의 권한을 분리하는지 검증합니다."""

import hashlib
import inspect
import unittest
from dataclasses import replace

from scripts.agent_harness.adaptive_control import (
    AmbiguityAssessment,
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
    GoalAttainment,
    GoalContract,
    GoalCoverage,
    IterationObservation,
    OracleOwner,
    ReflectionPolicy,
    RequirementSection,
    UserDeferral,
    approved_requirement_fingerprint,
    assess_ambiguity,
    assess_goal_attainment,
    reflection_scope,
    render_socratic_question,
)
from scripts.agent_harness.efficiency_assessment import (
    AuthoritativeResourceDelta,
    EfficiencyAssessment,
    EfficiencyAssessor,
    GoalAttainmentReadback,
    ResourceMetricDelta,
    ResourceTelemetryStatus,
    VerifiedGoalAttainmentDelta,
)


class AdaptiveControlTest(unittest.TestCase):
    """하나의 순수 계약이 self-score와 test green의 과잉 권한을 막는지 검증합니다."""

    def criterion(
        self,
        criterion_id: str,
        *required: EvidenceKind,
        hard: bool = True,
    ) -> CriterionSpec:
        """짧은 acceptance fixture를 만듭니다."""
        return CriterionSpec(
            criterion_id=criterion_id,
            description=f"{criterion_id} 결과가 관찰된다",
            source_requirement_id=f"REQ-{criterion_id}",
            approved_requirement_fingerprint=hashlib.sha256(
                f"approved:{criterion_id}".encode()
            ).hexdigest(),
            observer="사용자",
            precondition="승인된 요구사항이 현재 revision에 고정되어 있다",
            stimulus="요청한 동작을 실행한다",
            expected_outcome=f"{criterion_id} 결과가 실제 경계에서 관찰된다",
            oracle_owner=(
                OracleOwner.INDEPENDENT_EVALUATOR
                if EvidenceKind.INDEPENDENT_SEMANTIC in required
                else OracleOwner.USER
                if EvidenceKind.USER_ACCEPTANCE in required
                else OracleOwner.PRIMARY_SOURCE
                if EvidenceKind.SOURCE_READBACK in required
                else OracleOwner.EXECUTABLE
            ),
            hard=hard,
            required_evidence=frozenset(required),
        )

    def contract(
        self,
        *criteria: CriterionSpec,
        intent_revision: int = 1,
        source_revision: str = "approved-plan:1",
    ) -> GoalContract:
        """고정된 목표와 전달된 acceptance criteria로 snapshot을 만듭니다."""
        goal = "사용자의 현재 요청을 완수한다"
        constraints = ("기존 SessionKernel을 재사용한다",)
        non_goals = ("별도 Agent OS를 만들지 않는다",)
        requirement = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            intent_revision,
            source_revision,
        )
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset(item.source_requirement_id for item in criteria),
            criteria=tuple(
                replace(item, approved_requirement_fingerprint=requirement) for item in criteria
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )

    def lineage(
        self,
        authority: EvidenceAuthority,
        *,
        intent_revision: int = 1,
        source_revision: str = "approved-plan:1",
        issuer_id: str | None = None,
        subject_id: str = "implementation-agent",
    ) -> AuthorityReceipt:
        """Authority label을 검증 가능한 issuer와 revision receipt로 결속합니다."""
        selected_issuer = (
            issuer_id
            or {
                EvidenceAuthority.EXECUTABLE: "test-runner",
                EvidenceAuthority.INDEPENDENT_EVALUATOR: "independent-reviewer",
                EvidenceAuthority.USER: "user",
                EvidenceAuthority.PRIMARY_SOURCE: "repository",
                EvidenceAuthority.SAME_CONTEXT: subject_id,
            }[authority]
        )
        receipt_body = (
            f"{authority}:{selected_issuer}:{subject_id}:{intent_revision}:{source_revision}"
        )
        return AuthorityReceipt(
            authority=authority,
            issuer_id=selected_issuer,
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

    def evidence(
        self,
        contract: GoalContract,
        criterion_id: str,
        kind: EvidenceKind,
        authority: EvidenceAuthority,
        status: EvidenceStatus = EvidenceStatus.PASS,
        evaluation_revision: int = 1,
    ) -> CriterionEvidence:
        """현재 goal fingerprint에 결속된 evidence receipt를 만듭니다."""
        return CriterionEvidence(
            goal_fingerprint=contract.fingerprint,
            criterion_id=criterion_id,
            kind=kind,
            authority=authority,
            status=status,
            reference=f"receipt:{criterion_id}:{kind}",
            lineage=self.lineage(
                authority,
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
            ),
            evaluation_revision=evaluation_revision,
        )

    def coverage(
        self,
        contract: GoalContract,
        *,
        evaluation_revision: int = 1,
    ) -> GoalCoverage:
        """현재 acceptance 전체를 독립적으로 대조한 coverage를 만듭니다."""
        return GoalCoverage(
            goal_fingerprint=contract.fingerprint,
            criterion_ids=frozenset(item.criterion_id for item in contract.criteria),
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            status=EvidenceStatus.PASS,
            reference="cold-read:current-goal",
            goal_alignment=1.0,
            semantic_drift=0.0,
            uncertainty=0.0,
            reward_hacking_risk=0.0,
            lineage=self.lineage(
                EvidenceAuthority.INDEPENDENT_EVALUATOR,
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
            ),
            evaluation_revision=evaluation_revision,
        )

    def open_gap(
        self,
        gap_id: str,
        authority: GapAuthority,
        *,
        dependency_rank: int,
        weight: float,
        blocking: bool = True,
        reversible: bool = False,
        scope_local: bool = False,
        intent_revision: int = 1,
        deferral: UserDeferral | None = None,
    ) -> ClarificationGap:
        """Socratic routing에 필요한 material gap fixture를 만듭니다."""
        return ClarificationGap(
            gap_id=gap_id,
            section=RequirementSection.CONSTRAINT,
            authority=authority,
            dependency_rank=dependency_rank,
            weight=weight,
            blocking=blocking,
            reversible=reversible,
            scope_local=scope_local,
            context="현재 구현 결과를 바꾸는 결정이 남아 있다",
            question="어느 경계를 선택해야 하나요?",
            consequence="선택에 따라 소유권과 acceptance가 달라진다",
            recommendation="현재 근거상 더 작은 경계를 권장한다",
            recommendation_rationale="작은 경계가 reversible하고 부작용이 적다",
            intent_revision=intent_revision,
            deferral=deferral,
        )

    def inventory(
        self,
        *gaps: ClarificationGap,
        intent_revision: int = 1,
        source_revision: str = "repo:head-1",
        assessed: bool = True,
    ) -> GapInventory:
        """미작성 ledger와 현재 revision에서 확인된 빈 ledger를 구분합니다."""
        return GapInventory(
            intent_revision=intent_revision,
            source_revision=source_revision,
            assessed_sections=(frozenset(RequirementSection) if assessed else frozenset()),
            gaps=gaps,
        )

    def test_nontrivial_goal_rejects_empty_acceptance_criteria(self) -> None:
        """빈 acceptance 집합은 vacuous success가 아니라 계약 오류입니다."""
        with self.assertRaises(ValueError):
            self.contract()

    def test_nontrivial_goal_requires_at_least_one_hard_criterion(self) -> None:
        """Soft progress만 있는 계약은 formal completion의 기준이 될 수 없습니다."""
        with self.assertRaises(ValueError):
            self.contract(
                self.criterion("OPTIONAL", EvidenceKind.EXAMPLE_TEST, hard=False),
            )

    def test_criterion_requires_approved_requirement_and_observable_lineage(self) -> None:
        """Implementation과 함께 발명한 자유 문장은 acceptance가 될 수 없습니다."""
        with self.assertRaises(ValueError):
            CriterionSpec(
                criterion_id="AC1",
                description="helper class를 추가한다",
                source_requirement_id="",
                approved_requirement_fingerprint="",
                observer="",
                precondition="",
                stimulus="",
                expected_outcome="",
                oracle_owner=OracleOwner.EXECUTABLE,
                hard=True,
                required_evidence=frozenset({EvidenceKind.EXAMPLE_TEST}),
            )

    def test_contract_rejects_criterion_from_another_approved_requirement(self) -> None:
        """Shape가 맞는 임의 digest는 current north-star approval을 대신하지 못합니다."""
        criterion = self.criterion("AC1", EvidenceKind.EXAMPLE_TEST)

        with self.assertRaises(ValueError):
            GoalContract(
                goal="사용자의 현재 요청을 완수한다",
                constraints=("기존 SessionKernel을 재사용한다",),
                requirement_ids=frozenset({criterion.source_requirement_id}),
                criteria=(criterion,),
                non_goals=("별도 Agent OS를 만들지 않는다",),
                intent_revision=1,
                source_revision="approved-plan:1",
            )

    def test_requirement_ledger_is_nonempty_closed_and_fully_covered(self) -> None:
        """명시된 requirement ledger만 criterion provenance의 closed universe입니다."""
        criterion = self.criterion("AC1", EvidenceKind.EXAMPLE_TEST)
        requirement = approved_requirement_fingerprint(
            "사용자의 현재 요청을 완수한다",
            ("기존 SessionKernel을 재사용한다",),
            ("별도 Agent OS를 만들지 않는다",),
            1,
            "approved-plan:1",
        )
        bound = replace(criterion, approved_requirement_fingerprint=requirement)

        for requirement_ids in (
            frozenset(),
            frozenset({"REQ-another"}),
            frozenset({criterion.source_requirement_id, "REQ-uncovered"}),
        ):
            with self.subTest(requirement_ids=requirement_ids), self.assertRaises(ValueError):
                GoalContract(
                    goal="사용자의 현재 요청을 완수한다",
                    constraints=("기존 SessionKernel을 재사용한다",),
                    requirement_ids=requirement_ids,
                    criteria=(bound,),
                    non_goals=("별도 Agent OS를 만들지 않는다",),
                    intent_revision=1,
                    source_revision="approved-plan:1",
                )

    def test_requirement_ledger_participates_in_goal_fingerprint(self) -> None:
        """Requirement provenance 경계가 달라지면 기존 evidence identity도 달라집니다."""
        first = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        second_criterion = replace(
            first.criteria[0],
            source_requirement_id="REQ-RENAMED",
        )
        second = replace(
            first,
            requirement_ids=frozenset({"REQ-RENAMED"}),
            criteria=(second_criterion,),
        )

        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_unassessed_inventory_is_distinct_from_assessed_empty_inventory(self) -> None:
        """미작성 gap ledger는 현재 revision에서 확인된 빈 ledger로 간주되지 않습니다."""
        unassessed = assess_ambiguity(self.inventory(assessed=False))
        assessed = assess_ambiguity(self.inventory())

        self.assertFalse(unassessed.assessment_complete)
        self.assertFalse(unassessed.ready)
        self.assertEqual(ControlAction.BLOCKED, unassessed.action)
        self.assertTrue(assessed.assessment_complete)
        self.assertTrue(assessed.ready)

    def test_every_requirement_section_must_be_assessed_before_intent_is_ready(self) -> None:
        """한 section이라도 생략한 inventory는 빈 gap을 이용해 ready로 우회하지 못합니다."""
        for omitted in RequirementSection:
            with self.subTest(omitted=omitted):
                inventory = GapInventory(
                    intent_revision=1,
                    source_revision="repo:head-1",
                    assessed_sections=frozenset(RequirementSection) - {omitted},
                    gaps=(),
                )

                assessment = assess_ambiguity(inventory)

                self.assertFalse(assessment.assessment_complete)
                self.assertFalse(assessment.ready)
                self.assertEqual(ControlAction.BLOCKED, assessment.action)

        complete = assess_ambiguity(self.inventory())
        self.assertTrue(complete.assessment_complete)
        self.assertTrue(complete.ready)

    def test_gap_section_must_belong_to_the_assessed_inventory_sections(self) -> None:
        """평가하지 않은 requirement section의 gap을 inventory에 섞을 수 없습니다."""
        gap = self.open_gap(
            "G-unassessed-section",
            GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=1.0,
        )

        with self.assertRaises(ValueError):
            GapInventory(
                intent_revision=1,
                source_revision="repo:head-1",
                assessed_sections=frozenset(RequirementSection) - {RequirementSection.CONSTRAINT},
                gaps=(gap,),
            )

    def test_gap_must_belong_to_the_inventory_intent_revision(self) -> None:
        """다른 user intent에서 작성된 gap은 current inventory에 섞일 수 없습니다."""
        gap = self.open_gap(
            "G-old-intent",
            GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=1.0,
            intent_revision=1,
        )

        with self.assertRaises(ValueError):
            GapInventory(
                intent_revision=2,
                source_revision="repo:head-2",
                assessed_sections=frozenset(RequirementSection),
                gaps=(gap,),
            )

    def test_hard_user_gap_cannot_be_hidden_by_low_aggregate_ambiguity(self) -> None:
        """낮은 ambiguity score도 user-owned material blocker를 보상하지 못합니다."""
        resolved = self.open_gap(
            "G1",
            GapAuthority.REPOSITORY,
            dependency_rank=2,
            weight=0.95,
        ).resolve(
            GapResolution.REPOSITORY_FACT,
            "source:path:12",
            self.lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision="repo:head-1",
            ),
        )
        user_gap = self.open_gap(
            "G2",
            GapAuthority.USER,
            dependency_rank=1,
            weight=0.05,
        )

        assessment = assess_ambiguity(
            self.inventory(resolved, user_gap),
            threshold=0.20,
        )

        self.assertAlmostEqual(0.05, assessment.score)
        self.assertFalse(assessment.ready)
        self.assertEqual(ControlAction.ASK_USER, assessment.action)
        self.assertEqual("G2", assessment.selected_gap_id)

    def test_question_selection_is_upstream_and_permutation_invariant(self) -> None:
        """질문 순서는 입력 배열이 아니라 dependency와 materiality로 결정됩니다."""
        upstream = self.open_gap(
            "G-upstream",
            GapAuthority.USER,
            dependency_rank=0,
            weight=0.4,
        )
        downstream = self.open_gap(
            "G-downstream",
            GapAuthority.USER,
            dependency_rank=2,
            weight=0.6,
        )

        first = assess_ambiguity(self.inventory(upstream, downstream))
        second = assess_ambiguity(self.inventory(downstream, upstream))

        self.assertEqual("G-upstream", first.selected_gap_id)
        self.assertEqual(first, second)

    def test_same_frontier_uses_repository_then_safe_assumption_then_user(self) -> None:
        """같은 dependency frontier에서는 근거 조회가 사용자 질문보다 먼저입니다."""
        repository = self.open_gap(
            "G-repository",
            GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=0.1,
        )
        safe = self.open_gap(
            "G-safe",
            GapAuthority.SAFE_ASSUMPTION,
            dependency_rank=0,
            weight=0.2,
            blocking=False,
            reversible=True,
            scope_local=True,
        )
        user = self.open_gap(
            "G-user",
            GapAuthority.USER,
            dependency_rank=0,
            weight=0.7,
        )

        first = assess_ambiguity(self.inventory(user, safe, repository))
        without_repository = assess_ambiguity(self.inventory(user, safe))

        self.assertEqual("G-repository", first.selected_gap_id)
        self.assertEqual(ControlAction.RESEARCH, first.action)
        self.assertEqual("G-safe", without_repository.selected_gap_id)
        self.assertEqual(ControlAction.APPLY_SAFE_ASSUMPTION, without_repository.action)

    def test_socratic_prompt_is_canonical_and_uses_every_explanatory_field(self) -> None:
        """질문 receipt는 context, 영향, 권고, 근거, 실제 질문 전체에 결속됩니다."""
        gap = self.open_gap(
            "G-user",
            GapAuthority.USER,
            dependency_rank=0,
            weight=1.0,
        )
        baseline = render_socratic_question(gap)

        variants = (
            ("context", replace(gap, context="다른 맥락")),
            ("consequence", replace(gap, consequence="다른 영향")),
            ("recommendation", replace(gap, recommendation="다른 권고")),
            (
                "recommendation_rationale",
                replace(gap, recommendation_rationale="다른 권고 근거"),
            ),
            ("question", replace(gap, question="다른 질문인가요?")),
        )
        for field, variant in variants:
            with self.subTest(field=field):
                changed = render_socratic_question(variant)
                self.assertNotEqual(baseline, changed)
                self.assertNotEqual(
                    hashlib.sha256(baseline.encode()).hexdigest(),
                    hashlib.sha256(changed.encode()).hexdigest(),
                )

        self.assertIn(gap.context, baseline)
        self.assertIn(gap.consequence, baseline)
        self.assertIn(gap.recommendation, baseline)
        self.assertIn(gap.recommendation_rationale, baseline)
        self.assertIn(gap.question, baseline)

    def test_repository_answerable_gap_routes_to_research(self) -> None:
        """Repository에서 확인할 수 있는 사실은 사용자 질문으로 전가하지 않습니다."""
        assessment = assess_ambiguity(
            self.inventory(
                self.open_gap(
                    "G-repo",
                    GapAuthority.REPOSITORY,
                    dependency_rank=0,
                    weight=1.0,
                ),
            )
        )

        self.assertEqual(ControlAction.RESEARCH, assessment.action)

    def test_safe_assumption_requires_local_reversible_low_risk_scope(self) -> None:
        """Safe assumption은 local하고 reversible한 gap에서만 자동 적용됩니다."""
        unsafe = self.open_gap(
            "G-unsafe",
            GapAuthority.SAFE_ASSUMPTION,
            dependency_rank=0,
            weight=1.0,
        )
        safe = self.open_gap(
            "G-safe",
            GapAuthority.SAFE_ASSUMPTION,
            dependency_rank=0,
            weight=1.0,
            blocking=False,
            reversible=True,
            scope_local=True,
        )

        self.assertEqual(
            ControlAction.BLOCKED,
            assess_ambiguity(self.inventory(unsafe)).action,
        )
        self.assertEqual(
            ControlAction.APPLY_SAFE_ASSUMPTION,
            assess_ambiguity(self.inventory(safe)).action,
        )

    def test_gap_resolution_requires_matching_authority(self) -> None:
        """Model inference는 user-owned decision을 confirmed fact로 바꾸지 못합니다."""
        gap = self.open_gap(
            "G-user",
            GapAuthority.USER,
            dependency_rank=0,
            weight=1.0,
        )

        with self.assertRaises(ValueError):
            gap.resolve(
                GapResolution.REPOSITORY_FACT,
                "repo cannot decide product intent",
                self.lineage(
                    EvidenceAuthority.PRIMARY_SOURCE,
                    source_revision="repo:head-1",
                ),
            )

        resolved = gap.resolve(
            GapResolution.USER_FACT,
            "user-message:42",
            self.lineage(EvidenceAuthority.USER),
        )
        self.assertTrue(resolved.is_resolved)

    def test_repository_resolution_reopens_when_its_source_basis_changes(self) -> None:
        """Repository fact는 다른 exact source revision에서 current로 재사용되지 않습니다."""
        resolved = self.open_gap(
            "G-repo",
            GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=1.0,
        ).resolve(
            GapResolution.REPOSITORY_FACT,
            "source:path:12",
            self.lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision="repo:head-1",
            ),
        )

        assessment = assess_ambiguity(self.inventory(resolved, source_revision="repo:head-2"))

        self.assertFalse(assessment.ready)
        self.assertEqual(ControlAction.RESEARCH, assessment.action)
        self.assertEqual(("G-repo",), assessment.stale_gap_ids)

    def test_authoritative_user_and_repository_blockers_route_blocked_without_reasking(
        self,
    ) -> None:
        """Current terminal fact는 반복 평가에서도 ASK_USER/RESEARCH가 아닌 BLOCKED입니다."""
        cases = (
            (
                GapAuthority.USER,
                self.lineage(
                    EvidenceAuthority.USER,
                    source_revision="repo:head-1",
                ),
            ),
            (
                GapAuthority.REPOSITORY,
                self.lineage(
                    EvidenceAuthority.PRIMARY_SOURCE,
                    source_revision="repo:head-1",
                ),
            ),
        )
        for authority, lineage in cases:
            with self.subTest(authority=authority):
                blocked = self.open_gap(
                    f"G-blocked-{authority.value}",
                    authority,
                    dependency_rank=0,
                    weight=1.0,
                ).mark_blocked("terminal-evidence:1", lineage)
                inventory = self.inventory(blocked)

                first = assess_ambiguity(inventory)
                repeated = assess_ambiguity(inventory)

                self.assertEqual(first, repeated)
                self.assertFalse(first.ready)
                self.assertEqual(ControlAction.BLOCKED, first.action)
                self.assertEqual(blocked.gap_id, first.selected_gap_id)

    def test_blocker_requires_external_authority_and_cannot_be_directly_unproven(self) -> None:
        """Model label과 evidence 없는 direct enum construction은 terminal blocker가 아닙니다."""
        user_gap = self.open_gap(
            "G-user-blocker",
            GapAuthority.USER,
            dependency_rank=0,
            weight=1.0,
        )
        with self.assertRaises(ValueError):
            replace(user_gap, resolution=GapResolution.BLOCKER)
        with self.assertRaises(ValueError):
            user_gap.mark_blocked(
                "self-authored:blocker",
                self.lineage(
                    EvidenceAuthority.SAME_CONTEXT,
                    source_revision="repo:head-1",
                ),
            )
        safe_gap = self.open_gap(
            "G-safe-blocker",
            GapAuthority.SAFE_ASSUMPTION,
            dependency_rank=0,
            weight=1.0,
            blocking=False,
            reversible=True,
            scope_local=True,
        )
        with self.assertRaises(ValueError):
            safe_gap.mark_blocked(
                "self-authored:blocker",
                self.lineage(
                    EvidenceAuthority.SAME_CONTEXT,
                    source_revision="repo:head-1",
                ),
            )

    def test_blocker_selection_is_upstream_and_permutation_invariant(self) -> None:
        """여러 blocker의 선택은 배열 순서가 아니라 dependency frontier로 결정됩니다."""
        lineage = self.lineage(
            EvidenceAuthority.PRIMARY_SOURCE,
            source_revision="repo:head-1",
        )
        upstream = self.open_gap(
            "G-upstream-blocker",
            GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=0.1,
        ).mark_blocked("terminal:upstream", lineage)
        downstream = self.open_gap(
            "G-downstream-blocker",
            GapAuthority.REPOSITORY,
            dependency_rank=2,
            weight=0.9,
        ).mark_blocked("terminal:downstream", lineage)

        first = assess_ambiguity(self.inventory(upstream, downstream))
        second = assess_ambiguity(self.inventory(downstream, upstream))

        self.assertEqual(first, second)
        self.assertEqual(ControlAction.BLOCKED, first.action)
        self.assertEqual("G-upstream-blocker", first.selected_gap_id)

    def test_resolved_fact_remains_ready_and_is_not_reclassified_as_blocker(self) -> None:
        """Existing authoritative fact semantics는 BLOCKER terminal path 추가 뒤에도 유지됩니다."""
        resolved = self.open_gap(
            "G-repository-fact",
            GapAuthority.REPOSITORY,
            dependency_rank=0,
            weight=1.0,
        ).resolve(
            GapResolution.REPOSITORY_FACT,
            "source:path:12",
            self.lineage(
                EvidenceAuthority.PRIMARY_SOURCE,
                source_revision="repo:head-1",
            ),
        )

        assessment = assess_ambiguity(self.inventory(resolved))

        self.assertTrue(assessment.ready)
        self.assertEqual(ControlAction.CONTINUE, assessment.action)

    def test_user_owned_nonblocking_gap_requires_current_user_deferral(self) -> None:
        """Model-authored nonblocking bool은 user decision을 완료에서 제외하지 못합니다."""
        with self.assertRaises(ValueError):
            self.open_gap(
                "G-owner",
                GapAuthority.USER,
                dependency_rank=0,
                weight=0.1,
                blocking=False,
            )

        deferral = UserDeferral(
            gap_id="G-owner",
            intent_revision=1,
            reason="사용자가 현재 작업에서 이 선택을 명시적으로 유예했다",
            lineage=self.lineage(EvidenceAuthority.USER),
        )
        deferred = self.open_gap(
            "G-owner",
            GapAuthority.USER,
            dependency_rank=0,
            weight=0.1,
            blocking=False,
            deferral=deferral,
        )

        assessment = assess_ambiguity(self.inventory(deferred))

        self.assertTrue(assessment.ready)
        self.assertEqual((), assessment.unresolved_gap_ids)

    def test_goal_requires_exact_independent_coverage_and_all_evidence(self) -> None:
        """현재 goal의 criterion 전체와 required evidence가 모두 있어야 완료됩니다."""
        contract = self.contract(
            self.criterion("AC1", EvidenceKind.EXAMPLE_TEST),
            self.criterion("AC2", EvidenceKind.INDEPENDENT_SEMANTIC),
        )
        receipts = (
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
            ),
            self.evidence(
                contract,
                "AC2",
                EvidenceKind.INDEPENDENT_SEMANTIC,
                EvidenceAuthority.INDEPENDENT_EVALUATOR,
            ),
        )

        missing_coverage = assess_goal_attainment(
            contract, receipts, None, ExecutionStatus.COMPLETED
        )
        complete = assess_goal_attainment(
            contract, receipts, self.coverage(contract), ExecutionStatus.COMPLETED
        )

        self.assertFalse(missing_coverage.achieved)
        self.assertEqual(("goal-coverage",), missing_coverage.pending)
        self.assertTrue(complete.achieved)
        self.assertEqual(ControlAction.COMPLETE, complete.action)

    def test_passing_tests_do_not_satisfy_semantic_or_user_acceptance(self) -> None:
        """TDD green은 독립 의미 판정이나 사용자 acceptance를 대신하지 않습니다."""
        contract = self.contract(
            self.criterion("SEM", EvidenceKind.INDEPENDENT_SEMANTIC),
            self.criterion("PREFERENCE", EvidenceKind.USER_ACCEPTANCE),
        )
        receipts = (
            self.evidence(
                contract,
                "SEM",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
            ),
            self.evidence(
                contract,
                "PREFERENCE",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
            ),
        )

        assessment = assess_goal_attainment(
            contract, receipts, self.coverage(contract), ExecutionStatus.COMPLETED
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("SEM", "PREFERENCE"), assessment.pending)
        self.assertEqual(ControlAction.AWAIT_USER, assessment.action)

    def test_hard_failure_is_not_compensated_by_soft_passes(self) -> None:
        """Soft progress가 늘어도 하나의 hard failure는 성공을 계속 veto합니다."""
        contract = self.contract(
            self.criterion("HARD", EvidenceKind.EXAMPLE_TEST),
            self.criterion("SOFT", EvidenceKind.EXAMPLE_TEST, hard=False),
        )
        receipts = (
            self.evidence(
                contract,
                "HARD",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.FAIL,
            ),
            self.evidence(
                contract,
                "SOFT",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
            ),
        )

        assessment = assess_goal_attainment(
            contract, receipts, self.coverage(contract), ExecutionStatus.COMPLETED
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("HARD",), assessment.failed)
        self.assertGreater(assessment.progress, 0.0)

    def test_missing_soft_criterion_cannot_be_reclassified_as_complete(self) -> None:
        """Acceptance inventory에 든 quality criterion도 evidence 없이는 미달입니다."""
        contract = self.contract(
            self.criterion("HARD", EvidenceKind.EXAMPLE_TEST),
            self.criterion("QUALITY", EvidenceKind.EXAMPLE_TEST, hard=False),
        )

        assessment = assess_goal_attainment(
            contract,
            (
                self.evidence(
                    contract,
                    "HARD",
                    EvidenceKind.EXAMPLE_TEST,
                    EvidenceAuthority.EXECUTABLE,
                ),
            ),
            self.coverage(contract),
            ExecutionStatus.COMPLETED,
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("QUALITY",), assessment.pending)

    def test_failure_vetoes_pass_on_the_same_required_surface(self) -> None:
        """같은 hard evidence surface의 FAIL은 다른 PASS로 상쇄되지 않습니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        evidence = (
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.FAIL,
            ),
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.PASS,
            ),
        )

        assessment = assess_goal_attainment(
            contract,
            evidence,
            self.coverage(contract),
            ExecutionStatus.COMPLETED,
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("AC1",), assessment.failed)
        self.assertIsNot(ControlAction.COMPLETE, assessment.action)

    def test_not_evaluated_vetoes_pass_on_the_same_required_surface(self) -> None:
        """최신 surface의 미판정 또는 부정 판정은 같은 revision의 PASS로 상쇄되지 않습니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        veto_expectations = (
            (EvidenceStatus.NOT_EVALUATED, (), ("AC1",)),
            (EvidenceStatus.FAIL, ("AC1",), ()),
            (EvidenceStatus.ERROR, ("AC1",), ()),
            (EvidenceStatus.STALE, ("AC1",), ()),
        )

        for veto_status, expected_failed, expected_pending in veto_expectations:
            with self.subTest(veto_status=veto_status):
                latest_conflict = (
                    self.evidence(
                        contract,
                        "AC1",
                        EvidenceKind.EXAMPLE_TEST,
                        EvidenceAuthority.EXECUTABLE,
                        EvidenceStatus.PASS,
                        evaluation_revision=1,
                    ),
                    self.evidence(
                        contract,
                        "AC1",
                        EvidenceKind.EXAMPLE_TEST,
                        EvidenceAuthority.EXECUTABLE,
                        veto_status,
                        evaluation_revision=1,
                    ),
                )

                conflicted = assess_goal_attainment(
                    contract,
                    latest_conflict,
                    self.coverage(contract),
                    ExecutionStatus.COMPLETED,
                )
                superseded = assess_goal_attainment(
                    contract,
                    latest_conflict
                    + (
                        self.evidence(
                            contract,
                            "AC1",
                            EvidenceKind.EXAMPLE_TEST,
                            EvidenceAuthority.EXECUTABLE,
                            EvidenceStatus.PASS,
                            evaluation_revision=2,
                        ),
                    ),
                    self.coverage(contract),
                    ExecutionStatus.COMPLETED,
                )

                self.assertFalse(conflicted.achieved)
                self.assertEqual(expected_failed, conflicted.failed)
                self.assertEqual(expected_pending, conflicted.pending)
                self.assertEqual((), conflicted.settled)
                self.assertIsNot(ControlAction.COMPLETE, conflicted.action)
                self.assertTrue(superseded.achieved)
                self.assertEqual((), superseded.failed)
                self.assertEqual((), superseded.pending)
                self.assertEqual(("AC1",), superseded.settled)

    def test_newer_evaluation_revision_supersedes_an_old_failure(self) -> None:
        """동일 surface의 authoritative 재평가는 더 높은 revision으로만 이전 FAIL을 닫습니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        evidence = (
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.FAIL,
                evaluation_revision=1,
            ),
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.PASS,
                evaluation_revision=2,
            ),
        )

        assessment = assess_goal_attainment(
            contract,
            evidence,
            self.coverage(contract),
            ExecutionStatus.COMPLETED,
        )

        self.assertTrue(assessment.achieved)
        self.assertEqual((), assessment.failed)

    def test_failure_veto_applies_only_within_the_latest_evaluation_revision(self) -> None:
        """최신 revision에서 PASS와 FAIL이 충돌하면 FAIL이 non-compensating veto입니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        evidence = (
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.FAIL,
                evaluation_revision=1,
            ),
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.PASS,
                evaluation_revision=2,
            ),
            self.evidence(
                contract,
                "AC1",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
                EvidenceStatus.FAIL,
                evaluation_revision=2,
            ),
        )

        assessment = assess_goal_attainment(
            contract,
            evidence,
            self.coverage(contract),
            ExecutionStatus.COMPLETED,
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("AC1",), assessment.failed)

    def test_goal_override_invalidates_old_receipts(self) -> None:
        """사용자 correction으로 goal fingerprint가 바뀌면 과거 evidence는 stale입니다."""
        old = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        old_receipt = self.evidence(
            old,
            "AC1",
            EvidenceKind.EXAMPLE_TEST,
            EvidenceAuthority.EXECUTABLE,
        )
        corrected_goal = "사용자가 교정한 요청을 완수한다"
        corrected_requirement = approved_requirement_fingerprint(
            corrected_goal,
            old.constraints,
            old.non_goals,
            2,
            old.source_revision,
        )
        current = GoalContract(
            goal=corrected_goal,
            constraints=old.constraints,
            requirement_ids=old.requirement_ids,
            criteria=tuple(
                replace(item, approved_requirement_fingerprint=corrected_requirement)
                for item in old.criteria
            ),
            non_goals=old.non_goals,
            intent_revision=2,
            source_revision=old.source_revision,
        )

        assessment = assess_goal_attainment(
            current,
            (old_receipt,),
            self.coverage(current),
            ExecutionStatus.COMPLETED,
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("AC1",), assessment.pending)
        self.assertEqual(("AC1",), assessment.stale)

    def test_same_text_new_intent_revision_invalidates_old_receipts(self) -> None:
        """동일한 문구라도 새 user intent revision은 이전 evidence를 폐기합니다."""
        criterion = self.criterion("AC1", EvidenceKind.EXAMPLE_TEST)
        old = self.contract(criterion, intent_revision=1)
        old_receipt = self.evidence(
            old,
            "AC1",
            EvidenceKind.EXAMPLE_TEST,
            EvidenceAuthority.EXECUTABLE,
        )
        current = self.contract(criterion, intent_revision=2)

        assessment = assess_goal_attainment(
            current,
            (old_receipt,),
            self.coverage(current),
            ExecutionStatus.COMPLETED,
        )

        self.assertNotEqual(old.fingerprint, current.fingerprint)
        self.assertFalse(assessment.achieved)
        self.assertEqual(("AC1",), assessment.stale)

    def test_self_authored_coverage_cannot_authorize_goal_completion(self) -> None:
        """Implementation context의 자체 coverage 주장은 독립 goal 판정이 아닙니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        receipt = self.evidence(
            contract,
            "AC1",
            EvidenceKind.EXAMPLE_TEST,
            EvidenceAuthority.EXECUTABLE,
        )
        coverage = GoalCoverage(
            goal_fingerprint=contract.fingerprint,
            criterion_ids=frozenset({"AC1"}),
            authority=EvidenceAuthority.SAME_CONTEXT,
            status=EvidenceStatus.PASS,
            reference="self-score:1.0",
            goal_alignment=1.0,
            semantic_drift=0.0,
            uncertainty=0.0,
            reward_hacking_risk=0.0,
            lineage=self.lineage(
                EvidenceAuthority.SAME_CONTEXT,
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
            ),
        )

        assessment = assess_goal_attainment(
            contract, (receipt,), coverage, ExecutionStatus.COMPLETED
        )

        self.assertFalse(assessment.achieved)
        self.assertEqual(("goal-coverage",), assessment.pending)

    def test_user_acceptance_does_not_replace_independent_goal_coverage(self) -> None:
        """사용자 evidence와 별개로 전체 criterion coverage는 독립 평가자가 판정합니다."""
        contract = self.contract(
            self.criterion("AC1", EvidenceKind.USER_ACCEPTANCE),
        )
        user_lineage = self.lineage(
            EvidenceAuthority.USER,
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
        )
        user_coverage = replace(
            self.coverage(contract),
            authority=EvidenceAuthority.USER,
            lineage=user_lineage,
        )

        assessment = assess_goal_attainment(
            contract,
            (
                self.evidence(
                    contract,
                    "AC1",
                    EvidenceKind.USER_ACCEPTANCE,
                    EvidenceAuthority.USER,
                ),
            ),
            user_coverage,
            ExecutionStatus.COMPLETED,
        )

        self.assertFalse(assessment.achieved)
        self.assertIn("goal-coverage", assessment.pending)

    def test_independent_authority_requires_distinct_issuer_and_delegation_lineage(self) -> None:
        """Independent label은 exact delegated issuer receipt 없이 생성될 수 없습니다."""
        receipt_body = "independent:self:self:1:approved-plan:1"

        with self.assertRaises(ValueError):
            AuthorityReceipt(
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                issuer_id="implementation-agent",
                subject_id="implementation-agent",
                intent_revision=1,
                source_revision="approved-plan:1",
                receipt_digest=hashlib.sha256(receipt_body.encode()).hexdigest(),
                delegation_id=None,
            )

    def test_authority_lineage_accepts_runtime_opaque_actor_identities(self) -> None:
        """Authority lineage는 SessionKernel의 colon-delimited opaque ActorId와 호환됩니다."""
        receipt = AuthorityReceipt(
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            issuer_id="codex:subagent:evaluator-1",
            subject_id="codex:session:019fc098-1371-7092-85d4-7b1130c32bb2",
            intent_revision=1,
            source_revision="approved-plan:1",
            receipt_digest="a" * 64,
            delegation_id="adaptive:evaluation:1",
        )

        self.assertEqual("codex:subagent:evaluator-1", receipt.issuer_id)
        self.assertEqual(
            "codex:session:019fc098-1371-7092-85d4-7b1130c32bb2",
            receipt.subject_id,
        )
        with self.assertRaises(ValueError):
            AuthorityReceipt(
                authority=EvidenceAuthority.EXECUTABLE,
                issuer_id="contains whitespace",
                subject_id="codex:session:root",
                intent_revision=1,
                source_revision="approved-plan:1",
                receipt_digest="b" * 64,
            )

    def test_non_code_goal_can_complete_without_example_tests(self) -> None:
        """조사·결정 작업은 그 acceptance surface가 충족되면 test 없이 완료할 수 있습니다."""
        contract = self.contract(
            self.criterion(
                "RESEARCH",
                EvidenceKind.SOURCE_READBACK,
                EvidenceKind.INDEPENDENT_SEMANTIC,
            )
        )
        receipts = (
            self.evidence(
                contract,
                "RESEARCH",
                EvidenceKind.SOURCE_READBACK,
                EvidenceAuthority.PRIMARY_SOURCE,
            ),
            self.evidence(
                contract,
                "RESEARCH",
                EvidenceKind.INDEPENDENT_SEMANTIC,
                EvidenceAuthority.INDEPENDENT_EVALUATOR,
            ),
        )

        assessment = assess_goal_attainment(
            contract, receipts, self.coverage(contract), ExecutionStatus.COMPLETED
        )

        self.assertTrue(assessment.achieved)

    def test_semantic_thresholds_are_non_compensating_goal_vetoes(self) -> None:
        """Alignment, drift, uncertainty, reward risk는 평균 score로 상쇄되지 않습니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        receipt = self.evidence(
            contract,
            "AC1",
            EvidenceKind.EXAMPLE_TEST,
            EvidenceAuthority.EXECUTABLE,
        )
        cases = (
            (0.69, 0.0, 0.0, 0.0, "goal-alignment"),
            (1.0, 0.31, 0.0, 0.0, "semantic-drift"),
            (1.0, 0.0, 0.31, 0.0, "semantic-uncertainty"),
            (1.0, 0.0, 0.0, 0.70, "reward-hacking-risk"),
        )

        for alignment, drift, uncertainty, reward_risk, expected in cases:
            with self.subTest(expected=expected):
                coverage = GoalCoverage(
                    goal_fingerprint=contract.fingerprint,
                    criterion_ids=frozenset({"AC1"}),
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    status=EvidenceStatus.PASS,
                    reference=f"semantic:{expected}",
                    goal_alignment=alignment,
                    semantic_drift=drift,
                    uncertainty=uncertainty,
                    reward_hacking_risk=reward_risk,
                    lineage=self.lineage(
                        EvidenceAuthority.INDEPENDENT_EVALUATOR,
                        intent_revision=contract.intent_revision,
                        source_revision=contract.source_revision,
                    ),
                )
                assessment = assess_goal_attainment(
                    contract,
                    (receipt,),
                    coverage,
                    ExecutionStatus.COMPLETED,
                )
                self.assertFalse(assessment.achieved)
                self.assertIn(expected, assessment.pending)

    def test_completed_evidence_cannot_hide_incomplete_execution(self) -> None:
        """모든 criterion이 pass해도 실제 execution이 끝나지 않으면 goal은 미달성입니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        receipt = self.evidence(
            contract,
            "AC1",
            EvidenceKind.EXAMPLE_TEST,
            EvidenceAuthority.EXECUTABLE,
        )

        assessment = assess_goal_attainment(
            contract,
            (receipt,),
            self.coverage(contract),
            ExecutionStatus.INCOMPLETE,
        )

        self.assertFalse(assessment.achieved)
        self.assertIn("execution", assessment.pending)

    def test_reflection_keeps_settled_criteria_out_of_active_scope(self) -> None:
        """통과한 criterion은 challenge나 regression이 없으면 다시 파생하지 않습니다."""
        contract = self.contract(
            self.criterion("DONE", EvidenceKind.EXAMPLE_TEST),
            self.criterion("OPEN", EvidenceKind.EXAMPLE_TEST),
        )
        receipts = (
            self.evidence(
                contract,
                "DONE",
                EvidenceKind.EXAMPLE_TEST,
                EvidenceAuthority.EXECUTABLE,
            ),
        )
        assessment = assess_goal_attainment(
            contract, receipts, self.coverage(contract), ExecutionStatus.COMPLETED
        )

        stable = reflection_scope(contract, assessment, challenged=(), regressed=())
        reopened = reflection_scope(contract, assessment, challenged=("DONE",), regressed=())

        self.assertEqual(("OPEN",), stable)
        self.assertEqual(("DONE", "OPEN"), reopened)

    def test_repeated_introduced_root_cause_requires_approach_change(self) -> None:
        """같은 수정이 같은 introduced defect를 두 번 만들면 point fix를 중단합니다."""
        decision = ReflectionPolicy().decide(
            self._clear(),
            self._incomplete_goal(),
            (
                self._observation(1, "A", 0.2, ("introduced-owner-leak",)),
                self._observation(2, "B", 0.3, ("introduced-owner-leak",)),
            ),
        )

        self.assertEqual(ControlAction.CHANGE_APPROACH, decision.action)

    def test_repeated_preexisting_root_cause_switches_to_exhaustive_invariant(self) -> None:
        """흩어진 preexisting 사례 반복은 다음 사례 요청 대신 전수 검사로 전환합니다."""
        decision = ReflectionPolicy().decide(
            self._clear(),
            self._incomplete_goal(),
            (
                self._observation(1, "A", 0.2, ("preexisting-raw-token",)),
                self._observation(2, "B", 0.3, ("preexisting-raw-token",)),
            ),
        )

        self.assertEqual(ControlAction.ENUMERATE_INVARIANT, decision.action)

    def test_recovered_epoch_does_not_replay_old_root_cause_or_stagnation(self) -> None:
        """Material recovery를 승인한 새 epoch는 이전 epoch의 반복 신호를 재사용하지 않습니다."""
        observations = (
            self._observation(1, "A", 0.2, ("introduced-owner-leak",), recovery_epoch=0),
            self._observation(2, "A", 0.2, ("introduced-owner-leak",), recovery_epoch=0),
            self._observation(3, "B", 0.3, (), recovery_epoch=1),
        )

        decision = ReflectionPolicy().decide(
            self._clear(),
            self._incomplete_goal(),
            observations,
        )

        self.assertEqual(ControlAction.CONTINUE, decision.action)

    def test_same_root_cause_reintroduced_after_recovery_is_a_global_veto(self) -> None:
        """새 recovery epoch도 이전과 같은 introduced cause를 다시 만들면 접근을 바꿉니다."""
        observations = (
            self._observation(1, "A", 0.2, ("introduced-owner-leak",), recovery_epoch=0),
            self._observation(2, "B", 0.3, ("introduced-owner-leak",), recovery_epoch=0),
            self._observation(3, "C", 0.4, ("introduced-owner-leak",), recovery_epoch=1),
        )

        changed = ReflectionPolicy().decide(
            self._clear(),
            self._incomplete_goal(),
            observations,
        )
        exhausted = ReflectionPolicy(max_generations=3).decide(
            self._clear(),
            self._incomplete_goal(),
            observations,
        )

        self.assertEqual(ControlAction.CHANGE_APPROACH, changed.action)
        self.assertEqual(ControlAction.EXHAUSTED, exhausted.action)

    def test_generation_cap_counts_all_recovery_epochs(self) -> None:
        """Recovery acknowledgement는 hard safety generation budget을 초기화하지 않습니다."""
        observations = (
            self._observation(1, "A", 0.1, (), recovery_epoch=0),
            self._observation(2, "B", 0.2, (), recovery_epoch=1),
            self._observation(3, "C", 0.3, (), recovery_epoch=2),
        )

        decision = ReflectionPolicy(max_generations=3).decide(
            self._clear(),
            self._incomplete_goal(),
            observations,
        )

        self.assertEqual(ControlAction.EXHAUSTED, decision.action)

    def test_oscillation_and_plateau_stop_without_claiming_success(self) -> None:
        """A/B oscillation과 동일 output plateau는 success가 아닌 접근 변경입니다."""
        policy = ReflectionPolicy(stagnation_window=3)
        oscillating = tuple(
            self._observation(index, fingerprint, 0.2 + index * 0.01, ())
            for index, fingerprint in enumerate(("A", "B", "A", "B"), start=1)
        )
        plateau = tuple(self._observation(index, "SAME", 0.2, ()) for index in range(1, 4))

        oscillation_decision = policy.decide(self._clear(), self._incomplete_goal(), oscillating)
        plateau_decision = policy.decide(self._clear(), self._incomplete_goal(), plateau)

        self.assertEqual(ControlAction.CHANGE_APPROACH, oscillation_decision.action)
        self.assertEqual(ControlAction.CHANGE_APPROACH, plateau_decision.action)
        self.assertFalse(oscillation_decision.achieved)
        self.assertFalse(plateau_decision.achieved)

    def test_zero_goal_delta_changes_approach_without_waiting_for_a_stagnation_window(self) -> None:
        """Raw zero-delta shape는 store admission 없이 reflection을 직접 제어하지 못합니다."""
        efficiency = self._zero_progress_efficiency(
            self._incomplete_goal().goal_fingerprint,
        )

        self.assertIsInstance(efficiency, EfficiencyAssessment)
        self.assertNotIn(
            "efficiency",
            inspect.signature(ReflectionPolicy.decide).parameters,
        )

    def test_foreign_goal_efficiency_cannot_control_current_reflection(self) -> None:
        """다른 goal의 resource-efficiency receipt는 current goal action 권한을 얻지 못합니다."""
        efficiency = self._zero_progress_efficiency(hashlib.sha256(b"foreign-goal").hexdigest())

        self.assertNotEqual(
            self._incomplete_goal().goal_fingerprint,
            efficiency.goal_delta.goal_fingerprint,
        )
        self.assertNotIn(
            "efficiency",
            inspect.signature(ReflectionPolicy.decide).parameters,
        )

    def test_generation_cap_is_exhaustion_not_success(self) -> None:
        """Hard generation cap은 safety stop이며 목표 달성으로 변환되지 않습니다."""
        policy = ReflectionPolicy(max_generations=3)
        observations = tuple(
            self._observation(index, f"F{index}", index / 10, ()) for index in range(1, 4)
        )

        decision = policy.decide(self._clear(), self._incomplete_goal(), observations)

        self.assertEqual(ControlAction.EXHAUSTED, decision.action)
        self.assertFalse(decision.achieved)

    def test_default_reflection_has_no_arbitrary_generation_cap(self) -> None:
        """Material convergence가 남은 default loop를 회차 숫자만으로 소진시키지 않습니다."""
        observations = tuple(
            self._observation(index, f"unique-{index}", index / 100, ()) for index in range(1, 32)
        )

        decision = ReflectionPolicy().decide(
            self._clear(),
            self._incomplete_goal(),
            observations,
        )

        self.assertEqual(ControlAction.CONTINUE, decision.action)
        self.assertFalse(decision.achieved)

    def test_reproducible_harness_gap_routes_to_promotion(self) -> None:
        """재현된 harness gap은 보고서가 아니라 evaluate-harness promotion으로 향합니다."""
        observation = self._observation(1, "A", 0.4, (), harness_gap=True)

        decision = ReflectionPolicy().decide(self._clear(), self._incomplete_goal(), (observation,))

        self.assertEqual(ControlAction.PROMOTE_HARNESS, decision.action)

    def test_reproducible_harness_gap_does_not_reopen_an_achieved_goal(self) -> None:
        """현재 goal 밖의 harness follow-up은 이미 충족된 goal을 다시 열지 않습니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        attainment = assess_goal_attainment(
            contract,
            (
                self.evidence(
                    contract,
                    "AC1",
                    EvidenceKind.EXAMPLE_TEST,
                    EvidenceAuthority.EXECUTABLE,
                ),
            ),
            self.coverage(contract),
            ExecutionStatus.COMPLETED,
        )
        observation = IterationObservation(
            goal_fingerprint=contract.fingerprint,
            generation=1,
            output_fingerprint="output-a",
            active_criteria=("AC1",),
            root_causes=(),
            progress=1.0,
            material_change=True,
            reproducible_harness_gap=True,
        )

        decision = ReflectionPolicy().decide(
            self._clear(),
            attainment,
            (observation,),
        )

        self.assertTrue(decision.achieved)
        self.assertEqual(ControlAction.COMPLETE, decision.action)

    def test_goal_can_finish_in_first_generation_when_every_authority_passes(self) -> None:
        """모든 결합 조건이 이미 참이면 불필요한 최소 회차를 강제하지 않습니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        attainment = assess_goal_attainment(
            contract,
            (
                self.evidence(
                    contract,
                    "AC1",
                    EvidenceKind.EXAMPLE_TEST,
                    EvidenceAuthority.EXECUTABLE,
                ),
            ),
            self.coverage(contract),
            ExecutionStatus.COMPLETED,
        )

        decision = ReflectionPolicy().decide(self._clear(), attainment, ())

        self.assertEqual(ControlAction.COMPLETE, decision.action)
        self.assertTrue(decision.achieved)

    def _clear(self) -> AmbiguityAssessment:
        """모호함이 없는 현재 intent assessment를 반환합니다."""
        return assess_ambiguity(self.inventory())

    def _zero_progress_efficiency(self, goal_fingerprint: str) -> EfficiencyAssessment:
        """Receipt-backed 자원 소비와 0 goal delta를 가진 adaptive fixture를 만듭니다."""
        metric = ResourceMetricDelta(
            status=ResourceTelemetryStatus.VERIFIED,
            value=1,
            source_id="runtime-hook",
            receipt_reference="runtime-receipt:generation-1",
            receipt_digest=hashlib.sha256(b"resource-receipt").hexdigest(),
        )
        evidence_basis_fingerprint = hashlib.sha256(b"evidence-basis").hexdigest()
        return EfficiencyAssessor().assess(
            VerifiedGoalAttainmentDelta(
                before=GoalAttainmentReadback(
                    goal_fingerprint=goal_fingerprint,
                    evidence_basis_fingerprint=evidence_basis_fingerprint,
                    evaluation_revision=1,
                    settled_evidence_units=frozenset({"AC1:example-test"}),
                    failed_evidence_units=frozenset(),
                    reopened_evidence_units=frozenset(),
                    authority_source_id="adaptive-control-store",
                    readback_reference="adaptive-readback:1",
                    receipt_digest=hashlib.sha256(b"adaptive-readback:1").hexdigest(),
                ),
                after=GoalAttainmentReadback(
                    goal_fingerprint=goal_fingerprint,
                    evidence_basis_fingerprint=evidence_basis_fingerprint,
                    evaluation_revision=2,
                    settled_evidence_units=frozenset({"AC1:example-test"}),
                    failed_evidence_units=frozenset(),
                    reopened_evidence_units=frozenset(),
                    authority_source_id="adaptive-control-store",
                    readback_reference="adaptive-readback:2",
                    receipt_digest=hashlib.sha256(b"adaptive-readback:2").hexdigest(),
                ),
            ),
            AuthoritativeResourceDelta(
                basis_fingerprint=hashlib.sha256(b"resource-basis").hexdigest(),
                wall_clock_milliseconds=metric,
                tool_invocations=metric,
                input_tokens=metric,
                output_tokens=metric,
                evaluator_generations=metric,
            ),
        )

    def _incomplete_goal(self) -> GoalAttainment:
        """한 acceptance가 아직 평가되지 않은 goal assessment를 반환합니다."""
        contract = self.contract(self.criterion("AC1", EvidenceKind.EXAMPLE_TEST))
        return assess_goal_attainment(
            contract, (), self.coverage(contract), ExecutionStatus.COMPLETED
        )

    def _observation(
        self,
        generation: int,
        fingerprint: str,
        progress: float,
        root_causes: tuple[str, ...],
        *,
        harness_gap: bool = False,
        recovery_epoch: int = 0,
    ) -> IterationObservation:
        """Reflection fixture 한 세대를 만듭니다."""
        return IterationObservation(
            goal_fingerprint=self._incomplete_goal().goal_fingerprint,
            generation=generation,
            output_fingerprint=fingerprint,
            active_criteria=("AC1",),
            root_causes=root_causes,
            progress=progress,
            material_change=fingerprint != "SAME",
            reproducible_harness_gap=harness_gap,
            recovery_epoch=recovery_epoch,
        )


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
