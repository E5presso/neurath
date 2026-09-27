"""Provider wave admission and result consumption, without native model calls."""
import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from neurath.agents.store import AgentIdentity, MessageStore
from neurath.memory.store import canonical
from neurath.providers import jobs, waves
from neurath.providers.job_recovery import JobRecovery
from tests.test_task_ledger_service import service as task_service_fixture

service = task_service_fixture


@pytest.fixture
def wave(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    owner = AgentIdentity('codex', 'creator', 'codex:session:creator')
    MessageStore(tmp_path).register(owner)
    monkeypatch.setattr(waves, '_validate_scope', lambda *args: None)
    monkeypatch.setattr(jobs, 'validate_target', lambda *args: tmp_path)
    launches, leases = [], []

    def launch(argv, **kwargs):
        run_id = argv[argv.index('--run-id') + 1]
        with jobs._store(tmp_path).connection() as db:
            # Every slot must already be durable before the first spawn.
            count = db.execute('SELECT COUNT(*) FROM provider_jobs').fetchone()[0]
        launches.append((run_id, count))
        leases.append(JobRecovery(jobs._store(tmp_path)).claim_worker(owner.address, run_id))

    monkeypatch.setattr(jobs, '_launch', launch)
    scope = {'session_id': 'creator', 'actor_id': owner.actor, 'task_id': 'task',
                 'task_revision': 1, 'definition_digest': 'a' * 64}
    yield tmp_path, owner, scope, launches, leases
    for lease in leases:
        lease.close()


def entry(root, name, depends=()):
    return {'entry_id': name, 'depends_on': list(depends), 'request': {
        'worktree': str(root / name), 'assignment': 'Read ' + name, 'mode': 'read-only', 'purpose': 'worktree-worker'}}


def admit(wave, entries=None, parallel=2, key='admit'):
    root, owner, scope, _, _ = wave
    return waves.admit(root, owner, wave_id='wave', task_scope=scope,
                       entries=entries or [entry(root, 'a'), entry(root, 'b'), entry(root, 'c')],
                       max_parallel=parallel, capacity_basis='observed capacity', key=key)


def finish(wave, name, status='completed'):
    root, owner, _, _, leases = wave
    state = waves.read(root, owner, 'wave')
    selected = next(e for e in state['entries'] if e['entry_id'] == name)
    lease = next(lease for lease in leases if lease.run_id == selected['run_id'])
    result = {'status': status, 'worker_generation': lease.generation}
    if status == 'completed':
        result.update(implementation_dispatched=True, execution='native-turn-completed',
                      created={'provider': 'codex', 'native_session': 'observed-native'},
                      completion={'id': 'observed-turn', 'status': 'completed', 'error': None},
                      submission={'delivery': 'submitted', 'native_turn': 'observed-turn'},
                      completion_link={'native_session': 'observed-native', 'submitted_turn': 'observed-turn',
                                       'completed_turn': 'observed-turn', 'disposition': 'terminal'})
    jobs._finish(jobs._store(root), lease.run_id, result, lease)
    lease.close()
    return next(e for e in waves.read(root, owner, 'wave')['entries'] if e['entry_id'] == name)


def consume(wave, result, **overrides):
    root, owner, *_ = wave
    fields = {'wave_id': 'wave', 'entry_id': result['entry_id'], 'run_id': result['run_id'],
                  'generation': result['generation'], 'result_digest': result['result_digest'],
                  'verdict': 'accepted', 'key': 'consume-' + result['entry_id']}
    return waves.consume(root, owner, **(fields | overrides))


def test_all_ready_slots_reserved_before_first_launch_and_terminal_refills(wave):
    result = admit(wave)
    assert len(wave[3]) == 2
    assert wave[3][0][1] == 2
    assert result['pending'] is True
    finish(wave, 'a')
    assert len(wave[3]) == 3  # Does not wait for owner consumption of independent work.


def test_dependency_needs_exact_consumed_completed_result(wave):
    root = wave[0]
    admit(wave, [entry(root, 'a'), entry(root, 'b', ['a'])])
    completed = finish(wave, 'a')
    assert len(wave[3]) == 1
    assert completed['result_digest'] == 'sha256:' + hashlib.sha256(canonical(completed['result']).encode()).hexdigest()
    consume(wave, completed)
    assert len(wave[3]) == 2
    consume(wave, completed)
    assert len(wave[3]) == 2
    consume(wave, finish(wave, 'b'))
    assert waves.read(root, wave[1], 'wave')['pending'] is False


@pytest.mark.parametrize('override', [{'run_id': 'foreign'}, {'generation': 9},
                                     {'result_digest': 'sha256:' + '0' * 64}])
def test_consumption_exact_tuple_is_required(wave, override):
    root = wave[0]
    admit(wave, [entry(root, 'a'), entry(root, 'b', ['a'])])
    completed = finish(wave, 'a')
    with pytest.raises(ValueError):
        consume(wave, completed, **override)
    assert len(wave[3]) == 1


def test_failed_result_cannot_unlock_success_dependency(wave):
    root = wave[0]
    admit(wave, [entry(root, 'a'), entry(root, 'b', ['a'])])
    failed = finish(wave, 'a', 'failed')
    with pytest.raises(ValueError, match='completed'):
        consume(wave, failed)
    result = consume(wave, failed, verdict='rejected')
    assert result['pending'] is False
    assert result['all_succeeded'] is False
    assert len(wave[3]) == 1


def test_concurrent_replay_reserves_only_capacity_and_executes_once(wave):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: admit(wave), range(4)))
    assert len(wave[3]) == 2
    assert len({r['entries'][0]['run_id'] for r in results}) == 1


