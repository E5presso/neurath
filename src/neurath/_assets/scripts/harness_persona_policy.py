"""구조화된 Constructive Skeptic Persona 정책을 검증합니다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path(".agents/rules/constructive-skeptic-policy.json")
POLICY_ID = "constructive-skeptic-v1"
EXPECTED_SCENARIOS: dict[str, dict[str, object]] = {
    "unsupported_fix": {
        "surface": "collaboration",
        "decision": "defer",
        "required_evidence": [
            "independent_verification",
            "contradiction_or_risk",
            "alternative",
        ],
        "blocker_count": 0,
        "dedup": "not_applicable",
        "rebuttal_outcome": "challenge_with_evidence",
    },
    "correct_user": {
        "surface": "collaboration",
        "decision": "allow",
        "required_evidence": ["supporting_reason", "confirmed_decision"],
        "blocker_count": 0,
        "dedup": "not_applicable",
        "rebuttal_outcome": "explain_and_execute",
    },
    "means_goal_mismatch": {
        "surface": "collaboration",
        "decision": "defer",
        "required_evidence": [
            "user_goal",
            "practical_constraint",
            "tradeoff",
            "convergent_alternative",
        ],
        "blocker_count": 0,
        "dedup": "not_applicable",
        "rebuttal_outcome": "propose_convergent_compromise",
    },
    "speculative_review": {
        "surface": "review",
        "decision": "allow",
        "required_evidence": ["warning_or_gap_triage", "concrete_risk"],
        "blocker_count": 0,
        "dedup": "root_cause_key",
        "rebuttal_outcome": "open",
    },
    "reproducible_blocker": {
        "surface": "review",
        "decision": "deny",
        "required_evidence": ["head_sha", "reproduction", "impact", "root_cause_key"],
        "blocker_count": 1,
        "dedup": "root_cause_key",
        "rebuttal_outcome": "unresolved",
    },
    "strong_rebuttal": {
        "surface": "review",
        "decision": "allow",
        "required_evidence": ["rebuttal_evidence", "same_strength_revalidation"],
        "blocker_count": 0,
        "dedup": "root_cause_key",
        "rebuttal_outcome": "accepted",
    },
}
EXPECTED_REVIEW_RECEIPT: dict[str, object] = {
    "required_fields": [
        "head_sha",
        "reproduction",
        "impact",
        "root_cause_key",
        "decision",
        "rebuttal_evidence",
    ],
    "critical_decision": "deny",
    "nonblocking_decisions": ["allow", "defer"],
    "deduplicate_by": "root_cause_key",
}


def load_policy(root: Path) -> dict[str, Any] | None:
    """Repository root에서 Persona policy JSON을 읽습니다.

    Args:
        root: 검사 대상 repository root입니다.

    Returns:
        JSON object이거나 읽기/형식 오류가 있을 때 None입니다.
    """
    path = root / POLICY_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return None
    return payload if isinstance(payload, dict) else None


def policy_is_canonical(policy: dict[str, Any] | None) -> bool:
    """정책의 scenario decision과 receipt schema가 canonical인지 판단합니다.

    Args:
        policy: 검증할 Persona policy object입니다.

    Returns:
        모든 canonical decision과 document digest가 보존됐는지 여부입니다.
    """
    if policy is None:
        return False
    return (
        policy.get("policy_id") == POLICY_ID
        and policy.get("scenarios") == EXPECTED_SCENARIOS
        and policy.get("review_receipt") == EXPECTED_REVIEW_RECEIPT
    )


def markdown_section(text: str, heading: str) -> str:
    """지정한 H2 heading부터 다음 H2 직전까지의 원문을 반환합니다.

    Args:
        text: Markdown 원문입니다.
        heading: `## ` prefix를 제외한 heading입니다.

    Returns:
        Heading을 포함한 section 원문이거나 찾지 못했을 때 빈 문자열입니다.
    """
    start_marker = f"## {heading}\n"
    start = text.find(start_marker)
    if start < 0:
        return ""
    next_heading = text.find("\n## ", start + len(start_marker))
    end = len(text) if next_heading < 0 else next_heading + 1
    return text[start:end]
