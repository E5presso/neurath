"""Transactional local host configuration and immutable wheel installation."""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from neurath import __version__

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'SubagentStop', 'SessionEnd')


def _safe_path(path):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f'Refusing symlink installation path: {component}')


def _atomic(path, data, mode=0o600):
    _safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f'Refusing symlink configuration: {path.name}')
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.neurath-install-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def _hooks(config, root, provider):
    result = json.loads(json.dumps(config))
    hooks = result.setdefault('hooks', {})
    events = tuple(event for event in EVENTS if provider != 'codex' or event != 'PostToolUseFailure')
    for event in set(hooks) | set(events):
        kept = []
        for group in hooks.get(event, []):
            group = dict(group)
            group['hooks'] = [h for h in group.get('hooks', []) if not any(
                signature in h.get('command', '')
                for signature in ('tools/checkout_host', '.neurath/run', 'neurath.core.hooks', 'neurath.transport.hooks')
            )]
            if group['hooks']:
                kept.append(group)
        if event in events:
            kept.append({'hooks': [{'type': 'command', 'command': f'{shlex.quote(str(root / ".neurath/run"))} hook --provider {provider}', 'timeout': 3 if provider == 'codex' and event == 'SessionEnd' else 30}]})
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return result


def configure(root, python, wheel_hash):
    """Preserve unrelated configuration and retain a rollback journal before writes."""
    root = Path(root).resolve()
    local = root / '.neurath/local'
    for directory in (root / '.neurath', local, root / '.codex', root / '.claude'):
        _safe_path(directory)
    local.mkdir(parents=True, exist_ok=True)
    codex = root / '.codex/config.toml'
    _safe_path(codex)
    toml = codex.read_text() if codex.exists() else ''
    tomllib.loads(toml)
    # Remove only named Neurath server tables; all other host preferences remain intact.
    toml = re.sub(r'(?ms)^\[mcp_servers\.(?:neurath_collaboration|neurath)(?:\.[^\]]+)?\]\s*\n.*?(?=^\[|\Z)', '', toml)
    command = str(root / '.neurath/run')
    toml += '\n[mcp_servers.neurath]\ncommand = ' + json.dumps(command) + '\nargs = ["mcp", "--provider", "codex"]\nstartup_timeout_sec = 60\n'
    try:
        tomllib.loads(toml)
    except tomllib.TOMLDecodeError as error:
        raise ValueError('Neurath registration cannot be safely updated in this TOML layout') from error
    mcp = _json(root / '.mcp.json')
    mcp.setdefault('mcpServers', {}).pop('neurath_collaboration', None)
    mcp['mcpServers']['neurath'] = {'command': command, 'args': ['mcp', '--provider', 'claude-code']}
    policy = '''# Neurath execution contract

Use the neurath MCP server. Native host events establish identity and retain original input.
Keep the user's goal and unfinished work; failures are attempts, never cancellation.
Use task and delegation commands for work, native host tools for execution.
Evidence distinguishes observed output, user input, agent reports, and explicit approval.
Claim a writer lease before changes. Read and diagnose without a writer lease.
Use harness_bypass(enabled=true) to recover a malfunction without changing task status.
Repair, verify, then set enabled=false. Host permissions always remain authoritative.
Never invent native identity, approval, success, or evidence. No public push or release without authorization.
'''
    block = '''<!-- neurath:managed -->
## Neurath

Use MCP server `neurath`. Read `.neurath/policy.md`.
Inspect `session.get` and `task.list`; preserve unfinished user requirements.
Register the requested outcome with `task.create`, then start it with `task.activate`.
Use ordered phases and criterion-specific evidence; delegation reports need owner acceptance.
Use `lease.acquire` and `lease.release` for writer ownership, native tools for actual execution.
Recover with `harness_bypass(enabled=true)` when the harness malfunctions, then restore it after verification.
<!-- /neurath:managed -->'''
    instructions = root / 'AGENTS.md'
    agents = instructions.read_text() if instructions.exists() else ''
    if '<!-- neurath:managed -->' in agents:
        agents = re.sub(r'(?s)<!-- neurath:managed -->.*?<!-- /neurath:managed -->', block, agents)
    else:
        agents += '\n\n' + block + '\n'
    claude_path = root / 'CLAUDE.md'
    claude_alias = claude_path.is_symlink() and claude_path.resolve() == instructions.resolve()
    if claude_path.is_symlink() and not claude_alias:
        raise ValueError('Unsupported Claude instruction symlink')
    claude_text = claude_path.read_text() if claude_path.exists() else ''
    if '<!-- neurath:managed -->' in claude_text:
        claude_text = re.sub(r'(?s)<!-- neurath:managed -->.*?<!-- /neurath:managed -->', block, claude_text)
    else:
        claude_text += '\n\n' + block + '\n'
    values = {
        '.neurath/run': ('#!/bin/sh\nset -eu\nexec ' + shlex.quote(str(python)) + ' -I -m neurath --root ' + shlex.quote(str(root)) + ' "$@"\n').encode(),
        '.codex/config.toml': toml.encode(),
        '.codex/hooks.json': (json.dumps(_hooks(_json(root / '.codex/hooks.json'), root, 'codex'), indent=2) + '\n').encode(),
        '.claude/settings.json': (json.dumps(_hooks(_json(root / '.claude/settings.json'), root, 'claude-code'), indent=2) + '\n').encode(),
        '.mcp.json': (json.dumps(mcp, indent=2) + '\n').encode(),
        '.neurath/policy.md': policy.encode(),
        'AGENTS.md': agents.encode(),
        **({} if claude_alias else {'CLAUDE.md': claude_text.encode()}),
    }
    receipt = {'version': __version__, 'server': 'neurath', 'wheel_sha256': wheel_hash, 'python': str(python), 'files': {k: hashlib.sha256(v).hexdigest() for k, v in values.items()}, 'native_activation': 'unverified'}
    values['.neurath/install.json'] = (json.dumps(receipt, indent=2) + '\n').encode()
    backup = local / 'install-backups' / str(time.time_ns())
    _safe_path(backup)
    backup.mkdir(parents=True, mode=0o700)
    before = {}
    for name in values:
        path = root / name
        if path.is_symlink():
            raise ValueError('Refusing symlink installation target')
        before[name] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        if before[name] is not None:
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(before[name][0])
            target.chmod(0o600)
    (backup / 'journal.json').write_text(json.dumps({'targets': list(values), 'existed': [n for n, v in before.items() if v is not None]}, indent=2))
    (backup / 'journal.json').chmod(0o600)
    changed = []
    try:
        for name, data in values.items():
            _atomic(root / name, data, 0o700 if name == '.neurath/run' else (before[name][1] if before[name] else 0o600))
            changed.append(name)
    except BaseException:
        for name in reversed(changed):
            if before[name] is None:
                (root / name).unlink(missing_ok=True)
            else:
                _atomic(root / name, *before[name])
        raise
    return {**receipt, 'backup': str(backup)}


