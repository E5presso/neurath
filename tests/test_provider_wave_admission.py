"""A provider wave cannot start partially admitted work or change its authority."""

from types import SimpleNamespace

import pytest

from neurath.runtime.task_schema import TaskError, arguments

pytest_plugins = ["tests.test_agent_hooks"]


def request():
    return {"wave_id": "wave", "task_id": "task", "expected_task_revision": 2,
            "entries": [{"entry_id": "a", "depends_on": [], "request": {
                "worktree": "/project/worker-a", "assignment": "Inspect A",
                "plan_id": "plan-a", "plan_revision": 1}}],
            "max_parallel": 2, "capacity_basis": "Two isolated worker worktrees", "key": "wave"}


def test_wave_schema_accepts_planned_worktree_workers_and_rejects_caller_identity():
    value = request()
    assert arguments("provider_wave_run", value)["entries"][0]["entry_id"] == "a"
    value["entries"][0]["request"]["actor_id"] = "invented"
    with pytest.raises(TaskError):
        arguments("provider_wave_run", value)


@pytest.mark.parametrize('mode', ['target-native', 'read-only', 'danger-full-access'])
def test_batch_cannot_change_the_issuer_execution_policy(mode):
    value = request()
    value['entries'][0]['request']['mode'] = mode
    with pytest.raises(TaskError):
        arguments('provider_wave_run', value)


def test_wave_entry_admission_keeps_existing_plan_policy_and_target_gates(monkeypatch):
    from neurath.runtime import provider_execution, model_tasks, provider_policy
    events = []
    monkeypatch.setattr(provider_execution, "_worktree_worker_preflight",
                        lambda root, fields: events.append("target"))
    monkeypatch.setattr(model_tasks, "admitted_request",
                        lambda root, identity, fields, policy: events.append("plan") or fields)
    monkeypatch.setattr(provider_policy, "resolve_policy",
                        lambda root, identity, fields, policy: events.append("policy") or fields)
    identity = SimpleNamespace(host="codex")
    fields = arguments("provider_run", {**request()["entries"][0]["request"],
        "purpose": "worktree-worker", "reason": "Runtime-owned wave", "key": "a"})
    result = provider_execution.admit_wave_entry("/project", identity, fields, {"observed": True})
    assert events == ["target", "plan", "policy"]
    assert result["assignment"] == "Inspect A" and "key" not in result
    fields["purpose"] = "user-session"
    with pytest.raises(TaskError, match="worktree-worker"):
        provider_execution.admit_wave_entry("/project", identity, fields, {})


def test_native_batch_is_atomic_and_unfinished_runs_block_task_success(sessions, monkeypatch):
    """Use the real native binding, task ledger, wave store and completion gate.

    External model/target admission and process launch are substituted; no model
    execution or host activation is claimed by this integration test.
    """
    from neurath.agents import mcp
    from neurath.providers import jobs
    from neurath.runtime import provider_execution
    from tests.test_state_tasks import call
    from tests.test_task_ledger_service import item
    from tests.test_task_tools import claim_fixture

    root, _ = sessions
    claim_fixture(root)
    defined = call(sessions, "task_define", {
        "tasks": [item()], "expected_revision": 0, "key": "define"})
    task_id = defined["tasks"][0]["id"]
    call(sessions, "task_start", {"task_id": task_id, "expected_revision": 1,
        "expected_task_revision": 1, "key": "start"})
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a: None)
    monkeypatch.setattr("neurath.runtime.model_tasks.observed_policy", lambda *a: {})
    monkeypatch.setattr(jobs, "validate_target", lambda *a: root)
    launches = []
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: launches.append(a))
    inputs = request() | {"task_id": task_id}
    inputs["entries"].append({"entry_id": "b", "depends_on": [], "request": {
        "worktree": str(root / "b"), "assignment": "Inspect B", "plan_id": "plan-b"}})

    def admit(_root, _identity, fields, _policy):
        if fields["assignment"] == "Inspect B":
            raise TaskError("invalid-input", "second target admission failed")
        return fields

    monkeypatch.setattr(provider_execution, "admit_wave_entry", admit)
    with pytest.raises(TaskError, match="second target"):
        call(sessions, "provider_wave_run", inputs, invocation="failed-batch")
    with jobs._store(root).connection() as db:
        assert db.execute("SELECT COUNT(*) FROM provider_jobs").fetchone()[0] == 0
    assert not launches
    monkeypatch.setattr(provider_execution, "admit_wave_entry", lambda r, i, f, p: f)
    result = call(sessions, "provider_wave_run", inputs, invocation="admitted-batch")
    assert result["task_scope"]["task_id"] == task_id
    assert len({entry["run_id"] for entry in result["entries"]}) == 2
    assert len(launches) == 2
    with pytest.raises(TaskError, match="unfinished or unsuccessful provider waves"):
        call(sessions, "task_resolve", {"task_id": task_id, "expected_revision": 2,
            "expected_task_revision": 2, "key": "resolve", "status": "succeeded",
            "references": ["claimed-success"], "summary": "Claimed success"})
    assert call(sessions, "task_list")["tasks"][0]["status"] == "in_progress"
    with pytest.raises(ValueError):
        mcp.call_tool(root, inputs, name="provider_wave_run")
