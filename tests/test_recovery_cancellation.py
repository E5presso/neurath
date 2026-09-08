import hashlib
import json
import subprocess

import pytest

from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import AgentIdentity, MessageStore
from neurath.memory.store import canonical
from neurath.providers import jobs
from neurath.providers.job_recovery import ClosedTransportEvidence, JobRecovery, RecoveryBlocked


@pytest.fixture
def completed(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    identity = AgentIdentity('codex', 'issuer', 'codex:session:issuer')
    store = MessageStore(tmp_path)
    store.register(identity)
    monkeypatch.setattr(jobs, 'validate_target', lambda *_: tmp_path)
    monkeypatch.setattr(jobs, '_launch', lambda *args, **kwargs: None)
    run = jobs.start(tmp_path, identity, {'worktree': str(tmp_path), 'assignment': 'Original task'}, key='run')
    run_id = run['run_id']
    closure = {'native_session': 'native', 'transport': 'codex-app-server', 'source': 'owned-close',
               'connection_closed': True, 'native_process_exited': True, 'reason': 'transport-closed'}
    created = {'provider': 'codex', 'transport': 'codex-app-server', 'native_session': 'native',
               'worktree': str(tmp_path), 'requested_model': None, 'actual_model': 'observed-model',
               'policy': {'requested': {'mode': 'read-only'}}}
    with JobRecovery(store).claim_worker(identity.address, run_id) as lease:
        original = jobs._finish(store, run_id, {'status': 'completed', 'created': created,
            'closure': closure, 'worker_generation': 1, 'text': 'Original result'}, lease)
    return tmp_path, identity, store, run_id, original


def task_id(owner, run_id, generation=1):
    key = 'provider:' + run_id + (':recovery:' + str(generation) if generation > 1 else '')
    return hashlib.sha256(canonical([owner, key]).encode()).hexdigest()


def test_recovery_admission_is_visible_and_has_separate_task(completed):
    root, identity, store, run_id, original = completed
    result = jobs.recover(root, identity, run_id, key='recover')
    assert result['generation'] == 2
    assert jobs.status(root, identity, run_id)['status'] == 'recovery-accepted'
    recovery = TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id, 2))
    assert recovery['state'] == 'assigned'
    with store.connection() as db:
        row = db.execute('SELECT result FROM provider_job_results WHERE run_id=? AND generation=1', (run_id,)).fetchone()
        assert json.loads(row[0]) == original


def test_cancel_accepted_recovery_finishes_without_start_or_original_report(completed, monkeypatch):
    root, identity, store, run_id, original = completed
    jobs.recover(root, identity, run_id, key='recover')
    monkeypatch.setattr(jobs, 'execute_session', lambda *_args, **_kwargs: pytest.fail('cancelled recovery executed'))
    assert jobs.cancel(root, identity, run_id)['cancel_requested'] is True
    assert jobs.status(root, identity, run_id)['status'] == 'cancelled'
    assert 'text' not in jobs.status(root, identity, run_id)['result']
    old_task = TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id))
    new_task = TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id, 2))
    assert old_task['state'] == 'completed'
    assert len(old_task['reports']) == 1
    assert new_task['state'] == 'cancelled'
    assert len(new_task['reports']) == 1
    with store.connection() as db:
        assert json.loads(db.execute('SELECT result FROM provider_job_results WHERE run_id=? AND generation=1', (run_id,)).fetchone()[0]) == original
    with pytest.raises(RecoveryBlocked):
        jobs.worker(root, run_id, generation=2)
    assert len(TaskLifecycle(store).read(identity.address, new_task['id'])['reports']) == 1


def test_cancel_after_worker_claim_keeps_flag_until_worker_finishes(completed):
    root, identity, store, run_id, _ = completed
    jobs.recover(root, identity, run_id, key='recover')
    with JobRecovery(store).claim_worker(identity.address, run_id, generation=2) as lease:
        assert jobs.cancel(root, identity, run_id)['cancel_requested'] is True
        assert jobs.status(root, identity, run_id)['cancel_requested'] is True
        result = jobs._finish(store, run_id, {'status': 'cancelled', 'worker_generation': 2}, lease)
    assert result['status'] == 'cancelled'
    assert TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id, 2))['state'] == 'cancelled'


def test_worker_prestart_cancellation_uses_actual_recovery_generation(completed, monkeypatch):
    root, identity, store, run_id, original = completed
    jobs.recover(root, identity, run_id, key='recover')
    with store.connection() as db:
        db.execute('UPDATE provider_jobs SET cancel_requested=1 WHERE id=?', (run_id,))
    monkeypatch.setattr(jobs, 'execute_session', lambda *_args, **_kwargs: pytest.fail('cancelled recovery executed'))
    assert jobs.worker(root, run_id, generation=2)['status'] == 'cancelled'
    assert len(TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id))['reports']) == 1
    assert TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id, 2))['state'] == 'cancelled'
    with store.connection() as db:
        assert json.loads(db.execute('SELECT result FROM provider_job_results WHERE run_id=? AND generation=1', (run_id,)).fetchone()[0]) == original


def test_admission_callback_failure_rolls_back_state_and_generation(completed):
    _, identity, store, run_id, _ = completed
    evidence = ClosedTransportEvidence(1, 'native', 'codex-app-server', 'receipt', True, True, True, 'transport-closed')
    with store.connection() as db:
        before = tuple(db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone())
    def fail(_db, _admission):
        raise RuntimeError('outbox unavailable')
    with pytest.raises(RuntimeError, match='outbox'):
        JobRecovery(store).recover(identity.address, run_id, 'recover', evidence, on_admit=fail)
    with store.connection() as db:
        assert db.execute('SELECT status FROM provider_jobs WHERE id=?', (run_id,)).fetchone()[0] == 'completed'
        assert tuple(db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()) == before
        assert db.execute('SELECT COUNT(*) FROM provider_recovery_requests').fetchone()[0] == 0


def test_cancel_terminal_outbox_failure_leaves_admission_retriable(completed, monkeypatch):
    root, identity, store, run_id, original = completed
    jobs.recover(root, identity, run_id, key='recover')
    with monkeypatch.context() as patch:
        patch.setattr(TaskLifecycle, 'emit', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('outbox unavailable')))
        with pytest.raises(RuntimeError, match='outbox'):
            jobs.cancel(root, identity, run_id)
    saved = jobs.status(root, identity, run_id)
    assert saved['status'] == 'recovery-accepted'
    assert saved['cancel_requested'] is True
    assert saved['result'] == original
    with store.connection() as db:
        assert tuple(db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()) == (2, 'accepted')
        assert db.execute('SELECT COUNT(*) FROM provider_job_results WHERE run_id=? AND generation=2', (run_id,)).fetchone()[0] == 0
    assert jobs.cancel(root, identity, run_id)['cancel_requested'] is True
    assert TaskLifecycle(store).read(identity.address, task_id(identity.address, run_id, 2))['state'] == 'cancelled'


def test_generation_archive_cannot_be_overwritten(completed):
    _, _identity, store, run_id, original = completed
    from neurath.providers.job_recovery import archive_result
    with store.connection() as db, pytest.raises(RecoveryBlocked, match='already recorded'):
        archive_result(db, run_id, 1, {**original, 'status': 'cancelled'})
    with store.connection() as db:
        assert json.loads(db.execute('SELECT result FROM provider_job_results WHERE run_id=? AND generation=1', (run_id,)).fetchone()[0]) == original
