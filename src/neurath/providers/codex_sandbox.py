"""Preserve supported Codex sandbox dimensions and reject unsupported ones."""

from copy import deepcopy
from pathlib import Path

from neurath.providers.contracts import UnsupportedOperation

TYPES = {'read-only': 'readOnly', 'workspace-write': 'workspaceWrite',
         'danger-full-access': 'dangerFullAccess'}
FIELDS = {'network_access': 'networkAccess', 'writable_roots': 'writableRoots',
          'exclude_tmpdir_env_var': 'excludeTmpdirEnvVar', 'exclude_slash_tmp': 'excludeSlashTmp'}


def _paths(values):
    if not isinstance(values, list) or any(not isinstance(v, str) or not Path(v).is_absolute() for v in values):
        raise UnsupportedOperation('sandbox writable_roots must be absolute paths')
    return list(dict.fromkeys(str(Path(value).resolve()) for value in values))


def prepare_sandbox(mode, inherited, root, state_roots, source_worktree=None):
    source = deepcopy(inherited) if inherited is not None else {'type': mode}
    if not isinstance(source, dict) or source.get('type') != mode or mode not in TYPES:
        raise UnsupportedOperation('sandbox mode does not match inherited policy')
    allowed = {'type'} | ({'network_access'} if mode == 'read-only' else set(FIELDS) if mode == 'workspace-write' else set())
    if unknown := set(source) - allowed:
        raise UnsupportedOperation('sandbox dimensions unsupported: ' + ', '.join(sorted(unknown)))
    if mode == 'danger-full-access':
        return source, {'type': TYPES[mode]}, {}
    for field in allowed - {'type', 'writable_roots'}:
        if field in source and type(source[field]) is not bool:
            raise UnsupportedOperation('sandbox ' + field + ' must be boolean')
        source.setdefault(field, False)
    if mode == 'read-only' and source['network_access']:
        raise UnsupportedOperation('sandbox read-only network_access cannot be preserved by thread/start')
    if mode == 'workspace-write':
        roots = _paths(source.get('writable_roots', []))
        target, shared = Path(root).resolve(), set(_paths(state_roots))
        if source_worktree is not None:
            original = Path(source_worktree).resolve()
            roots = [str(target / Path(path).relative_to(original))
                     if path not in shared and Path(path).is_relative_to(original) else path for path in roots]
        source['writable_roots'] = list(dict.fromkeys([*roots, *state_roots]))
    native = {'type': TYPES[mode], **{FIELDS[k]: v for k, v in source.items() if k != 'type'}}
    config = {'sandbox_workspace_write.' + k: v for k, v in source.items() if k != 'type'} if mode == 'workspace-write' else {}
    return source, native, config


def sandbox_matches(actual, expected, root):
    """Compare supported dimensions; unknown response restrictions fail closed."""
    if not isinstance(actual, dict) or set(actual) - set(expected) or actual.get('type') != expected['type']:
        return False
    for name, value in expected.items():
        if name == 'writableRoots':
            try:
                wanted, observed = set(_paths(value)), set(_paths(actual.get(name)))
            except UnsupportedOperation:
                return False
            target = str(Path(root).resolve())
            if wanted - {target} != observed - {target}:
                return False
        elif name in ('excludeTmpdirEnvVar', 'excludeSlashTmp'):
            if type(actual.get(name, False)) is not bool or actual.get(name, False) != value:
                return False
        elif actual.get(name) != value or type(actual.get(name)) is not type(value):
            return False
    return True
