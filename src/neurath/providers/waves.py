"""Durable scheduling of an authenticated provider batch.

Runtime admission supplies fully checked requests and native task scope. Background
callbacks use this stored capability only: they never reconstruct a native actor,
create a direct-child grant, or grant evaluation authority to a provider worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict

from neurath.agents.lifecycle import TERMINAL, TaskLifecycle
from neurath.agents.store import bounded
from neurath.providers import jobs, wave_dispatch
from neurath.providers.contracts import implementation_completed
from neurath.providers.job_recovery import JobRecovery
from neurath.providers.wave_policy import (
    TaskScope,
    descendants,
    digest,
    normalize_entries,
    request_scope,
    schedule,
)
from neurath.providers.wave_store import (
    open_wave_store,
    owned_wave,
    record_operation,
    wave_key,
)
from neurath.providers.wave_store import (
    snapshot as wave_snapshot,
)
from neurath.redaction import clean
from neurath.runtime.database import RuntimeTransaction
from neurath.serialization import canonical


def _drain(store, wave_id):
    return wave_dispatch.drain(store, wave_id, validate_scope=_validate_scope, finish=jobs._finish)


def _close_initial(store, recovery, owner, run_id, reason, *, generation=None):
    return wave_dispatch.close_initial(store, recovery, owner, run_id, reason,
                                       generation=generation, finish=jobs._finish)


def _validate_scope(store, db, scope):
    """Read original authority atomically; foreground liveness is not re-created."""
    from scripts.agent_harness.session_kernel import (
        ActorStatus,
        SessionKernelError,
        SessionLocator,
        SessionStateStore,
        SessionStatus,
    )
    from scripts.agent_harness.task_service import validate_task_scope

    scope = TaskScope(**scope)
    tx = RuntimeTransaction(db)
    path = SessionLocator(store.root).locate(scope.session_id).process_state
    try:
        process = SessionStateStore(path).read_transaction(tx, scope.session_id)
    except SessionKernelError as error:
        raise ValueError('wave native scope is unavailable') from error
    root_actor = process.session.root_actor_id
    actor = process.actors.get(root_actor)
    if (str(root_actor) != scope.actor_id or process.session.status is not SessionStatus.ACTIVE
            or actor is None or actor.status not in {ActorStatus.ACTIVE, ActorStatus.IDLE}):
        raise ValueError('wave requires its original active native task owner')
    validate_task_scope(tx, process, {name: getattr(scope, name)
        for name in ('task_id', 'task_revision', 'definition_digest')})


def _schedule(store, db, wave_id):
    row = db.execute('SELECT * FROM provider_waves WHERE id=?', (wave_id,)).fetchone()
    db.after_commit[('provider-wave', wave_id)] = lambda: _drain(store, wave_id)
    if row['cancel_requested']:
        return
    request = json.loads(row['request'])
    try:
        _validate_scope(store, db, request['task_scope'])
    except (ValueError, FileNotFoundError) as error:
        db.execute('UPDATE provider_waves SET blocked_reason=? WHERE id=?', (clean(str(error)), wave_id))
        return
    db.execute("UPDATE provider_waves SET blocked_reason='' WHERE id=?", (wave_id,))
    state = wave_snapshot(db, row)
    entries = {e['entry_id']: e for e in state['entries']}
    decision = schedule(state['entries'], request['max_parallel'])
    db.executemany("UPDATE provider_wave_entries SET state='blocked' WHERE wave_id=? AND entry_id=?",
                   [(wave_id, name) for name in decision.blocked])
    tasks = TaskLifecycle(store)
    definitions = {entry['entry_id']: entry for entry in request['entries']}
    for name in decision.ready:
        definition, e = definitions[name], entries[name]
        run_key = ['provider-wave', row['owner'], wave_id, name]
        if e['attempt']:
            run_key.append(e['attempt'])
        run_id = hashlib.sha256(canonical(run_key).encode()).hexdigest()
        override = db.execute('SELECT request_override FROM provider_wave_entries WHERE wave_id=? AND entry_id=?',
                              (wave_id, name)).fetchone()[0]
        admitted = json.loads(override) if override else definition['request']
        control = tempfile.mkdtemp(prefix='neurath-job-', dir='/tmp')
        db.execute('INSERT INTO provider_jobs(id,owner,request,status,control,updated) VALUES(?,?,?,?,?,?)',
                   (run_id, row['owner'], canonical(admitted), 'accepted', control, time.time()))
        tasks.bind(row['owner'], row['owner'], key='provider:' + run_id,
                   transport='provider-supervisor', _db=db)
        db.execute("UPDATE provider_wave_entries SET run_id=?,state='reserved' WHERE wave_id=? AND entry_id=?",
                   (run_id, wave_id, name))
        db.execute('INSERT INTO provider_wave_outbox(run_id,wave_id) VALUES(?,?)', (run_id, wave_id))
    db.after_commit[('provider-wave', wave_id)] = lambda: _drain(store, wave_id)


def admit(root, identity, *, wave_id, task_scope, entries, max_parallel, capacity_basis, key, workflow_id='', request_digest=''):
    bounded(wave_id, 'wave ID', 128)
    bounded(capacity_basis, 'capacity basis', 4096)
    if type(max_parallel) is not int or not 1 <= max_parallel <= 32:
        raise ValueError('invalid wave capacity')
    scope = TaskScope(**task_scope)
    if not identity.is_root or identity.session != scope.session_id or identity.actor != scope.actor_id:
        raise ValueError('wave requires its exact native root owner')
    normalized = normalize_entries(entries)
    internal_id = wave_key(identity, wave_id)
    request = {'task_scope': asdict(scope), 'entries': [asdict(e) for e in normalized],
                   'max_parallel': max_parallel, 'capacity_basis': capacity_basis, 'workflow_id': workflow_id, 'request_digest': request_digest}
    if len(canonical(request).encode()) > 1048576:
        raise ValueError('wave admission exceeds one MiB')
    store = open_wave_store(root)
    with store.connection() as db:
        store._agent(db, identity.address)
        _validate_scope(store, db, asdict(scope))
        record_operation(db, identity.address, key, ['admit', wave_id, request])
        previous = db.execute('SELECT * FROM provider_waves WHERE id=?', (internal_id,)).fetchone()
        if previous:
            owned_wave(db, identity, wave_id)
            if previous['request'] != canonical(request):
                raise ValueError('wave admission changed request')
        else:
            for e in normalized:
                jobs.validate_target(root, e.request)
            db.execute('INSERT INTO provider_waves(id,public_id,owner,actor,session,task_id,request) VALUES(?,?,?,?,?,?,?)',
                       (internal_id, wave_id, identity.address, identity.actor, identity.session, scope.task_id, canonical(request)))
            db.executemany('INSERT INTO provider_wave_entries(wave_id,entry_id,ordinal) VALUES(?,?,?)',
                           [(internal_id, e.entry_id, n) for n, e in enumerate(normalized)])
        _schedule(store, db, internal_id)
    return _read(store, identity, wave_id)


def _read(store, identity, wave_id):
    with store.connection() as db:
        return wave_snapshot(db, owned_wave(db, identity, wave_id))


def snapshot(root, identity, wave_id):
    """Pure owner read; no outbox reconciliation or provider launch."""
    return _read(open_wave_store(root), identity, wave_id)


def replay(root, identity, *, wave_id, request_digest, key):
    store = open_wave_store(root)
    with store.connection() as db:
        if not db.execute('SELECT 1 FROM provider_waves WHERE id=?', (wave_key(identity, wave_id),)).fetchone():
            return None
        row = owned_wave(db, identity, wave_id)
        request = json.loads(row['request'])
        if not request_digest or request.get('request_digest') != request_digest:
            raise ValueError('wave replay changed public request')
        _validate_scope(store, db, request['task_scope'])
        record_operation(db, identity.address, key, ['admit', wave_id, request])
        _schedule(store, db, row['id'])
    return _read(store, identity, wave_id)


def read(root, identity, wave_id):
    store = open_wave_store(root)
    with store.connection() as db:
        row = owned_wave(db, identity, wave_id)
        _schedule(store, db, row['id'])
    return _read(store, identity, wave_id)


def consume(root, identity, *, wave_id, entry_id, run_id, generation, result_digest, verdict, key):
    if type(generation) is not int or generation < 1 or verdict not in {'accepted', 'rejected'}:
        raise ValueError('invalid result consumption')
    store = open_wave_store(root)
    proof = {'run_id': run_id, 'generation': generation, 'result_digest': result_digest, 'verdict': verdict}
    with store.connection() as db:
        wave = owned_wave(db, identity, wave_id)
        item = db.execute('SELECT * FROM provider_wave_entries WHERE wave_id=? AND entry_id=?', (wave['id'], entry_id)).fetchone()
        if item is None or item['run_id'] != run_id:
            raise ValueError('result is not the exact wave entry run')
        job = db.execute('SELECT * FROM provider_jobs WHERE id=?', (run_id,)).fetchone()
        result = json.loads(job['result']) if job['result'] else {}
        lease = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
        if (job['owner'] != wave['owner'] or job['status'] not in TERMINAL or lease is None
                or (lease['generation'], lease['state']) != (generation, 'finished')
                or result.get('worker_generation') != generation or digest(result) != result_digest):
            raise ValueError('result generation/digest is not the exact completed provider run')
        if verdict == 'accepted':
            if job['status'] != 'completed':
                raise ValueError('only completed provider results can be accepted')
            if not implementation_completed(json.loads(job['request']), result, generation):
                raise ValueError('accepted result requires the original implementation native completion')
        if item['consumption'] and item['consumption'] != canonical(proof):
            raise ValueError('entry consumption changed result or verdict')
        record_operation(db, identity.address, key, ['consume', wave_id, entry_id, proof])
        db.execute('UPDATE provider_wave_entries SET consumption=? WHERE wave_id=? AND entry_id=?',
                   (canonical(proof), wave['id'], entry_id))
        _schedule(store, db, wave['id'])
    return _read(store, identity, wave_id)


def cancel(root, identity, *, wave_id, key):
    store = open_wave_store(root)
    with store.connection() as db:
        row = owned_wave(db, identity, wave_id)
        internal_id = row['id']
        record_operation(db, identity.address, key, ['cancel', wave_id])
        db.execute('UPDATE provider_waves SET cancel_requested=1 WHERE id=?', (internal_id,))
        db.execute("UPDATE provider_wave_entries SET state='cancelled' WHERE wave_id=? AND run_id IS NULL", (internal_id,))
        runs = [row[0] for row in db.execute('SELECT run_id FROM provider_wave_entries WHERE wave_id=? AND run_id IS NOT NULL', (internal_id,))]
        for run_id in runs:
            db.execute('UPDATE provider_jobs SET cancel_requested=1 WHERE id=?', (run_id,))
    recovery = JobRecovery(store)
    for run_id in runs:
        jobs.cancel(root, identity, run_id)
        _close_initial(store, recovery, identity.address, run_id, 'cancelled')
    return _read(store, identity, wave_id)


def pending(root, *, session_id, actor_id, task_id=None, db=None):
    """Task gates can supply their existing connection without nested initialization."""
    if db is None:
        with open_wave_store(root).connection() as connection:
            return pending(root, session_id=session_id, actor_id=actor_id, task_id=task_id, db=connection)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_waves'").fetchone():
        return []
    rows = db.execute('SELECT * FROM provider_waves WHERE session=? AND actor=?', (session_id, actor_id))
    return [snapshot for row in rows if task_id is None or row['task_id'] == task_id
            if not (snapshot := wave_snapshot(db, row))['all_succeeded']]


def on_terminal(store, db, run_id, result):
    """Called inside jobs._finish after result and generation are committed together."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_wave_entries'").fetchone():
        return
    entry = db.execute('SELECT wave_id FROM provider_wave_entries WHERE run_id=?', (run_id,)).fetchone()
    if entry is not None:
        db.execute('DELETE FROM provider_wave_outbox WHERE run_id=?', (run_id,))
        _schedule(store, db, entry['wave_id'])


