"""Compact state references preserve typed validation and request identity."""
import json

import pytest

from neurath.runtime.task_schema import arguments, definitions
from tests.test_workflow_tasks import adaptive_candidate, call, start

pytest_plugins = ["tests.test_agent_hooks"]
TOOLS = {"adaptive_replace", "adaptive_override_goal", "evaluation_prepare", "evaluation_execute"}


def test_adaptive_tools_advertise_references_but_keep_legacy_arguments():
    for tool in definitions():
        if tool["name"] in TOOLS:
            schema = tool["inputSchema"]
            assert "state" not in schema["properties"]
            assert "state_ref" in schema["required"]
            assert len(json.dumps(schema)) < 3000
    legacy = {"workflow_id": "phase", "expected_revision": 0,
              "state": adaptive_candidate(), "key": "legacy"}
    assert arguments("adaptive_replace", legacy) == legacy


@pytest.mark.parametrize("selection", [{}, {"state": {}, "state_ref": "sha256:" + "a" * 64}])
def test_state_input_requires_exactly_one_selector(selection):
    with pytest.raises(ValueError, match="exactly one"):
        arguments("adaptive_replace", {"workflow_id": "phase", "expected_revision": 0,
                                       "key": "choice", **selection})


def test_reference_roundtrip_and_request_replay(sessions, monkeypatch):
    from neurath.runtime import workflow_tasks
    candidate = adaptive_candidate()
    artifact = call(sessions, "artifact_put", {"document": candidate, "key": "candidate"})
    call(sessions, "worktree_claim", {})
    calls = []
    def consume(root, name, fields, handle):
        calls.append(name)
        return {"state": workflow_tasks.resolve_adaptive_state(handle, fields).to_payload()}
    monkeypatch.setattr(workflow_tasks, "_dispatch", consume)
    inputs = {"workflow_id": "phase", "expected_revision": 0, "key": "use-ref",
              "state_ref": artifact["reference"]}
    result = call(sessions, "adaptive_replace", inputs)
    assert result == {"state": candidate}
    assert call(sessions, "adaptive_replace", inputs, invocation="retry-ref") == result
    assert calls == ["adaptive_replace"]
    with pytest.raises(ValueError, match="different input"):
        call(sessions, "adaptive_replace", {**inputs, "state_ref": "sha256:" + "a" * 64}, invocation="changed-ref")
    legacy = {"workflow_id": "phase", "expected_revision": 0, "key": "legacy", "state": candidate}
    assert call(sessions, "adaptive_replace", legacy, invocation="inline") == result
    assert call(sessions, "adaptive_replace", legacy, invocation="inline-retry") == result


@pytest.mark.parametrize("kind", ["missing", "foreign", "malformed", "nested-injection"])
def test_invalid_reference_does_not_reserve_request_key(sessions, kind):
    from neurath.agents.store import MessageStore
    reference = "sha256:" + "a" * 64
    if kind != "missing":
        document = {} if kind == "malformed" else adaptive_candidate()
        if kind == "nested-injection":
            document["contract"]["actor"] = "forged"
        destination = {"host": "claude-code", "session": "ui"} if kind == "foreign" else {}
        reference = call(sessions, "artifact_put", {"document": document, "key": "candidate"}, **destination)["reference"]
    call(sessions, "worktree_claim", {})
    with pytest.raises((ValueError, RuntimeError)):
        call(sessions, "adaptive_replace", {"workflow_id": "phase", "expected_revision": 0,
            "state_ref": reference, "key": "invalid-state"})
    with MessageStore(sessions[0]).connection() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_task_requests'").fetchone()
        if exists:
            assert db.execute("SELECT count(*) FROM workflow_task_requests WHERE key='invalid-state'").fetchone()[0] == 0


def test_reference_does_not_grant_adaptive_authority(sessions):
    artifact = call(sessions, "artifact_put", {"document": adaptive_candidate(), "key": "candidate"})
    call(sessions, "worktree_claim", {})
    start(sessions)
    with pytest.raises(ValueError):
        call(sessions, "adaptive_replace", {"workflow_id": "phase", "expected_revision": 0,
            "state_ref": artifact["reference"], "key": "forged-ref-authority"})
