"""의도 명확화, 목표 판정, 회차 반성을 하나의 순수 제어 계약으로 제공합니다."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from scripts.agent_harness.efficiency_assessment import EfficiencyAssessment

IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
OPAQUE_IDENTITY_PATTERN = re.compile(r"^\S{1,256}$")


class RequirementSection(StrEnum):
    """질문과 provenance ledger가 다루는 requirement section입니다."""

    GOAL = "goal"
    """달성하려는 최종 상태와 그 의미를 다루는 구획입니다."""
    SCOPE = "scope"
    """현재 작업에 포함되는 책임과 경계를 다루는 구획입니다."""
    NON_GOAL = "non-goal"
    """현재 작업에서 의도적으로 제외한 결과를 다루는 구획입니다."""
    CONSTRAINT = "constraint"
    """목표 달성 과정에서 지켜야 하는 제한을 다루는 구획입니다."""
    SUCCESS = "success"
    """사용자가 성공으로 인정할 관찰 결과를 다루는 구획입니다."""
    VERIFICATION = "verification"
    """성공 여부를 입증할 검증 방법을 다루는 구획입니다."""
    CONTEXT = "context"
    """판단에 필요한 배경 사실과 선행 결정을 다루는 구획입니다."""
    OWNERSHIP = "ownership"
    """결정과 산출물의 책임 주체를 다루는 구획입니다."""
    LIFECYCLE = "lifecycle"
    """상태 전이와 종료 조건을 다루는 구획입니다."""


class GapAuthority(StrEnum):
    """미해결 gap을 닫을 수 있는 사실의 소유자입니다."""

    USER = "user"
    """사용자만 확정할 수 있는 제품 의도나 승인 사실의 소유권입니다."""
    REPOSITORY = "repository"
    """저장소의 source of truth를 읽어 확정할 수 있는 사실의 소유권입니다."""
    SAFE_ASSUMPTION = "safe-assumption"
    """되돌릴 수 있고 범위가 국소적인 가정으로 닫을 수 있는 소유권입니다."""


class GapResolution(StrEnum):
    """Gap에 현재 저장된 latest-only resolution입니다."""

    OPEN = "open"
    """아직 authority가 제공한 사실로 닫히지 않은 gap입니다."""
    USER_FACT = "user-fact"
    """사용자 결정을 근거로 닫힌 gap입니다."""
    REPOSITORY_FACT = "repository-fact"
    """현재 저장소 read-back을 근거로 닫힌 gap입니다."""
    SAFE_ASSUMPTION = "safe-assumption"
    """명시적인 안전 가정을 근거로 닫힌 gap입니다."""
    BLOCKER = "blocker"
    """외부 authority가 해소 전 진행 불가로 확정한 gap입니다."""


class UserDecisionTarget(StrEnum):
    """독립 evaluator가 해석한 USER decision의 bounded consumer 종류입니다."""

    GAP = "gap"
    """사용자 해석 결과가 clarification gap의 상태를 바꾸는 대상입니다."""
    CRITERION = "criterion"
    """사용자 해석 결과가 acceptance criterion 판정을 바꾸는 대상입니다."""


class UserDecisionDisposition(StrEnum):
    """Raw response를 저장하지 않고 보존하는 closed semantic disposition입니다."""

    FACT = "fact"
    """사용자 답변이 gap을 닫는 사실로 해석됐음을 나타냅니다."""
    DEFERRED = "deferred"
    """사용자가 현재 intent에서 결정을 보류했음을 나타냅니다."""
    BLOCKED = "blocked"
    """사용자가 외부 선행 조건 때문에 진행 불가를 확정했음을 나타냅니다."""
    ACCEPTED = "accepted"
    """사용자가 criterion의 관찰 결과를 수용했음을 나타냅니다."""
    REJECTED = "rejected"
    """사용자가 criterion의 관찰 결과를 거부했음을 나타냅니다."""

class UserDecisionProvenance(StrEnum):
    """USER decision이 사용한 authenticated native source 형태입니다."""

    ADAPTIVE_QUESTION = "adaptive-question"
    """직전 canonical question과 foreground prompt context를 함께 검증합니다."""
    NATIVE_PROMPT = "native-prompt"
    """질문을 발명하지 않고 native prompt와 독립적인 typed interpretation을 검증합니다."""


class ControlAction(StrEnum):
    """하네스가 다음 한 단계에 부여하는 closed action 집합입니다."""

    ASK_USER = "ask-user"
    """가장 상류의 사용자 소유 gap 하나를 질문하는 action입니다."""
    RESEARCH = "research"
    """저장소나 primary source에서 사실을 조회하는 action입니다."""
    APPLY_SAFE_ASSUMPTION = "apply-safe-assumption"
    """명시된 국소적이고 되돌릴 수 있는 가정을 적용하는 action입니다."""
    CONTINUE = "continue"
    """현재 접근으로 아직 남은 criterion을 진행하는 action입니다."""
    ENUMERATE_INVARIANT = "enumerate-invariant"
    """재발한 기존 원인군의 불변식을 빠짐없이 열거하는 action입니다."""
    CHANGE_APPROACH = "change-approach"
    """정체나 재발을 만든 현재 접근을 교체하는 action입니다."""
    PROMOTE_HARNESS = "promote-harness"
    """재현 가능한 harness gap을 durable rule로 승격하는 action입니다."""
    AWAIT_USER = "await-user"
    """사용자 acceptance 또는 결정을 기다리는 terminal action입니다."""
    COMPLETE = "complete"
    """모든 completion authority가 충족됐음을 나타내는 action입니다."""
    BLOCKED = "blocked"
    """외부 blocker가 해소될 때까지 진행하지 않는 terminal action입니다."""
    EXHAUSTED = "exhausted"
    """목표 미달 상태에서 generation 안전 상한에 도달한 action입니다."""


class EvidenceKind(StrEnum):
    """Acceptance criterion이 요구할 수 있는 서로 대체 불가능한 evidence surface입니다."""

    EXAMPLE_TEST = "example-test"
    """구체적인 입력과 기대 결과 한 사례를 실행해 얻는 evidence입니다."""
    PROPERTY_TEST = "property-test"
    """입력 공간 전반의 불변식을 반복 검증해 얻는 evidence입니다."""
    METAMORPHIC_TEST = "metamorphic-test"
    """입력 변환 전후의 관계가 유지됨을 검증하는 evidence입니다."""
    MUTATION_TEST = "mutation-test"
    """의도적 결함을 test가 탐지하는지 검증해 얻는 evidence입니다."""
    INDEPENDENT_SEMANTIC = "independent-semantic"
    """실행 주체와 분리된 evaluator의 의미 판정 evidence입니다."""
    USER_ACCEPTANCE = "user-acceptance"
    """사용자가 실제 결과를 수용하거나 거부한 evidence입니다."""
    SOURCE_READBACK = "source-readback"
    """현재 authoritative source를 다시 읽어 얻는 evidence입니다."""


class EvidenceAuthority(StrEnum):
    """Evidence를 발행할 권한과 독립성입니다."""

    EXECUTABLE = "executable"
    """현재 source에서 실제 명령을 실행해 결과를 발행한 authority입니다."""
    INDEPENDENT_EVALUATOR = "independent-evaluator"
    """실행 주체와 분리되어 의미와 목표 정렬을 판정하는 authority입니다."""
    USER = "user"
    """제품 의도와 최종 수용 여부를 소유하는 사용자 authority입니다."""
    PRIMARY_SOURCE = "primary-source"
    """저장소나 공식 자료의 현재 상태를 직접 읽는 authority입니다."""
    SAME_CONTEXT = "same-context"
    """현재 실행 주체가 국소적 안전 가정을 발행하는 제한된 authority입니다."""


class EvidenceStatus(StrEnum):
    """Evidence가 현재 goal에 대해 내린 non-vacuous 판정입니다."""

    PASS = "pass"
    """해당 evidence가 기대 계약을 충족했다고 판정한 상태입니다."""
    FAIL = "fail"
    """해당 evidence가 기대 계약을 위반했다고 판정한 상태입니다."""
    NOT_EVALUATED = "not-evaluated"
    """해당 evidence surface가 아직 판정되지 않은 상태입니다."""
    ERROR = "error"
    """검증 자체가 정상적으로 완료되지 못한 상태입니다."""
    STALE = "stale"
    """현재 goal이나 revision에 더는 적용할 수 없는 상태입니다."""


class ExecutionStatus(StrEnum):
    """작업 실행과 목표 판정을 분리하는 execution lifecycle입니다."""

    COMPLETED = "completed"
    """실행이 끝났고 별도 completion 판정을 요청할 수 있는 상태입니다."""
    INCOMPLETE = "incomplete"
    """현재 goal을 위한 실행 작업이 아직 남아 있는 상태입니다."""
    FAILED = "failed"
    """실행이 실패해 복구 결정 없이는 계속할 수 없는 상태입니다."""


class OracleOwner(StrEnum):
    """Acceptance outcome을 최종 판정할 수 있는 authority입니다."""

    EXECUTABLE = "executable"
    """재현 가능한 실행 결과가 criterion 판정을 소유합니다."""
    INDEPENDENT_EVALUATOR = "independent-evaluator"
    """실행자와 분리된 evaluator가 의미 판정을 소유합니다."""
    USER = "user"
    """사용자가 경험과 제품 수용에 관한 판정을 소유합니다."""
    PRIMARY_SOURCE = "primary-source"
    """authoritative source의 현재 내용이 판정을 소유합니다."""


@dataclass(frozen=True, slots=True)
class AuthorityReceipt:
    """Authority label을 exact issuer, subject, revision과 digest에 결속합니다."""

    authority: EvidenceAuthority
    """Receipt를 발행할 수 있는 검증 주체의 종류입니다."""
    issuer_id: str
    """Receipt를 실제로 발행한 agent 또는 runtime의 stable identity입니다."""
    subject_id: str
    """검증 대상 작업을 수행해 독립성 비교에 쓰이는 identity입니다."""
    intent_revision: int
    """Receipt가 판정한 사용자 intent의 정확한 revision입니다."""
    source_revision: str
    """Receipt가 판정한 source snapshot의 revision입니다."""
    receipt_digest: str
    """외부 검증 결과를 내용 주소로 식별하는 SHA-256 digest입니다."""
    delegation_id: str | None = None
    """Independent evaluator를 실행자와 분리해 추적하는 delegation identity입니다."""

    def __post_init__(self) -> None:
        """Independent claim에 distinct delegated issuer가 있는지 검증합니다.

        Raises:
            ValueError: Identity, revision, digest 또는 independent delegation 계약이
                유효하지 않을 때 발생합니다.
        """
        _require_opaque_identity(self.issuer_id, "receipt issuer_id")
        _require_opaque_identity(self.subject_id, "receipt subject_id")
        _require_revision(self.intent_revision, "receipt intent_revision")
        _require_text(self.source_revision, "receipt source_revision")
        _require_digest(self.receipt_digest, "receipt digest")
        if self.delegation_id is not None:
            _require_opaque_identity(self.delegation_id, "receipt delegation_id")
        if self.authority is EvidenceAuthority.INDEPENDENT_EVALUATOR:
            if self.delegation_id is None:
                raise ValueError("independent evidence requires a delegation identity")
            if self.issuer_id == self.subject_id:
                raise ValueError("independent evidence issuer must differ from its subject")

    def is_current(self, intent_revision: int, source_revision: str) -> bool:
        """Receipt가 현재 authoritative intent와 source basis에 결속됐는지 반환합니다.

        Args:
            intent_revision: 비교할 현재 사용자 intent revision입니다.
            source_revision: 비교할 현재 source snapshot revision입니다.

        Returns:
            두 revision이 receipt의 발행 기준과 모두 같으면 `True`입니다.
        """
        return self.intent_revision == intent_revision and self.source_revision == source_revision


def user_decision_value_summary_digest(
    target: UserDecisionTarget,
    target_id: str,
    disposition: UserDecisionDisposition,
    result_goal_fingerprint: str,
    result_intent_revision: int,
    result_source_revision: str,
) -> str:
    """USER response 대신 candidate의 normalized typed effect digest를 계산합니다.

    Natural-language meaning은 이 함수가 판정하지 않습니다. Independent semantic
    evaluator가 raw response와 candidate effect의 의미적 일치를 판정하고, 이 함수는
    그 effect의 identity만 canonicalize합니다.

    Args:
        target: Typed effect를 소비할 gap 또는 criterion 종류입니다.
        target_id: Effect가 바꾸는 gap 또는 criterion의 stable identity입니다.
        disposition: Independent evaluator가 해석한 bounded semantic 결과입니다.
        result_goal_fingerprint: Effect 적용 뒤 goal contract의 fingerprint입니다.
        result_intent_revision: Effect 적용 뒤 사용자 intent revision입니다.
        result_source_revision: Effect 적용 뒤 source snapshot revision입니다.

    Returns:
        Raw response를 포함하지 않고 typed effect만 식별하는 SHA-256 digest입니다.
    """
    _require_identity(target_id, "user decision target_id")
    _require_digest(result_goal_fingerprint, "user decision result goal fingerprint")
    _require_revision(result_intent_revision, "user decision result intent revision")
    normalized_source = _require_text(
        result_source_revision,
        "user decision result source revision",
    )
    encoded = json.dumps(
        {
            "disposition": disposition.value,
            "result_goal_fingerprint": result_goal_fingerprint,
            "result_intent_revision": result_intent_revision,
            "result_source_revision": normalized_source,
            "target_id": target_id,
            "target_kind": target.value,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class UserDecisionClaim:
    """한 user response의 provenance와 normalized semantic effect를 raw 없이 보존합니다."""

    workflow_id: str
    """질문과 effect가 속한 workflow의 stable identity입니다."""
    question_workflow_revision: int | None
    """사용자 질문을 발행한 시점의 workflow revision입니다."""
    source_goal_fingerprint: str
    """사용자 답변을 받기 전 goal contract의 fingerprint입니다."""
    source_intent_revision: int
    """사용자 답변을 받기 전 intent revision입니다."""
    source_revision: str
    """사용자 답변을 받기 전 source snapshot revision입니다."""
    question_digest: str | None
    """사용자에게 제시한 canonical Socratic question의 digest입니다."""
    question_generation: int | None
    """질문이 속한 agent loop generation입니다."""
    question_turn_revision: int | None
    """질문을 발행한 foreground turn의 revision입니다."""
    prompt_digest: str
    """Raw text를 저장하지 않고 사용자 응답을 식별하는 digest입니다."""
    prompt_reference: str
    """Foreground prompt receipt를 가리키는 opaque reference입니다."""
    prompt_generation: int | None
    """사용자 응답을 수신한 agent loop generation입니다."""
    prompt_turn_revision: int | None
    """사용자 응답을 수신한 foreground turn의 revision입니다."""
    target_kind: UserDecisionTarget
    """Normalized effect를 소비할 gap 또는 criterion 종류입니다."""
    target_id: str
    """Normalized effect가 적용되는 exact target identity입니다."""
    disposition: UserDecisionDisposition
    """Independent evaluator가 raw response에서 해석한 bounded 결과입니다."""
    value_summary_digest: str
    """Raw response가 아닌 normalized typed effect의 canonical digest입니다."""
    result_goal_fingerprint: str
    """Normalized effect 적용 뒤 goal contract의 fingerprint입니다."""
    result_intent_revision: int
    """Normalized effect 적용 뒤 intent revision입니다."""
    result_source_revision: str
    """Normalized effect 적용 뒤 source snapshot revision입니다."""
    provenance: UserDecisionProvenance = UserDecisionProvenance.ADAPTIVE_QUESTION
    """Legacy rendered-question provenance 또는 authenticated native-prompt provenance입니다."""
    source_workflow_revision: int | None = None
    """NATIVE_PROMPT effect를 독립 평가한 candidate의 exact pre-effect revision입니다."""

    def __post_init__(self) -> None:
        """Provenance, effect digest와 target/disposition matrix를 검증합니다.

        Raises:
            ValueError: Provenance field, target/disposition 조합 또는 typed effect digest가
                계약과 다를 때 발생합니다.
        """
        _require_opaque_identity(self.workflow_id, "user decision workflow_id")
        if not isinstance(self.target_kind, UserDecisionTarget):
            raise ValueError("user decision target_kind must be a UserDecisionTarget")
        if not isinstance(self.disposition, UserDecisionDisposition):
            raise ValueError("user decision disposition must be a UserDecisionDisposition")
        if not isinstance(self.provenance, UserDecisionProvenance):
            raise ValueError("user decision provenance must be a UserDecisionProvenance")
        _require_digest(self.source_goal_fingerprint, "user decision source goal fingerprint")
        _require_revision(self.source_intent_revision, "user decision source intent revision")
        _require_text(self.source_revision, "user decision source revision")
        _require_digest(self.prompt_digest, "user decision prompt digest")
        _require_opaque_identity(self.prompt_reference, "user decision prompt reference")
        if self.provenance is UserDecisionProvenance.ADAPTIVE_QUESTION:
            _require_non_negative_revision(
                self.question_workflow_revision, "user decision question workflow revision")
            _require_digest(self.question_digest, "user decision question digest")
            _require_revision(self.question_generation, "user decision question generation")
            _require_non_negative_revision(
                self.question_turn_revision, "user decision question turn revision")
            _require_revision(self.prompt_generation, "user decision prompt generation")
            _require_non_negative_revision(
                self.prompt_turn_revision, "user decision prompt turn revision")
            if self.source_workflow_revision is not None:
                raise ValueError("adaptive question decision cannot carry source workflow revision")
        else:
            if any(value is not None for value in (
                self.question_workflow_revision,
                self.question_digest,
                self.question_generation,
                self.question_turn_revision,
            )):
                raise ValueError("native prompt decision cannot carry question provenance")
            _require_non_negative_revision(
                self.source_workflow_revision, "user decision source workflow revision")
            if (self.prompt_generation is None) != (self.prompt_turn_revision is None):
                raise ValueError("native prompt kernel provenance must be all-or-none")
            if self.prompt_generation is not None:
                _require_revision(self.prompt_generation, "user decision prompt generation")
                _require_non_negative_revision(
                    self.prompt_turn_revision, "user decision prompt turn revision")
        _require_identity(self.target_id, "user decision target_id")
        _require_digest(self.result_goal_fingerprint, "user decision result goal fingerprint")
        _require_revision(self.result_intent_revision, "user decision result intent revision")
        _require_text(self.result_source_revision, "user decision result source revision")
        allowed = {
            UserDecisionTarget.GAP: frozenset({
                UserDecisionDisposition.FACT,
                UserDecisionDisposition.DEFERRED,
                UserDecisionDisposition.BLOCKED,
            }),
            UserDecisionTarget.CRITERION: frozenset({
                UserDecisionDisposition.ACCEPTED,
                UserDecisionDisposition.REJECTED,
                UserDecisionDisposition.DEFERRED,
            }),
        }[self.target_kind]
        if self.disposition not in allowed:
            raise ValueError(
                f"{self.target_kind.value} user decision does not allow "
                f"{self.disposition.value} disposition"
            )
        expected_summary = user_decision_value_summary_digest(
            self.target_kind,
            self.target_id,
            self.disposition,
            self.result_goal_fingerprint,
            self.result_intent_revision,
            self.result_source_revision,
        )
        if self.value_summary_digest != expected_summary:
            raise ValueError("user decision value summary digest does not match its typed effect")

    @property
    def decision_digest(self) -> str:
        """Independent lineage를 제외한 semantic claim의 canonical SHA-256을 반환합니다.

        Returns:
            Claim의 exact field를 정렬해 계산한 SHA-256 digest입니다.
        """
        encoded = json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_payload(self) -> dict[str, object]:
        """Raw prompt text가 존재할 수 없는 exact-field claim object를 반환합니다.

        Returns:
            Claim provenance와 normalized effect만 포함한 JSON-compatible object입니다.
        """
        common = {
            "workflow_id": self.workflow_id,
            "source_goal_fingerprint": self.source_goal_fingerprint,
            "source_intent_revision": self.source_intent_revision,
            "source_revision": self.source_revision,
            "prompt_digest": self.prompt_digest,
            "prompt_reference": self.prompt_reference,
            "target_kind": self.target_kind.value,
            "target_id": self.target_id,
            "disposition": self.disposition.value,
            "value_summary_digest": self.value_summary_digest,
            "result_goal_fingerprint": self.result_goal_fingerprint,
            "result_intent_revision": self.result_intent_revision,
            "result_source_revision": self.result_source_revision,
        }
        if self.provenance is UserDecisionProvenance.ADAPTIVE_QUESTION:
            # Preserve the exact legacy field set and therefore every existing digest.
            return {
                **common,
                "question_workflow_revision": self.question_workflow_revision,
                "question_digest": self.question_digest,
                "question_generation": self.question_generation,
                "question_turn_revision": self.question_turn_revision,
                "prompt_generation": self.prompt_generation,
                "prompt_turn_revision": self.prompt_turn_revision,
            }
        native = {
            **common,
            "provenance": self.provenance.value,
            "source_workflow_revision": self.source_workflow_revision,
        }
        if self.prompt_generation is not None:
            native["prompt_generation"] = self.prompt_generation
            native["prompt_turn_revision"] = self.prompt_turn_revision
        return native


@dataclass(frozen=True, slots=True)
class UserDecision:
    """Semantic claim과 exact independent evaluator report lineage를 결합합니다."""

    claim: UserDecisionClaim
    """질문 provenance와 normalized semantic effect를 결속한 claim입니다."""
    interpretation_lineage: AuthorityReceipt
    """Claim 해석을 승인한 independent evaluator receipt입니다."""

    def __post_init__(self) -> None:
        """Interpretation이 independent current-result authority인지 검증합니다.

        Raises:
            ValueError: Lineage가 독립 evaluator 소유가 아니거나 result revision보다
                오래됐을 때 발생합니다.
        """
        lineage = self.interpretation_lineage
        if lineage.authority is not EvidenceAuthority.INDEPENDENT_EVALUATOR:
            raise ValueError("user decision interpretation requires independent evaluator")
        if not lineage.is_current(
            self.claim.result_intent_revision,
            self.claim.result_source_revision,
        ):
            raise ValueError("user decision interpretation lineage is stale")

    @property
    def reference(self) -> str:
        """Gap 또는 criterion evidence가 소비할 stable decision reference를 반환합니다.

        Returns:
            Semantic claim digest로 구성한 `user-decision:` reference입니다.
        """
        return f"user-decision:{self.claim.decision_digest}"

    def to_payload(self) -> dict[str, object]:
        """Claim과 report lineage를 raw-free JSON object로 반환합니다.

        Returns:
            Decision claim, digest와 independent lineage를 담은 JSON-compatible object입니다.
        """
        return {
            "claim": self.claim.to_payload(),
            "decision_digest": self.claim.decision_digest,
            "interpretation_lineage": _authority_payload(self.interpretation_lineage),
        }


@dataclass(frozen=True, slots=True)
class UserDeferral:
    """User-owned gap을 현재 intent에서 non-blocking으로 둔 명시적 승인입니다."""

    gap_id: str
    """사용자가 현재 intent에서 보류하기로 한 gap의 identity입니다."""
    intent_revision: int
    """보류 결정이 적용되는 사용자 intent revision입니다."""
    reason: str
    """진행을 막지 않고 결정을 미루기로 한 사용자 소유 근거입니다."""
    lineage: AuthorityReceipt
    """보류 결정을 발행한 사용자의 authority receipt입니다."""
    decision_reference: str | None = None
    """보류 effect를 승인한 typed USER decision reference입니다."""

    def __post_init__(self) -> None:
        """Deferral이 user authority와 같은 intent revision에서 왔는지 검증합니다.

        Raises:
            ValueError: Gap identity, reason, USER lineage 또는 decision reference가 현재
                intent의 보류 계약과 다를 때 발생합니다.
        """
        _require_identity(self.gap_id, "deferred gap_id")
        _require_revision(self.intent_revision, "deferral intent_revision")
        _require_text(self.reason, "deferral reason")
        if self.lineage.authority is not EvidenceAuthority.USER:
            raise ValueError("gap deferral requires user authority")
        if self.lineage.intent_revision != self.intent_revision:
            raise ValueError("gap deferral lineage must match its intent revision")
        if self.decision_reference is not None:
            reference = _require_text(self.decision_reference, "deferral decision reference")
            if not reference.startswith("user-decision:"):
                raise ValueError("deferral decision reference must identify a USER decision")


@dataclass(frozen=True, slots=True)
class ClarificationGap:
    """한 material decision과 이를 닫을 authority를 함께 보존합니다."""

    gap_id: str
    """Inventory와 질문 provenance에서 gap을 식별하는 stable identity입니다."""
    section: RequirementSection
    """이 gap이 불완전하다고 판정한 requirement 구획입니다."""
    authority: GapAuthority
    """Gap을 사실, 가정 또는 blocker로 닫을 수 있는 소유자입니다."""
    dependency_rank: int
    """질문 순서에서 더 상류인 결정을 우선하는 dependency depth입니다."""
    weight: float
    """전체 ambiguity score에 반영되는 정규화된 중요도입니다."""
    blocking: bool
    """미해결 상태가 안전한 실행을 막는지 나타내는 policy flag입니다."""
    reversible: bool
    """잘못된 가정을 적용해도 안전하게 되돌릴 수 있는지 나타냅니다."""
    scope_local: bool
    """가정의 영향이 현재 작업 범위 안에 한정되는지 나타냅니다."""
    context: str
    """사용자가 gap을 판단하는 데 필요한 현재 상황입니다."""
    question: str
    """사용자가 material decision 하나를 확정하도록 묻는 핵심 질문입니다."""
    consequence: str
    """결정을 내리지 않거나 각 선택을 할 때 생기는 작업 영향입니다."""
    recommendation: str
    """현재 근거에서 agent가 제안하는 기본 선택입니다."""
    recommendation_rationale: str
    """권고가 목표와 제약에 더 적합하다고 판단한 근거입니다."""
    intent_revision: int
    """Gap이 발견되고 평가된 사용자 intent revision입니다."""
    resolution: GapResolution = GapResolution.OPEN
    """현재 revision에서 gap에 저장된 latest-only resolution입니다."""
    evidence_reference: str | None = None
    """Resolution 또는 blocker를 다시 확인할 수 있는 evidence reference입니다."""
    resolution_lineage: AuthorityReceipt | None = None
    """Resolution을 발행한 authority와 revision을 증명하는 receipt입니다."""
    deferral: UserDeferral | None = None
    """Non-blocking USER gap을 명시적으로 보류한 사용자 결정입니다."""

    def __post_init__(self) -> None:
        """질문 선택과 ambiguity 계산에 필요한 불변식을 검증합니다.

        Raises:
            ValueError: Identity, weight, resolution lineage, blocker 또는 deferral 상태가
                authority 계약과 다를 때 발생합니다.
        """
        _require_identity(self.gap_id, "gap_id")
        _require_revision(self.intent_revision, "gap intent_revision")
        if self.dependency_rank < 0:
            raise ValueError("dependency_rank must be zero or positive")
        if not 0.0 < self.weight <= 1.0:
            raise ValueError("gap weight must be greater than zero and at most one")
        for label, value in (
            ("context", self.context),
            ("question", self.question),
            ("consequence", self.consequence),
            ("recommendation", self.recommendation),
            ("recommendation rationale", self.recommendation_rationale),
        ):
            _require_text(value, label)
        if self.resolution is GapResolution.OPEN and (
            self.evidence_reference is not None or self.resolution_lineage is not None
        ):
            raise ValueError("open gap cannot have resolution evidence")
        if self.resolution is not GapResolution.OPEN:
            _require_text(self.evidence_reference, "resolution evidence")
            if self.resolution_lineage is None:
                raise ValueError("resolved gap requires authority lineage")
            if self.resolution_lineage.intent_revision != self.intent_revision:
                raise ValueError("gap resolution lineage must match its intent revision")
            expected_authority = _gap_evidence_authority(self.authority)
            if self.resolution_lineage.authority is not expected_authority:
                raise ValueError(f"{self.authority} gap requires {expected_authority} lineage")
        if self.resolution is GapResolution.BLOCKER:
            if self.authority is GapAuthority.SAFE_ASSUMPTION:
                raise ValueError("terminal blocker requires external authority")
            if not self.blocking:
                raise ValueError("terminal blocker requires a blocking gap")
        if self.deferral is not None:
            if self.authority is not GapAuthority.USER or self.blocking:
                raise ValueError("only a non-blocking user gap can carry a deferral")
            if self.resolution is not GapResolution.OPEN:
                raise ValueError("resolved gap cannot also be deferred")
            if self.deferral.gap_id != self.gap_id:
                raise ValueError("gap deferral must reference the same gap")
            if self.deferral.intent_revision != self.intent_revision:
                raise ValueError("gap deferral must match the gap intent revision")
        if (
            self.authority is GapAuthority.USER
            and not self.blocking
            and self.resolution is GapResolution.OPEN
            and self.deferral is None
        ):
            raise ValueError("non-blocking user gap requires explicit user deferral")

    @property
    def is_resolved(self) -> bool:
        """현재 resolution이 실행에 사용할 수 있는 authoritative fact인지 반환합니다.

        Returns:
            User, repository 또는 safe-assumption fact로 닫혔을 때만 `True`입니다.
        """
        return self.resolution in {
            GapResolution.USER_FACT,
            GapResolution.REPOSITORY_FACT,
            GapResolution.SAFE_ASSUMPTION,
        }

    @property
    def is_blocked(self) -> bool:
        """현재 resolution이 externally authorized terminal blocker인지 반환합니다.

        Returns:
            Resolution이 `BLOCKER`일 때만 `True`입니다.
        """
        return self.resolution is GapResolution.BLOCKER

    def resolve(
        self,
        resolution: GapResolution,
        evidence_reference: str,
        lineage: AuthorityReceipt,
    ) -> ClarificationGap:
        """Authority와 safe-assumption 경계를 지키는 새 latest gap을 반환합니다.

        Args:
            resolution: Gap owner가 허용하는 fact resolution 종류입니다.
            evidence_reference: Resolution 근거를 다시 확인할 stable reference입니다.
            lineage: Resolution을 발행한 authority와 intent를 증명하는 receipt입니다.

        Returns:
            Identity는 유지하고 authoritative resolution만 갱신한 immutable gap입니다.

        Raises:
            ValueError: Terminal blocker를 덮어쓰거나 authority, intent 또는 안전 가정
                경계를 위반할 때 발생합니다.
        """
        if self.is_blocked:
            raise ValueError("terminal blocker cannot be resolved without a goal override")
        expected = {
            GapAuthority.USER: GapResolution.USER_FACT,
            GapAuthority.REPOSITORY: GapResolution.REPOSITORY_FACT,
            GapAuthority.SAFE_ASSUMPTION: GapResolution.SAFE_ASSUMPTION,
        }[self.authority]
        if resolution is not expected:
            raise ValueError(f"{self.authority} gap requires {expected}, not {resolution}")
        expected_authority = _gap_evidence_authority(self.authority)
        if lineage.authority is not expected_authority:
            raise ValueError(f"{self.authority} gap requires {expected_authority} lineage")
        if lineage.intent_revision != self.intent_revision:
            raise ValueError("gap resolution lineage must match the gap intent revision")
        if resolution is GapResolution.SAFE_ASSUMPTION and not (
            self.reversible and self.scope_local and not self.blocking
        ):
            raise ValueError("safe assumption requires a reversible, local, non-blocking gap")
        return replace(
            self,
            resolution=resolution,
            evidence_reference=_require_text(evidence_reference, "resolution evidence"),
            resolution_lineage=lineage,
            deferral=None,
        )

    def mark_blocked(
        self,
        evidence_reference: str,
        lineage: AuthorityReceipt,
    ) -> ClarificationGap:
        """External authority가 입증한 terminal blocker resolution을 반환합니다.

        Args:
            evidence_reference: Terminal 판정을 재확인할 수 있는 non-empty reference입니다.
            lineage: Gap owner와 일치하는 external authority receipt입니다.

        Returns:
            기존 gap identity를 보존한 terminal blocker snapshot입니다.

        Raises:
            ValueError: Gap이 open이 아니거나 external authority와 intent가 맞지 않으면
                발생합니다.
        """
        if self.resolution is not GapResolution.OPEN or self.deferral is not None:
            raise ValueError("only an open non-deferred gap can become a terminal blocker")
        if self.authority is GapAuthority.SAFE_ASSUMPTION:
            raise ValueError("terminal blocker requires external authority")
        expected_authority = _gap_evidence_authority(self.authority)
        if lineage.authority is not expected_authority:
            raise ValueError(f"{self.authority} blocker requires {expected_authority} lineage")
        if lineage.intent_revision != self.intent_revision:
            raise ValueError("blocker lineage must match the gap intent revision")
        return replace(
            self,
            resolution=GapResolution.BLOCKER,
            evidence_reference=_require_text(evidence_reference, "blocker evidence"),
            resolution_lineage=lineage,
            deferral=None,
        )

    def is_blocked_for(self, inventory: GapInventory) -> bool:
        """Terminal blocker가 current intent와 source basis에서 유효한지 반환합니다.

        Args:
            inventory: Blocker provenance를 대조할 current intent/source basis입니다.

        Returns:
            Blocker lineage가 exact inventory revision에 결속됐을 때만 `True`입니다.
        """
        return (
            self.is_blocked
            and self.intent_revision == inventory.intent_revision
            and self.resolution_lineage is not None
            and self.resolution_lineage.is_current(
                inventory.intent_revision,
                inventory.source_revision,
            )
        )

    def is_resolved_for(self, inventory: GapInventory) -> bool:
        """Resolution 또는 deferral이 현재 inventory basis에서 유효한지 반환합니다.

        Args:
            inventory: Resolution lineage를 대조할 현재 intent/source basis입니다.

        Returns:
            Stored fact 또는 deferral이 current inventory에 결속돼 있으면 `True`입니다.
        """
        if self.intent_revision != inventory.intent_revision:
            return False
        if self.deferral is not None:
            return (
                self.deferral.intent_revision == inventory.intent_revision
                and self.deferral.lineage.intent_revision == inventory.intent_revision
            )
        if not self.is_resolved or self.resolution_lineage is None:
            return False
        if self.resolution_lineage.intent_revision != inventory.intent_revision:
            return False
        if self.authority is GapAuthority.REPOSITORY:
            return self.resolution_lineage.source_revision == inventory.source_revision
        return True

    def is_stale_for(self, inventory: GapInventory) -> bool:
        """저장된 authority가 있지만 current inventory에는 유효하지 않은지 반환합니다.

        Args:
            inventory: Stored authority의 freshness를 판정할 현재 basis입니다.

        Returns:
            Resolution, blocker 또는 deferral이 존재하지만 current basis와 다르면 `True`입니다.
        """
        if self.is_blocked:
            return not self.is_blocked_for(inventory)
        return (self.is_resolved or self.deferral is not None) and not self.is_resolved_for(
            inventory
        )


def render_socratic_question(gap: ClarificationGap) -> str:
    """저장된 gap 설명 전체를 canonical user-facing 질문 하나로 렌더링합니다.

    Args:
        gap: Current inventory가 선택한 exact clarification gap입니다.

    Returns:
        Context, consequence, recommendation, rationale와 question을 고정된 순서로
        보존한 deterministic prompt입니다.
    """
    return "\n".join((
        f"[맥락] {gap.context}",
        f"[영향] {gap.consequence}",
        f"[권고] {gap.recommendation}",
        f"[권고 근거] {gap.recommendation_rationale}",
        f"[질문] {gap.question}",
    ))


@dataclass(frozen=True, slots=True)
class GapInventory:
    """한 intent/source revision에서 실제로 평가한 clarification gap 집합입니다."""

    intent_revision: int
    """Inventory가 완전성을 평가한 사용자 intent revision입니다."""
    source_revision: str
    """Repository fact의 freshness를 판정할 source snapshot revision입니다."""
    assessed_sections: frozenset[RequirementSection]
    """현재 basis에서 실제로 확인을 마친 closed requirement 구획입니다."""
    gaps: tuple[ClarificationGap, ...]
    """확인 과정에서 발견해 동일 intent에 결속한 clarification gap 집합입니다."""

    def __post_init__(self) -> None:
        """Inventory basis와 gap identity를 검증합니다.

        Raises:
            ValueError: Revision, source, gap identity 또는 assessed-section 소속이
                invalid하면 발생합니다.
        """
        _require_revision(self.intent_revision, "inventory intent_revision")
        _require_text(self.source_revision, "inventory source_revision")
        _require_unique((gap.gap_id for gap in self.gaps), "gap")
        if any(gap.section not in self.assessed_sections for gap in self.gaps):
            raise ValueError("gap section must belong to the assessed requirement sections")
        if any(gap.intent_revision != self.intent_revision for gap in self.gaps):
            raise ValueError("gap must belong to the inventory intent revision")

    @property
    def assessment_complete(self) -> bool:
        """모든 requirement section을 current basis에서 확인했는지 반환합니다.

        Returns:
            Closed `RequirementSection` 전체를 평가했을 때만 `True`입니다.
        """
        return self.assessed_sections == frozenset(RequirementSection)


@dataclass(frozen=True, slots=True)
class AmbiguityAssessment:
    """Score를 우선순위로만 쓰고 blocker를 별도 veto로 보존한 결과입니다."""

    score: float
    """현재 unresolved gap weight를 정규화한 우선순위 지표입니다."""
    ready: bool
    """모든 구획과 blocking gap이 실행 가능한 상태인지 나타냅니다."""
    action: ControlAction
    """현재 ambiguity 상태가 요구하는 deterministic next action입니다."""
    selected_gap_id: str | None
    """다음 질문, 조사, 가정 또는 blocker로 선택한 exact gap identity입니다."""
    unresolved_gap_ids: tuple[str, ...]
    """현재 inventory에서 authoritative fact로 닫히지 않은 gap identity입니다."""
    stale_gap_ids: tuple[str, ...]
    """Stored authority가 current basis에 적용되지 않는 gap identity입니다."""
    assessment_complete: bool
    """Closed requirement section 전체를 평가했는지 나타냅니다."""


def assess_ambiguity(
    inventory: GapInventory,
    *,
    threshold: float = 0.20,
) -> AmbiguityAssessment:
    """모든 gap을 deterministic하게 계산하고 다음 하나의 action을 선택합니다.

    Args:
        inventory: 동일 intent/source basis에서 완전하게 수집한 gap inventory입니다.
        threshold: Ready 여부를 가르는 unresolved weight 비율의 상한입니다.

    Returns:
        전체 gap 상태와 가장 상류의 next action을 결속한 ambiguity 판정입니다.

    Raises:
        ValueError: Threshold가 0과 1 사이의 정규화 범위를 벗어날 때 발생합니다.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("ambiguity threshold must be between zero and one")
    gaps = inventory.gaps
    current_blockers = tuple(gap for gap in gaps if gap.is_blocked_for(inventory))
    if current_blockers:
        selected = min(
            current_blockers,
            key=lambda gap: (
                gap.dependency_rank,
                _gap_authority_priority(gap),
                -gap.weight,
                gap.gap_id,
            ),
        )
        return AmbiguityAssessment(
            score=1.0,
            ready=False,
            action=ControlAction.BLOCKED,
            selected_gap_id=selected.gap_id,
            unresolved_gap_ids=tuple(
                sorted(gap.gap_id for gap in gaps if not gap.is_resolved_for(inventory))
            ),
            stale_gap_ids=tuple(sorted(gap.gap_id for gap in gaps if gap.is_stale_for(inventory))),
            assessment_complete=inventory.assessment_complete,
        )
    if not inventory.assessment_complete:
        return AmbiguityAssessment(
            score=1.0,
            ready=False,
            action=ControlAction.BLOCKED,
            selected_gap_id=None,
            unresolved_gap_ids=tuple(sorted(gap.gap_id for gap in gaps)),
            stale_gap_ids=tuple(sorted(gap.gap_id for gap in gaps if gap.is_stale_for(inventory))),
            assessment_complete=False,
        )
    total_weight = sum(gap.weight for gap in gaps)
    unresolved = tuple(gap for gap in gaps if not gap.is_resolved_for(inventory))
    unresolved_weight = sum(gap.weight for gap in unresolved)
    score = 0.0 if total_weight == 0.0 else round(unresolved_weight / total_weight, 6)
    blockers = tuple(
        gap
        for gap in unresolved
        if gap.blocking
        or (
            gap.authority is GapAuthority.USER
            and gap.deferral is not None
            and gap.is_stale_for(inventory)
        )
    )
    stale_gap_ids = tuple(sorted(gap.gap_id for gap in gaps if gap.is_stale_for(inventory)))
    ready = not blockers and score <= threshold
    if ready:
        return AmbiguityAssessment(
            score=score,
            ready=True,
            action=ControlAction.CONTINUE,
            selected_gap_id=None,
            unresolved_gap_ids=tuple(sorted(gap.gap_id for gap in unresolved)),
            stale_gap_ids=stale_gap_ids,
            assessment_complete=True,
        )
    selected = min(
        unresolved,
        key=lambda gap: (
            gap.dependency_rank,
            _gap_authority_priority(gap),
            -gap.weight,
            gap.gap_id,
        ),
    )
    action = {
        GapAuthority.USER: ControlAction.ASK_USER,
        GapAuthority.REPOSITORY: ControlAction.RESEARCH,
        GapAuthority.SAFE_ASSUMPTION: (
            ControlAction.APPLY_SAFE_ASSUMPTION
            if selected.reversible and selected.scope_local and not selected.blocking
            else ControlAction.BLOCKED
        ),
    }[selected.authority]
    return AmbiguityAssessment(
        score=score,
        ready=False,
        action=action,
        selected_gap_id=selected.gap_id,
        unresolved_gap_ids=tuple(sorted(gap.gap_id for gap in unresolved)),
        stale_gap_ids=stale_gap_ids,
        assessment_complete=True,
    )


