"""Completion proof variants do not require a Git repository or worker lease."""
import pytest

from neurath.providers.contracts import implementation_completed


@pytest.mark.parametrize('broken', ['missing-link', 'missing-submission', 'wrong-original',
    'wrong-completion', 'wrong-session', 'empty-link-field', 'waiting', 'not-submitted'])
def test_codex_acceptance_requires_exact_runtime_completion_link(broken):
    result = {'status': 'completed', 'worker_generation': 1,
        'implementation_dispatched': True, 'execution': 'native-turn-completed',
        'created': {'provider': 'codex', 'native_session': 'observed-native'},
        'submission': {'delivery': 'submitted', 'native_turn': 'original-turn'},
        'completion': {'id': 'followup-turn', 'status': 'completed', 'error': None},
        'completion_link': {'native_session': 'observed-native', 'submitted_turn': 'original-turn',
                            'completed_turn': 'followup-turn', 'disposition': 'terminal'}}
    if broken == 'missing-link':
        del result['completion_link']
    elif broken == 'missing-submission':
        del result['submission']
    elif broken == 'wrong-original':
        result['submission']['native_turn'] = 'unrelated-original'
    elif broken == 'wrong-completion':
        result['completion']['id'] = 'unrelated-completion'
    elif broken == 'wrong-session':
        result['created']['native_session'] = 'unrelated-session'
    elif broken == 'empty-link-field':
        result['completion_link']['submitted_turn'] = ''
    elif broken == 'waiting':
        result['completion_link']['disposition'] = 'waiting'
    else:
        result['submission']['delivery'] = 'unconfirmed'
    assert not implementation_completed({'provider': 'codex'}, result, 1)
