"""Real pipe/socket/database path; fixture provider, not a native model claim."""

import subprocess
import sys
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import AgentIdentity, MessageStore
from neurath.providers.codex import CodexSessions
from neurath.providers.stdio import CodexStdio
from neurath.providers.supervision import SessionInbox


def test_committed_child_result_wakes_owned_idle_issuer_and_waits_for_ack(tmp_path, monkeypatch):
    from neurath.providers import stdio

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = tmp_path / "provider"
    script.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
created = False
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method, params = request['method'], request.get('params', {})
    thread = {'id': 'issuer', 'projectId': 'saved', 'cwd': os.getcwd(), 'status': {'type': 'idle'}}
    if method == 'initialize':
        result = {}
    elif method == 'project/list':
        result = {'data': [{'id': 'saved', 'roots': [{'path': os.getcwd()}]}]}
    elif method == 'thread/start':
        assert not created
        created = True
        result = {'thread': thread, 'cwd': os.getcwd(), 'model': 'fixture',
                  'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly', 'networkAccess': False}}
    elif method == 'thread/read':
        assert params['threadId'] == 'issuer'
        result = {'thread': thread}
    elif method == 'turn/start':
        assert params['threadId'] == 'issuer' and 'peer-report notification' in params['input'][0]['text']
        result = {'turn': {'id': 'reply-turn'}}
        print(json.dumps({'method': 'turn/started', 'params': {'threadId': 'issuer',
              'turn': {'id': 'reply-turn', 'status': 'inProgress'}}}), flush=True)
    else:
        raise AssertionError(method)
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
    if method == 'turn/start':
        print(json.dumps({'method': 'turn/completed', 'params': {'threadId': 'issuer',
              'turn': {'id': 'reply-turn', 'status': 'completed'}}}), flush=True)
''')
    script.chmod(0o700)
    monkeypatch.setattr(stdio.shutil, "which", lambda _: str(script))
    store = MessageStore(tmp_path)
    for host, name in (("codex", "issuer"), ("claude-code", "child")):
        store.register(AgentIdentity(host, name, f"{host}:session:{name}"))
    with CodexStdio(tmp_path, timeout=3) as host:
        sessions = CodexSessions(host)
        session = sessions.create(tmp_path)
        inbox = SessionInbox(sessions, session).start()
        try:
            tasks = TaskLifecycle(store)
            task = tasks.bind("codex:issuer", "claude-code:child", key="child", transport="peer-assignment")
            assert inbox.pending()
            entered = threading.Event()
            original = host._next
            def waiting(*args, **kwargs):
                entered.set()
                return original(*args, **kwargs)
            host._next = waiting
            observed = []
            reader = threading.Thread(target=lambda: observed.append(
                host.event(lambda event: event.get("method") == "turn/completed", timeout=3)))
            reader.start()
            assert entered.wait(1)
            report = tasks.emit("claude-code:child", task["id"], "completed", key="done")["message"]
            reader.join(4)
            assert not reader.is_alive()
            assert observed[0]["params"]["turn"]["id"] == inbox.expected_turn("original") == "reply-turn"
            assert inbox.pending()  # Submission and native completion are not acknowledgement.
            with inbox.service.changed:
                inbox.service.changed.wait_for(lambda: store.message("codex:issuer", report["id"])["status"] == "submitted", 2)
            assert store.message("codex:issuer", report["id"])["status"] == "submitted"
            assert store.forward("claude-code:child", report["id"])["status"] == "submitted"
            store.acknowledge("codex:issuer", report["id"])
            assert not inbox.pending()
        finally:
            inbox.close()


def test_rollback_never_notifies_and_transport_failure_keeps_committed_message(tmp_path, monkeypatch):
    from neurath.agents import delivery

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = MessageStore(tmp_path)
    for name in ("issuer", "child"):
        store.register(AgentIdentity("codex", name, f"codex:session:{name}"))
    calls = []
    def unavailable(store, message_id):
        calls.append(store.message("codex:issuer", message_id))
        raise OSError("transport unavailable")
    monkeypatch.setattr(delivery, "dispatch", unavailable)
    with pytest.raises(RuntimeError):
        with store.connection() as db:
            store._send(db, "codex:child", "codex:issuer", "Uncommitted", key="rollback")
            raise RuntimeError("rollback")
    assert calls == [] and store.inbox("codex:issuer") == []
    message = store.send("codex:child", "codex:issuer", "Committed", key="committed")
    assert calls[0]["id"] == message["id"]
    assert store.inbox("codex:issuer")[0]["status"] == "queued"


def _isolated_inbox(deliver):
    inbox = object.__new__(SessionInbox)
    inbox._lock = threading.RLock()
    inbox._closing = False
    inbox.turn = None
    inbox.address = "codex:issuer"
    inbox.deliver = deliver
    db = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: None))
    inbox.store = SimpleNamespace(connection=lambda: nullcontext(db))
    inbox.service = SimpleNamespace(close=lambda: None)
    return inbox


def test_inflight_notification_makes_previous_completion_stale():
    entered, release = threading.Event(), threading.Event()
    def deliver(message_id):
        entered.set()
        assert release.wait(3)
        return {"delivery": "submitted", "native_turn": "report"}
    inbox = _isolated_inbox(deliver)
    receiver = threading.Thread(target=inbox._notify, args=("a" * 64,))
    receiver.start()
    assert entered.wait(1)
    observed = []
    def complete():
        observed.append(inbox.complete_turn("original", "original", successful=True))
    completer = threading.Thread(target=complete)
    completer.start()
    release.set()
    receiver.join(3)
    completer.join(3)
    assert not receiver.is_alive() and not completer.is_alive()
    assert observed == ["stale"]
    assert inbox.complete_turn("report", "original", successful=True) == "terminal"


def test_terminal_decision_fences_notifications_before_socket_shutdown():
    calls = []
    inbox = _isolated_inbox(lambda identifier: calls.append(identifier) or {
        "delivery": "submitted", "native_turn": "late"})
    assert inbox.complete_turn("original", "original", successful=True) == "terminal"
    assert inbox._notify("b" * 64)["delivery"] == "unavailable"
    assert calls == []


def test_pending_obligations_keep_notification_route_open():
    inbox = _isolated_inbox(lambda identifier: {"delivery": "submitted", "native_turn": "report"})
    inbox.pending = lambda: True
    assert inbox.complete_turn("original", "original", successful=True) == "waiting"
    assert inbox._notify("c" * 64)["native_turn"] == "report"
