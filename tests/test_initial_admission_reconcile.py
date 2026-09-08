import json
import subprocess

import pytest

from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import AgentIdentity, MessageStore
from neurath.providers import jobs
from neurath.providers.job_recovery import JobRecovery
from neurath.runtime import model_tasks, provider_execution


@pytest.fixture
def accepted(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    identity = AgentIdentity('codex', 'issuer', 'codex:session:issuer')
    MessageStore(tmp_path).register(identity)
    fields = {'provider': 'codex', 'worktree': str(tmp_path), 'assignment': 'Do this once'}
    monkeypatch.setattr(jobs, 'validate_target', lambda *_: tmp_path)
    def crash(*_args, **_kwargs):
        raise SystemExit('issuer died before launch')
    monkeypatch.setattr(jobs, '_launch', crash)
    with pytest.raises(SystemExit):
        jobs.start(tmp_path, identity, fields, key='key')
    previous = model_tasks.previous_admission(tmp_path, identity, 'key', {**fields, 'key': 'key'})
    return tmp_path, identity, fields, previous['run_id']


def test_same_key_reconciles_committed_but_unlaunched_initial_admission(accepted, monkeypatch):
    root, identity, fields, run_id = accepted
    launches = []
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: launches.append(a))
    result = jobs.start(root, identity, fields, key='key')
    assert launches
    assert result['run_id'] == run_id
    assert result['replayed'] is True
    assert result['status'] == 'accepted'


def test_previous_admission_marks_required_write_but_does_not_execute(accepted, monkeypatch):
    root, identity, fields, _ = accepted
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('read-only lookup launched'))
    result = model_tasks.previous_admission(root, identity, 'key', {**fields, 'key': 'key'})
    assert result['reconciliation_required'] is True


@pytest.mark.parametrize('allow', [False, True])
def test_mcp_policy_checked_before_reconciliation_write(accepted, monkeypatch, allow):
    root, identity, fields, _ = accepted
    order = []
    monkeypatch.setattr(provider_execution, 'arguments', lambda _name, values: values)
    monkeypatch.setattr('neurath.runtime.tasks._verification_owner', lambda *_: (1, 'turn'))
    def policy(*_args, **_kwargs):
        order.append('policy')
        if not allow:
            raise ValueError('current MCP execution denied')
    monkeypatch.setattr('neurath.runtime.tasks._mcp_execution_policy', policy)
    monkeypatch.setattr(model_tasks, 'admitted_request', lambda *a: pytest.fail('accepted plan re-admitted'))
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: order.append('launch'))
    if allow:
        result = provider_execution.run(root, {**fields, 'key': 'key'}, identity=identity, expected_turn='bound')
        assert result['replayed'] is True
        assert order.index('policy') < order.index('launch')
    else:
        with pytest.raises(ValueError, match='denied'):
            provider_execution.run(root, {**fields, 'key': 'key'}, identity=identity, expected_turn='bound')
        assert order == ['policy']


@pytest.mark.parametrize('terminal', ['completed', 'failed'])
def test_terminal_replay_is_read_only_even_if_current_execution_is_denied(accepted, monkeypatch, terminal):
    root, identity, fields, run_id = accepted
    saved = jobs._finish(jobs._store(root), run_id, {'status': terminal, 'answer': 'saved'})
    monkeypatch.setattr(provider_execution, 'arguments', lambda _name, values: values)
    monkeypatch.setattr('neurath.runtime.tasks._verification_owner', lambda *_: (1, 'turn'))
    monkeypatch.setattr('neurath.runtime.tasks._mcp_execution_policy', lambda *a, **k: pytest.fail('read required execution'))
    monkeypatch.setattr(jobs, 'validate_target', lambda *a: pytest.fail('terminal replay revalidated target'))
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('terminal replay launched'))
    assert jobs.start(root, identity, fields, key='key')['status'] == terminal
    result = provider_execution.run(root, {**fields, 'key': 'key'}, identity=identity, expected_turn='bound')
    assert result['result'] == saved
    assert result['reconciliation_required'] is False


def test_launch_error_cannot_overwrite_worker_that_claimed_first(accepted, monkeypatch):
    root, identity, fields, run_id = accepted
    store = jobs._store(root)
    leases = []
    def competing_launch(*_args, **_kwargs):
        lease = JobRecovery(store).claim_worker(identity.address, run_id)
        leases.append(lease)
        with store.connection() as db:
            db.execute("UPDATE provider_jobs SET status='starting' WHERE id=?", (run_id,))
        raise OSError('other contender failed to launch')
    monkeypatch.setattr(jobs, '_launch', competing_launch)
    try:
        result = jobs.start(root, identity, fields, key='key')
        assert result['status'] == 'starting'
        assert jobs.status(root, identity, run_id)['result'] is None
        assert MessageStore(root).inbox(identity.address) == []
        with store.connection() as db:
            leases[0].assert_current(db)
    finally:
        for lease in leases:
            lease.close()


