"""Cutover preserves canonical data and fences dormant legacy launchers."""
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
import os
import sys

import pytest

from neurath.install.cutover import inspect_cutover, apply_cutover, recover_cutover
from neurath.runtime.database import RuntimeDatabase, LegacyStateChanged


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    path = root / '.neurath/local/agents/messages.sqlite3'
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.executescript("CREATE TABLE agents(id TEXT PRIMARY KEY,status TEXT,updated REAL);"
                         "CREATE TABLE messages(id TEXT PRIMARY KEY,body TEXT,recipient TEXT);"
                         "INSERT INTO agents VALUES('agent','retired',1);"
                         "INSERT INTO messages VALUES('known','keep','owner');")
    store = RuntimeDatabase(root)
    with store.transaction() as tx:
        tx.put('sessions', 'one', b'canonical', expected_revision=None)
    return root, path, store


def test_diagnosis_and_retirement_of_late_shutdown_preserve_canonical(project):
    root, path, store = project
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("UPDATE agents SET status='paused',updated=2")
    with pytest.raises(LegacyStateChanged):
        RuntimeDatabase(root)
    plan = inspect_cutover(root)
    assert plan['status'] == 'ready', plan
    receipt = apply_cutover(root, expected_token=plan['token'])
    assert receipt['status'] == 'completed'
    assert receipt['application_digest_before'] == receipt['application_digest_after']
    assert path.is_dir()
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(path)
    with store.transaction() as tx:
        assert tx.get('sessions', 'one').payload == b'canonical'
    with store.connection() as db:
        assert db.execute('SELECT body FROM messages').fetchone()[0] == 'keep'
        assert db.execute('SELECT count(*) FROM runtime_legacy_retirements').fetchone()[0] == 4


@pytest.mark.parametrize('statement', [
    "INSERT INTO messages VALUES('late','new','owner')",
    "UPDATE messages SET body='changed'",
    "UPDATE messages SET recipient='other'",
])
def test_unknown_late_message_content_is_never_discarded(project, statement):
    root, path, _ = project
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute(statement)
    plan = inspect_cutover(root)
    assert plan['status'] == 'blocked'
    before = path.read_bytes()
    with pytest.raises(ValueError):
        apply_cutover(root, expected_token=plan['token'])
    assert path.read_bytes() == before


def test_changed_plan_is_rejected(project):
    root, path, _ = project
    plan = inspect_cutover(root)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("INSERT INTO messages VALUES('late','new','owner')")
    with pytest.raises(ValueError):
        apply_cutover(root, expected_token=plan['token'])
    assert path.is_file()


def test_open_database_handle_blocks(project):
    root, path, _ = project
    db = sqlite3.connect(path)
    try:
        db.execute('SELECT * FROM messages').fetchall()
        assert inspect_cutover(root)['status'] == 'blocked'
    finally:
        db.close()


def test_mid_move_failure_restores_sources(project, monkeypatch):
    root, path, store = project
    from neurath.install import cutover
    plan = inspect_cutover(root)
    original = cutover._tombstone
    def fail(*args):
        original(*args)
        raise RuntimeError('injected after tombstone')
    monkeypatch.setattr(cutover, '_tombstone', fail)
    with pytest.raises(RuntimeError, match='injected'):
        apply_cutover(root, expected_token=plan['token'])
    assert path.is_file()
    store.revalidate_legacy()
    with store.connection() as db:
        assert db.execute('SELECT body FROM messages').fetchone()[0] == 'keep'
    assert recover_cutover(root)['status'] == 'not-needed'


def sibling_launcher(root, tmp_path):
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture', '-c',
                    'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'], check=True)
    sibling = tmp_path / 'sibling with space'
    subprocess.run(['git', '-C', str(root), 'worktree', 'add', '-qb', 'sibling', str(sibling)], check=True)
    path = sibling / '.neurath/run'
    path.parent.mkdir()
    path.write_text('#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)\nexec /old/python -I -m neurath --root "$root" "$@"\n')
    path.chmod(0o755)
    return path


