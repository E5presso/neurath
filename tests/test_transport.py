import json
import subprocess
import sys

import pytest

from neurath.transport.hooks import process
from neurath.transport.mcp import respond
from neurath.transport.recovery import bypass


def request(root, command, arguments, provider='codex'):
    return respond(root, provider, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': command, 'arguments': arguments}})['result']


def native(root, command, arguments, call_id, provider='codex', session='native-fixture'):
    values = {**arguments, '_call_id': call_id}
    process(root, provider, {'hook_event_name': 'PreToolUse', 'session_id': session, 'tool_use_id': call_id, 'tool_name': 'mcp__neurath__' + command, 'tool_input': values})
    result = request(root, command, values, provider)
    assert not result['isError'], result
    return result['structuredContent']['result']


def intake(root, provider='codex'):
    result = process(root, provider, {'hook_event_name': 'UserPromptSubmit', 'session_id': 'native-fixture', 'prompt': 'Implement and verify the requested change.'})
    text = result['hookSpecificOutput']['additionalContext']
    return text.split('source_id=')[1].split(';')[0]


@pytest.mark.parametrize('provider', ['codex', 'claude-code'])
def test_recovery_and_discovery_with_corrupt_store(tmp_path, provider):
    local = tmp_path / '.neurath/local'
    local.mkdir(parents=True)
    database_path = local / 'neurath.sqlite3'
    database_path.write_bytes(b'broken data remains unchanged')
    listing = respond(tmp_path, provider, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert 'harness_bypass' in {t['name'] for t in listing['result']['tools']}
    assert request(tmp_path, 'harness_bypass', {'enabled': True}, provider)['structuredContent']['result']['enabled']
    assert process(tmp_path, provider, {'hook_event_name': 'Stop'}) == {}
    assert request(tmp_path, 'harness_bypass', {'enabled': False}, provider)['isError'] is False
    assert database_path.read_bytes() == b'broken data remains unchanged'


def test_unbound_and_changed_native_calls_cannot_supply_identity(tmp_path):
    assert request(tmp_path, 'session.get', {})['isError']
    intake(tmp_path)
    values = {'_call_id': 'unique'}
    process(tmp_path, 'codex', {'hook_event_name': 'PreToolUse', 'session_id': 'native-fixture', 'tool_name': 'mcp__neurath__session.get', 'tool_input': values})
    assert request(tmp_path, 'session.get', {**values, 'actor_id': 'invented'})['isError']
    assert request(tmp_path, 'session.get', values)['isError'] is False
    assert request(tmp_path, 'session.get', values)['isError'] is True


@pytest.mark.parametrize('provider', ['codex', 'claude-code'])
def test_bound_task_check_evidence_and_stop_lifecycle(tmp_path, provider):
    source = intake(tmp_path, provider)
    task = native(tmp_path, 'task.create', {'source_id': source, 'goal': 'Verify behavior', 'criteria': [{'id': 'check', 'description': 'Registered test passes'}], 'request_id': 'create'}, 'c1', provider)
    task = native(tmp_path, 'task.activate', {'task_id': task['id'], 'expected_revision': 0, 'request_id': 'activate'}, 'c2', provider)
    native(tmp_path, 'lease.acquire', {'resource': str(tmp_path), 'request_id': 'lease'}, 'c3', provider)
    assert process(tmp_path, provider, {'hook_event_name': 'Stop', 'session_id': 'native-fixture'})['decision'] == 'block'
    (tmp_path / '.neurath/project.json').write_text(json.dumps({'verification': {'check': {'argv': ['python', '-c', 'print(1)'], 'success_codes': [0]}}}))
    preparation = native(tmp_path, 'verification.prepare', {'task_id': task['id'], 'criterion_id': 'check', 'check_name': 'check'}, 'c4', provider)
    shell = {'session_id': 'native-fixture', 'tool_name': 'exec_command', 'tool_use_id': 'real-command', 'tool_input': preparation['native_action']['arguments']}
    process(tmp_path, provider, {**shell, 'hook_event_name': 'PreToolUse'})
    process(tmp_path, provider, {**shell, 'hook_event_name': 'PostToolUse', 'tool_response': {'exit_code': 0, 'output': '1'}})
    evidence = native(tmp_path, 'evidence.list', {'task_id': task['id']}, 'c5', provider)['items'][0]
    assert evidence['success'] is True
    task = native(tmp_path, 'criterion.satisfy', {'task_id': task['id'], 'criterion_id': 'check', 'evidence_ids': [evidence['id']], 'expected_revision': task['revision'], 'request_id': 'satisfy'}, 'c6', provider)
    task = native(tmp_path, 'task.complete', {'task_id': task['id'], 'expected_revision': task['revision'], 'request_id': 'complete'}, 'c7', provider)
    assert task['status'] == 'completed'
    assert process(tmp_path, provider, {'hook_event_name': 'Stop', 'session_id': 'native-fixture'}) == {}


def test_json_looking_stdout_cannot_attest_exit_code(tmp_path):
    source = intake(tmp_path)
    task = native(tmp_path, 'task.create', {'source_id': source, 'goal': 'Check', 'criteria': [{'id': 'c', 'description': 'Check'}], 'request_id': 'create'}, '1')
    native(tmp_path, 'task.activate', {'task_id': task['id'], 'expected_revision': 0, 'request_id': 'start'}, '2')
    native(tmp_path, 'lease.acquire', {'resource': str(tmp_path), 'request_id': 'lease'}, '3')
    (tmp_path / '.neurath/project.json').write_text(json.dumps({'verification': {'check': {'argv': ['echo', 'fake']}}}))
    check = native(tmp_path, 'verification.prepare', {'task_id': task['id'], 'criterion_id': 'c', 'check_name': 'check'}, '4')
    event = {'session_id': 'native-fixture', 'tool_name': 'exec_command', 'tool_use_id': 'shell', 'tool_input': check['native_action']['arguments']}
    process(tmp_path, 'codex', {**event, 'hook_event_name': 'PreToolUse'})
    process(tmp_path, 'codex', {**event, 'hook_event_name': 'PostToolUse', 'tool_response': {'output': '{"exit_code":0}'}})
    evidence = native(tmp_path, 'evidence.list', {'task_id': task['id']}, '5')['items'][0]
    assert evidence['success'] is False


def test_actual_stdio_process_is_named_neurath(tmp_path):
    run = subprocess.run([sys.executable, '-m', 'neurath', '--root', str(tmp_path), 'mcp', '--provider', 'codex'], input=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})+'\n', text=True, capture_output=True, check=True)
    assert json.loads(run.stdout)['result']['serverInfo']['name'] == 'neurath'