@dataclass(frozen=True, slots=True)
class CriterionSpec:
    """한 acceptance criterion과 필요한 evidence surface를 고정합니다."""

    criterion_id: str
    """Goal contract 안에서 criterion을 식별하는 stable identity입니다."""
    description: str
    """Criterion이 보호하는 사용자 관찰 결과의 간결한 설명입니다."""
    source_requirement_id: str
    """Criterion이 직접 증명해야 하는 approved requirement identity입니다."""
    approved_requirement_fingerprint: str
    """Criterion 작성 시점의 goal boundary를 고정한 canonical digest입니다."""
    observer: str
    """Expected outcome을 실제로 관찰하고 판정하는 주체입니다."""
    precondition: str
    """Criterion을 평가하기 전에 성립해야 하는 환경과 상태입니다."""
    stimulus: str
    """Expected outcome을 유발하기 위해 수행하는 행동이나 입력입니다."""
    expected_outcome: str
    """Observer가 성공으로 확인해야 하는 구체적인 관찰 결과입니다."""
    oracle_owner: OracleOwner
    """Criterion의 최종 outcome 판정을 소유하는 authority입니다."""
    hard: bool
    """Criterion이 completion에서 생략할 수 없는 hard requirement인지 나타냅니다."""
    required_evidence: frozenset[EvidenceKind]
    """Criterion completion에 conjunctive하게 필요한 evidence surface입니다."""

    def __post_init__(self) -> None:
        """Vacuous 또는 identity 없는 acceptance criterion을 거부합니다.

        Raises:
            ValueError: Identity, 관찰 계약, evidence 집합 또는 oracle ownership이
                비어 있거나 서로 일치하지 않을 때 발생합니다.
        """
        _require_identity(self.criterion_id, "criterion_id")
        _require_text(self.description, "criterion description")
        _require_identity(self.source_requirement_id, "source requirement_id")
        _require_digest(
            self.approved_requirement_fingerprint,
            "approved requirement fingerprint",
        )
        for label, value in (
            ("criterion observer", self.observer),
            ("criterion precondition", self.precondition),
            ("criterion stimulus", self.stimulus),
            ("criterion expected_outcome", self.expected_outcome),
        ):
            _require_text(value, label)
        if not self.required_evidence:
            raise ValueError("criterion requires at least one evidence kind")
        required_authorities = frozenset(_authority_for(kind) for kind in self.required_evidence)
        oracle_authority = _oracle_authority(self.oracle_owner)
        if oracle_authority not in required_authorities:
            raise ValueError("criterion oracle owner must have a matching evidence surface")


