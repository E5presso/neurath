"""Durable admission for restoring an owned provider connection after proven exit.

Public callers supply run_id/key only. The wrapper authenticates the live issuer
and supplies current, host-verified closure evidence. No PID probing, foreign
session adoption, native resume, task rerun, polling or time-based lease expiry
happens here. Initial and recovered workers must hold WorkerLease for their whole
lifetime; legacy workers without that contract cannot be adopted by recovery.
"""

import fcntl
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from neurath.providers.contracts import Session


class RecoveryBlocked(ValueError):
    pass


class RecoveryUnavailable(RecoveryBlocked):
    """Another worker owns or consumed the requested lifecycle transition."""


def _text(value):
    if not isinstance(value, str) or not value or len(value.encode()) > 4096 or '\0' in value:
        raise ValueError('expected bounded recovery reference')


def _json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > 1048576:
        raise ValueError('recovery record too large')
    return encoded


@dataclass(frozen=True)
class ClosedTransportEvidence:
    generation: int
    native_session: str
    transport: str
    source: str
    connection_closed: bool
    native_process_exited: bool
    issuer_active: bool
    reason: str

    def __post_init__(self):
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError('invalid closed generation')
        for value in (self.native_session, self.transport, self.source):
            _text(value)
        if self.reason not in ('process-exit', 'worker-exit', 'transport-closed'):
            raise ValueError('unsupported closure reason')
        if any(type(v) is not bool for v in (self.connection_closed, self.native_process_exited, self.issuer_active)):
            raise ValueError('closure observations must be boolean')


