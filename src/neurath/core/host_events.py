"""Small native event translations; no host policy or progress state lives here.

Native permissions and arbitrary command semantics belong to the host. This
module only translates identity, completion and explicit editor destinations.
"""

from pathlib import Path

from neurath.core.commands import Context
from neurath.core.domain import require

READ_TOOLS = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "read_file",
        "view_image",
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "read_mcp_resource",
        "ToolSearch",
        "tool_search",
    }
)
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "apply_patch"})
SHELL_TOOLS = frozenset({"Bash", "exec_command", "shell", "shell_command"})


def context_from_event(provider, payload, receipt_id):
    require(provider in {"codex", "claude-code"}, "provider")
    session = payload.get("session_id")
    require(isinstance(session, str) and bool(session), "native-session-required")
    require(isinstance(receipt_id, str) and bool(receipt_id), "native-receipt-required")
    agent = payload.get("agent_id")
    require(agent is None or isinstance(agent, str) and bool(agent), "native-agent-required")
    actor = f"{provider}:agent:{agent}" if agent else f"{provider}:session:{session}"
    return Context(actor, session, receipt_id)


def stop_response(result):
    if result["allowed"]:
        return {}
    pending = ", ".join(dict.fromkeys(item["task_id"] for item in result["pending"]))
    return {
        "decision": "block",
        "reason": f"Unfinished work: {pending}. Continue the existing task; inspect task_list for its current phase and obligations.",
    }


def write_targets(name, values, cwd):
    """Resolve explicit native write destinations before checking checkout leases."""
    paths = []
    if name in {"Write", "Edit", "MultiEdit"}:
        require(isinstance(values.get("file_path"), str), "write-target-required")
        paths.append(values["file_path"])
    elif name == "apply_patch":
        patch = values.get("command", values.get("patch", ""))
        require(isinstance(patch, str), "write-target-required")
        for line in patch.splitlines():
            for marker in (
                "*** Add File: ",
                "*** Update File: ",
                "*** Delete File: ",
                "*** Move to: ",
            ):
                if line.startswith(marker):
                    paths.append(line[len(marker) :])
        require(bool(paths), "write-target-required")
    else:
        paths.append(cwd)
    result = []
    for raw in paths:
        require(isinstance(raw, str) and bool(raw), "write-target-required")
        path = Path(raw)
        if not path.is_absolute():
            require(isinstance(cwd, str) and bool(cwd), "write-target-required")
            path = Path(cwd) / path
        path = path.resolve()
        while not path.exists() and path.parent != path:
            path = path.parent
        if path.is_file():
            path = path.parent
        result.append(path)
    return tuple(dict.fromkeys(result))
