"""Persist host adapter observations with a session mutex and transactional CAS.

Session identity, scoped foregrounds and delegation waves are revalidated in the
same transaction as the journal write. This store does not attest native lineage.
"""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path

from neurath.project_paths import control_root


def _locator(root):
    from scripts.agent_harness.session_kernel import SessionLocator

    return SessionLocator(control_root(Path(root)))



def _state(root, session):
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionStatus

    state = SessionKernel(_locator(root)).inspect(SessionId(session))
    if state.session.status is not SessionStatus.ACTIVE:
        raise ValueError("host identity requires an active session")
    return state



def _path(root, session):
    from scripts.agent_harness.session_kernel import SessionId

    return _locator(root).locate(SessionId(session)).directory / ".neurath-host.json"



def _database(root):
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    return RuntimeDatabase(_locator(root).control_root)



def _host_data(record, session):
    data = ({"session": session, "spawns": {}, "tools": {}} if record is None
            else json.loads(record.payload))
    if not isinstance(data, dict) or data.get("session") != session:
        raise ValueError("host record belongs to a different session")
    return data



@contextlib.contextmanager
def _journal_lock(root, session):
    path = _path(root, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path



def _host_record(tx, path, session):
    """Import exact legacy metadata under its existing journal mutex."""
    record = tx.get("host-journal", session)
    if record is None and path.is_file():
        if path.is_symlink():
            raise ValueError("host journal must not be a symlink")
        content = path.read_bytes()
        data = json.loads(content)
        if not isinstance(data, dict) or data.get("session") != session:
            raise ValueError("host record belongs to a different session")
        record = tx.put("host-journal", session, content, expected_revision=None)
        tx.connection.execute(
            "UPDATE runtime_records SET legacy_path=?,legacy_digest=? WHERE namespace='host-journal' AND key=?",
            (str(path), hashlib.sha256(content).hexdigest(), session))
    return record



def snapshot(root, session):
    database = _database(root)
    with database.transaction() as tx:
        record = tx.get("host-journal", session)
    if record is None and _path(root, session).is_file():
        with _journal_lock(root, session) as path, database.transaction() as tx:
            record = _host_record(tx, path, session)
    return _host_data(record, session)



def _journal_exists(root, session):
    with _database(root).transaction() as tx:
        if tx.get("host-journal", session) is not None:
            return True
    return _path(root, session).is_file()



@contextlib.contextmanager
def journal(root, session):
    _state(root, session)
    database = _database(root)
    with _journal_lock(root, session) as path:
        with database.transaction() as tx:
            record = _host_record(tx, path, session)
            data = _host_data(record, session)
        yield data
        if data.get("session") != session:
            raise ValueError("host journal mutation changed session identity")
        with database.transaction() as tx:
            old = _host_data(record, session)
            changed_scopes = [value["foreground"] for group in ("intents", "spawns")
                for key, value in data.get(group, {}).items()
                if value != old.get(group, {}).get(key)
                and value.get("foreground", {}).get("task_scope") is not None]
            changed_waves = [value for key, value in data.get("waves", {}).items()
                             if value != old.get("waves", {}).get(key)]
            if changed_scopes or changed_waves:
                from scripts.agent_harness.session_kernel import SessionStateStore, SessionId
                from scripts.agent_harness.task_service import validate_scoped_foreground
                locator = _locator(root)
                state = SessionStateStore(locator.locate(SessionId(session)).process_state).read_transaction(
                    tx, SessionId(session))
                for foreground in changed_scopes:
                    validate_scoped_foreground(tx, state, foreground)
                if changed_waves:
                    from scripts.agent_harness.delegation_wave import validate_mutation
                    for wave in changed_waves:
                        validate_mutation(tx, state, wave)
            tx.put("host-journal", session,
                   json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
                   expected_revision=None if record is None else record.revision)



def _all_journals(root):
    database = _database(root)
    with database.transaction() as tx:
        sessions = [row[0] for row in tx.connection.execute(
            "SELECT key FROM runtime_records WHERE namespace='host-journal'")]
        values = [_host_data(tx.get("host-journal", session), session) for session in sessions]
    from scripts._neurath_paths import state_path
    for path in state_path(_locator(root).control_root, "runs").glob("*/.neurath-host.json"):
        if path.parent.name not in sessions:
            values.append(snapshot(root, path.parent.name))
    return values
