import json
import os
import tomllib
from pathlib import Path

import pytest

from neurath.install import configure


def test_install_preserves_unrelated_settings_and_renames_server(tmp_path):
    (tmp_path / '.codex').mkdir()
    (tmp_path / '.codex/config.toml').write_text('model = "chosen"\n[mcp_servers.neurath_collaboration]\ncommand = "old"\n[mcp_servers.other]\ncommand = "keep"\n')
    (tmp_path / '.codex/hooks.json').write_text(json.dumps({'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'user-hook'}, {'type': 'command', 'command': '/root/tools/checkout_host hook'}]}]}}))
    (tmp_path / 'AGENTS.md').write_text('User instructions remain.\n')
    result = configure(tmp_path, Path('/new/python'), 'a' * 64)
    config = tomllib.loads((tmp_path / '.codex/config.toml').read_text())
    assert config['model'] == 'chosen'
    assert set(config['mcp_servers']) == {'neurath', 'other'}
    hooks = json.loads((tmp_path / '.codex/hooks.json').read_text())
    commands = [h['command'] for group in hooks['hooks']['PreToolUse'] for h in group['hooks']]
    assert 'user-hook' in commands and len(commands) == 2
    assert (tmp_path / 'AGENTS.md').read_text().startswith('User instructions remain.')
    assert Path(result['backup']).is_dir()
    assert os.access(tmp_path / '.neurath/run', os.X_OK)


def test_repeat_install_does_not_duplicate_registration(tmp_path):
    configure(tmp_path, Path('/new/python'), 'a' * 64)
    configure(tmp_path, Path('/new/python'), 'b' * 64)
    assert (tmp_path / '.codex/config.toml').read_text().count('[mcp_servers.neurath]') == 1
    assert (tmp_path / 'AGENTS.md').read_text().count('<!-- neurath:managed -->') == 1


def test_install_failure_restores_all_changed_files(tmp_path, monkeypatch):
    import neurath.install as module
    configure(tmp_path, Path('/old/python'), 'a' * 64)
    targets = ['.neurath/run', '.codex/config.toml', '.codex/hooks.json', '.claude/settings.json', '.mcp.json', '.neurath/policy.md', 'AGENTS.md', '.neurath/install.json']
    before = {name: (tmp_path / name).read_bytes() for name in targets}
    original = module._atomic
    calls = 0
    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError('injected failure')
        return original(*args)
    monkeypatch.setattr(module, '_atomic', fail_once)
    with pytest.raises(OSError):
        configure(tmp_path, Path('/new/python'), 'b' * 64)
    assert {name: (tmp_path / name).read_bytes() for name in targets} == before


def test_install_rejects_symlink_before_creating_target_directory(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.neurath').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        configure(project, Path('/new/python'), 'a' * 64)
    assert list(outside.iterdir()) == []


def test_install_rejects_symlink_backup_directory(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (tmp_path / '.neurath/local').mkdir(parents=True)
    (tmp_path / '.neurath/local/install-backups').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        configure(tmp_path, Path('/new/python'), 'a' * 64)
    assert list(outside.iterdir()) == []
    assert not (tmp_path / '.neurath/run').exists()


def test_failure_and_delegated_stop_events_are_registered(tmp_path):
    configure(tmp_path, Path('/new/python'), 'a' * 64)
    for name in ('.codex/hooks.json', '.claude/settings.json'):
        hooks = json.loads((tmp_path / name).read_text())['hooks']
        assert ('PostToolUseFailure' in hooks) == (name == '.claude/settings.json')
        assert 'SubagentStop' in hooks


def test_unsupported_toml_layout_fails_before_configuration_writes(tmp_path):
    (tmp_path / '.codex').mkdir()
    config = tmp_path / '.codex/config.toml'
    original = 'mcp_servers = { neurath = {command = "existing"}, unrelated = {command = "keep"} }\n'
    config.write_text(original)
    with pytest.raises(ValueError, match='TOML'):
        configure(tmp_path, Path('/new/python'), 'a' * 64)
    assert config.read_text() == original
    assert not (tmp_path / '.neurath/run').exists()


def test_partial_environment_install_is_retried(tmp_path, monkeypatch):
    import hashlib
    import neurath.install as module
    wheel_bytes = b'fixture wheel'
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    environment = tmp_path / '.neurath/local/environments' / digest
    (environment / 'bin').mkdir(parents=True)
    (environment / 'bin/python').write_text('partial virtualenv')
    calls = []
    def run(arguments, **kwargs):
        calls.append(arguments)
        if arguments[:2] == ['uv', 'build']:
            (Path(arguments[arguments.index('--out-dir') + 1]) / 'neurath.whl').write_bytes(wheel_bytes)
    monkeypatch.setattr(module.subprocess, 'run', run)
    monkeypatch.setattr(module, 'configure', lambda *args: {'configured': True})
    assert module.install(tmp_path, tmp_path) == {'configured': True}
    assert any(call[:3] == ['uv', 'pip', 'install'] for call in calls)
    assert json.loads((environment / '.neurath-wheel.json').read_text())['wheel_sha256'] == digest


def test_shared_claude_instruction_symlink_is_preserved(tmp_path):
    (tmp_path / 'AGENTS.md').write_text('Shared original instructions.\n')
    (tmp_path / 'CLAUDE.md').symlink_to('AGENTS.md')
    configure(tmp_path, Path('/new/python'), 'a' * 64)
    assert (tmp_path / 'CLAUDE.md').is_symlink()
    assert 'Use MCP server `neurath`' in (tmp_path / 'CLAUDE.md').read_text()
    assert (tmp_path / 'CLAUDE.md').read_text().startswith('Shared original instructions.')


def test_codex_session_end_uses_supported_timeout(tmp_path):
    configure(tmp_path, Path('/new/python'), 'a' * 64)
    hooks = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']
    assert hooks['SessionEnd'][0]['hooks'][0]['timeout'] == 3