def test_launch_failure_preserves_outbox_for_event_reconciliation(wave, monkeypatch):
    launch = jobs._launch
    with monkeypatch.context() as patch:
        patch.setattr(jobs, '_launch', lambda *a, **k: (_ for _ in ()).throw(OSError('launch unavailable')))
        result = admit(wave)
        assert all(e['status'] == 'accepted' for e in result['entries'][:2])
    monkeypatch.setattr(jobs, '_launch', launch)
    waves.read(wave[0], wave[1], 'wave')
    assert len(wave[3]) == 2


def test_scope_revision_change_blocks_future_reservations(wave, monkeypatch):
    admit(wave)
    monkeypatch.setattr(waves, '_validate_scope', lambda *a: (_ for _ in ()).throw(ValueError('stale task')))
    finish(wave, 'a')
    assert len(wave[3]) == 2
    assert waves.read(wave[0], wave[1], 'wave')['blocked_reason']


def test_other_owner_cannot_read_consume_or_cancel(wave):
    admit(wave)
    other = AgentIdentity('codex', 'other', 'codex:session:other')
    with pytest.raises(ValueError, match='owner'):
        waves.read(wave[0], other, 'wave')
    with pytest.raises(ValueError, match='owner'):
        waves.cancel(wave[0], other, wave_id='wave', key='cancel')
    result = finish(wave, 'a')
    with pytest.raises(ValueError, match='owner'):
        waves.consume(wave[0], other, wave_id='wave', entry_id='a', run_id=result['run_id'],
                      generation=result['generation'], result_digest=result['result_digest'], verdict='accepted', key='x')


def test_cancel_blocks_queued_work_and_flags_only_wave_jobs(wave, monkeypatch):
    admit(wave)
    with monkeypatch.context() as patch:
        patch.setattr(jobs, '_launch', lambda *a, **k: None)
        unrelated = jobs.start(wave[0], wave[1], {'worktree': str(wave[0]), 'assignment': 'Other'}, key='other')
    waves.cancel(wave[0], wave[1], wave_id='wave', key='stop')
    state = waves.read(wave[0], wave[1], 'wave')
    assert state['cancel_requested'] is True
    assert state['entries'][2]['status'] == 'cancelled'
    assert all(jobs.status(wave[0], wave[1], e['run_id'])['cancel_requested'] for e in state['entries'][:2])
    assert not jobs.status(wave[0], wave[1], unrelated['run_id'])['cancel_requested']
    finish(wave, 'a', 'cancelled')
    assert len(wave[3]) == 2


def test_changed_replay_and_invalid_dag_leave_no_extra_jobs(wave):
    root, owner, *_ = wave
    with pytest.raises(ValueError):
        admit(wave, [entry(root, 'a', ['b']), entry(root, 'b', ['a'])])
    with jobs._store(root).connection() as db:
        assert db.execute('SELECT COUNT(*) FROM provider_jobs').fetchone()[0] == 0
    admit(wave)
    with pytest.raises(ValueError, match='changed'):
        admit(wave, [entry(root, 'different')])
    assert len(wave[3]) == 2
    assert len(waves.pending(root, session_id=owner.session, actor_id=owner.actor, task_id='task')) == 1


