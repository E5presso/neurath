"""MCP JSON-RPC transport with database-independent discovery and recovery."""

import json
import sys

from neurath import __version__
from neurath.transport.recovery import bypass

RECOVERY = {
    "name": "harness_bypass",
    "description": "Inspect or suspend Neurath hooks during repair. This worktree-local switch preserves tasks and host permissions. Set enabled=false after repair.",
    "inputSchema": {
        "type": "object",
        "properties": {"enabled": {"type": "boolean"}},
        "required": [],
        "additionalProperties": False,
    },
}


def definitions():
    from neurath.application.catalog import CATALOG
    from neurath.transport.verification import TOOL

    result = [RECOVERY]
    for original in [*CATALOG.values(), TOOL]:
        tool = json.loads(json.dumps(original))
        tool.pop("mutation", None)
        tool["name"] = tool["name"].replace(".", "_")
        schema = tool["inputSchema"]
        schema["properties"]["_call_id"] = {"type": "string", "minLength": 1}
        schema.setdefault("required", []).append("_call_id")
        tool["description"] += " Supply a fresh _call_id to correlate this exact native invocation."
        result.append(tool)
    return result


def respond(root, provider, request):
    if (
        not isinstance(request, dict)
        or request.get("jsonrpc") != "2.0"
        or not isinstance(request.get("method"), str)
        or not request["method"]
        or (
            "id" in request
            and (
                isinstance(request["id"], bool)
                or not isinstance(request["id"], (str, int, float, type(None)))
            )
        )
    ):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid request"},
        }
    if "id" not in request:
        return None
    reply = {"jsonrpc": "2.0", "id": request["id"]}
    method, params = request.get("method"), request.get("params", {})
    if not isinstance(params, dict):
        return {**reply, "error": {"code": -32602, "message": "Invalid parameters"}}
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "neurath", "version": __version__},
            "instructions": "Retain the user goal and unfinished work. Native hooks bind identity. Host tools perform edits and checks. Use harness_bypass to recover storage failures.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": definitions()}
    elif method == "tools/call":
        try:
            name, arguments = params.get("name"), params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object")
            if name == "harness_bypass":
                if set(arguments) - {"enabled"} or (
                    "enabled" in arguments and type(arguments["enabled"]) is not bool
                ):
                    raise ValueError("Only an optional boolean enabled is accepted")
                value = bypass(root, arguments.get("enabled"))
            else:
                from neurath.transport.binding import invoke

                value = invoke(root, provider, name, arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                "structuredContent": {"ok": True, "result": value},
                "isError": False,
            }
        except Exception as error:
            result = {
                "content": [{"type": "text", "text": str(error)}],
                "structuredContent": {
                    "ok": False,
                    "error": type(error).__name__,
                    "message": str(error),
                },
                "isError": True,
            }
    else:
        return {**reply, "error": {"code": -32601, "message": "Method not found"}}
    return {**reply, "result": result}


def serve(root, provider):
    for line in sys.stdin:
        try:
            if len(line.encode()) > 1048576:
                raise ValueError("Request exceeds limit")
            request = json.loads(line)
            result = respond(root, provider, request)
        except ValueError, TypeError:
            result = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Invalid JSON"},
            }
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)
