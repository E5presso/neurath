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
                   session_basis='native-capability-gap',
                   reason='The observed native child tool cannot bind the required concurrent writer checkout',
                   worktree='/linked', assignment='Implement the ticket')
    assert result['collaboration']['kind'] == 'provider-worker'
    assert result['next_operation']['tool'] == 'provider_run'
    assert result['next_operation']['arguments']['purpose'] == 'worktree-worker'
    assert result['next_operation']['arguments']['session_basis'] == 'native-capability-gap'
    with pytest.raises(ValueError):
        route('claude-code', 'create', source_provider='codex', purpose='worktree-worker',
              reason='Move a root ticket', worktree='/linked', assignment='Implement')


def test_worktree_location_alone_keeps_native_subagent_choice():
    result = route('codex', 'create', source_provider='codex', purpose='worktree-worker',
                   reason='Move a root ticket into a worktree',
                   worktree='/linked', assignment='Implement the ticket')
    assert result['collaboration']['kind'] == 'native-subagent'
    assert result['next_operation']['tool'] == 'delegation_prepare'


@pytest.mark.parametrize('basis', ['independent-lifecycle', 'native-capability-gap'])
def test_independent_session_requires_a_specific_selection_basis(basis):
    result = route('codex', 'create', source_provider='codex', purpose='worktree-worker',
                   session_basis=basis, reason='Observed host constraint or independent delivery lifecycle',
                   worktree='/linked', assignment='Implement the ticket')
    assert result['collaboration']['execution'] == 'session'
    assert result['next_operation']['arguments']['session_basis'] == basis


def test_session_basis_cannot_silently_promote_a_default_task():
    with pytest.raises(ValueError, match='session basis'):
        route('codex', 'create', session_basis='native-capability-gap',
              worktree='/linked', assignment='Implement')


def test_direct_worktree_execution_without_session_selection_never_launches(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from neurath.runtime import provider_execution, model_tasks, admission
    from neurath.runtime.task_schema import TaskError
    from neurath.providers import jobs
    monkeypatch.setattr(admission, '_verification_owner', lambda *args: (1, 'turn'))
    monkeypatch.setattr(model_tasks, 'previous_admission', lambda *args: None)
    monkeypatch.setattr(jobs, 'start', lambda *args, **kwargs: pytest.fail('new session launched'))
    with pytest.raises(TaskError, match='native child'):
        provider_execution.run(tmp_path, {
            'purpose': 'worktree-worker', 'reason': 'Separate worktree',
            'worktree': '/linked', 'assignment': 'Implement', 'key': 'new-run'},
            identity=SimpleNamespace(host='codex'))


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