def install(root, source):
    root, source = Path(root).resolve(), Path(source).resolve()
    if not root.is_dir():
        raise ValueError('Installation target does not exist')
    _safe_path(root / '.neurath/local/environments')
    with tempfile.TemporaryDirectory(prefix='neurath-wheel-') as temporary:
        subprocess.run(['uv', 'build', '--wheel', '--out-dir', temporary, str(source)], check=True, stdout=sys.stderr)
        wheels = list(Path(temporary).glob('*.whl'))
        if len(wheels) != 1:
            raise ValueError('Expected one built wheel')
        wheel = wheels[0]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        environment = root / '.neurath/local/environments' / digest
        python = environment / 'bin/python'
        marker = environment / '.neurath-wheel.json'
        _safe_path(environment)
        _safe_path(marker)
        # uv virtual environments legitimately symlink bin/python to the runtime.
        # Validate enclosing directories while allowing that managed executable.
        _safe_path(python.parent)
        if not python.exists():
            subprocess.run(['uv', 'venv', '--python', '3.14', str(environment)], check=True, stdout=sys.stderr)
        installed = _json(marker) if marker.exists() else {}
        if installed.get('wheel_sha256') != digest:
            subprocess.run(['uv', 'pip', 'install', '--python', str(python), str(wheel)], check=True, stdout=sys.stderr)
        subprocess.run([str(python), '-I', '-c', 'import neurath; from neurath.transport.mcp import definitions; assert definitions()[0]["name"] == "harness_bypass"'], check=True)
        _atomic(marker, (json.dumps({'wheel_sha256': digest}) + '\n').encode())
        return configure(root, python, digest)