def approved_requirement_fingerprint(
    goal: str,
    constraints: tuple[str, ...],
    non_goals: tuple[str, ...],
    intent_revision: int,
    source_revision: str,
) -> str:
    """승인된 goal boundary를 criterion이 재사용할 canonical digest로 고정합니다.

    Args:
        goal: 사용자와 합의한 현재 north-star 문장입니다.
        constraints: Goal 달성 중 계속 지켜야 할 hard boundary입니다.
        non_goals: 현재 loop가 새로 열어서는 안 되는 범위입니다.
        intent_revision: 사용자 의도가 마지막으로 교정된 단조 증가 revision입니다.
        source_revision: 승인된 source basis를 식별하는 current revision입니다.

    Returns:
        순서 비의존 collection과 current revision을 포함한 SHA-256 digest입니다.

    Raises:
        ValueError: Goal, revision 또는 collection entry가 canonical contract가 아니면
            발생합니다.
    """
    normalized_goal = _require_text(goal, "goal")
    _require_revision(intent_revision, "goal intent_revision")
    normalized_source = _require_text(source_revision, "goal source_revision")
    normalized: dict[str, tuple[str, ...]] = {}
    for label, values in (("constraints", constraints), ("non_goals", non_goals)):
        entries = tuple(value.strip() for value in values)
        if any(not value for value in entries):
            raise ValueError(f"{label.removesuffix('s')} entries must be non-empty")
        normalized[label] = tuple(sorted(entries))
    encoded = json.dumps(
        {
            "constraints": normalized["constraints"],
            "goal": normalized_goal,
            "intent_revision": intent_revision,
            "non_goals": normalized["non_goals"],
            "source_revision": normalized_source,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class GoalContract:
    """사용자 goal, hard constraint, acceptance, non-goal의 immutable snapshot입니다."""

    goal: str
    """현재 loop가 달성해야 하는 사용자 소유 north-star 문장입니다."""
    constraints: tuple[str, ...]
    """Goal을 달성하는 동안 계속 지켜야 하는 hard boundary입니다."""
    requirement_ids: frozenset[str]
    """모든 criterion이 빠짐없이 증명해야 하는 closed requirement ledger입니다."""
    criteria: tuple[CriterionSpec, ...]
    """Goal completion을 관찰 가능한 결과로 판정하는 criterion 집합입니다."""
    non_goals: tuple[str, ...]
    """현재 loop가 확장하거나 새로 열어서는 안 되는 명시적 범위입니다."""
    intent_revision: int
    """Contract가 반영한 사용자의 최신 intent revision입니다."""
    source_revision: str
    """Contract와 criterion이 승인된 source snapshot revision입니다."""

    def __post_init__(self) -> None:
        """Goal completion이 빈 집합의 참으로 변하지 않도록 snapshot을 검증합니다.

        Raises:
            ValueError: Goal, revision, requirement ledger, criterion coverage 또는 approved
                requirement binding이 closed contract를 이루지 못할 때 발생합니다.
        """
        _require_text(self.goal, "goal")
        _require_revision(self.intent_revision, "goal intent_revision")
        _require_text(self.source_revision, "goal source_revision")
        if not self.criteria:
            raise ValueError("nontrivial goal requires at least one acceptance criterion")
        if not any(item.hard for item in self.criteria):
            raise ValueError("nontrivial goal requires at least one hard acceptance criterion")
        if not self.requirement_ids:
            raise ValueError("nontrivial goal requires a requirement identity ledger")
        for requirement_id in self.requirement_ids:
            _require_identity(requirement_id, "requirement_id")
        _require_unique((item.criterion_id for item in self.criteria), "criterion")
        criterion_requirements = frozenset(item.source_requirement_id for item in self.criteria)
        if criterion_requirements != self.requirement_ids:
            raise ValueError(
                "criterion source requirements must exactly cover the requirement ledger"
            )
        for label, values in (
            ("constraint", self.constraints),
            ("non-goal", self.non_goals),
        ):
            if any(not value.strip() for value in values):
                raise ValueError(f"{label} entries must be non-empty")
        expected_requirement = self.approved_requirement_fingerprint
        if any(
            item.approved_requirement_fingerprint != expected_requirement for item in self.criteria
        ):
            raise ValueError("criterion is not bound to the current approved requirement")

    @property
    def approved_requirement_fingerprint(self) -> str:
        """모든 criterion이 공유해야 할 current north-star boundary digest를 반환합니다.

        Returns:
            Goal, constraint, non-goal, intent와 source revision의 canonical digest입니다.
        """
        return approved_requirement_fingerprint(
            self.goal,
            self.constraints,
            self.non_goals,
            self.intent_revision,
            self.source_revision,
        )

    @property
    def fingerprint(self) -> str:
        """순서가 의미가 없는 collection을 canonicalize한 semantic digest를 반환합니다.

        Returns:
            Goal boundary와 모든 criterion field를 결속한 SHA-256 fingerprint입니다.
        """
        payload = {
            "goal": self.goal.strip(),
            "intent_revision": self.intent_revision,
            "source_revision": self.source_revision,
            "constraints": sorted(value.strip() for value in self.constraints),
            "requirement_ids": sorted(self.requirement_ids),
            "criteria": sorted(
                (
                    {
                        "criterion_id": item.criterion_id,
                        "description": item.description.strip(),
                        "source_requirement_id": item.source_requirement_id,
                        "approved_requirement_fingerprint": (item.approved_requirement_fingerprint),
                        "observer": item.observer.strip(),
                        "precondition": item.precondition.strip(),
                        "stimulus": item.stimulus.strip(),
                        "expected_outcome": item.expected_outcome.strip(),
                        "oracle_owner": item.oracle_owner.value,
                        "hard": item.hard,
                        "required_evidence": sorted(kind.value for kind in item.required_evidence),
                    }
                    for item in self.criteria
                ),
                key=lambda item: str(item["criterion_id"]),
            ),
            "non_goals": sorted(value.strip() for value in self.non_goals),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CriterionEvidence:
    """현재 goal과 criterion에 결속된 한 evidence surface 판정입니다."""

    goal_fingerprint: str
    """Evidence가 판정한 immutable goal contract의 fingerprint입니다."""
    criterion_id: str
    """Evidence가 직접 판정한 acceptance criterion identity입니다."""
    kind: EvidenceKind
    """서로 대체할 수 없는 검증 surface의 종류입니다."""
    authority: EvidenceAuthority
    """해당 evidence kind를 발행할 수 있는 authority입니다."""
    status: EvidenceStatus
    """현재 evaluation revision이 criterion에 내린 non-vacuous 판정입니다."""
    reference: str
    """실행 결과나 평가 보고서를 다시 확인할 수 있는 reference입니다."""
    lineage: AuthorityReceipt
    """Evidence issuer와 current intent/source를 증명하는 receipt입니다."""
    evaluation_revision: int = 1
    """같은 criterion과 surface에서 최신 판정을 가리는 단조 증가 revision입니다."""

    def __post_init__(self) -> None:
        """Evidence가 자기 surface의 발행 권한을 가장하지 못하게 검증합니다.

        Raises:
            ValueError: Goal, criterion, reference, revision 또는 kind별 authority와 lineage가
                evidence 계약에 맞지 않을 때 발생합니다.
        """
        _require_digest(self.goal_fingerprint, "goal_fingerprint")
        _require_identity(self.criterion_id, "criterion_id")
        _require_text(self.reference, "evidence reference")
        _require_revision(self.evaluation_revision, "evidence evaluation_revision")
        expected = _authority_for(self.kind)
        if self.authority is not expected:
            raise ValueError(f"{self.kind} evidence requires {expected}, not {self.authority}")
        if self.lineage.authority is not self.authority:
            raise ValueError("evidence authority must match its issuer lineage")


@dataclass(frozen=True, slots=True)
class GoalCoverage:
    """Goal과 criterion 집합의 의미적 coverage를 별도 권한으로 판정합니다."""

    goal_fingerprint: str
    """Coverage가 의미적 완전성을 평가한 goal contract fingerprint입니다."""
    criterion_ids: frozenset[str]
    """Coverage evaluator가 빠짐없이 검토한 exact criterion identity 집합입니다."""
    authority: EvidenceAuthority
    """Goal-level 의미 판정을 발행한 evidence authority입니다."""
    status: EvidenceStatus
    """Coverage evaluator가 현재 revision에 내린 overall 판정입니다."""
    reference: str
    """독립 평가 결과를 다시 확인할 수 있는 report reference입니다."""
    goal_alignment: float
    """Criterion 집합이 사용자 goal을 직접 다루는 정도입니다."""
    semantic_drift: float
    """판정 기준이 approved goal 의미에서 벗어난 정도입니다."""
    uncertainty: float
    """Evaluator가 coverage 판정에 남긴 의미적 불확실성입니다."""
    reward_hacking_risk: float
    """측정값 충족이 실제 목표를 대체할 위험의 정도입니다."""
    lineage: AuthorityReceipt
    """Coverage issuer와 current intent/source를 증명하는 receipt입니다."""
    evaluation_revision: int = 1
    """Goal-level coverage의 latest 판정을 가리는 단조 증가 revision입니다."""

    def __post_init__(self) -> None:
        """Coverage receipt의 identity와 non-empty evidence를 검증합니다.

        Raises:
            ValueError: Goal, criterion set, reference, authority, revision 또는 정규화된
                coverage metric이 계약 범위를 벗어날 때 발생합니다.
        """
        _require_digest(self.goal_fingerprint, "goal_fingerprint")
        _require_revision(self.evaluation_revision, "coverage evaluation_revision")
        if not self.criterion_ids:
            raise ValueError("goal coverage cannot be empty")
        _require_unique(self.criterion_ids, "coverage criterion")
        for criterion_id in self.criterion_ids:
            _require_identity(criterion_id, "coverage criterion_id")
        _require_text(self.reference, "coverage reference")
        if self.lineage.authority is not self.authority:
            raise ValueError("coverage authority must match its issuer lineage")
        for label, value in (
            ("goal_alignment", self.goal_alignment),
            ("semantic_drift", self.semantic_drift),
            ("uncertainty", self.uncertainty),
            ("reward_hacking_risk", self.reward_hacking_risk),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be between zero and one")


def effective_criterion_evidence(
    evidence: tuple[CriterionEvidence, ...],
    *,
    goal_fingerprint: str,
    intent_revision: int,
    source_revision: str,
) -> tuple[CriterionEvidence, ...]:
    """각 criterion/evidence surface의 current latest evaluation set을 반환합니다.

    동일한 latest revision에 PASS와 non-pass가 함께 있으면 두 receipt를 모두 보존하므로
    caller가 non-compensating failure 또는 pending veto를 적용할 수 있습니다. 이전
    revision은 history로 남지만 current 판정 집합에서는 제외됩니다.

    Args:
        evidence: Append-only history에 저장된 모든 criterion evidence입니다.
        goal_fingerprint: Current goal contract의 exact fingerprint입니다.
        intent_revision: Current user intent revision입니다.
        source_revision: Current source snapshot revision입니다.

    Returns:
        Current basis와 일치하는 각 criterion/surface의 latest revision receipt입니다.
    """
    current = tuple(
        item
        for item in evidence
        if item.goal_fingerprint == goal_fingerprint
        and item.lineage.is_current(intent_revision, source_revision)
    )
    latest_revisions: dict[tuple[str, EvidenceKind], int] = {}
    for item in current:
        key = (item.criterion_id, item.kind)
        latest_revisions[key] = max(
            item.evaluation_revision,
            latest_revisions.get(key, 0),
        )
    return tuple(
        item
        for item in current
        if item.evaluation_revision == latest_revisions[(item.criterion_id, item.kind)]
    )


def adaptive_output_fingerprint(
    contract: GoalContract,
    inventory: GapInventory,
    evidence: tuple[CriterionEvidence, ...],
    coverage: GoalCoverage | None,
    execution_status: ExecutionStatus,
    user_decisions: tuple[UserDecision, ...] = (),
) -> str:
    """Observation 밖의 canonical adaptive state를 SHA-256 output identity로 만듭니다.

    Root-cause prose나 caller label은 fingerprint에 참여하지 않습니다. 따라서 reflection의
    material-change 판정은 실제 goal, intent, authority와 execution state 변화에서만
    파생됩니다.

    Args:
        contract: 현재 adaptive loop가 보존하는 immutable goal contract입니다.
        inventory: Current intent/source에서 평가한 clarification inventory입니다.
        evidence: Append-only criterion evidence history입니다.
        coverage: 독립 evaluator의 current goal-level coverage 또는 미평가 상태입니다.
        execution_status: 목표 판정과 분리해 저장한 현재 실행 lifecycle입니다.
        user_decisions: Raw prompt 없이 보존한 typed USER decision history입니다.

    Returns:
        Reflection이 material change를 비교할 canonical SHA-256 output identity입니다.
    """
    payload = {
        "contract_fingerprint": contract.fingerprint,
        "inventory": {
            "intent_revision": inventory.intent_revision,
            "source_revision": inventory.source_revision,
            "assessed_sections": sorted(item.value for item in inventory.assessed_sections),
            "gaps": [
                _gap_payload(item) for item in sorted(inventory.gaps, key=lambda gap: gap.gap_id)
            ],
        },
        "evidence": [
            _evidence_payload(item)
            for item in sorted(
                evidence,
                key=lambda receipt: (
                    receipt.criterion_id,
                    receipt.kind.value,
                    receipt.evaluation_revision,
                    receipt.status.value,
                    receipt.reference,
                    receipt.lineage.receipt_digest,
                ),
            )
        ],
        "coverage": None if coverage is None else _coverage_payload(coverage),
        "execution_status": execution_status.value,
        "user_decisions": [
            item.to_payload()
            for item in sorted(
                user_decisions,
                key=lambda decision: decision.claim.decision_digest,
            )
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class GoalAttainment:
    """Progress와 authoritative completion을 분리한 goal 판정입니다."""

    goal_fingerprint: str
    """Attainment이 판정한 immutable goal contract fingerprint입니다."""
    achieved: bool
    """모든 criterion, coverage와 execution authority가 충족됐는지 나타냅니다."""
    progress: float
    """필수 evidence surface 중 current PASS가 차지하는 정규화 비율입니다."""
    action: ControlAction
    """현재 completion 판정에서 직접 파생된 next action입니다."""
    failed: tuple[str, ...]
    """Latest current evidence에 non-compensating failure가 있는 criterion입니다."""
    pending: tuple[str, ...]
    """필수 evidence, coverage 또는 execution authority가 남은 identity입니다."""
    stale: tuple[str, ...]
    """과거 evidence는 있지만 current goal/source에 적용되지 않는 criterion입니다."""
    settled: tuple[str, ...]
    """모든 필수 evidence surface가 current PASS인 criterion입니다."""


def assess_goal_attainment(
    contract: GoalContract,
    evidence: tuple[CriterionEvidence, ...],
    coverage: GoalCoverage | None,
    execution_status: ExecutionStatus,
) -> GoalAttainment:
    """Evidence conjunction만으로 현재 immutable goal의 달성 여부를 판정합니다.

    Args:
        contract: 판정 대상인 closed immutable goal contract입니다.
        evidence: Criterion별 append-only evidence history입니다.
        coverage: 독립 evaluator의 current goal-level coverage 판정입니다.
        execution_status: 목표 판정과 분리된 현재 실행 lifecycle입니다.

    Returns:
        Progress, failure, pending authority와 completion action을 담은 판정입니다.
    """
    criterion_ids = frozenset(item.criterion_id for item in contract.criteria)
    coverage_identity_valid = (
        coverage is not None
        and coverage.goal_fingerprint == contract.fingerprint
        and coverage.criterion_ids == criterion_ids
        and coverage.authority is EvidenceAuthority.INDEPENDENT_EVALUATOR
        and coverage.status is EvidenceStatus.PASS
        and coverage.lineage.is_current(
            contract.intent_revision,
            contract.source_revision,
        )
    )
    effective = effective_criterion_evidence(
        evidence,
        goal_fingerprint=contract.fingerprint,
        intent_revision=contract.intent_revision,
        source_revision=contract.source_revision,
    )
    failed: list[str] = []
    pending: list[str] = []
    stale: list[str] = []
    settled: list[str] = []
    required_count = sum(len(item.required_evidence) for item in contract.criteria)
    passed_count = 0
    for criterion in contract.criteria:
        current = tuple(
            receipt for receipt in effective if receipt.criterion_id == criterion.criterion_id
        )
        obsolete = tuple(
            receipt
            for receipt in evidence
            if receipt.criterion_id == criterion.criterion_id
            and (
                receipt.goal_fingerprint != contract.fingerprint
                or not receipt.lineage.is_current(
                    contract.intent_revision,
                    contract.source_revision,
                )
            )
        )
        criterion_failed = False
        criterion_pending = False
        for kind in criterion.required_evidence:
            matching = tuple(receipt for receipt in current if receipt.kind is kind)
            if any(
                receipt.status
                in {
                    EvidenceStatus.FAIL,
                    EvidenceStatus.ERROR,
                    EvidenceStatus.STALE,
                }
                for receipt in matching
            ):
                criterion_failed = True
            elif any(receipt.status is EvidenceStatus.NOT_EVALUATED for receipt in matching):
                criterion_pending = True
            elif any(receipt.status is EvidenceStatus.PASS for receipt in matching):
                passed_count += 1
            else:
                criterion_pending = True
        if obsolete and (criterion_pending or criterion_failed):
            stale.append(criterion.criterion_id)
        if criterion_failed:
            failed.append(criterion.criterion_id)
        if criterion_pending:
            pending.append(criterion.criterion_id)
        if not criterion_failed and not criterion_pending:
            settled.append(criterion.criterion_id)
    if not coverage_identity_valid:
        pending.insert(0, "goal-coverage")
    elif coverage is not None:
        if coverage.goal_alignment < 0.70:
            pending.append("goal-alignment")
        if coverage.semantic_drift > 0.30:
            pending.append("semantic-drift")
        if coverage.uncertainty > 0.30:
            pending.append("semantic-uncertainty")
        if coverage.reward_hacking_risk >= 0.70:
            pending.append("reward-hacking-risk")
    if execution_status is not ExecutionStatus.COMPLETED:
        pending.append("execution")
    achieved = coverage_identity_valid and not failed and not pending
    user_pending = any(
        item.criterion_id in pending and EvidenceKind.USER_ACCEPTANCE in item.required_evidence
        for item in contract.criteria
    )
    action = (
        ControlAction.COMPLETE
        if achieved
        else ControlAction.AWAIT_USER
        if user_pending
        else ControlAction.CONTINUE
    )
    return GoalAttainment(
        goal_fingerprint=contract.fingerprint,
        achieved=achieved,
        progress=0.0 if required_count == 0 else round(passed_count / required_count, 6),
        action=action,
        failed=tuple(sorted(failed)),
        pending=tuple(pending),
        stale=tuple(sorted(stale)),
        settled=tuple(sorted(settled)),
    )


def reflection_scope(
    contract: GoalContract,
    attainment: GoalAttainment,
    *,
    challenged: tuple[str, ...],
    regressed: tuple[str, ...],
) -> tuple[str, ...]:
    """Settled work를 보호하고 explicit challenge/regression만 다시 엽니다.

    Args:
        contract: Reflection 대상 criterion identity를 소유한 goal contract입니다.
        attainment: Current evidence에서 계산한 goal attainment 판정입니다.
        challenged: 독립 검토가 명시적으로 다시 연 criterion identity입니다.
        regressed: 새 변경으로 회귀했다고 관찰된 criterion identity입니다.

    Returns:
        Failed, pending, challenged 또는 regressed 상태인 criterion을 contract 순서로
        정렬한 active scope입니다.

    Raises:
        ValueError: Challenge 또는 regression이 contract에 없는 criterion을 가리킬 때
            발생합니다.
    """
    known = {item.criterion_id for item in contract.criteria}
    requested = set(challenged) | set(regressed)
    if not requested.issubset(known):
        raise ValueError("reflection scope references an unknown criterion")
    active = (set(attainment.failed) | set(attainment.pending) | requested) - {"goal-coverage"}
    return tuple(item.criterion_id for item in contract.criteria if item.criterion_id in active)


@dataclass(frozen=True, slots=True)
class IterationObservation:
    """한 generation의 material progress와 failure identity입니다."""

    goal_fingerprint: str
    """Observation이 속한 immutable goal contract fingerprint입니다."""
    generation: int
    """동일 goal history에서 observation이 기록된 단조 증가 회차입니다."""
    output_fingerprint: str
    """Observation 시점의 canonical adaptive state identity입니다."""
    active_criteria: tuple[str, ...]
    """해당 generation에서 실제로 다시 연 criterion identity입니다."""
    root_causes: tuple[str, ...]
    """실패와 정체를 설명하는 canonical root-cause identity입니다."""
    progress: float
    """해당 generation에서 계산된 evidence completion 비율입니다."""
    material_change: bool
    """직전 observation 대비 canonical adaptive state가 바뀌었는지 나타냅니다."""
    reproducible_harness_gap: bool = False
    """동일 실패가 harness 부재로 재현되어 durable promotion이 필요한지 나타냅니다."""
    recovery_epoch: int = 0
    """승인된 recovery decision 뒤 새 접근을 구분하는 epoch입니다."""
    efficiency_assessment: EfficiencyAssessment | None = None
    """Store가 연속 snapshot과 runtime receipt에서 파생한 optional 효율 판정입니다."""

    def __post_init__(self) -> None:
        """Stagnation 판정에 쓸 bounded observation을 검증합니다.

        Raises:
            ValueError: Goal identity, generation, recovery epoch, output identity, progress 또는
                active criterion identity가 bounded 계약과 다를 때 발생합니다.
        """
        _require_digest(self.goal_fingerprint, "goal_fingerprint")
        if self.generation < 1:
            raise ValueError("generation must be positive")
        if self.recovery_epoch < 0:
            raise ValueError("recovery_epoch must be zero or positive")
        _require_text(self.output_fingerprint, "output_fingerprint")
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("progress must be between zero and one")
        _require_unique(self.active_criteria, "active criterion")
        if (
            self.efficiency_assessment is not None
            and self.efficiency_assessment.goal_delta.goal_fingerprint != self.goal_fingerprint
        ):
            raise ValueError("efficiency admission must match the observation goal fingerprint")


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """현재 generation 뒤에 허용되는 한 action과 success 여부입니다."""

    action: ControlAction
    """현재 generation 뒤에 실행하도록 허용된 deterministic action입니다."""
    achieved: bool
    """Action이 authoritative goal completion을 나타내는지 구분합니다."""
    reason: str
    """선택한 action을 ambiguity, attainment 또는 reflection 상태로 설명합니다."""


@dataclass(frozen=True, slots=True)
class ReflectionPolicy:
    """Wonder/Reflect 결과를 bounded deterministic action으로 변환합니다."""

    stagnation_window: int = 3
    """정체를 판정할 때 연속으로 비교하는 current-epoch observation 수입니다."""
    max_generations: int | None = None
    """명시적으로 구성한 emergency 회차 watchdog이며 default에는 상한이 없습니다."""
    minimum_progress_delta: float = 0.01
    """Material progress로 인정할 generation 간 최소 evidence 증가량입니다."""

    def __post_init__(self) -> None:
        """Safety bound와 stagnation window를 검증합니다.

        Raises:
            ValueError: Window, generation cap 또는 progress delta가 bounded policy 범위를
                벗어날 때 발생합니다.
        """
        if self.stagnation_window < 2:
            raise ValueError("stagnation_window must be at least two")
        if self.max_generations is not None and self.max_generations < 1:
            raise ValueError("max_generations must be positive")
        if not 0.0 <= self.minimum_progress_delta <= 1.0:
            raise ValueError("minimum_progress_delta must be between zero and one")

    def decide(
        self,
        ambiguity: AmbiguityAssessment,
        attainment: GoalAttainment,
        observations: tuple[IterationObservation, ...],
    ) -> ControlDecision:
        """명확성, 목표 authority, 정체 순으로 다음 action을 판정합니다.

        Args:
            ambiguity: Current intent/source gap inventory에서 계산한 readiness입니다.
            attainment: Current goal evidence와 execution authority의 completion 판정입니다.
            observations: Append-only generation observation history입니다.
        Returns:
            우선순위가 가장 높은 completion, blocker, reflection 또는 continuation action입니다.
        """
        if not ambiguity.ready:
            return ControlDecision(ambiguity.action, False, "intent is not ready")
        current = tuple(
            item for item in observations if item.goal_fingerprint == attainment.goal_fingerprint
        )
        if attainment.achieved:
            return ControlDecision(ControlAction.COMPLETE, True, "goal evidence is complete")
        if (
            self.max_generations is not None
            and current
            and max(item.generation for item in current) >= self.max_generations
        ):
            return ControlDecision(
                ControlAction.EXHAUSTED,
                False,
                "generation safety cap reached without goal attainment",
            )
        current_epoch = (
            tuple(
                item
                for item in current
                if item.recovery_epoch == max(entry.recovery_epoch for entry in current)
            )
            if current
            else ()
        )
        if current_epoch and current_epoch[-1].reproducible_harness_gap:
            return ControlDecision(
                ControlAction.PROMOTE_HARNESS,
                False,
                "reproducible harness gap requires durable promotion",
            )
        repeated = _active_repeated_root_causes(current, current_epoch)
        if any(root.startswith("introduced-") for root in repeated):
            return ControlDecision(
                ControlAction.CHANGE_APPROACH,
                False,
                "introduced root cause recurred",
            )
        if any(root.startswith("preexisting-") for root in repeated):
            return ControlDecision(
                ControlAction.ENUMERATE_INVARIANT,
                False,
                "preexisting family must be enumerated",
            )
        if repeated:
            return ControlDecision(
                ControlAction.CHANGE_APPROACH,
                False,
                "same root cause recurred",
            )
        if _is_oscillating(current_epoch):
            return ControlDecision(ControlAction.CHANGE_APPROACH, False, "A/B oscillation")
        if _is_stagnant(
            current_epoch,
            self.stagnation_window,
            self.minimum_progress_delta,
        ):
            return ControlDecision(
                ControlAction.CHANGE_APPROACH,
                False,
                "material progress stagnated",
            )
        if attainment.action is ControlAction.AWAIT_USER:
            return ControlDecision(ControlAction.AWAIT_USER, False, "user acceptance is pending")
        return ControlDecision(ControlAction.CONTINUE, False, "active criteria remain")


def _authority_for(kind: EvidenceKind) -> EvidenceAuthority:
    return {
        EvidenceKind.EXAMPLE_TEST: EvidenceAuthority.EXECUTABLE,
        EvidenceKind.PROPERTY_TEST: EvidenceAuthority.EXECUTABLE,
        EvidenceKind.METAMORPHIC_TEST: EvidenceAuthority.EXECUTABLE,
        EvidenceKind.MUTATION_TEST: EvidenceAuthority.EXECUTABLE,
        EvidenceKind.INDEPENDENT_SEMANTIC: EvidenceAuthority.INDEPENDENT_EVALUATOR,
        EvidenceKind.USER_ACCEPTANCE: EvidenceAuthority.USER,
        EvidenceKind.SOURCE_READBACK: EvidenceAuthority.PRIMARY_SOURCE,
    }[kind]


def _gap_authority_priority(gap: ClarificationGap) -> int:
    """같은 dependency frontier에서 local authority 비용 순서를 반환합니다."""
    return {
        GapAuthority.REPOSITORY: 0,
        GapAuthority.SAFE_ASSUMPTION: 1,
        GapAuthority.USER: 2,
    }[gap.authority]


def _authority_payload(receipt: AuthorityReceipt) -> dict[str, object]:
    """Authority receipt를 canonical fingerprint payload로 변환합니다."""
    return {
        "authority": receipt.authority.value,
        "issuer_id": receipt.issuer_id,
        "subject_id": receipt.subject_id,
        "intent_revision": receipt.intent_revision,
        "source_revision": receipt.source_revision,
        "receipt_digest": receipt.receipt_digest,
        "delegation_id": receipt.delegation_id,
    }


def _deferral_payload(deferral: UserDeferral) -> dict[str, object]:
    """User deferral을 canonical fingerprint payload로 변환합니다."""
    return {
        "gap_id": deferral.gap_id,
        "intent_revision": deferral.intent_revision,
        "reason": deferral.reason,
        "lineage": _authority_payload(deferral.lineage),
        "decision_reference": deferral.decision_reference,
    }


def _gap_payload(gap: ClarificationGap) -> dict[str, object]:
    """Clarification gap을 canonical fingerprint payload로 변환합니다."""
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
            None if gap.resolution_lineage is None else _authority_payload(gap.resolution_lineage)
        ),
        "deferral": None if gap.deferral is None else _deferral_payload(gap.deferral),
    }


def _evidence_payload(evidence: CriterionEvidence) -> dict[str, object]:
    """Criterion evidence를 canonical fingerprint payload로 변환합니다."""
    return {
        "goal_fingerprint": evidence.goal_fingerprint,
        "criterion_id": evidence.criterion_id,
        "kind": evidence.kind.value,
        "authority": evidence.authority.value,
        "status": evidence.status.value,
        "reference": evidence.reference,
        "lineage": _authority_payload(evidence.lineage),
        "evaluation_revision": evidence.evaluation_revision,
    }


def _coverage_payload(coverage: GoalCoverage) -> dict[str, object]:
    """Goal coverage를 canonical fingerprint payload로 변환합니다."""
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
        "lineage": _authority_payload(coverage.lineage),
        "evaluation_revision": coverage.evaluation_revision,
    }


def _oracle_authority(owner: OracleOwner) -> EvidenceAuthority:
    return {
        OracleOwner.EXECUTABLE: EvidenceAuthority.EXECUTABLE,
        OracleOwner.INDEPENDENT_EVALUATOR: EvidenceAuthority.INDEPENDENT_EVALUATOR,
        OracleOwner.USER: EvidenceAuthority.USER,
        OracleOwner.PRIMARY_SOURCE: EvidenceAuthority.PRIMARY_SOURCE,
    }[owner]


def _gap_evidence_authority(authority: GapAuthority) -> EvidenceAuthority:
    return {
        GapAuthority.USER: EvidenceAuthority.USER,
        GapAuthority.REPOSITORY: EvidenceAuthority.PRIMARY_SOURCE,
        GapAuthority.SAFE_ASSUMPTION: EvidenceAuthority.SAME_CONTEXT,
    }[authority]


def _repeated_root_causes(observations: tuple[IterationObservation, ...]) -> frozenset[str]:
    generations: dict[str, set[int]] = {}
    for observation in observations:
        for root_cause in set(observation.root_causes):
            generations.setdefault(root_cause, set()).add(observation.generation)
    return frozenset(root_cause for root_cause, values in generations.items() if len(values) >= 2)


def _active_repeated_root_causes(
    observations: tuple[IterationObservation, ...],
    current_epoch: tuple[IterationObservation, ...],
) -> frozenset[str]:
    """현재 recovery scope에서 재발한 root cause만 global recurrence로 반환합니다."""
    if not current_epoch:
        return frozenset()
    active_epoch = current_epoch[0].recovery_epoch
    active_roots = {
        root_cause for observation in current_epoch for root_cause in observation.root_causes
    }
    historical_roots = {
        root_cause
        for observation in observations
        if observation.recovery_epoch < active_epoch
        for root_cause in observation.root_causes
    }
    return _repeated_root_causes(current_epoch) | frozenset(active_roots & historical_roots)


def _is_oscillating(observations: tuple[IterationObservation, ...]) -> bool:
    if len(observations) < 4:
        return False
    fingerprints = tuple(item.output_fingerprint for item in observations[-4:])
    return (
        fingerprints[0] == fingerprints[2]
        and fingerprints[1] == fingerprints[3]
        and fingerprints[0] != fingerprints[1]
    )


def _is_stagnant(
    observations: tuple[IterationObservation, ...],
    window: int,
    minimum_progress_delta: float,
) -> bool:
    if len(observations) < window:
        return False
    recent = observations[-window:]
    if len({item.output_fingerprint for item in recent}) == 1:
        return True
    if all(not item.material_change for item in recent):
        return True
    deltas = tuple(
        recent[index].progress - recent[index - 1].progress for index in range(1, len(recent))
    )
    return bool(deltas) and all(delta < minimum_progress_delta for delta in deltas)


def _require_identity(value: str, label: str) -> str:
    if not isinstance(value, str) or IDENTITY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a stable identity")
    return value


def _require_opaque_identity(value: str, label: str) -> str:
    if not isinstance(value, str) or OPAQUE_IDENTITY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a stable opaque identity")
    return value


def _require_text(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    return value.strip()


def _require_digest(value: str, label: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def _require_revision(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_non_negative_revision(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _require_unique(values: Iterable[str], label: str) -> None:
    normalized = tuple(values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} identities must be unique")
