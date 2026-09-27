"""Versioned adaptive payload encoding and strict persisted-state validation."""

from __future__ import annotations

import hmac
from collections.abc import (
    Mapping,
)
from enum import (
    StrEnum,
)
from typing import (
    TypeVar,
)

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    ClarificationGap,
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
    RequirementSection,
    UserDecision,
    UserDecisionClaim,
    UserDecisionDisposition,
    UserDecisionProvenance,
    UserDecisionTarget,
    UserDeferral,
)
from scripts.agent_harness.adaptive_resource_admission import (
    _EfficiencyAdmissionFactory,
)
from scripts.agent_harness.adaptive_state import (
    AdaptiveControlState,
    InvalidAdaptiveControlState,
)
from scripts.agent_harness.efficiency_assessment import (
    AuthoritativeResourceDelta,
    EfficiencyAssessment,
    EfficiencyAssessor,
    EfficiencyStatus,
    GoalAttainmentReadback,
    ResourceMetricDelta,
    ResourceTelemetryStatus,
    VerifiedGoalAttainmentDelta,
)

EnumValue = TypeVar("EnumValue", bound=StrEnum)


class _AdaptiveControlCodec:
    """Adaptive domain value와 canonical JSON object 사이를 왕복합니다."""

    _SCHEMA_VERSION = 5
    _USER_DECISION_SCHEMA_VERSION = 4
    _LEGACY_SCHEMA_VERSION = 3

    def encode(self, state: AdaptiveControlState) -> Mapping[str, object]:
        """Immutable domain state를 JSON-compatible object로 변환합니다.

        Args:
            state: 모든 cross-record invariant를 만족한 adaptive domain state입니다.

        Returns:
            Raw USER 응답을 제외하고 schema version을 명시한 canonical payload입니다.
        """
        return {
            "schema_version": self._SCHEMA_VERSION,
            "contract": self._encode_contract(state.contract),
            "inventory": self._encode_inventory(state.inventory),
            "evidence": [self._encode_evidence(item) for item in state.evidence],
            "coverage": (None if state.coverage is None else self._encode_coverage(state.coverage)),
            "execution_status": state.execution_status.value,
            "observations": [self._encode_observation(item) for item in state.observations],
            "user_decisions": [self._encode_user_decision(item) for item in state.user_decisions],
        }

    def decode(self, payload: Mapping[str, object]) -> AdaptiveControlState:
        """Persisted JSON object를 검증된 immutable domain state로 복원합니다.

        Args:
            payload: Supported schema version과 exact field set을 가진 persisted object입니다.

        Returns:
            Schema와 모든 domain invariant를 통과한 immutable adaptive state입니다.

        Raises:
            InvalidAdaptiveControlState: Field, type, enum, schema 또는 cross-record invariant가
                invalid하면 발생합니다.
        """
        try:
            schema_version = self._integer(payload.get("schema_version"), "schema_version")
            if schema_version not in {
                self._LEGACY_SCHEMA_VERSION,
                self._USER_DECISION_SCHEMA_VERSION,
                self._SCHEMA_VERSION,
            }:
                raise InvalidAdaptiveControlState("unsupported adaptive control schema version")
            expected_fields = {
                "schema_version",
                "contract",
                "inventory",
                "evidence",
                "coverage",
                "execution_status",
                "observations",
            }
            if schema_version >= self._USER_DECISION_SCHEMA_VERSION:
                expected_fields.add("user_decisions")
            self._exact_fields(payload, expected_fields, "adaptive control")
            raw_coverage = payload.get("coverage")
            coverage = (
                None
                if raw_coverage is None
                else self._decode_coverage(self._mapping(raw_coverage, "coverage"))
            )
            state = AdaptiveControlState(
                contract=self._decode_contract(self._mapping(payload.get("contract"), "contract")),
                inventory=self._decode_inventory(
                    self._mapping(payload.get("inventory"), "inventory")
                ),
                evidence=tuple(
                    self._decode_evidence(self._mapping(item, "evidence"))
                    for item in self._list(payload.get("evidence"), "evidence")
                ),
                coverage=coverage,
                execution_status=self._enum(
                    ExecutionStatus,
                    payload.get("execution_status"),
                    "execution_status",
                ),
                observations=tuple(
                    self._decode_observation(self._mapping(item, "observation"))
                    for item in self._list(payload.get("observations"), "observations")
                ),
                user_decisions=(
                    ()
                    if schema_version == self._LEGACY_SCHEMA_VERSION
                    else tuple(
                        self._decode_user_decision(self._mapping(item, "user decision"))
                        for item in self._list(
                            payload.get("user_decisions"),
                            "user_decisions",
                        )
                    )
                ),
            )
            _EfficiencyAdmissionFactory().validate(state)
            return state
        except InvalidAdaptiveControlState:
            raise
        except (TypeError, ValueError) as error:
            raise InvalidAdaptiveControlState("invalid adaptive control payload") from error

    def _encode_contract(self, contract: GoalContract) -> Mapping[str, object]:
        return {
            "goal": contract.goal,
            "constraints": list(contract.constraints),
            "requirement_ids": sorted(contract.requirement_ids),
            "criteria": [
                {
                    "criterion_id": item.criterion_id,
                    "description": item.description,
                    "source_requirement_id": item.source_requirement_id,
                    "approved_requirement_fingerprint": (item.approved_requirement_fingerprint),
                    "observer": item.observer,
                    "precondition": item.precondition,
                    "stimulus": item.stimulus,
                    "expected_outcome": item.expected_outcome,
                    "oracle_owner": item.oracle_owner.value,
                    "hard": item.hard,
                    "required_evidence": sorted(kind.value for kind in item.required_evidence),
                }
                for item in contract.criteria
            ],
            "non_goals": list(contract.non_goals),
            "intent_revision": contract.intent_revision,
            "source_revision": contract.source_revision,
        }

    def _decode_contract(self, payload: Mapping[str, object]) -> GoalContract:
        criteria: list[CriterionSpec] = []
        for raw_item in self._list(payload.get("criteria"), "contract.criteria"):
            item = self._mapping(raw_item, "criterion")
            criteria.append(
                CriterionSpec(
                    criterion_id=self._text(item.get("criterion_id"), "criterion_id"),
                    description=self._text(item.get("description"), "criterion.description"),
                    source_requirement_id=self._text(
                        item.get("source_requirement_id"),
                        "criterion.source_requirement_id",
                    ),
                    approved_requirement_fingerprint=self._text(
                        item.get("approved_requirement_fingerprint"),
                        "criterion.approved_requirement_fingerprint",
                    ),
                    observer=self._text(item.get("observer"), "criterion.observer"),
                    precondition=self._text(
                        item.get("precondition"),
                        "criterion.precondition",
                    ),
                    stimulus=self._text(item.get("stimulus"), "criterion.stimulus"),
                    expected_outcome=self._text(
                        item.get("expected_outcome"),
                        "criterion.expected_outcome",
                    ),
                    oracle_owner=self._enum(
                        OracleOwner,
                        item.get("oracle_owner"),
                        "criterion.oracle_owner",
                    ),
                    hard=self._boolean(item.get("hard"), "criterion.hard"),
                    required_evidence=frozenset(
                        self._enum(EvidenceKind, value, "criterion.required_evidence")
                        for value in self._list(
                            item.get("required_evidence"),
                            "criterion.required_evidence",
                        )
                    ),
                )
            )
        return GoalContract(
            goal=self._text(payload.get("goal"), "contract.goal"),
            constraints=self._text_tuple(payload.get("constraints"), "contract.constraints"),
            requirement_ids=frozenset(
                self._text(item, "contract.requirement_id")
                for item in self._list(
                    payload.get("requirement_ids"),
                    "contract.requirement_ids",
                )
            ),
            criteria=tuple(criteria),
            non_goals=self._text_tuple(payload.get("non_goals"), "contract.non_goals"),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "contract.intent_revision",
            ),
            source_revision=self._text(
                payload.get("source_revision"),
                "contract.source_revision",
            ),
        )

    def _encode_inventory(self, inventory: GapInventory) -> Mapping[str, object]:
        return {
            "intent_revision": inventory.intent_revision,
            "source_revision": inventory.source_revision,
            "assessed_sections": sorted(item.value for item in inventory.assessed_sections),
            "gaps": [self._encode_gap(item) for item in inventory.gaps],
        }

    def _decode_inventory(self, payload: Mapping[str, object]) -> GapInventory:
        return GapInventory(
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "inventory.intent_revision",
            ),
            source_revision=self._text(
                payload.get("source_revision"),
                "inventory.source_revision",
            ),
            assessed_sections=frozenset(
                self._enum(RequirementSection, item, "inventory.assessed_section")
                for item in self._list(
                    payload.get("assessed_sections"),
                    "inventory.assessed_sections",
                )
            ),
            gaps=tuple(
                self._decode_gap(self._mapping(item, "gap"))
                for item in self._list(payload.get("gaps"), "inventory.gaps")
            ),
        )

    def _encode_gap(self, gap: ClarificationGap) -> Mapping[str, object]:
        return {
            "gap_id": gap.gap_id,
            "section": gap.section.value,
            "authority": gap.authority.value,
            "dependency_rank": gap.dependency_rank,
            "weight": gap.weight,
            "blocking": gap.blocking,
            "reversible": gap.reversible,
            "scope_local": gap.scope_local,
            "context": gap.context,
            "question": gap.question,
            "consequence": gap.consequence,
            "recommendation": gap.recommendation,
            "recommendation_rationale": gap.recommendation_rationale,
            "intent_revision": gap.intent_revision,
            "resolution": gap.resolution.value,
            "evidence_reference": gap.evidence_reference,
            "resolution_lineage": (
                None
                if gap.resolution_lineage is None
                else self._encode_authority_receipt(gap.resolution_lineage)
            ),
            "deferral": (
                None if gap.deferral is None else self._encode_user_deferral(gap.deferral)
            ),
        }

    def _decode_gap(self, payload: Mapping[str, object]) -> ClarificationGap:
        return ClarificationGap(
            gap_id=self._text(payload.get("gap_id"), "gap_id"),
            section=self._enum(RequirementSection, payload.get("section"), "gap.section"),
            authority=self._enum(GapAuthority, payload.get("authority"), "gap.authority"),
            dependency_rank=self._integer(
                payload.get("dependency_rank"),
                "gap.dependency_rank",
            ),
            weight=self._number(payload.get("weight"), "gap.weight"),
            blocking=self._boolean(payload.get("blocking"), "gap.blocking"),
            reversible=self._boolean(payload.get("reversible"), "gap.reversible"),
            scope_local=self._boolean(payload.get("scope_local"), "gap.scope_local"),
            context=self._text(payload.get("context"), "gap.context"),
            question=self._text(payload.get("question"), "gap.question"),
            consequence=self._text(payload.get("consequence"), "gap.consequence"),
            recommendation=self._text(
                payload.get("recommendation"),
                "gap.recommendation",
            ),
            recommendation_rationale=self._text(
                payload.get("recommendation_rationale"),
                "gap.recommendation_rationale",
            ),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "gap.intent_revision",
            ),
            resolution=self._enum(
                GapResolution,
                payload.get("resolution"),
                "gap.resolution",
            ),
            evidence_reference=self._optional_text(
                payload.get("evidence_reference"),
                "gap.evidence_reference",
            ),
            resolution_lineage=self._decode_optional_authority_receipt(
                payload.get("resolution_lineage"),
                "gap.resolution_lineage",
            ),
            deferral=self._decode_optional_user_deferral(
                payload.get("deferral"),
                "gap.deferral",
            ),
        )

    def _encode_authority_receipt(
        self,
        receipt: AuthorityReceipt,
    ) -> Mapping[str, object]:
        return {
            "authority": receipt.authority.value,
            "issuer_id": receipt.issuer_id,
            "subject_id": receipt.subject_id,
            "intent_revision": receipt.intent_revision,
            "source_revision": receipt.source_revision,
            "receipt_digest": receipt.receipt_digest,
            "delegation_id": receipt.delegation_id,
        }

    def _decode_authority_receipt(self, payload: Mapping[str, object]) -> AuthorityReceipt:
        return AuthorityReceipt(
            authority=self._enum(
                EvidenceAuthority,
                payload.get("authority"),
                "lineage.authority",
            ),
            issuer_id=self._text(payload.get("issuer_id"), "lineage.issuer_id"),
            subject_id=self._text(payload.get("subject_id"), "lineage.subject_id"),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "lineage.intent_revision",
            ),
            source_revision=self._text(
                payload.get("source_revision"),
                "lineage.source_revision",
            ),
            receipt_digest=self._text(
                payload.get("receipt_digest"),
                "lineage.receipt_digest",
            ),
            delegation_id=self._optional_text(
                payload.get("delegation_id"),
                "lineage.delegation_id",
            ),
        )

    def _decode_optional_authority_receipt(
        self,
        value: object,
        label: str,
    ) -> AuthorityReceipt | None:
        if value is None:
            return None
        return self._decode_authority_receipt(self._mapping(value, label))

    def _encode_user_deferral(self, deferral: UserDeferral) -> Mapping[str, object]:
        return {
            "gap_id": deferral.gap_id,
            "intent_revision": deferral.intent_revision,
            "reason": deferral.reason,
            "lineage": self._encode_authority_receipt(deferral.lineage),
            "decision_reference": deferral.decision_reference,
        }

    def _decode_user_deferral(self, payload: Mapping[str, object]) -> UserDeferral:
        return UserDeferral(
            gap_id=self._text(payload.get("gap_id"), "deferral.gap_id"),
            intent_revision=self._integer(
                payload.get("intent_revision"),
                "deferral.intent_revision",
            ),
            reason=self._text(payload.get("reason"), "deferral.reason"),
            lineage=self._decode_authority_receipt(
                self._mapping(payload.get("lineage"), "deferral.lineage")
            ),
            decision_reference=self._optional_text(
                payload.get("decision_reference"),
                "deferral.decision_reference",
            ),
        )

    def _decode_optional_user_deferral(
        self,
        value: object,
        label: str,
    ) -> UserDeferral | None:
        if value is None:
            return None
        return self._decode_user_deferral(self._mapping(value, label))

    def _encode_user_decision(self, decision: UserDecision) -> Mapping[str, object]:
        return {
            "claim": decision.claim.to_payload(),
            "decision_digest": decision.claim.decision_digest,
            "interpretation_lineage": self._encode_authority_receipt(
                decision.interpretation_lineage
            ),
        }

    def _decode_user_decision(self, payload: Mapping[str, object]) -> UserDecision:
        self._exact_fields(
            payload,
            {"claim", "decision_digest", "interpretation_lineage"},
            "user decision",
        )
        claim_payload = self._mapping(payload.get("claim"), "user decision.claim")
        legacy_fields = {
            "workflow_id",
            "question_workflow_revision",
            "source_goal_fingerprint",
            "source_intent_revision",
            "source_revision",
            "question_digest",
            "question_generation",
            "question_turn_revision",
            "prompt_digest",
            "prompt_reference",
            "prompt_generation",
            "prompt_turn_revision",
            "target_kind",
            "target_id",
            "disposition",
            "value_summary_digest",
            "result_goal_fingerprint",
            "result_intent_revision",
            "result_source_revision",
        }
        native_fields = legacy_fields - {
            "question_workflow_revision",
            "question_digest",
            "question_generation",
            "question_turn_revision",
            "prompt_generation",
            "prompt_turn_revision",
        } | {"provenance", "source_workflow_revision"}
        native_with_kernel_fields = native_fields | {"prompt_generation", "prompt_turn_revision"}
        actual_fields = set(claim_payload)
        if actual_fields == legacy_fields:
            provenance = UserDecisionProvenance.ADAPTIVE_QUESTION
        elif frozenset(actual_fields) in {
            frozenset(native_fields),
            frozenset(native_with_kernel_fields),
        }:
            provenance = self._enum(
                UserDecisionProvenance,
                claim_payload.get("provenance"),
                "decision.provenance",
            )
            if provenance is not UserDecisionProvenance.NATIVE_PROMPT:
                raise InvalidAdaptiveControlState(
                    "native user decision fields require native-prompt provenance"
                )
        else:
            raise InvalidAdaptiveControlState(
                "user decision claim fields do not match a supported schema"
            )
        claim = UserDecisionClaim(
            workflow_id=self._text(claim_payload.get("workflow_id"), "decision.workflow_id"),
            question_workflow_revision=None
            if provenance is UserDecisionProvenance.NATIVE_PROMPT
            else self._integer(
                claim_payload.get("question_workflow_revision"),
                "decision.question_workflow_revision",
            ),
            source_goal_fingerprint=self._text(
                claim_payload.get("source_goal_fingerprint"),
                "decision.source_goal_fingerprint",
            ),
            source_intent_revision=self._integer(
                claim_payload.get("source_intent_revision"),
                "decision.source_intent_revision",
            ),
            source_revision=self._text(
                claim_payload.get("source_revision"),
                "decision.source_revision",
            ),
            question_digest=None
            if provenance is UserDecisionProvenance.NATIVE_PROMPT
            else self._text(
                claim_payload.get("question_digest"),
                "decision.question_digest",
            ),
            question_generation=None
            if provenance is UserDecisionProvenance.NATIVE_PROMPT
            else self._integer(
                claim_payload.get("question_generation"),
                "decision.question_generation",
            ),
            question_turn_revision=None
            if provenance is UserDecisionProvenance.NATIVE_PROMPT
            else self._integer(
                claim_payload.get("question_turn_revision"),
                "decision.question_turn_revision",
            ),
            prompt_digest=self._text(
                claim_payload.get("prompt_digest"),
                "decision.prompt_digest",
            ),
            prompt_reference=self._text(
                claim_payload.get("prompt_reference"),
                "decision.prompt_reference",
            ),
            prompt_generation=None
            if "prompt_generation" not in actual_fields
            else self._integer(
                claim_payload.get("prompt_generation"),
                "decision.prompt_generation",
            ),
            prompt_turn_revision=None
            if "prompt_turn_revision" not in actual_fields
            else self._integer(
                claim_payload.get("prompt_turn_revision"),
                "decision.prompt_turn_revision",
            ),
            target_kind=self._enum(
                UserDecisionTarget,
                claim_payload.get("target_kind"),
                "decision.target_kind",
            ),
            target_id=self._text(claim_payload.get("target_id"), "decision.target_id"),
            disposition=self._enum(
                UserDecisionDisposition,
                claim_payload.get("disposition"),
                "decision.disposition",
            ),
            value_summary_digest=self._text(
                claim_payload.get("value_summary_digest"),
                "decision.value_summary_digest",
            ),
            result_goal_fingerprint=self._text(
                claim_payload.get("result_goal_fingerprint"),
                "decision.result_goal_fingerprint",
            ),
            result_intent_revision=self._integer(
                claim_payload.get("result_intent_revision"),
                "decision.result_intent_revision",
            ),
            result_source_revision=self._text(
                claim_payload.get("result_source_revision"),
                "decision.result_source_revision",
            ),
            provenance=provenance,
            source_workflow_revision=(
                None
                if provenance is UserDecisionProvenance.ADAPTIVE_QUESTION
                else self._integer(
                    claim_payload.get("source_workflow_revision"),
                    "decision.source_workflow_revision",
                )
            ),
        )
        stored_digest = self._text(payload.get("decision_digest"), "decision.decision_digest")
        if not hmac.compare_digest(stored_digest, claim.decision_digest):
            raise InvalidAdaptiveControlState(
                "user decision digest does not match its canonical claim"
            )
        lineage_payload = self._mapping(
            payload.get("interpretation_lineage"),
            "decision.interpretation_lineage",
        )
        self._exact_fields(
            lineage_payload,
            {
                "authority",
                "issuer_id",
                "subject_id",
                "intent_revision",
                "source_revision",
                "receipt_digest",
                "delegation_id",
            },
            "user decision lineage",
        )
        return UserDecision(
            claim=claim,
            interpretation_lineage=self._decode_authority_receipt(lineage_payload),
        )

    def _encode_evidence(self, evidence: CriterionEvidence) -> Mapping[str, object]:
        return {
            "goal_fingerprint": evidence.goal_fingerprint,
            "criterion_id": evidence.criterion_id,
            "kind": evidence.kind.value,
            "authority": evidence.authority.value,
            "status": evidence.status.value,
            "reference": evidence.reference,
            "lineage": self._encode_authority_receipt(evidence.lineage),
            "evaluation_revision": evidence.evaluation_revision,
        }

    def _decode_evidence(self, payload: Mapping[str, object]) -> CriterionEvidence:
        return CriterionEvidence(
            goal_fingerprint=self._text(
                payload.get("goal_fingerprint"),
                "evidence.goal_fingerprint",
            ),
            criterion_id=self._text(payload.get("criterion_id"), "evidence.criterion_id"),
            kind=self._enum(EvidenceKind, payload.get("kind"), "evidence.kind"),
            authority=self._enum(
                EvidenceAuthority,
                payload.get("authority"),
                "evidence.authority",
            ),
            status=self._enum(EvidenceStatus, payload.get("status"), "evidence.status"),
            reference=self._text(payload.get("reference"), "evidence.reference"),
            lineage=self._decode_authority_receipt(
                self._mapping(payload.get("lineage"), "evidence.lineage")
            ),
            evaluation_revision=self._integer(
                payload.get("evaluation_revision"),
                "evidence.evaluation_revision",
            ),
        )

    def _encode_coverage(self, coverage: GoalCoverage) -> Mapping[str, object]:
        return {
            "goal_fingerprint": coverage.goal_fingerprint,
            "criterion_ids": sorted(coverage.criterion_ids),
            "authority": coverage.authority.value,
            "status": coverage.status.value,
            "reference": coverage.reference,
            "goal_alignment": coverage.goal_alignment,
            "semantic_drift": coverage.semantic_drift,
            "uncertainty": coverage.uncertainty,
            "reward_hacking_risk": coverage.reward_hacking_risk,
            "lineage": self._encode_authority_receipt(coverage.lineage),
            "evaluation_revision": coverage.evaluation_revision,
        }

    def _decode_coverage(self, payload: Mapping[str, object]) -> GoalCoverage:
        return GoalCoverage(
            goal_fingerprint=self._text(
                payload.get("goal_fingerprint"),
                "coverage.goal_fingerprint",
            ),
            criterion_ids=frozenset(
                self._text(item, "coverage.criterion_id")
                for item in self._list(payload.get("criterion_ids"), "coverage.criterion_ids")
            ),
            authority=self._enum(
                EvidenceAuthority,
                payload.get("authority"),
                "coverage.authority",
            ),
            status=self._enum(EvidenceStatus, payload.get("status"), "coverage.status"),
            reference=self._text(payload.get("reference"), "coverage.reference"),
            goal_alignment=self._number(
                payload.get("goal_alignment"),
                "coverage.goal_alignment",
            ),
            semantic_drift=self._number(
                payload.get("semantic_drift"),
                "coverage.semantic_drift",
            ),
            uncertainty=self._number(payload.get("uncertainty"), "coverage.uncertainty"),
            reward_hacking_risk=self._number(
                payload.get("reward_hacking_risk"),
                "coverage.reward_hacking_risk",
            ),
            lineage=self._decode_authority_receipt(
                self._mapping(payload.get("lineage"), "coverage.lineage")
            ),
            evaluation_revision=self._integer(
                payload.get("evaluation_revision"),
                "coverage.evaluation_revision",
            ),
        )

    def _encode_observation(self, observation: IterationObservation) -> Mapping[str, object]:
        return {
            "goal_fingerprint": observation.goal_fingerprint,
            "generation": observation.generation,
            "output_fingerprint": observation.output_fingerprint,
            "active_criteria": list(observation.active_criteria),
            "root_causes": list(observation.root_causes),
            "progress": observation.progress,
            "material_change": observation.material_change,
            "reproducible_harness_gap": observation.reproducible_harness_gap,
            "recovery_epoch": observation.recovery_epoch,
            "efficiency_assessment": self._encode_efficiency(observation.efficiency_assessment),
        }

    def _decode_observation(self, payload: Mapping[str, object]) -> IterationObservation:
        return IterationObservation(
            goal_fingerprint=self._text(
                payload.get("goal_fingerprint"),
                "observation.goal_fingerprint",
            ),
            generation=self._integer(payload.get("generation"), "observation.generation"),
            output_fingerprint=self._text(
                payload.get("output_fingerprint"),
                "observation.output_fingerprint",
            ),
            active_criteria=self._text_tuple(
                payload.get("active_criteria"),
                "observation.active_criteria",
            ),
            root_causes=self._text_tuple(
                payload.get("root_causes"),
                "observation.root_causes",
            ),
            progress=self._number(payload.get("progress"), "observation.progress"),
            material_change=self._boolean(
                payload.get("material_change"),
                "observation.material_change",
            ),
            reproducible_harness_gap=self._boolean(
                payload.get("reproducible_harness_gap"),
                "observation.reproducible_harness_gap",
            ),
            recovery_epoch=self._integer(
                payload.get("recovery_epoch"),
                "observation.recovery_epoch",
            ),
            efficiency_assessment=self._decode_optional_efficiency(
                payload.get("efficiency_assessment")
            ),
        )

    def _encode_efficiency(
        self,
        assessment: EfficiencyAssessment | None,
    ) -> Mapping[str, object] | None:
        if assessment is None:
            return None
        return {
            "goal_delta": {
                "before": self._encode_goal_readback(assessment.goal_delta.before),
                "after": self._encode_goal_readback(assessment.goal_delta.after),
            },
            "resource_delta": self._encode_resource_delta(assessment.resource_delta),
            "status": assessment.status.value,
            "reason": assessment.reason,
        }

    def _decode_optional_efficiency(self, value: object) -> EfficiencyAssessment | None:
        if value is None:
            return None
        payload = self._mapping(value, "efficiency assessment")
        self._exact_fields(
            payload,
            {"goal_delta", "resource_delta", "status", "reason"},
            "efficiency assessment",
        )
        goal_payload = self._mapping(payload.get("goal_delta"), "efficiency goal delta")
        self._exact_fields(goal_payload, {"before", "after"}, "efficiency goal delta")
        goal_delta = VerifiedGoalAttainmentDelta(
            before=self._decode_goal_readback(
                self._mapping(goal_payload.get("before"), "efficiency before readback")
            ),
            after=self._decode_goal_readback(
                self._mapping(goal_payload.get("after"), "efficiency after readback")
            ),
        )
        resource_delta = self._decode_resource_delta(
            self._mapping(payload.get("resource_delta"), "efficiency resource delta")
        )
        derived = EfficiencyAssessor().assess(goal_delta, resource_delta)
        stored_status = self._enum(
            EfficiencyStatus,
            payload.get("status"),
            "efficiency status",
        )
        stored_reason = self._text(payload.get("reason"), "efficiency reason")
        if derived.status is not stored_status or derived.reason != stored_reason:
            raise InvalidAdaptiveControlState(
                "efficiency status and reason must derive from goal-resource delta"
            )
        return derived

    def _encode_goal_readback(
        self,
        readback: GoalAttainmentReadback,
    ) -> Mapping[str, object]:
        return {
            "goal_fingerprint": readback.goal_fingerprint,
            "evidence_basis_fingerprint": readback.evidence_basis_fingerprint,
            "evaluation_revision": readback.evaluation_revision,
            "settled_evidence_units": sorted(readback.settled_evidence_units),
            "failed_evidence_units": sorted(readback.failed_evidence_units),
            "reopened_evidence_units": sorted(readback.reopened_evidence_units),
            "open_blocker_ids": sorted(readback.open_blocker_ids),
            "authority_source_id": readback.authority_source_id,
            "readback_reference": readback.readback_reference,
            "receipt_digest": readback.receipt_digest,
        }

    def _decode_goal_readback(self, payload: Mapping[str, object]) -> GoalAttainmentReadback:
        self._exact_fields(
            payload,
            {
                "goal_fingerprint",
                "evidence_basis_fingerprint",
                "evaluation_revision",
                "settled_evidence_units",
                "failed_evidence_units",
                "reopened_evidence_units",
                "open_blocker_ids",
                "authority_source_id",
                "readback_reference",
                "receipt_digest",
            },
            "efficiency goal readback",
        )
        return GoalAttainmentReadback(
            goal_fingerprint=self._text(payload.get("goal_fingerprint"), "goal fingerprint"),
            evidence_basis_fingerprint=self._text(
                payload.get("evidence_basis_fingerprint"),
                "evidence basis fingerprint",
            ),
            evaluation_revision=self._integer(
                payload.get("evaluation_revision"),
                "goal evaluation revision",
            ),
            settled_evidence_units=frozenset(
                self._text_tuple(payload.get("settled_evidence_units"), "settled evidence unit")
            ),
            failed_evidence_units=frozenset(
                self._text_tuple(payload.get("failed_evidence_units"), "failed evidence unit")
            ),
            reopened_evidence_units=frozenset(
                self._text_tuple(payload.get("reopened_evidence_units"), "reopened evidence unit")
            ),
            open_blocker_ids=frozenset(
                self._text_tuple(payload.get("open_blocker_ids"), "open blocker id")
            ),
            authority_source_id=self._text(
                payload.get("authority_source_id"),
                "goal authority source",
            ),
            readback_reference=self._text(
                payload.get("readback_reference"),
                "goal readback reference",
            ),
            receipt_digest=self._text(payload.get("receipt_digest"), "goal receipt digest"),
        )

    def _encode_resource_delta(
        self,
        resource: AuthoritativeResourceDelta,
    ) -> Mapping[str, object]:
        return {
            "basis_fingerprint": resource.basis_fingerprint,
            "wall_clock_milliseconds": self._encode_resource_metric(
                resource.wall_clock_milliseconds
            ),
            "tool_invocations": self._encode_resource_metric(resource.tool_invocations),
            "input_tokens": self._encode_resource_metric(resource.input_tokens),
            "output_tokens": self._encode_resource_metric(resource.output_tokens),
            "evaluator_generations": self._encode_resource_metric(resource.evaluator_generations),
        }

    def _decode_resource_delta(
        self,
        payload: Mapping[str, object],
    ) -> AuthoritativeResourceDelta:
        fields = {
            "basis_fingerprint",
            "wall_clock_milliseconds",
            "tool_invocations",
            "input_tokens",
            "output_tokens",
            "evaluator_generations",
        }
        self._exact_fields(payload, fields, "efficiency resource delta")
        return AuthoritativeResourceDelta(
            basis_fingerprint=self._text(
                payload.get("basis_fingerprint"),
                "resource basis fingerprint",
            ),
            wall_clock_milliseconds=self._decode_resource_metric(
                payload.get("wall_clock_milliseconds")
            ),
            tool_invocations=self._decode_resource_metric(payload.get("tool_invocations")),
            input_tokens=self._decode_resource_metric(payload.get("input_tokens")),
            output_tokens=self._decode_resource_metric(payload.get("output_tokens")),
            evaluator_generations=self._decode_resource_metric(
                payload.get("evaluator_generations")
            ),
        )

    def _encode_resource_metric(self, metric: ResourceMetricDelta) -> Mapping[str, object]:
        return {
            "status": metric.status.value,
            "value": metric.value,
            "source_id": metric.source_id,
            "receipt_reference": metric.receipt_reference,
            "receipt_digest": metric.receipt_digest,
        }

    def _decode_resource_metric(self, value: object) -> ResourceMetricDelta:
        payload = self._mapping(value, "efficiency resource metric")
        self._exact_fields(
            payload,
            {"status", "value", "source_id", "receipt_reference", "receipt_digest"},
            "efficiency resource metric",
        )
        status = self._enum(
            ResourceTelemetryStatus,
            payload.get("status"),
            "resource telemetry status",
        )
        raw_value = payload.get("value")
        metric_value = None if raw_value is None else self._integer(raw_value, "resource value")
        return ResourceMetricDelta(
            status=status,
            value=metric_value,
            source_id=self._optional_text(payload.get("source_id"), "resource source id"),
            receipt_reference=self._optional_text(
                payload.get("receipt_reference"),
                "resource receipt reference",
            ),
            receipt_digest=self._optional_text(
                payload.get("receipt_digest"),
                "resource receipt digest",
            ),
        )

    def _mapping(self, value: object, label: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            raise InvalidAdaptiveControlState(f"{label} must be a string-keyed object")
        return {str(key): item for key, item in value.items()}

    def _exact_fields(
        self,
        payload: Mapping[str, object],
        expected: set[str],
        label: str,
    ) -> None:
        actual = set(payload)
        if actual != expected:
            raise InvalidAdaptiveControlState(f"{label} fields do not match schema")

    def _list(self, value: object, label: str) -> list[object]:
        if not isinstance(value, list):
            raise InvalidAdaptiveControlState(f"{label} must be a list")
        return value

    def _text(self, value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidAdaptiveControlState(f"{label} must be non-empty text")
        return value

    def _optional_text(self, value: object, label: str) -> str | None:
        if value is None:
            return None
        return self._text(value, label)

    def _text_tuple(self, value: object, label: str) -> tuple[str, ...]:
        return tuple(self._text(item, label) for item in self._list(value, label))

    def _boolean(self, value: object, label: str) -> bool:
        if not isinstance(value, bool):
            raise InvalidAdaptiveControlState(f"{label} must be a boolean")
        return value

    def _integer(self, value: object, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidAdaptiveControlState(f"{label} must be an integer")
        return value

    def _number(self, value: object, label: str) -> float:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise InvalidAdaptiveControlState(f"{label} must be a number")
        return float(value)

    def _enum(
        self,
        enum_type: type[EnumValue],
        value: object,
        label: str,
    ) -> EnumValue:
        if not isinstance(value, str):
            raise InvalidAdaptiveControlState(f"{label} must be a string enum")
        try:
            return enum_type(value)
        except ValueError as error:
            raise InvalidAdaptiveControlState(f"{label} has an unknown value") from error
