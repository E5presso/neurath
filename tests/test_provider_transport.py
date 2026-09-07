"""Exercise the actual pipe transport against bounded hostile/partial servers."""

import json
import sys

import pytest

from neurath.providers.claude import normalize_listing
from neurath.providers.stdio import CodexStdio


@pytest.fixture
def server(tmp_path, monkeypatch):
    from neurath.providers import stdio

    def launch(body):
        script = tmp_path / "codex"
        script.write_text(f"#!{sys.executable}\n" + "import sys, json, time\n" + body)
        script.chmod(0o700)
        monkeypatch.setattr(stdio.shutil, "which", lambda _: str(script))
        return CodexStdio(tmp_path, timeout=3)
    return launch


def test_rpc_events_are_retained_and_unsupported_requests_never_grant_approval(server):
    body = '''
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    if request['method'] == 'check':
        print(json.dumps({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}}), flush=True)
        print(json.dumps({'id': 900, 'method': 'item/commandExecution/requestApproval', 'params': {}}), flush=True)
        response = json.loads(sys.stdin.readline())
        assert response['id'] == 900 and 'error' in response and 'result' not in response
    print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
'''
    with server(body) as host:
        host.request("check", {})
        event = host.event(lambda event: event.get("method") == "turn/completed", timeout=0.1)
        assert event["params"]["turn"]["status"] == "completed"
        process = host.process
    assert process.poll() is not None


def test_ambiguous_mutation_timeout_poisoned_connection_cannot_retry(server):
    body = '''
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
    elif request.get('method') == 'turn/start':
        time.sleep(10)
'''
    with server(body) as host:
        host.timeout = 0.2
        with pytest.raises(TimeoutError):
            host.request("turn/start", {})
        with pytest.raises(RuntimeError, match="uncertain"):
            host.request("turn/start", {})


def test_non_object_json_is_a_transport_error_and_child_is_reaped(server):
    body = '''
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
    elif request.get('method') == 'bad':
        print('[]', flush=True)
'''
    with server(body) as host:
        with pytest.raises(ValueError, match="object"):
            host.request("bad", {})
        process = host.process
    assert process.poll() is not None


def test_claude_native_session_job_and_waiting_state_are_separate(tmp_path):
    payload = [
        {"cwd": str(tmp_path), "kind": "background", "startedAt": 1,
         "id": "short-job", "sessionId": "full-native-uuid", "state": "blocked",
         "waitingFor": "permission prompt"},
        {"cwd": str(tmp_path.parent), "kind": "interactive", "startedAt": 1},
    ]
    rows = normalize_listing(json.dumps(payload), tmp_path)
    assert len(rows) == 1
    assert rows[0]["native_session"] == "full-native-uuid"
    assert rows[0]["job_id"] == "short-job"
    assert rows[0]["waiting_for"] == "permission prompt"
    assert rows[0]["policy"]["verification"] == "unobserved"


def test_long_normal_stream_keeps_completion_and_exact_interleaved_events(server):
    body = '''
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
    if request['method'] == 'stream':
        for index in range(1000):
            print(json.dumps({'method': 'item/agentMessage/delta', 'params': {'delta': str(index)}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {}}), flush=True)
'''
    with server(body) as host:
        host.request("stream", {})
        assert host.event(lambda e: e.get("method") == "turn/completed", timeout=3)
        assert not host._uncertain
        assert [host.event(lambda _: True)["params"]["delta"] for _ in range(1000)] == [str(i) for i in range(1000)]


def test_silent_event_poll_does_not_make_later_rpc_uncertain(server):
    body = '''
for line in sys.stdin:
    request = json.loads(line)
    if 'id' in request:
        print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
'''
    with server(body) as host:
        with pytest.raises(TimeoutError):
            host.event(lambda _: True, timeout=0.01)
        assert host.request("read", {}) == {}
        assert not host._uncertain
