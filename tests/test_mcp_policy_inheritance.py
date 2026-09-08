"""Known MCP exposure restrictions cannot vanish during native mode inheritance."""
import json
import pytest
from neurath.agents.store import AgentIdentity
from neurath.runtime.provider_policy import controls, resolve_policy
from neurath.runtime.provider_policy import PolicyObservationError


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path / 'home')
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    return source, target


@pytest.mark.parametrize('setting', [
    'disabled_tools=["delete_record"]',
    'enabled_tools=["read_record"]',
    'enabled=false',
    '[mcp_servers.fixture.tools.delete_record]\nenabled=false',
    '[mcp_servers.fixture.tools.delete_record]\napproval_mode="ask"',
])
def test_codex_mcp_restriction_cannot_map_to_unrestricted_target(roots, setting):
    source, target = roots
    (source / '.codex').mkdir()
    (target / '.codex').mkdir()
    (source / '.codex/config.toml').write_text('[mcp_servers.fixture]\n' + setting + '\n')
    (target / '.codex/config.toml').write_text('[mcp_servers.fixture]\n')
    policy = {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'}}
    assert controls(source, 'codex', policy) != controls(target, 'codex', policy)
    with pytest.raises(ValueError, match='tool_denylist'):
        resolve_policy(source, AgentIdentity('codex', 'root', 'actor'),
                       {'provider': 'codex', 'mode': 'inherit', 'worktree': str(target)}, policy)
    (target / '.codex/config.toml').write_bytes((source / '.codex/config.toml').read_bytes())
    assert resolve_policy(source, AgentIdentity('codex', 'root', 'actor'),
        {'provider': 'codex', 'mode': 'inherit', 'worktree': str(target)}, policy)['mode'] == 'danger-full-access'


@pytest.mark.parametrize('restriction', [
    {'disabledMcpjsonServers': ['fixture']},
    {'enabledMcpjsonServers': ['safe']},
    {'enableAllProjectMcpServers': False},
])
def test_claude_project_mcp_selection_is_retained(roots, restriction):
    source, target = roots
    (source / '.claude').mkdir()
    (source / '.claude/settings.json').write_text(json.dumps(restriction))
    policy = {'permission_mode': 'bypassPermissions'}
    with pytest.raises(ValueError, match='tool_denylist'):
        resolve_policy(source, AgentIdentity('claude-code', 'root', 'actor'),
            {'provider': 'claude-code', 'mode': 'inherit', 'worktree': str(target)}, policy)


def test_mcp_credentials_do_not_enter_permission_envelope(roots):
    source, target = roots
    for root, credential in ((source, 'first-fixture-secret'), (target, 'second-fixture-secret')):
        (root / '.codex').mkdir()
        (root / '.codex/config.toml').write_text('[mcp_servers.fixture]\ncommand="fixture"\n'
            'disabled_tools=["delete_record"]\n[mcp_servers.fixture.env]\nTOKEN="' + credential + '"\n')
    policy = {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'}}
    assert controls(source, 'codex', policy) == controls(target, 'codex', policy)


@pytest.mark.parametrize('restriction', [
    {'mcpServers': {'fixture': {'disabled_tools': ['delete_record']}}},
    {'allowedMcpServers': [{'serverName': 'safe'}]},
    {'deniedMcpServers': [{'serverName': 'fixture'}]},
])
def test_claude_user_mcp_policy_is_compared_without_transport_data(roots, restriction):
    source, target = roots
    (source / '.claude').mkdir()
    (source / '.claude/settings.local.json').write_text(json.dumps(restriction))
    policy = {'permission_mode': 'bypassPermissions'}
    assert controls(source, 'claude-code', policy) != controls(target, 'claude-code', policy)


@pytest.mark.parametrize('setting', [
    'mcp_servers=[]', '[mcp_servers.fixture]\nenabled="false"',
    '[mcp_servers.fixture]\ndisabled_tools="delete_record"',
    '[mcp_servers.fixture]\ntools=[]',
    '[mcp_servers.fixture.tools.delete_record]\nenabled="false"',
])
def test_malformed_mcp_controls_are_unsupported(roots, setting):
    source, _ = roots
    (source / '.codex').mkdir()
    (source / '.codex/config.toml').write_text(setting)
    with pytest.raises(PolicyObservationError, match='unsupported'):
        controls(source, 'codex', {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'}})


@pytest.mark.parametrize('name', ['disabledMcpServers', 'enabledMcpServers'])
def test_claude_native_project_toggle_is_bound_to_current_project(roots, name):
    from pathlib import Path
    source, target = roots
    home = Path.home()
    home.mkdir()
    config = home / '.claude.json'
    config.write_text(json.dumps({'oauthAccount': {'unrelated': 'fixture-secret'}, 'projects': {
        str(source): {name: ['fixture']}, str(target): {}, '/unrelated/project': {'disabledMcpServers': ['other']}}}))
    policy = {'permission_mode': 'bypassPermissions'}
    assert controls(source, 'claude-code', policy) != controls(target, 'claude-code', policy)
    payload = json.loads(config.read_text())
    payload['projects'][str(target)] = payload['projects'][str(source)]
    config.write_text(json.dumps(payload))
    assert controls(source, 'claude-code', policy) == controls(target, 'claude-code', policy)
