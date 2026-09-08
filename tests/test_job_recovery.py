import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest
from neurath.providers.job_recovery import ClosedTransportEvidence, JobRecovery, RecoveryBlocked


class Store:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / 'state.sqlite3'
        with self.connection() as db:
            db.execute('CREATE TABLE provider_jobs (id TEXT PRIMARY KEY,owner TEXT,request TEXT,status TEXT,result TEXT,cancel_requested INTEGER)')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()


def setup_job(tmp_path, run_id='run-1'):
    store = Store(tmp_path)
    created = {'provider': 'codex', 'transport': 'codex-app-server', 'native_session': 'observed-native',
               'worktree': '/assigned', 'requested_model': 'model-a', 'actual_model': 'model-a',
               'policy': {'requested': {'mode': 'danger-full-access', 'approval_policy': 'never'}}}
    request = {'provider': 'codex', 'worktree': '/assigned', 'assignment': 'Do the task once.',
               'model': 'model-a', 'mode': 'danger-full-access', 'plan_id': 'plan-1'}
    with store.connection() as db:
        db.execute('INSERT INTO provider_jobs VALUES(?,?,?,?,?,?)',
                   (run_id, 'issuer', json.dumps(request), 'accepted', json.dumps({'created': created}), 0))
    recovery = JobRecovery(store)
    evidence = ClosedTransportEvidence(1, 'observed-native', 'codex-app-server',
                                       'host-close-receipt', True, True, True, 'process-exit')
    return store, recovery, evidence


def test_lifetime_flock_and_cas_admission(tmp_path):
    store, recovery, evidence = setup_job(tmp_path)
    first = recovery.claim_worker('issuer', 'run-1')
    assert first.generation == 1
    with pytest.raises(RecoveryBlocked, match='worker-live'):
        recovery.recover('issuer', 'run-1', 'recover-1', evidence)
    first.close()
    admission = recovery.recover('issuer', 'run-1', 'recover-1', evidence)
    assert admission['admission']['status'] == 'accepted'
    assert admission['admission']['generation'] == 2
    assert admission['admission']['session']['native_session'] == 'observed-native'
    assert admission['admission']['resume_original_assignment'] is False
    assert 'assignment' not in admission['admission']['settings']
    assert admission['admission']['settings']['plan_id'] == 'plan-1'
    assert admission['replayed'] is False
    with pytest.raises(RecoveryBlocked, match='generation'):
        recovery.claim_worker('issuer', 'run-1', generation=1)
    with recovery.claim_worker('issuer', 'run-1', generation=2) as second:
        with store.connection() as db:
            second.assert_current(db)
        with pytest.raises(RecoveryBlocked, match='worker-live'):
            recovery.claim_worker('issuer', 'run-1', generation=2)
    with store.connection() as db, pytest.raises(RecoveryBlocked, match='released'):
        second.assert_current(db)


def test_key_replay_after_admission_and_new_key_conflict(tmp_path):
    _, recovery, evidence = setup_job(tmp_path)
    recovery.claim_worker('issuer', 'run-1').close()
    first = recovery.recover('issuer', 'run-1', 'key', evidence)
    replay = recovery.recover('issuer', 'run-1', 'key', replace(evidence, generation=999))
    assert replay['admission'] == first['admission']
    assert replay['replayed'] is True
    with pytest.raises(RecoveryBlocked, match='pending'):
        recovery.recover('issuer', 'run-1', 'other-key', evidence)


@pytest.mark.parametrize('field,value,reason', [
    ('generation', 2, 'generation'), ('native_session', 'foreign-native', 'session'),
    ('transport', 'claude-agent-sdk', 'transport'), ('connection_closed', False, 'connection'),
    ('native_process_exited', False, 'native-process'), ('issuer_active', False, 'issuer'),
])
def test_missing_or_stale_closure_proof_blocks(tmp_path, field, value, reason):
    _, recovery, evidence = setup_job(tmp_path)
    recovery.claim_worker('issuer', 'run-1').close()
    with pytest.raises(RecoveryBlocked, match=reason):
        recovery.recover('issuer', 'run-1', 'key', replace(evidence, **{field: value}))


def test_no_legacy_adoption_foreign_owner_or_arbitrary_session(tmp_path):
    _, recovery, evidence = setup_job(tmp_path)
    with pytest.raises(RecoveryBlocked, match='unmanaged'):
        recovery.recover('issuer', 'run-1', 'key', evidence)
    with pytest.raises(RecoveryBlocked, match='owner'):
        recovery.recover('foreign', 'run-1', 'key', evidence)
    with pytest.raises(RecoveryBlocked, match='owner'):
        recovery.claim_worker('foreign', 'run-1')


@pytest.mark.parametrize('case', ['missing-result', 'missing-session', 'cancelled', 'cancel-request', 'wrong-worktree'])
def test_result_and_cancel_boundaries(tmp_path, case):
    store, recovery, evidence = setup_job(tmp_path)
    recovery.claim_worker('issuer', 'run-1').close()
    with store.connection() as db:
        if case == 'missing-result':
            db.execute('UPDATE provider_jobs SET result=NULL')
        elif case == 'missing-session':
            db.execute("UPDATE provider_jobs SET result='{}'")
        elif case == 'cancelled':
            db.execute("UPDATE provider_jobs SET status='cancelled'")
        elif case == 'cancel-request':
            db.execute('UPDATE provider_jobs SET cancel_requested=1')
        else:
            result = json.loads(db.execute('SELECT result FROM provider_jobs').fetchone()[0])
            result['created']['worktree'] = '/foreign'
            db.execute('UPDATE provider_jobs SET result=?', (json.dumps(result),))
    with pytest.raises(RecoveryBlocked):
        recovery.recover('issuer', 'run-1', 'key', evidence)


def test_completed_turn_can_recover_for_late_messages(tmp_path):
    store, recovery, evidence = setup_job(tmp_path)
    recovery.claim_worker('issuer', 'run-1').close()
    with store.connection() as db:
        db.execute("UPDATE provider_jobs SET status='completed'")
    assert recovery.recover('issuer', 'run-1', 'key', evidence)['admission']['status'] == 'accepted'


def test_actual_worker_exit_releases_os_lease(tmp_path):
    import os

    _, recovery, evidence = setup_job(tmp_path)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            lease = recovery.claim_worker('issuer', 'run-1')
            os.write(write_fd, str(lease.generation).encode())
            os._exit(0)  # Abrupt native worker exit: no context cleanup or heartbeat.
        except BaseException:  # noqa: BLE001 - forked fixture must not run parent tests
            os._exit(1)
    os.close(write_fd)
    try:
        assert os.read(read_fd, 16) == b'1'
    finally:
        os.close(read_fd)
        _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert recovery.recover('issuer', 'run-1', 'recover', evidence)['admission']['generation'] == 2


def test_worker_cannot_consume_admission_twice_after_close(tmp_path):
    _, recovery, evidence = setup_job(tmp_path)
    recovery.claim_worker('issuer', 'run-1').close()
    recovery.recover('issuer', 'run-1', 'recover', evidence)
    recovery.claim_worker('issuer', 'run-1', generation=2).close()
    with pytest.raises(RecoveryBlocked, match='generation'):
        recovery.claim_worker('issuer', 'run-1', generation=2)
    next_admission = recovery.recover('issuer', 'run-1', 'recover-again', replace(evidence, generation=2))
    assert next_admission['admission']['generation'] == 3


def test_symlink_lease_directory_is_not_followed(tmp_path):
    store = Store(tmp_path)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (tmp_path / 'worker-leases').symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RecoveryBlocked, match='symlink'):
        JobRecovery(store)
