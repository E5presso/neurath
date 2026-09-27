"""A native wave proof must bind the poll, process, wave and released claim."""
import copy
from pathlib import Path

import pytest


def trace():
    claim = {'session_id': 'root', 'actor_id': 'codex:session:root', 'lease_epoch': 1, 'fencing_token': 'fixture'}
    receipt = {'authority': 'native-pre-tool-use', 'tool': 'write_stdin', 'invocation_id': 'poll-call',
               'native_turn': 'turn', 'process_id': 123, 'empty_input': True, 'dispatch_required': ['a', 'b']}
    def event(method, **values):
        return {'method': method, 'params': {'threadId': 'root', 'turnId': 'turn', **values}}
    def result(tool, data, **arguments):
        return event('item/completed', item={'type': 'mcpToolCall', 'tool': tool, 'arguments': arguments,
            'result': {'structuredContent': {'ok': True, 'result': data}}})
    process = {'type': 'commandExecution', 'id': 'cat-call', 'processId': '123',
               'commandActions': [{'command': '/bin/cat'}], 'status': 'inProgress', 'exitCode': None}
    return [
        result('worktree_claim', claim),
        result('task_start', {'tasks': [{'id': 'task', 'status': 'in_progress'}]}),
        event('item/started', item=process),
        result('delegation_wave_prepare', {'wave_id': 'wave', 'dispatch_required': ['a', 'b']}, task_id='task'),
        event('hook/completed', run={'id': 'pre:poll-call', 'eventName': 'preToolUse', 'status': 'blocked',
                                    'entries': [{'text': 'dispatch ready wave work before waiting'}]}),
        result('delegation_wave_read', {'wave_id': 'wave', 'last_wait_denial': receipt}),
        result('session_status', {}),
        result('delegation_prepare', {}, delegation_id='a'),
        result('delegation_prepare', {}, delegation_id='b'),
        event('item/completed', item={**process, 'status': 'completed', 'exitCode': 0}),
        result('delegation_wave_read', {'wave_id': 'wave', 'last_wait_denial': receipt,
            'all_succeeded': True, 'states': {'a': 'succeeded', 'b': 'succeeded'}}),
        result('task_resolve', {'all_terminal': True, 'tasks': [{'id': 'task', 'status': 'succeeded'}]}, task_id='task'),
        result('worktree_release', {'released': True, 'claim': claim}),
    ]


def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    from native_wave_probe import verify_wave_events
    return verify_wave_events


def test_complete_native_wave_proof(monkeypatch):
    result = verifier(monkeypatch)(trace(), 'root', 'turn')
    assert result['status'] == 'passed' and result['process_id'] == 123 and result['wave_id'] == 'wave'


@pytest.mark.parametrize('change', ['start', 'exit', 'release', 'process', 'turn', 'invocation', 'wave',
                                   'claim', 'ready', 'observation', 'reduced'])
def test_incomplete_or_substituted_wave_proof_is_rejected(monkeypatch, change):
    events = copy.deepcopy(trace())
    if change in {'start', 'exit', 'release'}:
        events.pop({'start': 2, 'exit': 9, 'release': 12}[change])
    elif change == 'claim':
        events[12]['params']['item']['result']['structuredContent']['result']['claim']['lease_epoch'] = 2
        # Preserve the original acquisition, despite deepcopy preserving fixture aliases.
        events[0]['params']['item']['result']['structuredContent']['result'] = {**trace()[0]['params']['item']['result']['structuredContent']['result']}
    elif change == 'reduced':
        events = [e for e in events if e['params'].get('item', {}).get('type') != 'commandExecution']
    else:
        for index in (5, 10):
            data = events[index]['params']['item']['result']['structuredContent']['result']
            if change == 'wave':
                data['wave_id'] = 'other'
            elif change == 'observation':
                data.pop('last_wait_denial', None)
            else:
                key, value = {'process': ('process_id', 456), 'turn': ('native_turn', 'old'),
                    'invocation': ('invocation_id', 'other-call'), 'ready': ('dispatch_required', ['a'])}[change]
                data['last_wait_denial'][key] = value
    with pytest.raises(AssertionError):
        verifier(monkeypatch)(events, 'root', 'turn')
