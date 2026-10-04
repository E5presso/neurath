"""New-core MCP transport; no old runtime, agent or hook implementation imports."""

import argparse
import json
import sqlite3
import subprocess
import sys

from neurath.core.commands import COMMANDS
from neurath.core.domain import CoreError
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Core
from neurath.core.tool_schema import definitions

INSTRUCTIONS = (
    "Use the native-bound task tools for work state and native host tools for edits and checks. "
    "Start the applicable skill on the task; its phases cannot be skipped. Normal completion requires "
    "every owned user task to be complete. A failed attempt does not cancel the task. "
    "Read state and report blockers without acquiring a writer lease. Choose subagent, session or "
    "cross-provider delegation according to actual needs. Native input provenance is not proof of human approval."
)


def server_config(root, provider):
    """Install a provider-specific adapter without supplying permission overrides."""
    import subprocess
    from pathlib import Path

    from neurath.core.domain import require
    from neurath.project_paths import control_root

    require(provider in {"codex", "claude-code"}, "provider")
    try:
        root = control_root(root)
    except subprocess.CalledProcessError:
        root = Path(root).resolve()
    return {
        "command": sys.executable,
        "args": [
            "-I",
            "-m",
            "neurath.core.mcp",
            "--root",
            str(Path(root).resolve()),
            "--provider",
            provider,
        ],
    }


def response(adapter, request):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid request"},
        }
    if "id" not in request:
        return None
    envelope = {"jsonrpc": "2.0", "id": request["id"]}
    method, params = request.get("method"), request.get("params", {})
    if not isinstance(params, dict):
        return {**envelope, "error": {"code": -32602, "message": "Invalid params"}}
    if method == "initialize":
        versions = ("2025-11-25", "2025-06-18", "2024-11-05")
        result = {
            "protocolVersion": params.get("protocolVersion")
            if params.get("protocolVersion") in versions
            else versions[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "neurath_collaboration", "version": "2"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": definitions()}
    elif method == "tools/call" and params.get("name") in COMMANDS:
        name = params["name"]
        try:
            value = adapter.call(name, params.get("arguments", {}))
            result = {
                "content": [{"type": "text", "text": f"{name}: ok"}],
                "structuredContent": {"ok": True, "operation": name, "result": value},
                "isError": False,
            }
        except CoreError as error:
            result = {
                "content": [{"type": "text", "text": error.code}],
                "structuredContent": {
                    "ok": False,
                    "operation": name,
                    "error": {"code": error.code, "details": error.details},
                },
                "isError": True,
            }
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            sqlite3.Error,
            subprocess.SubprocessError,
        ) as error:
            from neurath.redaction import clean

            result = {
                "content": [{"type": "text", "text": clean(str(error))}],
                "structuredContent": {
                    "ok": False,
                    "operation": name,
                    "error": {"code": "operation-failed", "message": clean(str(error))},
                },
                "isError": True,
            }
    else:
        return {**envelope, "error": {"code": -32601, "message": "Method or tool not found"}}
    return {**envelope, "result": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--provider", choices=("codex", "claude-code"), required=True)
    args = parser.parse_args()
    import os

    from neurath import __version__
    from neurath.resources import distribution_id

    core = Core(args.root)
    core.runtime_info = {
        "protocol": 2,
        "version": __version__,
        "distribution": distribution_id(),
        "process_id": os.getpid(),
        "provider": args.provider,
        "observed_at": "mcp-process-start",
    }
    adapter = HookAdapter(core, args.provider)
    for line in sys.stdin:
        try:
            if len(line.encode()) > 262144:
                raise ValueError("Request too large")
            result = response(adapter, json.loads(line))
        except ValueError, TypeError, KeyError:
            result = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Invalid request encoding"},
            }
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
