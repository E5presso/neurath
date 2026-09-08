"""Named MCP context and diagnostic operations preserve native/domain authority."""
import pytest
from neurath.runtime.task_schema import arguments
from tests.test_workflow_tasks import call, start
pytest_plugins = ["tests.test_agent_hooks"]


def test_context_inventory_and_identity_rejection():
    for name, fields in {
        "diagnostics_integrity": {},
        "diagnostics_project": {},
        "enclave_read": {},
        "enclave_set": {"fact_key": "scope", "value": "Docs", "expected_digest": "a" * 64, "key": "set"},
        "turn_yield": {"expected_turn_revision": 1, "outcome": "incomplete", "reason": "Pending", "key": "yield"},
    }.items():
        arguments(name, fields)
        with pytest.raises(ValueError):
            arguments(name, {**fields, "actor": "foreign"})


def test_enclave_named_lifecycle_uses_actual_actor_and_digest(sessions):
    before = call(sessions, "enclave_read", {})
    changed = call(sessions, "enclave_set", {
        "fact_key": "scope", "value": "Documented MCP face", "expected_digest": before["digest"], "key": "set",
    })
    assert changed["digest"] != before["digest"]
    with pytest.raises(ValueError, match="conflict"):
        call(sessions, "enclave_delete", {"fact_key": "scope", "expected_digest": before["digest"], "key": "stale"})
    result = call(sessions, "enclave_delete", {"fact_key": "scope", "expected_digest": changed["digest"], "key": "delete"}, invocation="delete-current")
    assert result["digest"] == before["digest"]


def test_evaluation_loop_named_lifecycle_keeps_round_gates(sessions):
    call(sessions, "worktree_claim", {})
    start(sessions)
    created = call(sessions, "evaluation_loop_open", {"workflow_id": "phase", "loop_id": "docs",
        "goal": "Check documentation", "acceptance": ["Source matches", "Links resolve"], "key": "open"})
    assert created["loop_id"] == "docs"
    close_fields = {"workflow_id": "phase", "loop_id": "docs", "outcome": "findings-clear",
                    "summary": "Independent inspection complete", "key": "close"}
    with pytest.raises(ValueError):
        call(sessions, "evaluation_loop_close", close_fields)
    call(sessions, "evaluation_loop_round", {"workflow_id": "phase", "loop_id": "docs",
        "number": 1, "findings": [], "key": "round"})
    result = call(sessions, "evaluation_loop_close", close_fields, invocation="close-after-round")
    assert result["outcome"] == "findings-clear"
    assert "rounds=1" in result["receipt"]
