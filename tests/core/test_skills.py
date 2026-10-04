"""Every existing skill phase survives in one typed distributed definition."""

import json
from pathlib import Path

import pytest

from neurath.core.domain import CoreError
from neurath.core.skills import load_skills
from neurath.resources import BUNDLE
from neurath.skill_names import public_name


def test_all_defined_phase_orders_are_preserved_without_legacy_engine():
    previous = json.loads((Path(__file__).parent / "fixtures/v1-phase-orders.json").read_text())
    current = load_skills()
    assert {public_name(name) for name in previous} <= set(current)
    for name, value in previous.items():
        assert [p.id for p in current[public_name(name)].phases] == value


def test_typed_evidence_replaces_legacy_receipt_strings():
    skills = load_skills()
    publication = next(p for p in skills["implement-issue"].phases if p.id == "publication")
    assert "local_review_matrix_receipt" not in {c.id for c in publication.requires}
    check = next(p for p in skills["implement-issue"].phases if p.id == "verification")
    assert next(c for c in check.requires if c.id == "focused_test_result").kinds == {"check"}
    review = skills["review-code"].phases[0]
    assert next(c for c in review.requires if c.id == "review_report_readback").kinds == {"review"}


def test_every_distributed_skill_has_an_ordered_definition():
    paths = (BUNDLE / ".agents/skills").glob("*/SKILL.md")
    assert set(load_skills()) == {public_name(path.parent.name) for path in paths}


def test_invalid_or_recursive_subskill_definitions_are_rejected(tmp_path):
    path = tmp_path / "skills.json"
    data = {
        "schema": 1,
        "skills": {
            "loop": {
                "source": "loop",
                "phases": [
                    {"id": "phase", "requires": [], "effects": ["read"], "subskills": ["loop"]}
                ],
            }
        },
    }
    path.write_text(json.dumps(data))
    with pytest.raises(CoreError, match="subskill-cycle"):
        load_skills(path)


def test_autopilot_declares_real_nested_work_and_recovery_paths():
    skill = load_skills()["autopilot"]
    phases = {phase.id: phase for phase in skill.phases}
    assert "review-spec" in phases["intent_audit"].subskills
    assert "sync-docs" in phases["sync_docs"].subskills
    for phase in ("recovery", "meta_detection", "intent_audit"):
        assert phases[phase].restart_from == "collect_issues"


def test_issue_publication_requires_independent_review_not_owner_report():
    from neurath.core.domain import Evidence, validate_conditions

    skill = load_skills()["implement-issue"]
    publication = next(phase for phase in skill.phases if phase.id == "publication")
    condition = next(item for item in publication.requires if item.id == "local_review_head_sha")
    assert condition.kinds == {"review"}
    owner = Evidence("owner", "report", "source", "implementer", "head", True)
    with pytest.raises(CoreError, match="evidence-kind"):
        validate_conditions((condition,), {condition.id: (owner,)}, {})
