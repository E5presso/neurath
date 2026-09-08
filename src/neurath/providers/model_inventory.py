"""Read metadata from native provider connections; never starts a model turn.

Codex model/list: https://learn.chatgpt.com/docs/app-server
Claude get_server_info: official claude-agent-sdk-python client interface.
The native catalog is availability evidence, not measured model quality or price.
"""
import time


class InventoryError(ValueError):
    """Native response violates the inventory protocol."""



def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise InventoryError("invalid native model metadata")
    return value


def _strings(value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 100:
        raise InventoryError("invalid native model capabilities")
    return [_text(item) for item in value]


def _observation(provider, host, source, models):
    return {"provider": provider, "host": _text(host), "source": source,
            "observed_at": time.time(), "status": "observed" if models else "unavailable",
            "models": models, "default_model": None,
            "default_source": None, "default_observation_revision": None,
            "reason": None if models else "native-model-inventory-unavailable"}


def codex_inventory(transport, *, host):
    """Read all visible model pages on an authorized app-server connection.

    isDefault is the recommended picker default, NOT proof of the target's
    configured default. Missing capability metadata stays unknown.
    """
    models, seen_models, cursors = [], set(), set()
    cursor = None
    for _ in range(100):
        params = {"limit": 100, "includeHidden": False}
        if cursor is not None:
            params["cursor"] = cursor
        response = transport.request("model/list", params)
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise InventoryError("invalid native model list")
        for entry in response["data"]:
            if not isinstance(entry, dict):
                raise InventoryError("invalid native model entry")
            model = _text(entry.get("model"))
            if model in seen_models:
                raise InventoryError("duplicate native model identity")
            seen_models.add(model)
            efforts = entry.get("supportedReasoningEfforts")
            if efforts is not None:
                if not isinstance(efforts, list) or any(not isinstance(e, dict) for e in efforts):
                    raise InventoryError("invalid native reasoning efforts")
                efforts = _strings([e.get("reasoningEffort") for e in efforts])
            models.append({"id": model, "display_name": entry.get("displayName"),
                           "description": entry.get("description"),
                           "reasoning_efforts": efforts,
                           "input_modalities": _strings(entry.get("inputModalities")),
                           "recommended": entry.get("isDefault") is True,
                           "cost": None, "latency": None})
            if len(models) > 10000:
                raise InventoryError("native model inventory exceeds limit")
        cursor = response.get("nextCursor")
        if cursor is None:
            return _observation("codex", host, "codex-app-server:model/list", models)
        _text(cursor)
        if cursor in cursors:
            raise InventoryError("native model pagination repeated cursor")
        cursors.add(cursor)
    raise InventoryError("native model pagination exceeds limit")


async def claude_inventory(client, *, host):
    """Inspect only an existing owned SDK client's initialization metadata.

    A client that does not expose model metadata yields unavailable. Never opens
    another session, calls query, changes permission mode, or invents model IDs.
    """
    if client is None:
        return _observation("claude-code", host, "claude-agent-sdk:get_server_info", [])
    info = await client.get_server_info()
    entries = info.get("models") if isinstance(info, dict) else None
    if entries is None:
        return _observation("claude-code", host, "claude-agent-sdk:get_server_info", [])
    if not isinstance(entries, list) or len(entries) > 10000:
        raise InventoryError("invalid native model list")
    models, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise InventoryError("invalid native model entry")
        model = _text(entry.get("value"))
        if model in seen:
            raise InventoryError("duplicate native model identity")
        seen.add(model)
        models.append({"id": model, "display_name": entry.get("displayName"),
                       "description": entry.get("description"), "reasoning_efforts": None,
                       "input_modalities": None, "recommended": None,
                       "cost": None, "latency": None})
    return _observation("claude-code", host, "claude-agent-sdk:get_server_info", models)

async def fresh_claude_inventory(target, *, host, timeout=30, client_factory=None):
    """Use the official SDK metadata handshake only; never query a model.

    This opens a short-lived control connection, not a separate LLM receiver or
    task session. Existing user/project/local settings and hooks remain enabled.
    The caller must enforce its native execution policy before entering here.
    """
    import asyncio
    import math
    import shutil
    from pathlib import Path
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ValueError("invalid metadata timeout")
    async def deny(_name,_input,_context):
        return PermissionResultDeny(message="Metadata discovery cannot execute model tools.")
    options=ClaudeAgentOptions(cwd=str(Path(target).resolve()),
                               setting_sources=["user","project","local"],
                               cli_path=shutil.which("claude"), can_use_tool=deny)
    client=(client_factory or ClaudeSDKClient)(options=options)
    try:
        # Same task owns connect/disconnect; wait_for would break SDK task scopes.
        async with asyncio.timeout(timeout):
            await client.connect()
            return await claude_inventory(client,host=host)
    finally:
        async with asyncio.timeout(timeout):
            await client.disconnect()

def claude_inventory_process(target, *, host="local", timeout=30):
    """Isolate SDK startup from the MCP process's caller identity environment."""
    import json
    import math
    import subprocess
    import sys
    from pathlib import Path
    from neurath.agents.runner import child_environment
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise InventoryError("invalid metadata timeout")
    result=subprocess.run(
        [sys.executable,"-I",str(Path(__file__).resolve()),"--claude-metadata",
         str(Path(target).resolve()),str(timeout)],
        cwd=target,env=child_environment(),stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout*2+5)
    if result.returncode or len(result.stdout.encode())>1048576:
        raise InventoryError("Claude metadata handshake failed or exceeded its output limit")
    value=json.loads(result.stdout)
    if not isinstance(value,dict) or value.get("provider")!="claude-code":
        raise InventoryError("invalid Claude metadata worker response")
    value["host"]=host
    return value


if __name__ == "__main__":
    import asyncio
    import json
    import sys
    if len(sys.argv)!=4 or sys.argv[1]!="--claude-metadata":
        raise SystemExit("private metadata worker arguments required")
    try:
        print(json.dumps(asyncio.run(fresh_claude_inventory(
            sys.argv[2],host="local",timeout=float(sys.argv[3])))))
    except Exception as error:
        print(json.dumps({"error":type(error).__name__}))
        raise SystemExit(1) from None
