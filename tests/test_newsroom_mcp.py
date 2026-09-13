"""The communication server speaks bounded stdio and exposes no arbitrary execution."""

import json
import subprocess
import sys

from neurath.agents.mcp import MAX_FRAME, response


def test_stdio_initialization_inventory_and_unbound_rejection(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "agent", "arguments": {"argv": ["newsroom", "headlines"]}}},
    ]
    from tests.test_mcp_concurrency import send, receive
    process = subprocess.Popen([sys.executable, "-I", "-m", "neurath.agents.mcp", "--root", str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    replies = []
    try:
        for request in requests:
            send(process, request)
            if "id" in request:
                reply = receive(process, timeout=5)
                assert reply is not None, "MCP request did not return before connection close"
                replies.append(reply)
        process.stdin.close()
        assert process.wait(timeout=5) == 0, process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()
        process.stderr.close()
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"memory_recall", "harness_bypass", "newsroom_publish"} <= names
    assert "verification_run" not in names
    assert "agent" not in names  # Saved calls below still reach their identity gate.
    assert replies[2]["result"]["isError"]
    assert "bound" in replies[2]["result"]["content"][0]["text"]


def test_oversized_frame_stops_without_dispatch(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = subprocess.run([sys.executable, "-I", "-m", "neurath.agents.mcp", "--root", str(tmp_path)],
        input=b" " * (MAX_FRAME + 1) + b"\n", capture_output=True, timeout=15)
    assert result.returncode == 1 and not result.stdout


def test_other_commands_are_unreachable(tmp_path):
    for argv in (["engine", "arbitrary"], ["delegate", "run"], ["sh", "-c", "echo bad"]):
        result = response(tmp_path, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "agent", "arguments": {"argv": argv}}})
        assert result["result"]["isError"]
