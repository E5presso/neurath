"""Real stdio transport/process tests with a simulated operation, not native admission proof."""
import json
import os
import select
import subprocess
import sys
import time

import pytest


@pytest.fixture
def server(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = tmp_path / "fixture_server.py"
    script.write_text('''
import os, time
from pathlib import Path
from neurath.agents import mcp
original = mcp.response
def simulated(root, request):
    if request.get("method") != "tools/call":
        return original(root, request)
    print("backend diagnostic", flush=True)
    if request["params"]["name"] == "verification_run":
        (Path(root) / ("started-" + str(request["id"]))).write_text(str(os.getpid()))
        while not (Path(root) / "release").exists():
            time.sleep(0.01)
    value = {"ok": True, "operation": request["params"]["name"], "result": {"observed": True}}
    return {"jsonrpc": "2.0", "id": request["id"], "result": {
        "structuredContent": value, "content": [], "isError": False}}
mcp.response = simulated
if __name__ == "__main__":
    raise SystemExit(mcp.main())
''')
    diagnostics = (tmp_path / "stderr.log").open("wb")
    process = subprocess.Popen([sys.executable, str(script), "--root", str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics, bufsize=0)
    try:
        yield tmp_path, process
    finally:
        (tmp_path / "release").touch()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        process.stdout.close()
        diagnostics.close()


def send(process, request):
    process.stdin.write((json.dumps(request) + "\n").encode())
    process.stdin.flush()


def call(process, identity, name):
    send(process, {"jsonrpc": "2.0", "id": identity, "method": "tools/call",
                   "params": {"name": name, "arguments": {}}})


def receive(process, timeout=3):
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        return None
    line = process.stdout.readline()
    return None if not line else json.loads(line)


def started(root, identity):
    marker = root / ("started-" + str(identity))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            value = marker.read_text()
        except FileNotFoundError:
            value = ""
        if value.isdecimal():
            return int(value)
        time.sleep(0.01)
    pytest.fail("simulated operation never started")


def test_long_mcp_call_does_not_block_message_or_ping(server):
    root, process = server
    call(process, 1, "verification_run")
    started(root, 1)
    call(process, 2, "collaboration_send")
    reply = receive(process)
    assert reply is not None and reply["id"] == 2, "message waited behind verification"
    send(process, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert receive(process)["id"] == 3
    (root / "release").touch()
    assert receive(process)["result"]["structuredContent"]["ok"] is True
    assert "backend diagnostic" in (root / "stderr.log").read_text()


def test_heavy_capacity_saturation_preserves_control_requests(server):
    root, process = server
    for identity in range(1, 5):
        call(process, identity, "verification_run")
    for identity in range(1, 5):
        started(root, identity)
    call(process, 5, "verification_run")
    refused = receive(process)
    assert refused is not None and refused["id"] == 5 and "error" in refused
    call(process, 6, "collaboration_send")
    message = receive(process)
    assert message is not None and message["id"] == 6 and "result" in message
    send(process, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert receive(process)["id"] == 7
    assert not (root / "started-5").exists()


def test_mcp_cancel_has_one_response_and_does_not_replay(server):
    root, process = server
    call(process, 1, "verification_run")
    worker = started(root, 1)
    send(process, {"jsonrpc": "2.0", "method": "notifications/cancelled",
                   "params": {"requestId": 1}})
    reply = receive(process, timeout=5)
    assert reply is not None and reply["id"] == 1 and reply["error"]["code"] == -32800
    (root / "release").touch()
    assert receive(process, timeout=0.2) is None
    assert worker != process.pid
    with pytest.raises(ProcessLookupError):
        os.kill(worker, 0)


def test_mcp_eof_stops_owned_call_workers(server):
    root, process = server
    call(process, 1, "verification_run")
    worker = started(root, 1)
    process.stdin.close()
    process.wait(timeout=6)
    assert worker != process.pid
    with pytest.raises(ProcessLookupError):
        os.kill(worker, 0)