def test_unbound_native_scope_is_rejected(wave, monkeypatch):
    monkeypatch.undo()
    with pytest.raises((ValueError, FileNotFoundError)):
        admit(wave)


def test_native_task_scope_rechecks_current_revision(service):
    from tests.test_task_ledger_service import item
    task_service, _, _ = service
    defined = task_service.define([item()], expected_revision=0, key='define-wave')
    task = defined['tasks'][0]
    active = task_service.start(task['id'], expected_revision=1, expected_task_revision=1, key='start-wave')['tasks'][0]
    scope = {'session_id': 'one', 'actor_id': 'owner', 'task_id': active['id'],
             'task_revision': active['revision'], 'definition_digest': active['definition_digest']}
    subprocess.run(['git', 'init', '-q', str(task_service.worktree)], check=True)
    store = jobs._store(task_service.worktree)
    with store.connection() as db:
        waves._validate_scope(store, db, scope)
        with pytest.raises(ValueError, match='in-progress'):
            waves._validate_scope(store, db, scope | {'task_revision': active['revision'] + 1})


def test_worker_crash_after_claim_is_failed_without_relaunch(wave):
    admit(wave)
    wave[4][0].close()  # OS lease released before job status advanced.
    state = waves.read(wave[0], wave[1], 'wave')
    assert state['entries'][0]['status'] == 'failed'
    assert len(wave[3]) == 3  # The independent queued entry uses the freed slot.
    assert wave[3][0][0] != wave[3][2][0]


def test_cancel_before_launch_finishes_accepted_reservations(wave, monkeypatch):
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: None)
    admit(wave)
    state = waves.cancel(wave[0], wave[1], wave_id='wave', key='cancel')
    assert [e['status'] for e in state['entries']] == ['cancelled'] * 3


def test_snapshot_never_reconciles_and_matching_replay_does(wave, monkeypatch):
    root, identity, scope, launches, _ = wave
    launch = jobs._launch
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: None)
    waves.admit(root, identity, wave_id='wave', task_scope=scope, entries=[entry(root, 'a')],
                max_parallel=1, capacity_basis='observed', request_digest='sha256:' + 'b' * 64, key='admit')
    monkeypatch.setattr(jobs, '_launch', launch)
    waves.snapshot(root, identity, 'wave')
    assert not launches
    with pytest.raises(ValueError, match='changed'):
        waves.replay(root, identity, wave_id='wave', request_digest='changed', key='admit')
    waves.replay(root, identity, wave_id='wave', request_digest='sha256:' + 'b' * 64, key='admit')
    assert len(launches) == 1


def test_inbox_recovery_is_forbidden_for_every_wave_run(wave):
    admit(wave)
    result = finish(wave, 'a')
    store = jobs._store(wave[0])
    with store.connection() as db, pytest.raises(ValueError, match='wave'):
        waves.assert_recoverable(store, db, result['run_id'])
    consume(wave, result)
    with store.connection() as db, pytest.raises(ValueError, match='wave'):
        waves.assert_recoverable(store, db, result['run_id'])


def test_public_wave_names_are_independent_for_distinct_owners(wave, monkeypatch):
    root, first, scope, *_ = wave
    second = AgentIdentity('codex', 'second', 'codex:session:second')
    MessageStore(root).register(second)
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: None)
    one = admit(wave, [entry(root, 'a')])
    two = waves.admit(root, second, wave_id='wave', task_scope=scope | {
        'session_id': second.session, 'actor_id': second.actor}, entries=[entry(root, 'a')],
        max_parallel=1, capacity_basis='observed capacity', key='admit')
    assert one['wave_id'] == two['wave_id'] == 'wave'
    assert one['entries'][0]['run_id'] != two['entries'][0]['run_id']
    waves.cancel(root, second, wave_id='wave', key='cancel')
    assert waves.snapshot(root, second, 'wave')['cancel_requested']
    assert not waves.snapshot(root, first, 'wave')['cancel_requested']
    for identity in (first, second):
        assert waves.snapshot_for_scope(root, session_id=identity.session,
            actor_id=identity.actor, wave_id='wave')['owner'] == identity.address


