from copy import deepcopy
from pathlib import Path

import pytest

from neurath.providers.codex import CodexSessions
from neurath.providers.contracts import CreationRejected, ExecutionPolicy, Session, UnsupportedOperation


def test_empty_explicit_project_id_is_rejected_without_discovery():
    host = Host({'type': 'readOnly', 'networkAccess': False})
    with pytest.raises(ValueError, match='project ID'):
        CodexSessions(host).create('/target', project_id='')
    assert host.calls == []


class Host:
    approval_policies = ('never',)
    supports_collaboration_mode = True

    def __init__(self, sandbox):
        self.calls = []
        self.sandbox = sandbox
        self.thread = {'id': 'owned', 'cwd': '/target', 'status': {'type': 'idle'}, 'turns': []}

    def request(self, method, params):
        self.calls.append((method, deepcopy(params)))
        if method.startswith('project/'):
            raise AssertionError('No project lookup without explicit project ID')
        if method in ('thread/start', 'thread/resume'):
            return {'thread': self.thread.copy(), 'cwd': '/target', 'model': 'host-model',
                    'approvalPolicy': 'never', 'sandbox': self.sandbox}
        if method == 'thread/read':
            return {'thread': self.thread.copy()}
        if method == 'turn/start':
            return {'turn': {'id': 'turn-1'}}
        return {}


def policy():
    return {'type': 'workspace-write', 'writable_roots': ['/source', '/source/subdir', '/allowed'],
            'network_access': True, 'exclude_tmpdir_env_var': True, 'exclude_slash_tmp': True}


def actual():
    return {'type': 'workspaceWrite', 'writableRoots': ['/target', '/target/subdir', '/allowed', '/source/.neurath/local'],
            'networkAccess': True, 'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True}


def test_workspace_details_rebased_sent_and_read_back(monkeypatch):
    monkeypatch.setattr(CodexSessions, '_state_roots', staticmethod(lambda _: ['/source/.neurath/local']))
    host = Host(actual())
    adapter = CodexSessions(host)
    session = adapter.create('/target', policy=ExecutionPolicy('workspace-write'),
                             inherited_sandbox=policy(), source_worktree='/source')
    assert session.policy['verification'] == 'verified'
    params = host.calls[0][1]
    assert params['config'] == {
        'sandbox_workspace_write.writable_roots': ['/target', '/target/subdir', '/allowed', '/source/.neurath/local'],
        'sandbox_workspace_write.network_access': True,
        'sandbox_workspace_write.exclude_tmpdir_env_var': True,
        'sandbox_workspace_write.exclude_slash_tmp': True,
    }
    assert 'projectId' not in params
    adapter.bootstrap(session)
    assert host.calls[-1][1]['sandboxPolicy'] == actual()
    prompt = host.calls[-1][1]['input'][0]['text']
    assert all(name in prompt for name in ('session_status', 'session_inspect', 'worktree_claim'))
    assert '.neurath/run' not in prompt
    assert '/source' not in session.policy['requested']['inherited_sandbox']['writable_roots']


@pytest.mark.parametrize('field,value', [
    ('networkAccess', False), ('excludeTmpdirEnvVar', False), ('excludeSlashTmp', False),
    ('writableRoots', ['/target']), ('writableRoots', [*actual()['writableRoots'], '/foreign']),
])
def test_changed_or_missing_native_dimensions_withhold_prompt(monkeypatch, field, value):
    monkeypatch.setattr(CodexSessions, '_state_roots', staticmethod(lambda _: ['/source/.neurath/local']))
    host = Host({**actual(), field: value})
    with pytest.raises(CreationRejected) as caught:
        CodexSessions(host).create('/target', policy=ExecutionPolicy('workspace-write'),
                                   inherited_sandbox=policy(), source_worktree='/source')
    assert caught.value.session.native_session == 'owned'
    assert not any(method.startswith('turn/') for method, _ in host.calls)


@pytest.mark.parametrize('extra', [{'read_access': {'type': 'restricted', 'readable_roots': ['/target']}},
                                  {'future_dimension': True}])
def test_unrepresentable_read_restrictions_fail_before_creation(monkeypatch, extra):
    monkeypatch.setattr(CodexSessions, '_state_roots', staticmethod(lambda _: []))
    host = Host(actual())
    with pytest.raises(UnsupportedOperation, match='sandbox'):
        CodexSessions(host).create('/target', policy=ExecutionPolicy('workspace-write'),
                                   inherited_sandbox={**policy(), **extra})
    assert host.calls == []


def test_read_only_network_request_not_silently_narrowed():
    host = Host({'type': 'readOnly', 'networkAccess': False})
    with pytest.raises(UnsupportedOperation, match='network'):
        CodexSessions(host).create('/target', inherited_sandbox={'type': 'read-only', 'network_access': True})
    assert host.calls == []


def test_native_extra_restriction_is_not_ignored():
    host = Host({'type': 'readOnly', 'networkAccess': False, 'readAccess': {'type': 'restricted'}})
    with pytest.raises(CreationRejected):
        CodexSessions(host).create('/target', inherited_sandbox={'type': 'read-only', 'network_access': False})


def test_restore_preserves_previously_applied_sandbox(monkeypatch):
    monkeypatch.setattr(CodexSessions, '_state_roots', staticmethod(lambda _: ['/source/.neurath/local']))
    session = CodexSessions(Host(actual())).create('/target', policy=ExecutionPolicy('workspace-write'),
                       inherited_sandbox=policy(), source_worktree='/source')
    host = Host(actual())
    restored = CodexSessions(host).restore(session)
    assert host.calls[0][0] == 'thread/resume'
    assert host.calls[0][1]['config']['sandbox_workspace_write.writable_roots'] == actual()['writableRoots']
    assert restored.policy['requested']['inherited_sandbox'] == session.policy['requested']['inherited_sandbox']


def test_unspecified_project_allows_native_work_and_optional_affiliation_change():
    host = Host({'type': 'readOnly', 'networkAccess': False})
    adapter = CodexSessions(host)
    session = adapter.create('/target')
    host.thread['projectId'] = 'optional-existing-association'
    assert adapter.bootstrap(session)['delivery'] == 'submitted'
    assert not any(method.startswith('project/') for method, _ in host.calls)


def test_execution_forwards_inherited_policy_to_adapter(monkeypatch):
    from neurath.providers import execution
    captured = {}
    class Adapter:
        def __init__(self, *_): pass
        def create(self, *args, **kwargs):
            captured.update(kwargs)
            return Session('codex', 'codex-app-server', 'owned', '/target', None, 'host-model', {})
        def bootstrap(self, *_): return {'delivery': 'needs-input'}
        def cancel(self, *_): return {}
    class Process:
        diagnostic = ''
        def close(self): pass
    monkeypatch.setattr(execution, '_target', lambda *_: Path('/target'))
    monkeypatch.setattr(execution, 'CodexSessions', Adapter)
    monkeypatch.setattr(execution, 'CodexStdio', lambda *args, **kwargs: Process())
    result = execution.run('/source', worktree='/target', assignment='Prepare', mode='workspace-write',
        approval_policy='never', collaboration_mode='default', inherited_sandbox=policy())
    assert result['status'] == 'needs-input'
    assert captured == {'inherited_sandbox': policy(), 'source_worktree': '/source'}
