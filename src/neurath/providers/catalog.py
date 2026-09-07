"""Transport support, distinct from installed versions or evaluator authority."""

from neurath.providers.contracts import UnsupportedOperation

OPERATIONS = ("create", "discover", "connect", "message", "status", "resume", "cancel", "peer")


def capabilities(provider, *, available_tools=()):
    """Tool names must come from the caller's current host inventory, not config.

    This catalog selects a route; it does not attest a session, permission or tool.
    Neither a binary version nor a desktop installation proves a live capability.
    """
    if provider not in ("codex", "claude-code"):
        raise UnsupportedOperation("unsupported provider")
    tools = set(available_tools)

    def row(transport, supported, condition, *, external=True, observed=()):
        return {"provider": provider, "transport": transport, "external": external,
                "operations": {op: {"implemented": op in supported,
                                    "available": op in supported and op in observed,
                                    "reason": condition if op in supported else
                                    "not implemented by this transport"} for op in OPERATIONS},
                "authority": "agent-report"}

    result = [row("cli", {"create", "status", "resume", "cancel"},
                  "installed authenticated CLI; only owned bounded runs, no live attach")]
    if provider == "codex":
        result += [row("codex-app-server", set(OPERATIONS) - {"peer"},
                       "explicit connected JSON-RPC transport; owned sessions; applied policy readback")]
        names = {"create": "create_thread", "discover": "list_threads", "connect": "read_thread",
                 "message": "send_message_to_thread", "status": "read_thread",
                 "peer": "send_message_to_thread"}
        observed = {op for op, name in names.items() if name in tools}
        result += [row("codex-app", set(names),
                       "requires the current app tool; session creation policy cannot be set or verified here",
                       external=False, observed=observed)]
    else:
        names = {"discover": "ListAgents", "message": "SendMessage", "peer": "SendMessage"}
        observed = {op for op, name in names.items() if name in tools}
        result += [row("claude-native", set(names),
                       "current host tool only; discover exact peer address; inbound may hold or refuse",
                       external=False, observed=observed),
                   row("claude-background", {"discover", "status"},
                       "claude agents --json; short job ID differs from native session UUID; policy unobserved"),
                   row("claude-desktop", set(),
                       "no documented external Desktop session-control API implemented", external=False),
                   row("claude-agent-sdk", set(),
                       "official SDK exists but is not installed or implemented by this adapter")]
    return result