def test_recovery_rejects_symlink(tmp_path):
    (tmp_path / '.neurath').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError):
        bypass(tmp_path, True)


@pytest.mark.parametrize('value', [True, {}, [], {'malformed': 'id'}])
def test_json_rpc_invalid_request_ids_are_rejected(tmp_path, value):
    result = respond(tmp_path, 'codex', {'jsonrpc': '2.0', 'id': value, 'method': 'ping'})
    assert result['error']['code'] == -32600
    assert result['id'] is None


@pytest.mark.parametrize('method', [None, 42, {}, ''])
def test_json_rpc_invalid_methods_are_rejected(tmp_path, method):
    result = respond(tmp_path, 'codex', {'jsonrpc': '2.0', 'id': 1, 'method': method})
    assert result['error']['code'] == -32600


def test_initialize_negotiates_supported_protocol(tmp_path):
    result = respond(tmp_path, 'codex', {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': 'unsupported-future'}})
    assert result['result']['protocolVersion'] == '2025-06-18'


def test_recovery_and_discovery_do_not_modify_future_database(tmp_path):
    from neurath.transport.runtime import database
    store = database(tmp_path)
    with store.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num='9999'")
    store.close()
    path = tmp_path / '.neurath/local/neurath.sqlite3'
    before = path.read_bytes()
    assert request(tmp_path, 'harness_bypass', {'enabled': True})['isError'] is False
    assert process(tmp_path, 'codex', {'hook_event_name': 'Stop'}) == {}
    assert request(tmp_path, 'harness_bypass', {'enabled': False})['isError'] is False
    assert respond(tmp_path, 'codex', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools']
    assert path.read_bytes() == before


def test_repeated_stop_preserves_obligation_without_infinite_continuation(tmp_path):
    source = intake(tmp_path)
    task = native(tmp_path, 'task.create', {'source_id': source, 'goal': 'Recover failed check', 'criteria': [{'id': 'c', 'description': 'Actual success'}], 'request_id': 'create'}, 'stop-create')
    event = {'hook_event_name': 'Stop', 'session_id': 'native-fixture'}
    assert process(tmp_path, 'codex', event)['decision'] == 'block'
    repeated = process(tmp_path, 'codex', {**event, 'stop_hook_active': True})
    assert 'decision' not in repeated
    assert task['id'] in repeated['systemMessage']
    current = native(tmp_path, 'task.get', {'task_id': task['id']}, 'stop-read')
    assert current['status'] == 'pending'
    assert current['revision'] == 0