class WorkerLease:
    def __init__(self, run_id, generation, token, fd):
        self.run_id, self.generation, self.token, self._fd = run_id, generation, token, fd

    def assert_current(self, db):
        if self._fd is None:
            raise RecoveryBlocked('worker lease released')
        row = db.execute('SELECT generation,state,token FROM provider_worker_leases WHERE run_id=?',
                         (self.run_id,)).fetchone()
        if row is None or (row['generation'], row['state'], row['token']) != (self.generation, 'active', self.token):
            raise RecoveryBlocked('worker generation/token conflict')

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class JobRecovery:
    def __init__(self, store):
        self.store = store
        self.directory = Path(store.directory) / 'worker-leases'
        if self.directory.is_symlink():
            raise RecoveryBlocked('lease directory symlink')
        self.directory.mkdir(exist_ok=True, mode=0o700)
        with store.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS provider_worker_leases (
                run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                state TEXT NOT NULL, token TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS provider_recovery_requests (
                owner TEXT NOT NULL, request_key TEXT NOT NULL, run_id TEXT NOT NULL,
                admission TEXT NOT NULL, PRIMARY KEY(owner,request_key))''')

    def _lock(self, run_id):
        _text(run_id)
        if self.directory.is_symlink():
            raise RecoveryBlocked('lease directory symlink')
        path = self.directory / (hashlib.sha256(run_id.encode()).hexdigest() + '.lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(fd)
            raise RecoveryUnavailable('worker-live: owned worker lease is held') from error
        except BaseException:
            os.close(fd)
            raise
        return fd

    @staticmethod
    def _job(db, owner, run_id, *, allow_cancelled=False):
        _text(owner)
        row = db.execute('SELECT * FROM provider_jobs WHERE id=? AND owner=?', (run_id, owner)).fetchone()
        if row is None:
            raise RecoveryBlocked('missing job or wrong owner')
        if not allow_cancelled and (row['cancel_requested'] or row['status'] == 'cancelled'):
            raise RecoveryBlocked('job explicitly cancelled')
        return row

    @staticmethod
    def _previous(db, owner, run_id, key):
        row = db.execute('SELECT run_id,admission FROM provider_recovery_requests WHERE owner=? AND request_key=?',
                         (owner, key)).fetchone()
        if row and row['run_id'] != run_id:
            raise RecoveryBlocked('recovery key changed run')
        return {'admission': json.loads(row['admission']), 'replayed': True} if row else None

    def claim_worker(self, owner, run_id, *, generation=0, allow_cancelled=False):
        """Claim once before launch work; hold returned lease until native cleanup.

        generation=0 registers an initial accepted job. A recovery worker receives
        the exact admitted generation; concurrent/repeated launches cannot claim
        it twice. assert_current fences later job/event writes within their DB tx.
        """
        if type(generation) is not int or generation < 0:
            raise ValueError('invalid worker generation')
        fd = self._lock(run_id)
        try:
            with self.store.connection() as db:
                job = self._job(db, owner, run_id, allow_cancelled=allow_cancelled)
                row = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
                token = uuid.uuid4().hex
                if generation == 0:
                    if row is not None or job['status'] != 'accepted':
                        raise RecoveryBlocked('initial worker already registered or not accepted')
                    generation = 1
                    db.execute('INSERT INTO provider_worker_leases VALUES(?,?,?,?)', (run_id, generation, 'active', token))
                else:
                    if row is None or (row['generation'], row['state']) != (generation, 'accepted'):
                        raise RecoveryBlocked('worker generation not pending acceptance')
                    db.execute("UPDATE provider_worker_leases SET state='active',token=? WHERE run_id=? AND generation=?",
                               (token, run_id, generation))
            return WorkerLease(run_id, generation, token, fd)
        except BaseException:
            os.close(fd)
            raise


    def _initial_job(self, db, owner, run_id):
        row = self._job(db, owner, run_id, allow_cancelled=True)
        result = json.loads(row['result']) if row['result'] else {}
        if row['status'] != 'accepted' or 'created' in result:
            raise RecoveryUnavailable('initial admission has advanced or native creation is observed')
        return row

    def initial_state(self, owner, run_id):
        """Inspect only an initial admission while holding the native worker fence."""
        fd = self._lock(run_id)
        try:
            with self.store.connection() as db:
                row = self._initial_job(db, owner, run_id)
                lease = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
                if row['cancel_requested']:
                    return 'cancel'
                return 'stranded' if lease is not None else 'launch'
        finally:
            os.close(fd)

    def finish_initial(self, owner, run_id, finalize):
        """Close unconsumed initial admission, never overwrite an active worker.

        status=accepted precedes all native work in jobs._worker. An existing
        generation-1 lease with a free OS lock here was consumed before start;
        terminal failure is safe, but pretending to resume it is not.
        """
        fd = self._lock(run_id)
        lease = None
        try:
            with self.store.connection() as db:
                self._initial_job(db, owner, run_id)
                previous = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
                if previous is not None and tuple(previous) != (1, 'active'):
                    raise RecoveryBlocked('initial worker lease has an inconsistent generation/state')
                lease = WorkerLease(run_id, 1, uuid.uuid4().hex, fd)
                if previous is None:
                    db.execute('INSERT INTO provider_worker_leases VALUES(?,?,?,?)', (run_id, 1, 'active', lease.token))
                else:
                    db.execute("UPDATE provider_worker_leases SET token=? WHERE run_id=? AND generation=1 AND state='active'", (lease.token, run_id))
                return finalize(db, lease)
        finally:
            if lease is not None:
                lease.close()
            else:
                os.close(fd)

    def cancel_unstarted(self, owner, run_id, generation, finalize):
        """Finalize a cancelled admission atomically; no native worker is started."""
        fd = self._lock(run_id)
        lease = None
        try:
            with self.store.connection() as db:
                job = self._job(db, owner, run_id, allow_cancelled=True)
                row = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
                if not job['cancel_requested'] or row is None or (row['generation'], row['state']) != (generation, 'accepted'):
                    raise RecoveryUnavailable('cancelled recovery generation is not pending')
                lease = WorkerLease(run_id, generation, uuid.uuid4().hex, fd)
                db.execute("UPDATE provider_worker_leases SET state='active',token=? WHERE run_id=? AND generation=?",
                           (lease.token, run_id, generation))
                return finalize(db, lease)
        finally:
            if lease is not None:
                lease.close()
            else:
                os.close(fd)

    def recover(self, owner, run_id, key, evidence, *, on_admit=None):
        """Admit restoration, not execution. A replay is the same stored admission.

        The launcher may reconcile an unclaimed accepted generation after a crash;
        only claim_worker can consume it. Never rerun the original assignment.
        """
        _text(key)
        if not isinstance(evidence, ClosedTransportEvidence):
            raise TypeError('verified closure evidence required')
        with self.store.connection() as db:
            self._job(db, owner, run_id)
            previous = self._previous(db, owner, run_id, key)
            if previous:
                return previous
        fd = self._lock(run_id)
        try:
            with self.store.connection() as db:
                job = self._job(db, owner, run_id)
                previous = self._previous(db, owner, run_id, key)
                if previous:
                    return previous
                lease = db.execute('SELECT generation,state FROM provider_worker_leases WHERE run_id=?', (run_id,)).fetchone()
                if lease is None:
                    raise RecoveryBlocked('unmanaged worker: no lifetime lease contract')
                if lease['state'] == 'accepted':
                    raise RecoveryBlocked('recovery already pending; reconcile admitted generation')
                if lease['generation'] != evidence.generation:
                    raise RecoveryBlocked('closure generation mismatch')
                for condition, reason in ((evidence.issuer_active, 'issuer not active'),
                        (evidence.connection_closed, 'connection exit unverified'),
                        (evidence.native_process_exited, 'native-process exit unverified')):
                    if not condition:
                        raise RecoveryBlocked(reason)
                try:
                    session = Session(**json.loads(job['result'])['created'])
                    request = json.loads(job['request'])
                except (TypeError, KeyError, ValueError) as error:
                    raise RecoveryBlocked('missing persisted created Session') from error
                _text(session.native_session)
                if session.native_session != evidence.native_session:
                    raise RecoveryBlocked('closed session mismatch')
                expected_transport = {'codex': 'codex-app-server', 'claude-code': 'claude-agent-sdk'}.get(session.provider)
                if session.transport != expected_transport or session.transport != evidence.transport:
                    raise RecoveryBlocked('closed transport mismatch')
                if (session.provider != request.get('provider', 'codex') or session.worktree != request.get('worktree')
                        or not isinstance(session.policy, dict) or not session.policy):
                    raise RecoveryBlocked('persisted session/request mismatch')
                admission = {'run_id': run_id, 'generation': evidence.generation + 1,
                             'previous_generation': evidence.generation, 'status': 'accepted',
                             'session': asdict(session), 'settings': {k: v for k, v in request.items() if k != 'assignment'},
                             'resume_original_assignment': False, 'closure': asdict(evidence)}
                db.execute("UPDATE provider_worker_leases SET generation=?,state='accepted',token=NULL WHERE run_id=? AND generation=?",
                           (admission['generation'], run_id, evidence.generation))
                archive_result(db, run_id, evidence.generation, json.loads(job['result']))
                db.execute("UPDATE provider_jobs SET status='recovery-accepted' WHERE id=?", (run_id,))
                db.execute('INSERT INTO provider_recovery_requests VALUES(?,?,?,?)', (owner, key, run_id, _json(admission)))
                if on_admit is not None:
                    on_admit(db, admission)
                return {'admission': admission, 'replayed': False}
        finally:
            os.close(fd)


def archive_result(db, run_id, generation, result):
    """An archived generation result cannot be overwritten by a recovery outcome."""
    db.execute("CREATE TABLE IF NOT EXISTS provider_job_results (run_id TEXT, generation INTEGER, result TEXT, PRIMARY KEY(run_id,generation))")
    previous = db.execute('SELECT result FROM provider_job_results WHERE run_id=? AND generation=?', (run_id, generation)).fetchone()
    if previous is not None and json.loads(previous[0]) != result:
        raise RecoveryBlocked('generation result already recorded with different content')
    db.execute('INSERT OR IGNORE INTO provider_job_results VALUES(?,?,?)', (run_id, generation, json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)))
