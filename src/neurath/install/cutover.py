"""Explicit offline retirement; ordinary runtime drift guards remain intact."""
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing, ExitStack
from pathlib import Path

from neurath.memory.store import control_root
from neurath.runtime.engine import activate

activate()
from scripts.agent_harness.sqlite_migration import (  # noqa: E402
    LEGACY_DATABASES, _feed, _quote, _rows, _schema, fingerprint,
    migration_lock, source_stats,
)

FENCE = b'#!/bin/sh\nprintf "%s\\n" "Neurath shared-store cutover requires recovery." >&2\nexit 1\n'
EXCLUDED = {'runtime_legacy_sqlite_sources', 'runtime_legacy_retirements'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _read(path):
    if path.is_symlink() or any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ValueError('Cutover requires regular checkpointed databases without journals')
    db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    return db


def _application_digest(db):
    digest = hashlib.sha256()
    schemas = [r for r in _schema(db) if r['tbl_name'] not in EXCLUDED]
    for schema in schemas:
        for value in schema:
            _feed(digest, value)
    for schema in schemas:
        if schema['type'] == 'table':
            for row in _rows(db, schema['name'], schema['sql'])[0]:
                for value in row:
                    _feed(digest, value)
    if db.execute("SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'").fetchone():
        for row in db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name'):
            for value in row:
                _feed(digest, value)
    return digest.hexdigest()


def _messages(old, current):
    differences = []
    for schema in _schema(old):
        target = current.execute('SELECT sql FROM sqlite_schema WHERE type=? AND name=?',
                                 (schema['type'], schema['name'])).fetchone()
        if target is None or target['sql'] != schema['sql']:
            raise ValueError('Legacy schema differs: ' + schema['name'])
        if schema['type'] != 'table':
            continue
        table = schema['name']
        columns = list(old.execute('PRAGMA table_info(' + _quote(table) + ')'))
        fields = [c['name'] for c in columns]
        keys = [c['name'] for c in sorted(columns, key=lambda c: c['pk']) if c['pk']]
        if not keys:
            raise ValueError('Changed legacy table has no explicit primary key: ' + table)
        names = ','.join(map(_quote, fields))
        count = 0
        for row in old.execute('SELECT ' + names + ' FROM ' + _quote(table)):
            target = current.execute('SELECT ' + names + ' FROM ' + _quote(table) + ' WHERE '
                                     + ' AND '.join(_quote(k) + ' IS ?' for k in keys),
                                     tuple(row[k] for k in keys)).fetchone()
            if target is None:
                raise ValueError('Unimported legacy row in ' + table)
            changed = {name for name in fields if row[name] != target[name]}
            allowed = set()
            if table == 'agents' and target['status'] == 'retired':
                allowed = {'status', 'updated'}
            elif table == 'newsroom_presence' and target['active'] == 0:
                allowed = {'active', 'epoch', 'updated', 'turn'}
            elif table == 'collaboration_calls' and target['status'] == 'closed' and target['result'] is None:
                allowed = {'status', 'result'}
            if changed - allowed:
                raise ValueError('Unexpected legacy content difference in ' + table)
            count += bool(changed)
        if count:
            differences.append({'table': table, 'lifecycle_rows': count})
    return differences


def _generated_launcher(data):
    prefix = '#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)\nexec '
    suffix = ' -I -m neurath --root "$root" "$@"\n'
    try:
        value = data.decode()
        if not value.startswith(prefix) or not value.endswith(suffix):
            return False
        executable = value[len(prefix):-len(suffix)]
        tokens = shlex.split(executable)
        return len(tokens) == 1 and Path(tokens[0]).is_absolute() and shlex.quote(tokens[0]) == executable
    except (UnicodeError, ValueError):
        return False


def _launchers(root):
    result = subprocess.run(['git', '-C', str(root), 'worktree', 'list', '--porcelain', '-z'],
                            capture_output=True, check=True)
    launchers = []
    for field in result.stdout.split(b'\0'):
        if not field.startswith(b'worktree '):
            continue
        worktree = Path(os.fsdecode(field[9:])).resolve()
        if not worktree.is_dir() or control_root(worktree) != root:
            raise ValueError('Linked worktree unavailable or belongs to another repository')
        path = worktree / '.neurath/run'
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError('Launcher is not a regular managed file: ' + str(path))
        data = path.read_bytes()
        launchers.append({'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
                          'mode': path.stat().st_mode & 0o777, 'managed': _generated_launcher(data)})
    return sorted(launchers, key=lambda item: item['path'])


def _open_handles(paths):
    result = subprocess.run(['lsof', '-Fp', '--', *map(str, paths)], capture_output=True, text=True)
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise ValueError('Cannot establish that database handles are closed')
    return sorted({int(line[1:]) for line in result.stdout.splitlines() if line.startswith('p')})


def inspect_cutover(worktree):
    """Read a bounded plan without initializing or repairing RuntimeDatabase."""
    root = control_root(Path(worktree).resolve())
    path = root / '.neurath/local/runtime.sqlite3'
    result = {'root': str(root), 'status': 'ready', 'blockers': [], 'sources': [], 'launchers': []}
    try:
        result['launchers'] = _launchers(root)
        if any(not item['managed'] for item in result['launchers']):
            result['blockers'].append('Unknown or modified launcher requires explicit restoration')
        stats = source_stats(root)
        with closing(_read(path)) as db:
            guards = {r['component']: dict(r) for r in db.execute('SELECT * FROM runtime_legacy_sqlite_sources')}
            if set(guards) != {name for name, _ in LEGACY_DATABASES}:
                raise ValueError('Legacy source registry is incomplete')
            result['canonical_digest'] = fingerprint(db)
            result['application_digest'] = _application_digest(db)
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Canonical database integrity check failed')
            for stat in stats:
                guard = guards[stat.component]
                item = {'component': stat.component, 'path': str(stat.path), 'presence': stat.presence,
                        'stat_token': stat.token, 'guard': guard, 'comparison': []}
                if guard['path'] != str(stat.path):
                    raise ValueError('Legacy guard belongs to another root')
                if stat.presence == 'present':
                    with closing(_read(stat.path)) as old:
                        item['digest'] = fingerprint(old)
                        if guard['presence'] != 'present':
                            raise ValueError('Unimported legacy source: ' + stat.component)
                        if item['digest'] != guard['digest']:
                            if stat.component != 'messages':
                                raise ValueError('Unreviewed legacy source changed: ' + stat.component)
                            item['comparison'] = _messages(old, db)
                elif guard['presence'] != 'absent' or guard['stat_token'] != stat.token:
                    raise ValueError('Legacy source disappeared or changed: ' + stat.component)
                result['sources'].append(item)
        if any(s.presence == 'present' for s in stats):
            handles = _open_handles([path, *(s.path for s in stats if s.presence == 'present')])
            if handles:
                result['blockers'].append('Database handles remain open: ' + ','.join(map(str, handles)))
        else:
            result['status'] = 'not-needed'
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
        result['blockers'].append(str(error))
    if result['blockers']:
        result['status'] = 'blocked'
    result['token'] = _digest(result)
    return result


def _atomic(path, data, mode=0o600):
    fd, temporary = tempfile.mkstemp(prefix='.cutover-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _save(path, document):
    _atomic(path, json.dumps(document, sort_keys=True, indent=2).encode())


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _tombstone(path, archive, component):
    path.mkdir(mode=0o700)
    _save(path / 'RETIRED.json', {'kind': 'retired-legacy-database', 'component': component,
                                 'archive': str(archive)})
    os.chmod(path / 'RETIRED.json', 0o400)
    os.chmod(path, 0o500)


def _restore_launchers(journal, archive):
    current_paths = {item['path'] for item in _launchers(Path(journal['root']))}
    for index, item in enumerate(journal['launchers']):
        path = Path(item['path'])
        if str(path) not in current_paths or path.is_symlink():
            raise ValueError('Launcher no longer belongs to the inventoried repository')
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        if current == item['sha256']:
            continue
        if current != hashlib.sha256(FENCE).hexdigest():
            raise ValueError('Launcher changed during cutover; original retained')
        data = (archive / ('launcher-' + str(index))).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Launcher backup integrity mismatch')
        _atomic(path, data, item['mode'])


def _restore_sources(journal, archive):
    source_stats(Path(journal['root']))  # Validate all parent paths before restoring any file.
    for item in reversed(journal['sources']):
        path = Path(item['path'])
        backup = archive / (item['component'] + '.sqlite3')
        if not backup.exists():
            continue
        if item['presence'] == 'present':
            with closing(_read(backup)) as db:
                if fingerprint(db) != item['digest']:
                    raise ValueError('Retained original integrity mismatch')
        if path.exists():
            marker = path / 'RETIRED.json'
            if path.is_symlink() or not path.is_dir():
                raise ValueError('Legacy path changed during cutover; retained original preserved')
            children = list(path.iterdir())
            if children and (children != [marker] or marker.is_symlink()
                    or json.loads(marker.read_text()).get('archive') != str(archive)):
                raise ValueError('Legacy marker changed during cutover; retained original preserved')
            os.chmod(path, 0o700)
            marker.unlink(missing_ok=True)
            path.rmdir()
        if item['presence'] == 'present':
            os.replace(backup, path)
        _sync_directory(path.parent)


def _restored_guards(db, root, journal):
    """Accept rename metadata only when the original import digest still matches."""
    for stat, item in zip(source_stats(root), journal['sources'], strict=True):
        old = item['guard']
        if old['presence'] == 'present' and old['digest'] != item.get('digest'):
            continue  # The pre-existing logical drift still requires explicit retirement.
        db.execute('UPDATE runtime_legacy_sqlite_sources SET stat_token=? WHERE component=? '
                   'AND presence=? AND digest IS ? AND stat_token=?',
                   (stat.token, stat.component, old['presence'], old['digest'], old['stat_token']))


def _committed(db, journal):
    exists = db.execute("SELECT 1 FROM sqlite_schema WHERE name='runtime_legacy_retirements'").fetchone()
    return bool(exists) and all((row := db.execute(
        'SELECT payload FROM runtime_legacy_retirements WHERE component=?', (item['component'],)).fetchone())
        and json.loads(row[0]).get('token') == journal['token'] for item in journal['sources'])


def apply_cutover(worktree, *, expected_token):
    """Apply only a reviewed current plan; never import late rows."""
    root = control_root(Path(worktree).resolve())
    local = root / '.neurath/local'
    journal_path = local / 'cutover-pending.json'
    with migration_lock(root):
        if journal_path.exists():
            raise ValueError('Interrupted cutover requires recovery')
        plan = inspect_cutover(root)
        if plan['token'] != expected_token or plan['status'] != 'ready':
            raise ValueError('Cutover plan changed or has blockers; inspect again')
        archives = local / 'cutovers'
        if archives.is_symlink():
            raise ValueError('Cutover archive must not use symlinks')
        archives.mkdir(mode=0o700, exist_ok=True)
        archive = Path(tempfile.mkdtemp(prefix=expected_token + '-', dir=archives))
        journal = {**plan, 'archive': str(archive)}
        for index, item in enumerate(plan['launchers']):
            shutil.copy2(item['path'], archive / ('launcher-' + str(index)))
        _save(journal_path, journal)
        _save(archive / 'plan.json', journal)
        db = sqlite3.connect(local / 'runtime.sqlite3', isolation_level=None)
        db.row_factory = sqlite3.Row
        committed = False
        legacy_connections = ExitStack()
        try:
            db.execute('BEGIN IMMEDIATE')
            if fingerprint(db) != plan['canonical_digest']:
                raise ValueError('Canonical state changed before cutover')
            shutil.copy2(local / 'runtime.sqlite3', archive / 'runtime-before.sqlite3')
            for item in plan['launchers']:
                if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
                    raise ValueError('Launcher changed before fencing')
                _atomic(Path(item['path']), FENCE, item['mode'])
            foreign = set(_open_handles([local / 'runtime.sqlite3',
                *(Path(item['path']) for item in plan['sources'] if item['presence'] == 'present')])) - {os.getpid()}
            if foreign:
                raise ValueError('Database opened during fencing')
            for item in plan['sources']:
                if item['presence'] == 'present':
                    old = legacy_connections.enter_context(closing(sqlite3.connect(item['path'], isolation_level=None)))
                    old.row_factory = sqlite3.Row
                    old.execute('BEGIN IMMEDIATE')
                    if fingerprint(old) != item['digest']:
                        raise ValueError('Legacy source changed while acquiring its lock')
            for stat, item in zip(source_stats(root), plan['sources'], strict=True):
                if stat.token != item['stat_token']:
                    raise ValueError('Legacy source changed before retirement')
                path = stat.path
                if path.is_dir():
                    continue
                destination = archive / (stat.component + '.sqlite3')
                path.parent.mkdir(parents=True, exist_ok=True)
                if stat.presence == 'present':
                    os.replace(path, destination)
                else:
                    destination.touch(mode=0o600)
                _tombstone(path, archive, stat.component)
                _sync_directory(path.parent)
                _sync_directory(archive)
            db.execute('CREATE TABLE IF NOT EXISTS runtime_legacy_retirements(component TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            for stat, item in zip(source_stats(root), plan['sources'], strict=True):
                old = item['guard']
                changed = db.execute("UPDATE runtime_legacy_sqlite_sources SET presence='absent',digest=NULL,stat_token=? "
                                     'WHERE component=? AND presence=? AND digest IS ? AND stat_token=?',
                                     (stat.token, stat.component, old['presence'], old['digest'], old['stat_token']))
                if changed.rowcount != 1:
                    raise ValueError('Legacy guard changed during cutover')
                db.execute('INSERT OR IGNORE INTO runtime_legacy_retirements VALUES(?,?)',
                           (stat.component, json.dumps({**item, 'archive': str(archive), 'token': expected_token})))
            after = _application_digest(db)
            if after != plan['application_digest'] or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Canonical application state changed')
            db.commit()
            committed = True
            receipt = {'status': 'completed', 'token': expected_token, 'archive': str(archive),
                       'application_digest_before': plan['application_digest'], 'application_digest_after': after,
                       'worktrees_to_update': [str(Path(item['path']).parent.parent) for item in plan['launchers']]}
            _save(archive / 'receipt.json', receipt)
            _restore_launchers(journal, archive)
            journal_path.unlink()
            _sync_directory(local)
            return receipt
        except BaseException:
            db.rollback()
            legacy_connections.close()
            committed = committed or _committed(db, journal)
            if not committed:
                _restore_sources(journal, archive)
                _restore_launchers(journal, archive)
                db.execute('BEGIN IMMEDIATE')
                _restored_guards(db, root, journal)
                db.commit()
                journal_path.unlink()
            raise
        finally:
            legacy_connections.close()
            db.close()


def recover_cutover(worktree):
    """Recover the exact staged filesystem transition, preserving originals."""
    root = control_root(Path(worktree).resolve())
    journal_path = root / '.neurath/local/cutover-pending.json'
    if not journal_path.exists():
        return {'status': 'not-needed'}
    with migration_lock(root):
        journal = json.loads(journal_path.read_text())
        archive = Path(journal['archive'])
        if journal['root'] != str(root) or archive.parent != root / '.neurath/local/cutovers':
            raise ValueError('Cutover journal belongs to another root')
        if _digest({k: v for k, v in journal.items() if k not in {'token', 'archive'}}) != journal['token']:
            raise ValueError('Cutover journal integrity mismatch')
        if [(item['component'], item['path']) for item in journal['sources']] != [
                (component, str(root / relative)) for component, relative in LEGACY_DATABASES]:
            raise ValueError('Cutover journal source scope mismatch')
        if journal_path.is_symlink() or archive.is_symlink() or archive.parent.is_symlink():
            raise ValueError('Cutover recovery paths must not use symlinks')
        with closing(sqlite3.connect(root / '.neurath/local/runtime.sqlite3')) as db:
            committed = _committed(db, journal)
        if not committed:
            _restore_sources(journal, archive)
            with closing(sqlite3.connect(root / '.neurath/local/runtime.sqlite3')) as db:
                db.execute('BEGIN IMMEDIATE')
                _restored_guards(db, root, journal)
                db.commit()
        _restore_launchers(journal, archive)
        journal_path.unlink()
        return {'status': 'completed' if committed else 'rolled-back', 'archive': str(archive)}


def prepare_cutover(worktree):
    """Explicitly stage an initial import; it is not retirement or activation."""
    root = control_root(Path(worktree).resolve())
    if (root / '.neurath/local/runtime.sqlite3').exists():
        return inspect_cutover(root)
    launchers = _launchers(root)
    if any(not item['managed'] for item in launchers):
        raise ValueError('Unknown launcher prevents initial import')
    paths = [s.path for s in source_stats(root) if s.presence == 'present']
    if not paths:
        raise ValueError('No retained legacy SQLite sources require cutover')
    if _open_handles(paths):
        raise ValueError('Stop database writers before staging the initial import')
    from neurath.runtime.database import RuntimeDatabase
    RuntimeDatabase(root)
    return inspect_cutover(root)


def require_cutover(worktree):
    """Installation must not implicitly start a shared legacy transition."""
    root = control_root(Path(worktree).resolve())
    if any((root / relative).is_file() for _, relative in LEGACY_DATABASES):
        raise ValueError('Shared legacy SQLite requires explicit cutover inspection and retirement before installation')
    if (root / '.neurath/local/cutover-pending.json').exists():
        raise ValueError('Interrupted shared-store cutover requires recovery before installation')