def test_states_only_call_exact_consumed_completed_results_succeeded(wave):
    admit(wave)
    assert set(waves.snapshot(wave[0], wave[1], 'wave')['states'].values()) == {'accepted', 'queued'}
    result = finish(wave, 'a')
    assert waves.snapshot(wave[0], wave[1], 'wave')['states']['a'] == 'completed'
    consumed = consume(wave, result)
    assert consumed['states']['a'] == 'succeeded'
    failed = finish(wave, 'b', 'failed')
    rejected = consume(wave, failed, verdict='rejected')
    assert rejected['states']['b'] == 'rejected'
    assert not rejected['all_succeeded']


def test_launch_error_is_visible_and_clears_after_successful_retry(wave, monkeypatch):
    launch = jobs._launch
    monkeypatch.setattr(jobs, '_launch', lambda *a, **k: (_ for _ in ()).throw(OSError('launcher unavailable')))
    state = admit(wave)
    assert state['entries'][0]['dispatch_state'] == 'launch-failed'
    assert 'launcher unavailable' in state['entries'][0]['dispatch_diagnostic']
    monkeypatch.setattr(jobs, '_launch', launch)
    retried = waves.read(wave[0], wave[1], 'wave')
    assert retried['entries'][0]['dispatch_state'] == 'worker-claimed'
    assert retried['entries'][0]['dispatch_diagnostic'] == ''


def starting(wave, *, result=None, drop_outbox=False):
    lease = wave[4][0]
    with jobs._store(wave[0]).connection() as db:
        lease.assert_current(db)
        db.execute("UPDATE provider_jobs SET status='starting',result=? WHERE id=?",
                   (None if result is None else canonical(result), lease.run_id))
        if drop_outbox:
            db.execute('DELETE FROM provider_wave_outbox WHERE run_id=?', (lease.run_id,))
    return lease


def test_crashed_starting_job_is_failed_without_repeating_assignment(wave):
    root = wave[0]
    admit(wave, [entry(root, 'a'), entry(root, 'b', ['a']), entry(root, 'c')], parallel=1)
    dead = starting(wave, drop_outbox=True)
    dead.close()
    state = waves.read(root, wave[1], 'wave')
    failed = state['entries'][0]
    assert failed['status'] == 'failed'
    assert failed['result']['execution'] == 'unobserved'
    assert failed['result']['native_creation'] == 'unobserved'
    assert 'created' not in failed['result'] and not failed['consumption']
    assert state['entries'][1]['status'] == 'queued'
    assert state['entries'][2]['status'] == 'accepted'
    assert [run for run, _ in wave[3]].count(dead.run_id) == 1


def test_cancel_can_finish_crashed_starting_job(wave):
    admit(wave)
    dead = starting(wave)
    dead.close()
    state = waves.cancel(wave[0], wave[1], wave_id='wave', key='cancel-starting')
    assert state['entries'][0]['status'] == 'cancelled'
    assert state['entries'][0]['result']['execution'] == 'unobserved'


def test_starting_live_lease_cannot_be_reconciled(wave):
    admit(wave)
    live = starting(wave)
    state = waves.read(wave[0], wave[1], 'wave')
    assert state['entries'][0]['status'] == 'starting'
    with jobs._store(wave[0]).connection() as db:
        live.assert_current(db)
    assert len(wave[3]) == 2


@pytest.mark.parametrize('evidence', ['created', 'assignment', 'observation', 'route'])
def test_starting_native_evidence_cannot_be_reconciled(wave, evidence):
    admit(wave)
    result = {'created': {'native_session': 'observed-session'}} if evidence == 'created' else (
        {'implementation_dispatched': True} if evidence == 'assignment' else None)
    dead = starting(wave, result=result)
    if evidence in {'observation', 'route'}:
        from neurath.providers.report_routing import schema
        with jobs._store(wave[0]).connection() as db:
            schema(db)
            if evidence == 'observation':
                db.execute('INSERT INTO provider_executor_observations VALUES(?,?,?)', (dead.run_id, 1, '{}'))
            else:
                db.execute('INSERT INTO provider_executor_routes VALUES(?,?,?,?)', (dead.run_id, 1, 'observed-peer', 'digest'))
    dead.close()
    state = waves.read(wave[0], wave[1], 'wave')
    assert state['entries'][0]['status'] == 'starting'
    assert len(wave[3]) == 2