def test_sibling_launcher_is_inventoried_and_preserved(project, tmp_path):
    root, _, _ = project
    launcher = sibling_launcher(root, tmp_path)
    before = launcher.read_bytes()
    plan = inspect_cutover(root)
    assert plan['status'] == 'ready', plan
    assert plan['launchers'][0]['path'] == str(launcher)
    result = apply_cutover(root, expected_token=plan['token'])
    assert str(launcher.parent.parent) in result['worktrees_to_update']
    assert launcher.read_bytes() == before
    assert (Path(result['archive']) / 'launcher-0').read_bytes() == before


def test_unknown_or_changed_launcher_is_never_overwritten(project, tmp_path):
    root, legacy, _ = project
    launcher = sibling_launcher(root, tmp_path)
    plan = inspect_cutover(root)
    launcher.write_text('#!/bin/sh\nexit 17\n')
    with pytest.raises(ValueError):
        apply_cutover(root, expected_token=plan['token'])
    assert inspect_cutover(root)['status'] == 'blocked'
    assert legacy.is_file()
    assert launcher.read_text() == '#!/bin/sh\nexit 17\n'


@pytest.mark.parametrize('stage', ['moved', 'mkdir', 'committed'])
def test_crash_recovery_reopens_runtime(project, stage):
    root, path, _ = project
    script = '''import os, sys
from neurath.install import cutover
original = cutover._tombstone
def crash(*args):
    if sys.argv[2] == 'mkdir' and args[2] == 'messages':
        args[0].mkdir()
        os._exit(23)
    original(*args)
    if sys.argv[2] == 'moved' and args[2] == 'messages':
        os._exit(23)
cutover._tombstone = crash
save = cutover._save
def crash_commit(path, document):
    if sys.argv[2] == 'committed' and path.name == 'receipt.json':
        os._exit(23)
    save(path, document)
cutover._save = crash_commit
plan = cutover.inspect_cutover(sys.argv[1])
cutover.apply_cutover(sys.argv[1], expected_token=plan['token'])
'''
    result = subprocess.run([sys.executable, '-c', script, str(root), stage],
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)}, capture_output=True, text=True)
    assert result.returncode == 23, result.stderr
    assert recover_cutover(root)['status'] == ('completed' if stage == 'committed' else 'rolled-back')
    assert path.is_dir() if stage == 'committed' else path.is_file()
    RuntimeDatabase(root)


def test_nonterminal_lifecycle_change_is_rejected(project):
    root, path, store = project
    with store.connection() as db:
        db.execute("UPDATE agents SET status='active'")
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("UPDATE agents SET status='paused',updated=2")
    assert inspect_cutover(root)['status'] == 'blocked'


def test_explicit_initial_import_is_separate_from_retirement(tmp_path):
    from neurath.install.cutover import prepare_cutover, require_cutover
    root = tmp_path / 'initial'
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    path = root / '.neurath/local/memory/project.sqlite3'
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, value TEXT)')
        db.execute("INSERT INTO events VALUES(1,'retained')")
    with pytest.raises(ValueError, match='explicit cutover'):
        require_cutover(root)
    plan = prepare_cutover(root)
    assert plan['status'] == 'ready', plan
    assert path.is_file()
    apply_cutover(root, expected_token=plan['token'])
    require_cutover(root)
    with RuntimeDatabase(root).connection() as db:
        assert db.execute('SELECT value FROM events').fetchone()[0] == 'retained'


def test_installer_refuses_implicit_legacy_transition(project):
    from neurath.install.transaction import make_plan
    root, path, _ = project
    before = path.read_bytes()
    with pytest.raises(ValueError, match='explicit cutover'):
        make_plan(root)
    assert path.read_bytes() == before


def test_bootstrap_diagnostic_command_works_with_drift(project):
    root, path, _ = project
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("UPDATE agents SET status='paused',updated=2")
    result = subprocess.run([sys.executable, '-m', 'neurath', '--root', str(root),
                             'cutover', 'inspect'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'canonical_digest' in result.stdout
