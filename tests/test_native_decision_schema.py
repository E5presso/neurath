"""The named adaptive surface accepts exactly the domain claim wire variants."""
from copy import deepcopy

import pytest


def claim_payload(provenance, kernel_prompt=True):
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness.adaptive_control import (
        UserDecisionClaim, UserDecisionDisposition, UserDecisionProvenance,
        UserDecisionTarget, user_decision_value_summary_digest,
    )
    native = provenance == "native-prompt"
    result_goal, result_revision, result_source = "a" * 64, 1, "current-source"
    return UserDecisionClaim(
        workflow_id="active-work", source_goal_fingerprint=result_goal,
        source_intent_revision=1, source_revision=result_source,
        question_workflow_revision=None if native else 2,
        question_digest=None if native else "b" * 64,
        question_generation=None if native else 1,
        question_turn_revision=None if native else 3,
        prompt_digest="c" * 64, prompt_reference="native-prompt:observed",
        prompt_generation=1 if kernel_prompt else None,
        prompt_turn_revision=4 if kernel_prompt else None,
        target_kind=UserDecisionTarget.GAP, target_id="issue-4-project-affiliation",
        disposition=UserDecisionDisposition.FACT,
        value_summary_digest=user_decision_value_summary_digest(
            UserDecisionTarget.GAP, "issue-4-project-affiliation", UserDecisionDisposition.FACT,
            result_goal, result_revision, result_source),
        result_goal_fingerprint=result_goal, result_intent_revision=result_revision,
        result_source_revision=result_source,
        provenance=UserDecisionProvenance.NATIVE_PROMPT if native else UserDecisionProvenance.ADAPTIVE_QUESTION,
        source_workflow_revision=2 if native else None,
    ).to_payload()


def validate_claim(payload):
    from neurath.runtime.workflow_tasks import adaptive_schema
    from neurath.runtime.task_schema import _validate
    rule = adaptive_schema()["properties"]["user_decisions"]["items"]["properties"]["claim"]
    _validate(payload, rule, "state.user_decisions.claim")
    return payload


@pytest.mark.parametrize("provenance,kernel_prompt", [
    ("adaptive-question", True), ("native-prompt", True), ("native-prompt", False),
])
def test_named_schema_matches_actual_user_decision_payload(provenance, kernel_prompt):
    payload = claim_payload(provenance, kernel_prompt)
    assert validate_claim(payload) == payload
    if provenance == "native-prompt":
        assert not any(name.startswith("question_") for name in payload)
        assert payload["source_workflow_revision"] == 2


@pytest.mark.parametrize("fault", ["question-field", "half-kernel", "wrong-provenance", "missing-source-revision"])
def test_native_claim_schema_rejects_mixed_or_partial_provenance(fault):
    from neurath.runtime.task_schema import TaskError
    payload = deepcopy(claim_payload("native-prompt"))
    if fault == "question-field":
        payload["question_digest"] = "d" * 64
    elif fault == "half-kernel":
        payload.pop("prompt_generation")
    elif fault == "wrong-provenance":
        payload["provenance"] = "adaptive-question"
    else:
        payload.pop("source_workflow_revision")
    with pytest.raises(TaskError):
        validate_claim(payload)