def test_pre_native_close_requires_the_exact_observed_generation(wave):
    admit(wave)
    dead = starting(wave)
    dead.close()
    recovery = JobRecovery(jobs._store(wave[0]))
    finalized = []
    with pytest.raises(ValueError, match='generation'):
        recovery.finish_pre_native(wave[1].address, dead.run_id, 2,
                                   lambda db, lease: finalized.append(lease.generation))
    assert not finalized
    assert jobs.status(wave[0], wave[1], dead.run_id)['status'] == 'starting'


def test_sparse_completed_result_is_not_implementation_completion(wave):
    admit(wave)
    lease = wave[4][0]
    jobs._finish(jobs._store(wave[0]), lease.run_id,
                 {'status': 'completed', 'worker_generation': 1}, lease)
    lease.close()
    result = waves.snapshot(wave[0], wave[1], 'wave')['entries'][0]
    with pytest.raises(ValueError, match='implementation'):
        consume(wave, result)


def test_retry_replaces_failed_attempt_and_retains_original_evidence(wave):
    root, identity, *_ = wave
    admit(wave, [entry(root, 'a'), entry(root, 'b', ['a'])], parallel=1)
    failed = finish(wave, 'a', 'failed')
    consume(wave, failed, verdict='rejected')
    request = entry(root, 'a')['request'] | {'plan_id': 'fresh-plan'}
    retried = waves.retry(root, identity, wave_id='wave', entry_id='a', request=request, key='retry-a')
    current = retried['entries'][0]
    assert current['run_id'] != failed['run_id'] and current['attempt'] == 1
    assert current['attempts'][0]['run_id'] == failed['run_id']
    assert current['attempts'][0]['result_digest'] == failed['result_digest']
    assert current['attempts'][0]['consumption']['verdict'] == 'rejected'
    assert jobs.status(root, identity, failed['run_id'])['status'] == 'failed'
    assert waves.retry(root, identity, wave_id='wave', entry_id='a', request=request, key='retry-a')['entries'][0]['run_id'] == current['run_id']
    assert len(wave[3]) == 2
    for run_id in (failed['run_id'], current['run_id']):
        with jobs._store(root).connection() as db, pytest.raises(ValueError, match='wave'):
            waves.assert_recoverable(jobs._store(root), db, run_id)
    new = finish(wave, 'a')
    consume(wave, new, key='consume-a-retry')
    assert len(wave[3]) == 3


def test_retry_rejects_changed_assignment_or_unfinished_execution(wave):
    root, identity, *_ = wave
    admit(wave)
    request = entry(root, 'a')['request']
    with pytest.raises(ValueError):
        waves.retry(root, identity, wave_id='wave', entry_id='a', request=request, key='running')
    finish(wave, 'a', 'failed')
    with pytest.raises(ValueError, match='scope'):
        waves.retry(root, identity, wave_id='wave', entry_id='a', request=request | {'assignment': 'Different'}, key='changed')


def test_generation_two_inbox_completion_cannot_unlock_dependencies(wave):
    root, identity, *_ = wave
    admit(wave, [entry(root, 'a'), entry(root, 'b', ['a'])], parallel=1)
    failed = finish(wave, 'a', 'failed')
    store = jobs._store(root)
    with store.connection() as db:
        db.execute("UPDATE provider_worker_leases SET generation=2,state='accepted',token=NULL WHERE run_id=?", (failed['run_id'],))
    inbox = JobRecovery(store).claim_worker(identity.address, failed['run_id'], generation=2)
    jobs._finish(store, inbox.run_id, {'status': 'completed', 'worker_generation': 2,
        'implementation_dispatched': True, 'execution': 'native-turn-completed',
        'created': {'provider': 'codex', 'native_session': 'observed-native'},
        'completion': {'id': 'inbox-turn', 'status': 'completed', 'error': None}}, inbox)
    inbox.close()
    result = waves.snapshot(root, identity, 'wave')['entries'][0]
    with pytest.raises(ValueError, match='implementation'):
        consume(wave, result)
    assert len(wave[3]) == 1