def test_stale_claim_before_start_becomes_failed_with_issuer_report(accepted, monkeypatch):
    root, identity, fields, run_id = accepted
    store = jobs._store(root)
    JobRecovery(store).claim_worker(identity.address, run_id).close()
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('stale consumed worker relaunched'))
    result = jobs.start(root, identity, fields, key='key')
    assert result['status'] == 'failed'
    assert 'initial' in result['diagnostic']
    assert len(MessageStore(root).inbox(identity.address)) == 1
    assert TaskLifecycle(store).active(identity.address) == []


def test_cancelled_unlaunched_initial_admission_finalizes_without_model(accepted, monkeypatch):
    root, identity, fields, run_id = accepted
    assert jobs.cancel(root, identity, run_id)['cancel_requested'] is True
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('cancelled work launched'))
    result = jobs.start(root, identity, fields, key='key')
    assert result['status'] == 'cancelled'
    assert len(MessageStore(root).inbox(identity.address)) == 1


@pytest.mark.parametrize('state,created', [('starting', None), ('accepted', {'native_session': 'unknown-native'})])
def test_starting_or_native_observed_jobs_are_never_relaunched(accepted, monkeypatch, state, created):
    root, identity, fields, run_id = accepted
    with jobs._store(root).connection() as db:
        db.execute('UPDATE provider_jobs SET status=?,result=? WHERE id=?',
                   (state, json.dumps({'created': created}) if created else None, run_id))
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('possible native execution relaunched'))
    assert jobs.start(root, identity, fields, key='key')['replayed'] is True
    assert model_tasks.previous_admission(root, identity, 'key', {**fields, 'key': 'key'})['reconciliation_required'] is False


def test_launch_error_without_competitor_is_terminal_and_reported_once(accepted, monkeypatch):
    root, identity, fields, _run_id = accepted
    def failed(*_args, **_kwargs):
        raise OSError('native worker could not launch')
    monkeypatch.setattr(jobs, '_launch', failed)
    result = jobs.start(root, identity, fields, key='key')
    assert result['status'] == 'failed'
    assert len(MessageStore(root).inbox(identity.address)) == 1
    assert jobs.start(root, identity, fields, key='key')['status'] == 'failed'
    assert len(MessageStore(root).inbox(identity.address)) == 1


def test_concurrent_initial_launchers_have_one_native_creator(accepted, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from neurath.providers.job_recovery import RecoveryBlocked
    root, identity, fields, run_id = accepted
    store = jobs._store(root)
    barrier, leases, native_creates = Barrier(2), [], []
    def launch(*_args, **_kwargs):
        try:
            lease = JobRecovery(store).claim_worker(identity.address, run_id)
        except RecoveryBlocked:
            return
        leases.append(lease)
        native_creates.append(run_id)
    monkeypatch.setattr(jobs, '_launch', launch)
    def concurrent_start(_):
        # Race the public callers. A caller may legitimately observe the other
        # preflight lease and return before launch, so launch cannot rendezvous.
        barrier.wait(timeout=5)
        return jobs.start(root, identity, fields, key='key')
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(concurrent_start, range(2)))
        assert len(outcomes) == 2
        assert native_creates == [run_id]
    finally:
        for lease in leases:
            lease.close()


def test_current_owner_change_blocks_reconciliation_before_launch(accepted, monkeypatch):
    root, identity, fields, _ = accepted
    owners = iter([(1, 'turn'), (2, 'different-turn')])
    monkeypatch.setattr(provider_execution, 'arguments', lambda _name, values: values)
    monkeypatch.setattr('neurath.runtime.tasks._verification_owner', lambda *_: next(owners))
    monkeypatch.setattr('neurath.runtime.tasks._mcp_execution_policy', lambda *a, **k: None)
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('owner changed before launch'))
    with pytest.raises(ValueError, match='caller changed'):
        provider_execution.run(root, {**fields, 'key': 'key'}, identity=identity, expected_turn='bound')


def test_unconsumed_target_failure_is_reported_without_launch(accepted, monkeypatch):
    root, identity, fields, _run_id = accepted
    monkeypatch.setattr(jobs, 'validate_target', lambda *a: (_ for _ in ()).throw(ValueError('assigned worktree removed')))
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: pytest.fail('invalid target launched'))
    result = jobs.start(root, identity, fields, key='key')
    assert result['status'] == 'failed'
    assert result['diagnostic'] == 'assigned worktree removed'
    assert len(MessageStore(root).inbox(identity.address)) == 1


def test_initial_failure_report_rollback_preserves_reconciliation(accepted, monkeypatch):
    root, identity, fields, run_id = accepted
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: (_ for _ in ()).throw(OSError('launch failed')))
    with monkeypatch.context() as patch:
        patch.setattr(TaskLifecycle, 'emit', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('outbox unavailable')))
        with pytest.raises(RuntimeError, match='outbox'):
            jobs.start(root, identity, fields, key='key')
    store = jobs._store(root)
    with store.connection() as db:
        assert db.execute('SELECT status FROM provider_jobs WHERE id=?', (run_id,)).fetchone()[0] == 'accepted'
        assert db.execute('SELECT COUNT(*) FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()[0] == 0
    assert jobs.start(root, identity, fields, key='key')['status'] == 'failed'
    assert len(MessageStore(root).inbox(identity.address)) == 1
