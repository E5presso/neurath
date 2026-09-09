"""Outbox events start/steer the exact existing owner without session polling."""

from dataclasses import replace
import sys

import pytest

from neurath.providers.codex import CodexSessions
from neurath.providers.codex_delivery import CodexDelivery, notification
from neurath.providers.stdio import RpcRejected


MESSAGE = "a" * 64


class Host:
    def __init__(self):
        self.calls = []
        self.thread = {"id": "issuer", "projectId": "saved", "cwd": "/work", "status": {"type": "idle"}}
        self.failure = None

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "project/list":
            return {"data": [{"id": "saved", "roots": [{"path": "/work"}]}]}
        if method == "thread/start":
            return {"thread": self.thread.copy(), "cwd": "/work", "model": "host-model",
                    "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False}}
        if method == "thread/read":
            return {"thread": self.thread.copy()}
        if self.failure:
            raise self.failure
        if method == "turn/start":
            return {"turn": {"id": "report-turn"}}
        if method == "turn/steer":
            return {"turnId": params["expectedTurnId"]}
        raise AssertionError(method)


def owner():
    host = Host()
    sessions = CodexSessions(host)
    session = sessions.create("/work")
    host.calls.clear()
    return host, sessions, session, CodexDelivery(sessions, session)


def test_committed_message_wakes_same_idle_issuer_and_retries_same_key():
    host, _, _, deliver = owner()
    result = deliver(MESSAGE)
    assert result["delivery"] == "submitted"
    assert result["native_session"] == "issuer"
    assert result["native_turn"] == "report-turn"
    assert [method for method, _ in host.calls] == ["thread/read", "turn/start"]
    assert host.calls[-1][1] == {"threadId": "issuer", "input": [{"type": "text", "text": notification(MESSAGE)}],
                               "sandboxPolicy": {"type": "readOnly", "networkAccess": False}}
    assert deliver(MESSAGE) == result
    assert len(host.calls) == 4


def test_idle_delivery_preserves_owned_session_reasoning_settings():
    host, _, session, deliver = owner()
    session.policy["requested"].update({
        "collaboration_mode": "default",
        "reasoning_effort": "high",
    })

    result = deliver(MESSAGE)

    assert result["delivery"] == "submitted"
    params = host.calls[-1][1]
    assert params["effort"] == "high"
    assert params["collaborationMode"] == {
        "mode": "default",
        "settings": {
            "model": "host-model",
            "developer_instructions": None,
            "reasoning_effort": "high",
        },
    }
    assert params["sandboxPolicy"] == {
        "type": "readOnly",
        "networkAccess": False,
    }


def test_active_issuer_uses_observed_turn_precondition():
    host, _, _, deliver = owner()
    host.thread.update(status={"type": "active"}, turns=[{"id": "current", "status": "inProgress"}])
    assert deliver(MESSAGE)["native_turn"] == "current"
    assert host.calls[-1][0] == "turn/steer"
    assert host.calls[-1][1]["expectedTurnId"] == "current"


@pytest.mark.parametrize("flag", ["waitingOnApproval", "waitingOnUserInput"])
def test_waiting_does_not_approve_or_interrupt_and_can_receive_later_event(flag):
    host, _, _, deliver = owner()
    host.thread.update(status={"type": "active", "activeFlags": [flag]},
                       turns=[{"id": "current", "status": "inProgress"}])
    assert deliver(MESSAGE)["delivery"] == "needs-input"
    assert [method for method, _ in host.calls] == ["thread/read"]
    host.thread.update(status={"type": "idle"}, turns=[])
    assert deliver(MESSAGE)["delivery"] == "submitted"


def test_unknown_active_turn_cannot_start_another_turn():
    host, _, _, deliver = owner()
    host.thread["status"] = {"type": "active"}
    with pytest.raises(ValueError, match="unobserved"):
        deliver(MESSAGE)
    assert [method for method, _ in host.calls] == ["thread/read"]


def test_foreign_or_reconstructed_handle_cannot_gain_ownership():
    host, sessions, session, _ = owner()
    for adapter, handle in [(CodexSessions(host), session), (sessions, replace(session))]:
        with pytest.raises(ValueError, match="owned"):
            CodexDelivery(adapter, handle)
    assert host.calls == []


def test_changed_worktree_is_refused_without_a_native_mutation():
    host, _, _, deliver = owner()
    host.thread["cwd"] = "/other"
    with pytest.raises(ValueError, match="workspace changed"):
        deliver(MESSAGE)
    assert [method for method, _ in host.calls] == ["thread/read"]


def test_ambiguous_rpc_can_retry_same_key_on_existing_owner():
    host, _, _, deliver = owner()
    host.failure = TimeoutError("lost native response")
    with pytest.raises(TimeoutError):
        deliver(MESSAGE)
    host.failure = None
    assert deliver(MESSAGE)["delivery"] == "submitted"
    assert [method for method, _ in host.calls] == ["thread/read", "turn/start", "thread/read", "turn/start"]


@pytest.mark.parametrize("message", ["no active turn to steer",
    "expected active turn id `current` but found `next`"])
def test_explicit_turn_precondition_rejection_can_deliver_on_next_event(message):
    host, _, _, deliver = owner()
    host.thread.update(status={"type": "active"}, turns=[{"id": "current", "status": "inProgress"}])
    host.failure = RpcRejected("turn/steer", {"code": -32600, "message": message})
    assert deliver(MESSAGE)["delivery"] == "unavailable"
    assert [method for method, _ in host.calls] == ["thread/read", "turn/steer"]
    host.failure = None
    host.thread.update(status={"type": "idle"}, turns=[])
    assert deliver(MESSAGE)["delivery"] == "submitted"


def test_unrelated_native_rejection_remains_an_error_on_each_attempt():
    host, _, _, deliver = owner()
    host.failure = RpcRejected("turn/start", {"code": -32600, "message": "no active turn to steer"})
    with pytest.raises(RpcRejected):
        deliver(MESSAGE)
    with pytest.raises(RpcRejected):
        deliver(MESSAGE)


@pytest.mark.parametrize("message", ["", "a" * 63, "a" * 65, "a; execute arbitrary code", None])
def test_locators_do_not_allow_instruction_or_shell_injection(message):
    host, _, _, deliver = owner()
    with pytest.raises(ValueError, match="message ID"):
        deliver(message)
    assert host.calls == []


def test_existing_pipe_connection_receives_start_and_completion_events(tmp_path, monkeypatch):
    """Real transport/process, fixture provider; this is not native model proof."""
    from neurath.providers import stdio

    server = tmp_path / "codex-fixture"
    server.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
created = False
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    params = request.get('params', {})
    thread = {'id': 'owned-issuer', 'projectId': 'saved', 'cwd': os.getcwd(), 'status': {'type': 'idle'}}
    if method == 'initialize':
        result = {}
    elif method == 'project/list':
        result = {'data': [{'id': 'saved', 'roots': [{'path': os.getcwd()}]}]}
    elif method == 'thread/start':
        assert not created
        created = True
        result = {'thread': thread, 'cwd': os.getcwd(), 'model': 'fixture-model',
                  'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly', 'networkAccess': False}}
    elif method == 'thread/read':
        assert created and params['threadId'] == 'owned-issuer'
        result = {'thread': thread}
    elif method == 'turn/start':
        assert created and params['threadId'] == 'owned-issuer'
        assert 'peer-report notification' in params['input'][0]['text']
        result = {'turn': {'id': 'notification-turn'}}
        print(json.dumps({'method': 'turn/started', 'params': {
            'threadId': 'owned-issuer', 'turn': {'id': 'notification-turn', 'status': 'inProgress'}}}), flush=True)
    else:
        raise AssertionError(method)
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
    if method == 'turn/start':
        print(json.dumps({'method': 'turn/completed', 'params': {
            'threadId': 'owned-issuer', 'turn': {'id': 'notification-turn', 'status': 'completed'}}}), flush=True)
''')
    server.chmod(0o700)
    monkeypatch.setattr(stdio.shutil, "which", lambda _: str(server))
    with stdio.CodexStdio(tmp_path, timeout=3) as host:
        sessions = CodexSessions(host)
        session = sessions.create(tmp_path)
        deliver = CodexDelivery(sessions, session)
        receipt = deliver(MESSAGE)
        assert receipt["delivery"] == "submitted"
        start = host.event(lambda e: e.get("method") == "turn/started", timeout=3)
        done = host.event(lambda e: e.get("method") == "turn/completed", timeout=3)
        assert start["params"]["threadId"] == done["params"]["threadId"] == session.native_session
        assert done["params"]["turn"] == {"id": receipt["native_turn"], "status": "completed"}
        process = host.process
    assert process.returncode == 0