def test_retry_replay_uses_exact_request_digest_without_target_revalidation(wave, monkeypatch):
    root, identity, *_ = wave
    admit(wave, [entry(root, 'a')], parallel=1)
    finish(wave, 'a', 'failed')
    request = entry(root, 'a')['request']
    initial = waves.retry(root, identity, wave_id='wave', entry_id='a', request=request,
                          request_digest='sha256:' + 'a' * 64, key='retry')
    monkeypatch.setattr(jobs, 'validate_target', lambda *a: (_ for _ in ()).throw(ValueError('now dirty')))
    replayed = waves.replay_retry(root, identity, wave_id='wave', entry_id='a',
                                  request_digest='sha256:' + 'a' * 64, key='retry')
    assert replayed['entries'][0]['run_id'] == initial['entries'][0]['run_id']
    assert len(wave[3]) == 2
    with pytest.raises(ValueError, match='changed'):
        waves.replay_retry(root, identity, wave_id='wave', entry_id='a', request_digest='changed', key='retry')


def test_retry_requires_released_worker_and_observed_native_closure(wave):
    root, identity, *_ = wave
    admit(wave, [entry(root, 'a')], parallel=1)
    lease = wave[4][0]
    jobs._finish(jobs._store(root), lease.run_id, {'status': 'failed', 'worker_generation': 1,
                 'created': {'provider': 'codex', 'native_session': 'observed-native'}}, lease)
    fields = {'wave_id': 'wave', 'entry_id': 'a', 'request': entry(root, 'a')['request'], 'key': 'retry'}
    with pytest.raises(ValueError, match='worker-live'):
        waves.retry(root, identity, **fields)
    lease.close()
    with pytest.raises(ValueError, match='closure'):
        waves.retry(root, identity, **fields)


def test_consumption_accepts_native_claude_completion_shape(wave):
    root, identity, *_ = wave
    request = entry(root, 'a')
    request['request']['provider'] = 'claude-code'
    admit(wave, [request], parallel=1)
    lease = wave[4][0]
    jobs._finish(jobs._store(root), lease.run_id, {'status': 'completed', 'worker_generation': 1,
        'implementation_dispatched': True, 'execution': 'native-response-completed',
        'created': {'provider': 'claude-code', 'native_session': 'observed-claude'},
        'completion': {'subtype': 'success', 'is_error': False, 'native_session': 'observed-claude',
                       'permission_denial_count': 0, 'approval_pending': False}}, lease)
    lease.close()
    result = waves.snapshot(root, identity, 'wave')['entries'][0]
    assert consume(wave, result)['all_succeeded']


def test_codex_forged_link_cannot_be_consumed(wave):
    admit(wave, [entry(wave[0], 'a')], parallel=1)
    lease = wave[4][0]
    result = {'status': 'completed', 'worker_generation': 1,
        'implementation_dispatched': True, 'execution': 'native-turn-completed',
        'created': {'provider': 'codex', 'native_session': 'observed-native'},
        'submission': {'delivery': 'submitted', 'native_turn': 'original-turn'},
        'completion': {'id': 'unrelated-turn', 'status': 'completed', 'error': None},
        'completion_link': {'native_session': 'observed-native', 'submitted_turn': 'original-turn',
                            'completed_turn': 'followup-turn', 'disposition': 'terminal'}}
    jobs._finish(jobs._store(wave[0]), lease.run_id, result, lease)
    lease.close()
    final = waves.snapshot(wave[0], wave[1], 'wave')['entries'][0]
    with pytest.raises(ValueError, match='implementation'):
        consume(wave, final)


def test_codex_acceptance_allows_owned_followup_completion_link(wave):
    admit(wave, [entry(wave[0], 'a')], parallel=1)
    lease = wave[4][0]
    jobs._finish(jobs._store(wave[0]), lease.run_id, {'status': 'completed', 'worker_generation': 1,
        'implementation_dispatched': True, 'execution': 'native-turn-completed',
        'created': {'provider': 'codex', 'native_session': 'observed-native'},
        'submission': {'delivery': 'submitted', 'native_turn': 'original-turn'},
        'completion': {'id': 'followup-turn', 'status': 'completed', 'error': None},
        'completion_link': {'native_session': 'observed-native', 'submitted_turn': 'original-turn',
                            'completed_turn': 'followup-turn', 'disposition': 'terminal'}}, lease)
    lease.close()
    final = waves.snapshot(wave[0], wave[1], 'wave')['entries'][0]
    assert consume(wave, final)['all_succeeded']