def assert_recoverable(store, db, run_id):
    """Inbox recovery never counts as a wave implementation attempt."""
    for table in ('provider_wave_entries', 'provider_wave_attempts'):
        if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                and db.execute(f'SELECT 1 FROM {table} WHERE run_id=?', (run_id,)).fetchone()):
            raise ValueError('provider wave runs require a fresh admitted implementation retry, not inbox recovery')


def snapshot_for_scope(root, *, session_id, actor_id, wave_id):
    """Internal phase read port for an already authenticated native handle."""
    store = open_wave_store(root)
    with store.connection() as db:
        row = db.execute('SELECT * FROM provider_waves WHERE public_id=? AND session=? AND actor=?',
                         (wave_id, session_id, actor_id)).fetchone()
        if row is None or (row['session'], row['actor']) != (session_id, actor_id):
            raise ValueError('provider wave requires its exact owner scope')
        return wave_snapshot(db, row)


def replay_retry(root, identity, *, wave_id, entry_id, request_digest, key):
    store = open_wave_store(root)
    with store.connection() as db:
        wave = owned_wave(db, identity, wave_id)
        _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
        previous = db.execute('SELECT * FROM provider_wave_retries WHERE owner=? AND key=?', (identity.address, key)).fetchone()
        if previous is None:
            return None
        if (not request_digest or previous['request_digest'] != request_digest
                or previous['wave_id'] != wave['id'] or previous['entry_id'] != entry_id):
            raise ValueError('wave retry replay changed public request')
        _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
        return wave_snapshot(db, wave)


