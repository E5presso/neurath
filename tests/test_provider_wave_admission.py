"""A provider wave cannot start partially admitted work or change its authority."""

from types import SimpleNamespace

import pytest

from neurath.runtime.task_schema import TaskError, arguments

pytest_plugins = ["tests.test_agent_hooks"]


def request():
    return {"wave_id": "wave", "task_id": "task", "expected_task_revision": 2,
            "entries": [{"entry_id": "a", "depends_on": [], "request": {
                "worktree": "/project/worker-a", "assignment": "Inspect A",
                "purpose": "worktree-worker", "session_basis": "native-capability-gap",
                "reason": "Observed native child lacks separate writer checkout support",
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


def test_legacy_batch_shape_remains_parseable_for_exact_replay():
    value = request()
    for field in ('purpose', 'reason', 'session_basis'):
        del value['entries'][0]['request'][field]
    assert arguments('provider_wave_run', value)['entries'] == value['entries']


def test_worktree_entry_without_session_basis_cannot_launch_an_independent_session(monkeypatch):
    from neurath.runtime import provider_execution
    monkeypatch.setattr(provider_execution, '_worktree_worker_preflight',
                        lambda *args: pytest.fail('target checked before execution selection'))
    fields = arguments('provider_run', {
        'purpose': 'worktree-worker', 'reason': 'Worktree location only',
        'worktree': '/linked', 'assignment': 'Implement', 'key': 'a'})
    with pytest.raises(TaskError, match='native child'):
        provider_execution.admit_wave_entry('/project', SimpleNamespace(host='codex'), fields, {})


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
    monkeypatch.setattr("neurath.runtime.admission._mcp_execution_policy", lambda *a: None)
    monkeypatch.setattr("neurath.runtime.model_tasks.observed_policy", lambda *a: {})
    monkeypatch.setattr(jobs, "validate_target", lambda *a: root)
    launches = []
    monkeypatch.setattr(jobs, "_launch", lambda *a, **k: launches.append(a))
    inputs = request() | {"task_id": task_id}
    inputs["entries"].append({"entry_id": "b", "depends_on": [], "request": {
        "worktree": str(root / "b"), "assignment": "Inspect B", "plan_id": "plan-b",
        "provider": "claude-code", "purpose": "perspective",
        "reason": "Claude capability is needed for this independent implementation"}})

    def admit(_root, _identity, fields, _policy):
        if fields["assignment"] == "Inspect B":
            raise TaskError("invalid-input", "second target admission failed")
        return fields

    monkeypatch.setattr(provider_execution, "admit_wave_entry", admit)
    from copy import deepcopy
    for field in ('purpose', 'reason'):
        missing = deepcopy(inputs)
        missing['wave_id'] = missing['key'] = 'missing-' + field
        del missing['entries'][0]['request'][field]
        with pytest.raises(TaskError, match='explicit execution choice'):
            call(sessions, 'provider_wave_run', missing, invocation='missing-' + field)
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
    selected = {entry['entry_id']: entry['original_request'] for entry in result['entries']}
    assert selected['a']['session_basis'] == 'native-capability-gap'
    assert selected['b']['purpose'] == 'perspective' and selected['b']['provider'] == 'claude-code'
    assert selected['b']['reason'] == inputs['entries'][1]['request']['reason']
    with pytest.raises(TaskError, match="unfinished or unsuccessful provider waves"):
        call(sessions, "task_resolve", {"task_id": task_id, "expected_revision": 2,
            "expected_task_revision": 2, "key": "resolve", "status": "succeeded",
            "references": ["claimed-success"], "summary": "Claimed success"})
    assert call(sessions, "task_list")["tasks"][0]["status"] == "in_progress"
    with pytest.raises(ValueError):
        mcp.call_tool(root, inputs, name="provider_wave_run")


@pytest.mark.parametrize('operation', ['provider_wave_run', 'provider_wave_retry'])
def test_exact_accepted_legacy_request_replays_without_new_admission(sessions, monkeypatch, operation):
    import hashlib
    from neurath.agents.store import AgentIdentity
    from neurath.providers import jobs, waves
    from neurath.providers.job_recovery import JobRecovery
    from neurath.runtime import provider_execution
    from neurath.hosts.task_scope import instruction_scope
    from neurath.serialization import canonical
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
    from tests.test_state_tasks import call
    from tests.test_task_ledger_service import item
    from tests.test_task_tools import claim_fixture

    root, _ = sessions
    claim_fixture(root)
    task_id = call(sessions, 'task_define', {
        'tasks': [item()], 'expected_revision': 0, 'key': 'define'})['tasks'][0]['id']
    call(sessions, 'task_start', {'task_id': task_id, 'expected_revision': 1,
        'expected_task_revision': 1, 'key': 'start'})
    handle = StateHandle.attach(SessionLocator.from_worktree(root),
        RuntimeEnvironmentResolver().resolve({'CODEX_THREAD_ID': 'api'}))
    owner = AgentIdentity('codex', 'api', str(handle.actor_id))
    scope = instruction_scope(root, handle.inspect(), task_id, 2)
    scope.update(session_id='api', actor_id=owner.actor)
    legacy = request() | {'task_id': task_id}
    for field in ('purpose', 'reason', 'session_basis'):
        del legacy['entries'][0]['request'][field]
    parsed = arguments('provider_wave_run', legacy)
    fingerprint = lambda value: 'sha256:' + hashlib.sha256(canonical(value).encode()).hexdigest()
    admitted = {**parsed['entries'][0]['request'], 'purpose': 'worktree-worker',
        'reason': 'Runtime-owned parallel worktree wave'}
    monkeypatch.setattr(jobs, 'validate_target', lambda *args: root)
    monkeypatch.setattr(jobs, '_launch', lambda *args, **kwargs: None)
    initial = waves.admit(root, owner, wave_id='wave', task_scope=scope,
        entries=[{**parsed['entries'][0], 'request': admitted}], max_parallel=2,
        capacity_basis=parsed['capacity_basis'], key='wave', request_digest=fingerprint(parsed))
    lease = JobRecovery(jobs._store(root)).claim_worker(owner.address, initial['entries'][0]['run_id'])
    if operation == 'provider_wave_retry':
        legacy = {'wave_id': 'wave', 'entry_id': 'a', 'request': legacy['entries'][0]['request'], 'key': 'old-retry'}
        parsed_retry = arguments(operation, legacy)
        with jobs._store(root).connection() as db:
            wave_id = db.execute('SELECT id FROM provider_waves').fetchone()[0]
            db.execute('INSERT INTO provider_wave_retries VALUES(?,?,?,?,?,?)',
                (owner.address, 'old-retry', wave_id, 'a', canonical(admitted), fingerprint(parsed_retry)))
    monkeypatch.setattr('neurath.runtime.admission._mcp_execution_policy', lambda *args: None)
    monkeypatch.setattr(provider_execution, 'admit_wave_entry', lambda *args: pytest.fail('legacy request re-admitted'))
    monkeypatch.setattr(jobs, '_launch', lambda *args, **kwargs: pytest.fail('legacy request launched again'))
    try:
        replayed = call(sessions, operation, legacy, invocation='legacy-replay')
        assert replayed['entries'][0]['run_id'] == initial['entries'][0]['run_id']
        assert replayed['task_scope'] == initial['task_scope']
    finally:
        lease.close()
