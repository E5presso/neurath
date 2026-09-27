"""Durable scheduling of an authenticated provider batch.

Runtime admission supplies fully checked requests and native task scope. Background
callbacks use this stored capability only: they never reconstruct a native actor,
create a direct-child grant, or grant evaluation authority to a provider worker.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from neurath.agents.lifecycle import TERMINAL, TaskLifecycle
from neurath.agents.runner import child_environment
from neurath.agents.store import bounded
from neurath.memory.store import canonical, clean
from neurath.providers import jobs
from neurath.providers.contracts import codex_completion_link
from neurath.providers.job_recovery import JobRecovery, RecoveryUnavailable
from neurath.runtime.database import RuntimeTransaction


@dataclass(frozen=True)
class TaskScope:
    session_id: str
    actor_id: str
    task_id: str
    task_revision: int
    definition_digest: str

    def __post_init__(self):
        for name in ('session_id', 'actor_id', 'task_id', 'definition_digest'):
            bounded(getattr(self, name), name)
        if type(self.task_revision) is not int or self.task_revision < 1:
            raise ValueError('invalid task revision')


@dataclass(frozen=True)
class Entry:
    entry_id: str
    depends_on: tuple[str, ...]
    request: dict


def _digest(value):
    return 'sha256:' + hashlib.sha256(canonical(value).encode()).hexdigest()


def _store(root):
    store = jobs._store(root)
    with store.connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS provider_waves (
            id TEXT PRIMARY KEY, public_id TEXT NOT NULL, owner TEXT NOT NULL, actor TEXT NOT NULL,
            session TEXT NOT NULL, task_id TEXT NOT NULL, request TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0, blocked_reason TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS provider_wave_entries (
            wave_id TEXT NOT NULL, entry_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            run_id TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'queued',
            consumption TEXT, attempt INTEGER NOT NULL DEFAULT 0, request_override TEXT, PRIMARY KEY(wave_id,entry_id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS provider_wave_outbox (
            run_id TEXT PRIMARY KEY, wave_id TEXT NOT NULL, diagnostic TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS provider_wave_attempts (
            wave_id TEXT NOT NULL, entry_id TEXT NOT NULL, attempt INTEGER NOT NULL,
            run_id TEXT UNIQUE NOT NULL, record TEXT NOT NULL, PRIMARY KEY(wave_id,entry_id,attempt))''')
        db.execute('''CREATE TABLE IF NOT EXISTS provider_wave_retries (
            owner TEXT NOT NULL, key TEXT NOT NULL, wave_id TEXT NOT NULL, entry_id TEXT NOT NULL,
            request TEXT NOT NULL, request_digest TEXT NOT NULL, PRIMARY KEY(owner,key))''')
        db.execute('''CREATE TABLE IF NOT EXISTS provider_wave_operations (
            owner TEXT NOT NULL, key TEXT NOT NULL, request TEXT NOT NULL,
            PRIMARY KEY(owner,key))''')
    return store


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


def _entries(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 32:
        raise ValueError('wave requires one to 32 entries')
    result, names = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'entry_id', 'depends_on', 'request'}:
            raise ValueError('entry requires entry_id, depends_on and admitted request')
        name = bounded(item['entry_id'], 'entry ID', 128)
        deps = item['depends_on']
        if (name in names or not isinstance(deps, list) or any(not isinstance(d, str) for d in deps)
                or len(set(deps)) != len(deps) or not isinstance(item['request'], dict)):
            raise ValueError('invalid wave entry')
        names.add(name)
        result.append(Entry(name, tuple(deps), item['request']))
    visited = set()
    while len(visited) < len(result):
        ready = {e.entry_id for e in result if e.entry_id not in visited and set(e.depends_on) <= visited}
        if not ready:
            raise ValueError('wave dependencies contain a cycle or unknown entry')
        visited.update(ready)
    return result


def _wave_key(identity, wave_id):
    return hashlib.sha256(canonical([identity.address, identity.actor, wave_id]).encode()).hexdigest()


def _owned(db, identity, wave_id):
    row = db.execute('SELECT * FROM provider_waves WHERE id=?', (_wave_key(identity, wave_id),)).fetchone()
    if row is None or row['owner'] != identity.address or row['actor'] != identity.actor:
        raise ValueError('provider wave requires its exact owner')
    return row


def _operation(db, owner, key, request):
    bounded(key, 'wave operation key')
    encoded = canonical(request)
    previous = db.execute('SELECT request FROM provider_wave_operations WHERE owner=? AND key=?', (owner, key)).fetchone()
    if previous:
        if previous['request'] != encoded:
            raise ValueError('wave operation key changed request')
        return True
    db.execute('INSERT INTO provider_wave_operations VALUES(?,?,?)', (owner, key, encoded))
    return False


def _dispatch_snapshot(db, item, job):
    if job is None:
        return item['state'], ''
    if job['status'] in TERMINAL:
        return 'terminal', ''
    has_leases = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_worker_leases'").fetchone()
    lease = (db.execute('SELECT state FROM provider_worker_leases WHERE run_id=?', (item['run_id'],)).fetchone()
             if has_leases else None)
    if lease and lease['state'] == 'active':
        return 'worker-claimed', ''
    outbox = db.execute('SELECT diagnostic FROM provider_wave_outbox WHERE run_id=?', (item['run_id'],)).fetchone()
    if outbox is not None:
        return ('launch-failed' if outbox['diagnostic'] else 'launch-pending'), outbox['diagnostic']
    return job['status'], ''


def _entry_state(entry):
    consumed = entry['consumption']
    if consumed and consumed['verdict'] == 'rejected':
        return 'rejected'
    if (consumed and consumed['verdict'] == 'accepted' and entry['status'] == 'completed'
            and consumed['run_id'] == entry['run_id'] and consumed['generation'] == entry['generation']
            and consumed['result_digest'] == entry['result_digest']):
        return 'succeeded'
    return entry['status']


def _snapshot(db, row):
    request = json.loads(row['request'])
    entries = []
    for item in db.execute('SELECT * FROM provider_wave_entries WHERE wave_id=? ORDER BY ordinal', (row['id'],)):
        definition = request['entries'][item['ordinal']]
        job = db.execute('SELECT status,result FROM provider_jobs WHERE id=?', (item['run_id'],)).fetchone()
        result = json.loads(job['result']) if job and job['result'] else None
        terminal = job and job['status'] in TERMINAL
        dispatch_state, diagnostic = _dispatch_snapshot(db, item, job)
        entries.append({'entry_id': item['entry_id'], 'depends_on': definition['depends_on'],
            'run_id': item['run_id'], 'status': job['status'] if job else item['state'],
            'attempt': item['attempt'], 'original_request': _request_scope(definition['request']),
            'attempts': [json.loads(prior[0]) for prior in db.execute(
                'SELECT record FROM provider_wave_attempts WHERE wave_id=? AND entry_id=? ORDER BY attempt',
                (row['id'], item['entry_id']))],
            'dispatch_state': dispatch_state, 'dispatch_diagnostic': diagnostic,
            'generation': result.get('worker_generation') if terminal and result else None,
            'result_digest': _digest(result) if terminal and result else None, 'result': result,
            'consumption': json.loads(item['consumption']) if item['consumption'] else None})
    states = {e['entry_id']: _entry_state(e) for e in entries}
    pending_entries = [e for e in entries if not e['consumption'] and
                       not (e['run_id'] is None and e['status'] in {'blocked', 'cancelled'})]
    return {'wave_id': row['public_id'], 'owner': row['owner'], 'task_scope': request['task_scope'],
                'workflow_id': request['workflow_id'], 'max_parallel': request['max_parallel'],
                'capacity_basis': request['capacity_basis'], 'cancel_requested': bool(row['cancel_requested']),
                'blocked_reason': row['blocked_reason'], 'entries': entries, 'states': states, 'pending': bool(pending_entries),
                'all_succeeded': all(state == 'succeeded' for state in states.values()),
                'assurance': 'agent-report', 'provenance': 'provider-peer'}


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
    state = _snapshot(db, row)
    entries = {e['entry_id']: e for e in state['entries']}
    # Rejection blocks descendants; it never turns them into successful results.
    blocked = {name for name, e in entries.items() if e['status'] == 'blocked' or
               e['consumption'] and e['consumption']['verdict'] == 'rejected'}
    changed = True
    while changed:
        changed = False
        for name, e in entries.items():
            if e['run_id'] is None and name not in blocked and set(e['depends_on']) & blocked:
                blocked.add(name)
                changed = True
                db.execute("UPDATE provider_wave_entries SET state='blocked' WHERE wave_id=? AND entry_id=?", (wave_id, name))
    active = sum(e['run_id'] is not None and e['status'] not in TERMINAL for e in entries.values())
    slots = request['max_parallel'] - active
    tasks = TaskLifecycle(store)
    for definition in request['entries']:
        name = definition['entry_id']
        e = entries[name]
        if slots <= 0:
            break
        if e['run_id'] is not None or name in blocked:
            continue
        if any(not entries[d]['consumption'] or entries[d]['consumption']['verdict'] != 'accepted'
               for d in definition['depends_on']):
            continue
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
        slots -= 1
    db.after_commit[('provider-wave', wave_id)] = lambda: _drain(store, wave_id)


def _drain(store, wave_id):
    """At-least-once launch from committed reservations; worker lease fences execution."""
    lock_path = store.directory / ('wave-' + hashlib.sha256(wave_id.encode()).hexdigest() + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stranded = []
    try:
        # Runs outside DB transactions. Waiting for another drain preserves a
        # terminal event that enqueued work while the previous drain was active.
        fcntl.flock(fd, fcntl.LOCK_EX)
        recovery = JobRecovery(store)
        with store.connection() as db:
            run_ids = [r[0] for r in db.execute(
                "SELECT e.run_id FROM provider_wave_entries e JOIN provider_jobs j ON j.id=e.run_id "
                "WHERE e.wave_id=? AND (j.status IN ('accepted','starting') OR EXISTS "
                "(SELECT 1 FROM provider_wave_outbox o WHERE o.run_id=e.run_id)) ORDER BY e.ordinal", (wave_id,))]
        for run_id in run_ids:
            with store.connection() as db:
                wave = db.execute('SELECT * FROM provider_waves WHERE id=?', (wave_id,)).fetchone()
                job = db.execute('SELECT * FROM provider_jobs WHERE id=?', (run_id,)).fetchone()
                if job['status'] not in {'accepted', 'starting'}:
                    db.execute('DELETE FROM provider_wave_outbox WHERE run_id=?', (run_id,))
                    continue
            try:
                initial, generation = recovery.pre_native_state(wave['owner'], run_id)
                if initial != 'launch' or wave['cancel_requested']:
                    stranded.append((wave['owner'], run_id, initial, generation))
                    continue
                with store.connection() as db:
                    _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
                fields = json.loads(job['request'])
                jobs.validate_target(store.worktree, fields)
                with (Path(job['control']) / 'worker.log').open('ab') as log:
                    jobs._launch([sys.executable, '-I', '-m', 'neurath.providers.jobs', '--root',
                                  str(store.worktree), '--run-id', run_id], cwd=fields['worktree'],
                                 env=child_environment(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
                with store.connection() as db:
                    db.execute("UPDATE provider_wave_outbox SET diagnostic='' WHERE run_id=?", (run_id,))
            except RecoveryUnavailable:
                continue
            except (OSError, ValueError) as error:
                with store.connection() as db:
                    db.execute('UPDATE provider_wave_outbox SET diagnostic=? WHERE run_id=?', (clean(str(error)), run_id))
            # Keep the outbox until worker lease consumption is observable. A
            # lost Popen reply or process crash before claim remains retryable.
    finally:
        os.close(fd)
    # Closing an orphan can enqueue another drain. Release our wave lock first.
    for owner, run_id, reason, generation in stranded:
        _close_initial(store, recovery, owner, run_id, reason, generation=generation)


def _close_initial(store, recovery, owner, run_id, reason, *, generation=None):
    def terminal(db, lease):
        cancelled = db.execute('SELECT cancel_requested FROM provider_jobs WHERE id=?', (run_id,)).fetchone()[0]
        return jobs._finish(store, run_id, {
            'run_id': run_id, 'status': 'cancelled' if cancelled else 'failed',
            'diagnostic': 'initial admission ' + reason, 'implementation_dispatched': False,
            'worker_generation': lease.generation, 'execution': 'unobserved',
            'native_creation': 'unobserved'}, lease, _db=db)
    try:
        if generation is None:
            _, generation = recovery.pre_native_state(owner, run_id)
        recovery.finish_pre_native(owner, run_id, generation, terminal)
    except RecoveryUnavailable:
        pass  # Actual worker ownership always wins over reconciliation.


def admit(root, identity, *, wave_id, task_scope, entries, max_parallel, capacity_basis, key, workflow_id='', request_digest=''):
    bounded(wave_id, 'wave ID', 128)
    bounded(capacity_basis, 'capacity basis', 4096)
    if type(max_parallel) is not int or not 1 <= max_parallel <= 32:
        raise ValueError('invalid wave capacity')
    scope = TaskScope(**task_scope)
    if not identity.is_root or identity.session != scope.session_id or identity.actor != scope.actor_id:
        raise ValueError('wave requires its exact native root owner')
    normalized = _entries(entries)
    internal_id = _wave_key(identity, wave_id)
    request = {'task_scope': asdict(scope), 'entries': [asdict(e) for e in normalized],
                   'max_parallel': max_parallel, 'capacity_basis': capacity_basis, 'workflow_id': workflow_id, 'request_digest': request_digest}
    if len(canonical(request).encode()) > 1048576:
        raise ValueError('wave admission exceeds one MiB')
    store = _store(root)
    with store.connection() as db:
        store._agent(db, identity.address)
        _validate_scope(store, db, asdict(scope))
        _operation(db, identity.address, key, ['admit', wave_id, request])
        previous = db.execute('SELECT * FROM provider_waves WHERE id=?', (internal_id,)).fetchone()
        if previous:
            _owned(db, identity, wave_id)
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
        return _snapshot(db, _owned(db, identity, wave_id))


def snapshot(root, identity, wave_id):
    """Pure owner read; no outbox reconciliation or provider launch."""
    return _read(_store(root), identity, wave_id)


def replay(root, identity, *, wave_id, request_digest, key):
    store = _store(root)
    with store.connection() as db:
        if not db.execute('SELECT 1 FROM provider_waves WHERE id=?', (_wave_key(identity, wave_id),)).fetchone():
            return None
        row = _owned(db, identity, wave_id)
        request = json.loads(row['request'])
        if not request_digest or request.get('request_digest') != request_digest:
            raise ValueError('wave replay changed public request')
        _validate_scope(store, db, request['task_scope'])
        _operation(db, identity.address, key, ['admit', wave_id, request])
        _schedule(store, db, row['id'])
    return _read(store, identity, wave_id)


def read(root, identity, wave_id):
    store = _store(root)
    with store.connection() as db:
        row = _owned(db, identity, wave_id)
        _schedule(store, db, row['id'])
    return _read(store, identity, wave_id)


def consume(root, identity, *, wave_id, entry_id, run_id, generation, result_digest, verdict, key):
    if type(generation) is not int or generation < 1 or verdict not in {'accepted', 'rejected'}:
        raise ValueError('invalid result consumption')
    store = _store(root)
    proof = {'run_id': run_id, 'generation': generation, 'result_digest': result_digest, 'verdict': verdict}
    with store.connection() as db:
        wave = _owned(db, identity, wave_id)
        item = db.execute('SELECT * FROM provider_wave_entries WHERE wave_id=? AND entry_id=?', (wave['id'], entry_id)).fetchone()
        if item is None or item['run_id'] != run_id:
            raise ValueError('result is not the exact wave entry run')
        job = db.execute('SELECT * FROM provider_jobs WHERE id=?', (run_id,)).fetchone()
        result = json.loads(job['result']) if job['result'] else {}
        lease = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
        if (job['owner'] != wave['owner'] or job['status'] not in TERMINAL or lease is None
                or (lease['generation'], lease['state']) != (generation, 'finished')
                or result.get('worker_generation') != generation or _digest(result) != result_digest):
            raise ValueError('result generation/digest is not the exact completed provider run')
        if verdict == 'accepted':
            if job['status'] != 'completed':
                raise ValueError('only completed provider results can be accepted')
            if not _implementation_completed(json.loads(job['request']), result, generation):
                raise ValueError('accepted result requires the original implementation native completion')
        if item['consumption'] and item['consumption'] != canonical(proof):
            raise ValueError('entry consumption changed result or verdict')
        _operation(db, identity.address, key, ['consume', wave_id, entry_id, proof])
        db.execute('UPDATE provider_wave_entries SET consumption=? WHERE wave_id=? AND entry_id=?',
                   (canonical(proof), wave['id'], entry_id))
        _schedule(store, db, wave['id'])
    return _read(store, identity, wave_id)


def cancel(root, identity, *, wave_id, key):
    store = _store(root)
    with store.connection() as db:
        row = _owned(db, identity, wave_id)
        internal_id = row['id']
        _operation(db, identity.address, key, ['cancel', wave_id])
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
        with _store(root).connection() as connection:
            return pending(root, session_id=session_id, actor_id=actor_id, task_id=task_id, db=connection)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_waves'").fetchone():
        return []
    rows = db.execute('SELECT * FROM provider_waves WHERE session=? AND actor=?', (session_id, actor_id))
    return [snapshot for row in rows if task_id is None or row['task_id'] == task_id
            if not (snapshot := _snapshot(db, row))['all_succeeded']]


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
    store = _store(root)
    with store.connection() as db:
        row = db.execute('SELECT * FROM provider_waves WHERE public_id=? AND session=? AND actor=?',
                         (wave_id, session_id, actor_id)).fetchone()
        if row is None or (row['session'], row['actor']) != (session_id, actor_id):
            raise ValueError('provider wave requires its exact owner scope')
        return _snapshot(db, row)



def _request_scope(request):
    return {'assignment': request.get('assignment'), 'provider': request.get('provider', 'codex'),
            'worktree': request.get('worktree')}


def _implementation_completed(request, result, generation):
    if generation != 1 or result.get('implementation_dispatched') is not True:
        return False
    created, completion = result.get('created'), result.get('completion')
    if not isinstance(created, dict) or not isinstance(completion, dict) or not created.get('native_session'):
        return False
    provider = request.get('provider', 'codex')
    if created.get('provider') != provider:
        return False
    if provider == 'codex':
        try:
            link = codex_completion_link(created['native_session'], result.get('submission'),
                                         completion.get('id'), 'terminal')
        except ValueError:
            return False
        return (result.get('completion_link') == link and result.get('execution') == 'native-turn-completed' and bool(completion.get('id'))
                and completion.get('status') == 'completed' and completion.get('error') is None)
    if provider == 'claude-code':
        return (result.get('execution') == 'native-response-completed' and completion.get('subtype') == 'success'
                and completion.get('is_error') is False and not completion.get('permission_denial_count')
                and not completion.get('approval_pending')
                and completion.get('native_session') == created['native_session'])
    return False


def replay_retry(root, identity, *, wave_id, entry_id, request_digest, key):
    store = _store(root)
    with store.connection() as db:
        wave = _owned(db, identity, wave_id)
        _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
        previous = db.execute('SELECT * FROM provider_wave_retries WHERE owner=? AND key=?', (identity.address, key)).fetchone()
        if previous is None:
            return None
        if (not request_digest or previous['request_digest'] != request_digest
                or previous['wave_id'] != wave['id'] or previous['entry_id'] != entry_id):
            raise ValueError('wave retry replay changed public request')
        _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
        return _snapshot(db, wave)


def retry(root, identity, *, wave_id, entry_id, request, key, request_digest=''):
    """Admit a new original-assignment attempt after a genuinely terminal failure.

    The runtime revalidates target, model and policy before providing this request.
    An old attempt remains immutable and never becomes generation-2 inbox work.
    """
    bounded(key, 'retry key')
    if not isinstance(request, dict) or len(canonical(request).encode()) > 1048576:
        raise ValueError('retry request must be an admitted object within one MiB')
    store = _store(root)
    recovery = JobRecovery(store)
    with store.connection() as db:
        wave = _owned(db, identity, wave_id)
        _validate_scope(store, db, json.loads(wave['request'])['task_scope'])
        previous = db.execute('SELECT * FROM provider_wave_retries WHERE owner=? AND key=?', (identity.address, key)).fetchone()
        if previous:
            if (previous['wave_id'] != wave['id'] or previous['entry_id'] != entry_id
                    or previous['request'] != canonical(request) or previous['request_digest'] != request_digest):
                raise ValueError('wave retry key changed request')
            return _snapshot(db, wave)
        item = db.execute('SELECT * FROM provider_wave_entries WHERE wave_id=? AND entry_id=?', (wave['id'], entry_id)).fetchone()
        if item is None or item['run_id'] is None:
            raise ValueError('retry requires an observed failed or cancelled attempt')
        old_run_id = item['run_id']
    fd = recovery._lock(old_run_id)
    try:
        with store.connection() as db:
            wave = _owned(db, identity, wave_id)
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
            if not isinstance(request, dict) or _request_scope(request) != _request_scope(original):
                raise ValueError('retry must preserve original assignment/provider/worktree scope')
            descendants = {entry_id}
            while True:
                expanded = descendants | {e['entry_id'] for e in definition['entries'] if set(e['depends_on']) & descendants}
                if expanded == descendants:
                    break
                descendants = expanded
            for entry in _snapshot(db, wave)['entries']:
                if entry['entry_id'] in descendants and entry['consumption'] and entry['consumption']['verdict'] == 'accepted':
                    raise ValueError('accepted descendant prevents retry')
            jobs.validate_target(root, request)
            _operation(db, identity.address, key, ['retry', wave_id, entry_id, request, request_digest])
            archived = {'attempt': item['attempt'], 'run_id': old_run_id, 'request': json.loads(job['request']),
                        'result': result, 'result_digest': _digest(result), 'consumption': consumed,
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