def retry(root, identity, *, wave_id, entry_id, request, key, request_digest=''):
    """Admit a new original-assignment attempt after a genuinely terminal failure.

    The runtime revalidates target, model and policy before providing this request.
    An old attempt remains immutable and never becomes generation-2 inbox work.
    """
    bounded(key, 'retry key')
    if not isinstance(request, dict) or len(canonical(request).encode()) > 1048576:
        raise ValueError('retry request must be an admitted object within one MiB')
    store = open_wave_store(root)
    recovery = JobRecovery(store)
    with store.connection() as db:
        wave = owned_wave(db, identity, wave_id)
        _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
        previous = db.execute('SELECT * FROM provider_wave_retries WHERE owner=? AND key=?', (identity.address, key)).fetchone()
        if previous:
            if (previous['wave_id'] != wave['id'] or previous['entry_id'] != entry_id
                    or previous['request'] != canonical(request) or previous['request_digest'] != request_digest):
                raise ValueError('wave retry key changed request')
            return wave_snapshot(db, wave)
        item = db.execute('SELECT * FROM provider_wave_entries WHERE wave_id=? AND entry_id=?', (wave['id'], entry_id)).fetchone()
        if item is None or item['run_id'] is None:
            raise ValueError('retry requires an observed failed or cancelled attempt')
        old_run_id = item['run_id']
    fd = recovery._lock(old_run_id)
    try:
        with store.connection() as db:
            wave = owned_wave(db, identity, wave_id)
            definition = json.loads(wave['request'])
            _validate_scope(store, db, definition['task_scope'])
            if wave['cancel_requested']:
                raise ValueError('cancelled wave cannot admit another attempt')
            item = db.execute('SELECT * FROM provider_wave_entries WHERE wave_id=? AND entry_id=?', (wave['id'], entry_id)).fetchone()
            if item['run_id'] != old_run_id:
                raise ValueError('retry current attempt changed')
            job = db.execute('SELECT * FROM provider_jobs WHERE id=?', (old_run_id,)).fetchone()
            result = json.loads(job['result']) if job['result'] else {}
            lease = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (old_run_id,)).fetchone()
            if (job['status'] not in {'failed', 'cancelled'} or lease is None
                    or tuple(lease) != (1, 'finished') or result.get('worker_generation') != 1):
                raise ValueError('retry requires exact finished failure generation and released worker lease')
            consumed = json.loads(item['consumption']) if item['consumption'] else None
            if consumed and consumed['verdict'] == 'accepted':
                raise ValueError('accepted implementation cannot retry')
            if result.get('created'):
                closure = result.get('closure') or {}
                if (closure.get('connection_closed') is not True or closure.get('native_process_exited') is not True
                        or closure.get('native_session') != result['created'].get('native_session')):
                    raise ValueError('retry native transport closure is unverified')
            original = definition['entries'][item['ordinal']]['request']
            if not isinstance(request, dict) or request_scope(request) != request_scope(original):
                raise ValueError('retry must preserve original assignment/provider/worktree scope')
            affected = descendants(definition['entries'], {entry_id})
            for entry in wave_snapshot(db, wave)['entries']:
                if entry['entry_id'] in affected and entry['consumption'] and entry['consumption']['verdict'] == 'accepted':
                    raise ValueError('accepted descendant prevents retry')
            jobs.validate_target(root, request)
            record_operation(db, identity.address, key, ['retry', wave_id, entry_id, request, request_digest])
            archived = {'attempt': item['attempt'], 'run_id': old_run_id, 'request': json.loads(job['request']),
                        'result': result, 'result_digest': digest(result), 'consumption': consumed,
                        'generation': 1, 'status': job['status']}
            db.execute('INSERT INTO provider_wave_attempts VALUES(?,?,?,?,?)',
                       (wave['id'], entry_id, item['attempt'], old_run_id, canonical(archived)))
            db.execute('INSERT INTO provider_wave_retries VALUES(?,?,?,?,?,?)',
                       (identity.address, key, wave['id'], entry_id, canonical(request), request_digest))
            db.execute("UPDATE provider_wave_entries SET run_id=NULL,state='queued',consumption=NULL,attempt=attempt+1,request_override=? "
                       'WHERE wave_id=? AND entry_id=?', (canonical(request), wave['id'], entry_id))
            db.execute("UPDATE provider_wave_entries SET state='queued' WHERE wave_id=? AND run_id IS NULL AND state='blocked'", (wave['id'],))
            _schedule(store, db, wave['id'])
    finally:
        os.close(fd)
    return _read(store, identity, wave_id)
