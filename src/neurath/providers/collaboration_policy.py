"""Choose task lifetime separately from the provider supplying a perspective."""


SESSION_BASES = ('independent-lifecycle', 'native-capability-gap')


def select(source_provider, target_provider, purpose='task', reason='', session_basis=''):
    session_basis = session_basis or ''
    if source_provider not in {'codex', 'claude-code'} or target_provider not in {'codex', 'claude-code'}:
        raise ValueError('collaboration requires a known source and target provider')
    if purpose not in {'task', 'perspective', 'worktree-worker', 'user-session'}:
        raise ValueError('unknown collaboration purpose')
    if purpose != 'task' and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError('nondefault collaboration requires its concrete reason')
    if purpose == 'perspective' and target_provider == source_provider:
        raise ValueError('a different perspective provider must differ from the issuer')
    if purpose == 'worktree-worker' and target_provider != source_provider:
        raise ValueError('a worktree worker must use the issuing provider')
    if session_basis and (purpose != 'worktree-worker' or session_basis not in SESSION_BASES):
        raise ValueError('session basis is only for a deliberately selected independent worktree session')
    kind = {'task': 'native-subagent', 'perspective': 'provider-worker',
            'worktree-worker': 'provider-worker', 'user-session': 'user-session'}[purpose]
    if purpose == 'worktree-worker' and not session_basis:
        kind = 'native-subagent'
    execution = ('subagent' if kind == 'native-subagent' else
                 'cross-provider' if purpose == 'perspective' else 'session')
    return {'kind': kind, 'purpose': purpose, 'reason': reason,
            'execution': execution, 'session_basis': session_basis,
            'provider': source_provider if purpose == 'task' else target_provider,
            'authority': 'routing-only'}
