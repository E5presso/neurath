"""Choose task lifetime separately from the provider supplying a perspective."""


def select(source_provider, target_provider, purpose='task', reason=''):
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
    kind = {'task': 'native-subagent', 'perspective': 'provider-worker',
            'worktree-worker': 'provider-worker', 'user-session': 'user-session'}[purpose]
    return {'kind': kind, 'purpose': purpose, 'reason': reason,
            'provider': source_provider if purpose == 'task' else target_provider,
            'authority': 'routing-only'}
