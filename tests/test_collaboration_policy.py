"""Intentional collaboration selection precedes provider transport selection."""
import pytest

from neurath.providers.operations import route


def test_leaf_and_full_ticket_default_to_native_child():
    for assignment in ('Read a module', 'Implement a large ticket in a worktree and monitor its PR'):
        result = route('codex', 'create', worktree='/work', assignment=assignment)
        assert result['next_operation']['tool'] == 'delegation_prepare'
        assert result['collaboration']['kind'] == 'native-subagent'


def test_user_continuation_selects_user_session_with_reason():
    result = route('codex', 'create', project_id='project', purpose='user-session',
                   reason='The user will return to iterate on this separate deliverable')
    assert result['next_operation']['tool'] == 'create_thread'
    assert result['collaboration']['kind'] == 'user-session'


def test_new_perspective_can_select_other_provider_without_user_cross_review_request():
    result = route('claude-code', 'create', source_provider='codex', purpose='perspective',
                   reason='Independent alternative to repeated architectural assumptions',
                   worktree='/work', assignment='Evaluate an alternative')
    assert result['next_operation']['tool'] == 'provider_run'
    assert result['collaboration']['kind'] == 'provider-worker'
    assert result['next_operation']['arguments']['purpose'] == 'perspective'


def test_root_worktree_worker_routes_to_same_provider_without_changing_default_task():
    result = route('codex', 'create', source_provider='codex', purpose='worktree-worker',
                   reason='Move a root ticket into an isolated checkout',
                   worktree='/linked', assignment='Implement the ticket')
    assert result['collaboration']['kind'] == 'provider-worker'
    assert result['next_operation']['tool'] == 'provider_run'
    assert result['next_operation']['arguments']['purpose'] == 'worktree-worker'
    with pytest.raises(ValueError):
        route('claude-code', 'create', source_provider='codex', purpose='worktree-worker',
              reason='Move a root ticket', worktree='/linked', assignment='Implement')


@pytest.mark.parametrize('purpose,reason,provider', [
    ('perspective', '', 'claude-code'),
    ('perspective', 'Need a different model perspective', 'codex'),
    ('user-session', '', 'codex'),
])
def test_nondefault_selection_requires_matching_reason_and_provider(purpose, reason, provider):
    with pytest.raises(ValueError):
        route(provider, 'create', source_provider='codex', purpose=purpose, reason=reason,
              worktree='/work', assignment='Evaluate')


@pytest.mark.parametrize('provider,source', [('codex', 'claude-code'), ('claude-code', 'codex')])
@pytest.mark.parametrize('partial', [{}, {'worktree': '/work'}, {'assignment': 'Review'}])
def test_perspective_never_falls_through_to_user_session(provider, source, partial):
    result = route(provider, 'create', source_provider=source, purpose='perspective',
                   reason='Independent alternative', project_id='project' if provider == 'codex' else None,
                   **partial)
    assert result['status'] == 'assignment-input-required'
    assert result['next_operation'] is None


def test_cli_perspective_routes_with_observed_issuer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from neurath import cli
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    output = []
    monkeypatch.setattr(cli, '_native_or_terminal', lambda root: SimpleNamespace(host='codex'))
    monkeypatch.setattr(cli, 'emit', output.append)
    code = cli.main(['--root', str(tmp_path), 'provider', 'route', 'claude-code', 'create',
                     '--purpose', 'perspective', '--reason', 'Independent alternative',
                     '--worktree', str(tmp_path), '--assignment', 'Review'])
    assert code == 0
    assert output[-1]['collaboration']['kind'] == 'provider-worker'
    assert output[-1]['status'] == 'model-plan-required'


def test_perspective_without_issuer_reports_missing_source():
    result = route('claude-code', 'create', purpose='perspective', reason='Different view',
                   worktree='/work', assignment='Review')
    assert result['status'] == 'source-provider-required'
    assert result['next_operation'] is None
