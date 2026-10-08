"""Contract tests built from synthetic legacy data, never old implementation."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from neurath.domain.errors import ConflictError
from neurath.infrastructure.storage import Database
from neurath.migration.legacy import LegacyImportError, capture_sqlite, decode_cell, import_legacy, prepare_import, verify_archive


def make_legacy(path: Path, *, corrupt=False):
    tasks = [{"id": status, "revision": 4, "status": status,
              "definition": {"goal": "Preserve " + status, "acceptance": ["Owner verifies outcome"],
                             "sources": [{"kind": "prompt", "reference": "original:42", "revision": 1}]},
              "evidence": [{"untrusted": "old report"}]} for status in ["in_progress", "failed", "invalidated", "succeeded"]]
    payload = json.dumps({"owner": "original-owner", "session": "original-session", "tasks": tasks}).encode()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runtime_records(namespace TEXT,key TEXT,revision INTEGER,payload BLOB,digest TEXT,legacy_path TEXT,legacy_digest TEXT,updated REAL)")
        connection.execute("INSERT INTO runtime_records VALUES(?,?,?,?,?,?,?,?)", (
            "task-ledger", "ledger-1", 3, payload, "bad" if corrupt else hashlib.sha256(payload).hexdigest(),
            "old.json", "original-file-checksum", 12.25))
        connection.execute('CREATE TABLE history(a BLOB,b TEXT,c INTEGER,d REAL,e)')
        connection.execute('INSERT INTO history(rowid,a,b,c,d,e) VALUES(?,?,?,?,?,?)', (42, b'\x00\xff\x80', '한글\x00', 2**62, -2.25, None))
        connection.execute('CREATE TABLE unknown(key TEXT PRIMARY KEY, value BLOB) WITHOUT ROWID')
        connection.execute('INSERT INTO unknown VALUES(?,?)', ('unknown-key', b'\x00\x01'))
    return tasks


def test_lossless_idempotent_and_no_authority_promotion(tmp_path):
    old = tmp_path / 'runtime.sqlite3'
    make_legacy(old)
    original = old.read_bytes()
    database = Database(tmp_path / 'neurath.sqlite3')
    database.initialize()
    first = import_legacy(database, [(old, 'original-runtime')])
    second = import_legacy(database, [(old, 'original-runtime')])
    assert first == second
    assert old.read_bytes() == original
    assert first['unfinished_imported'] == 3
    archive = database.read_archive(first['snapshot_id'])
    history = next(table for table in archive['sources'][0]['tables'] if table['name'] == 'history')
    assert [decode_cell(cell) for cell in history['rows'][0]] == [b'\x00\xff\x80', '한글\x00', 2**62, -2.25, None]
    assert decode_cell(history['rowids'][0]) == 42
    exported = database.export_records()
    assert {task['owner_id'] for task in exported['task']} == {'original-owner'}
    assert {task['status'] for task in exported['task']} == {'waiting'}
    assert {source['source_type'] for source in exported['source']} == {'legacy-import'}
    assert {source['session_id'] for source in exported['source']} == {'original-owner'}
    assert len(exported['session']) == 1
    assert exported['session'][0]['status'] == 'legacy-unknown'
    assert exported['session'][0]['native_id'] == 'original-session'
    assert {item['state']['original_status'] for item in exported['checkpoint']} == {'failed', 'invalidated', 'in_progress'}
    assert all(item['state']['original_task']['definition']['sources'][0]['kind'] == 'prompt' for item in exported['checkpoint'])
    assert exported['lease'] == exported['evidence'] == exported['receipt'] == []
    database.close()


def test_changed_task_conflict_rolls_back_archive_and_all_records(tmp_path):
    old = tmp_path / 'runtime.sqlite3'
    make_legacy(old)
    database = Database(tmp_path / 'neurath.sqlite3')
    database.initialize()
    initial = import_legacy(database, [old])
    before = database.export_records()
    with sqlite3.connect(old) as connection:
        raw = json.loads(connection.execute('SELECT payload FROM runtime_records').fetchone()[0])
        raw['tasks'][0]['definition']['goal'] = 'Different goal'
        raw['tasks'].append(dict(raw['tasks'][0], id='new-item'))
        payload = json.dumps(raw).encode()
        connection.execute('UPDATE runtime_records SET payload=?,digest=?', (payload, hashlib.sha256(payload).hexdigest()))
    candidate = prepare_import([old])
    with pytest.raises(ConflictError):
        import_legacy(database, [old])
    assert database.export_records() == before
    assert database.read_archive(candidate['snapshot_id']) is None
    assert database.read_archive(initial['snapshot_id']) is not None
    database.close()


def test_corrupt_digest_and_invalid_database_do_not_import(tmp_path):
    old = tmp_path / 'runtime.sqlite3'
    make_legacy(old, corrupt=True)
    database = Database(tmp_path / 'neurath.sqlite3')
    database.initialize()
    with pytest.raises(LegacyImportError, match='digest'):
        import_legacy(database, [old])
    assert not any(database.export_records().values())
    invalid = tmp_path / 'invalid.sqlite3'
    invalid.write_bytes(b'not sqlite')
    with pytest.raises(LegacyImportError):
        capture_sqlite(invalid)
    retired = tmp_path / 'retired.sqlite3'
    retired.mkdir()
    with pytest.raises(LegacyImportError, match='regular file'):
        capture_sqlite(retired)
    database.close()


def test_core_json_tasks_import_and_stable_ids_across_backup_locations(tmp_path):
    old = tmp_path / 'core.sqlite3'
    task = {'id': 'task-1', 'owner_id': 'native-original-owner', 'session_id': 'session-1',
            'status': 'active', 'goal': 'Finish original work', 'acceptance': []}
    with sqlite3.connect(old) as connection:
        connection.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,payload TEXT)')
        connection.execute('INSERT INTO tasks VALUES(?,?)', ('task-1', json.dumps(task)))
    one = prepare_import([(old, 'canonical-core')])
    copied = tmp_path / 'copied.sqlite3'
    copied.write_bytes(old.read_bytes())
    two = prepare_import([(copied, 'canonical-core')])
    assert one['records'] == two['records']
    assert one['records']['task'][0]['status'] == 'waiting'
    assert one['records']['task'][0]['owner_id'] == 'native-original-owner'


def test_archive_readback_detects_cell_corruption(tmp_path):
    old = tmp_path / 'runtime.sqlite3'
    make_legacy(old)
    prepared = prepare_import([old])
    assert verify_archive(prepared['archive']) == prepared['report']
    table = next(item for item in prepared['archive']['sources'][0]['tables'] if item['name'] == 'history')
    table['rows'][0][0] = ['blob', 'AAAA']
    with pytest.raises(LegacyImportError, match='table checksum'):
        verify_archive(prepared['archive'])
