"""Capture validated host events and deliver project recall to every root session."""

import hashlib
import json
from pathlib import Path

from neurath.memory.store import ProjectMemory, canonical


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _last_assistant(path):
    # Host transcripts can be large. Only complete recent records are inspected;
    # reasoning/thinking channels and tool output are never treated as a summary.
    with Path(path).open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 1024 * 1024))
        if size > 1024 * 1024:
            stream.readline()
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    answer = ""
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = (
            event.get("payload", {})
            if event.get("type") == "response_item"
            else event.get("message", {})
        )
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        if item.get("channel") not in (None, "final", "commentary"):
            continue
        content = item.get("content", [])
        if isinstance(content, list):
            text = "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") in ("text", "output_text")
            )
            if text.strip():
                answer = text[-12000:]
    return answer


def tool_result(payload):
    # Only host envelope metadata is usable here. JSON printed by a command is
    # application output, even when it happens to contain an exit_code field.
    for key in ("exit_code", "returncode"):
        if type(payload.get(key)) is int:
            return payload[key]
    if payload.get("hook_event_name") in ("PostToolUseFailure", "PermissionDenied"):
        return 1
    return None


def project_event(root, host, payload, output):
    from neurath.hosts.identity import _state, snapshot

    session = payload.get("session_id")
    if not session or payload.get("agent_id"):
        return output
    state = _state(root, session)
    memory = ProjectMemory(root)
    from neurath.memory.transcript import synchronize

    synchronize(memory, root, host, session, snapshot(root, session))
    event = payload["hook_event_name"]
    query = payload.get("prompt", "")
    if event == "UserPromptSubmit" and isinstance(query, str) and query.strip():
        turn = state.foreground_turns.get(state.session.root_actor_id)
        generation = turn.generation if turn is not None else 0
        # A native turn may receive several steering messages. The turn alone
        # identifies a conversation interval, not an immutable prompt receipt.
        revision = turn.revision if turn is not None else 0
        source = f"prompt:{generation}:{revision}:{_digest(query)}"
        memory.record(host, session, source, "prompt", query[:16000])
    if event in ("PostToolUse", "PostToolUseFailure", "PermissionDenied") and payload.get(
        "tool_use_id"
    ):
        inputs = payload.get("tool_input", {})
        command = inputs.get("command", inputs.get("cmd")) if isinstance(inputs, dict) else None
        if isinstance(command, str):
            # Claude's wrapper is an implementation detail, not the user's command.
            observed = snapshot(root, session).get("tools", {}).get(payload["tool_use_id"])
            if observed:
                command = observed.get("command", command)
            memory.record(
                host,
                session,
                f"tool:{event}:{payload['tool_use_id']}",
                "tool",
                command[:16000],
                {
                    "tool": payload.get("tool_name"),
                    "exit_code": tool_result(payload),
                    "worktree": str(Path(root).resolve()),
                },
            )
    if event in ("PreCompact", "Stop", "SessionEnd"):
        registered = snapshot(root, session).get("transcript")
        if registered and Path(registered).is_file():
            summary = _last_assistant(registered)
            if summary:
                memory.record(
                    host,
                    session,
                    "assistant:" + _digest(summary),
                    "assistant",
                    summary,
                    {"authority": "agent-report"},
                )
        workflows = [
            {
                "id": str(w.id),
                "goal": w.goal,
                "status": w.status.value,
                "owner": str(w.owner_actor_id),
            }
            for w in state.workflows.values()
            if w.goal
        ]
        if workflows:
            memory.record(
                host,
                session,
                "workflows:" + _digest(workflows),
                "workflow",
                canonical(workflows),
                {"authority": "reference-only"},
            )
    if event in ("SessionStart", "UserPromptSubmit"):
        result = dict(output)
        specific = dict(result.get("hookSpecificOutput", {}))
        specific.setdefault("hookEventName", event)
        existing = specific.get("additionalContext", "")
        context = memory.context(query, host=host, session=session)
        from neurath.memory.learning import Learning

        learning = Learning(memory)
        guidance = learning.guidance()
        if guidance:
            learning.expose(host, session, guidance=guidance)
            context += "\n\n" + guidance
        specific["additionalContext"] = existing + ("\n\n" if existing else "") + context
        result["hookSpecificOutput"] = specific
        return result
    return output


def checkpoint_request(root, host, payload):
    """Ask the running native agent to distil its work before its turn is closed."""
    if payload.get("hook_event_name") != "Stop" or payload.get("agent_id"):
        return None
    from neurath.runtime.engine import activate

    activate(root)
    from neurath.hosts.identity import _state, snapshot

    session = payload.get("session_id")
    if not session:
        return None
    state = _state(root, session)
    registered = snapshot(root, session)
    if (
        state.session.runtime.value != host
        or registered.get("host") != host
        or not registered.get("transcript")
    ):
        return None
    memory = ProjectMemory(root)
    from neurath.memory.transcript import synchronize

    synchronize(memory, root, host, session, registered)
    from neurath.memory.learning import Learning

    if Learning(memory).pending(host, session):
        return (
            "Neurath needs a durable handoff before this turn ends. Automatic learning has unvalidated recovery evidence. "
            "Prefer verification_run(check='check') when available and authorized, then memory_checkpoint for the actual outcome. "
            "If the named task is unavailable or cannot enforce current policy, preserve that unsupported state and its concrete reason. "
            "This is routine harness maintenance; no separate user request to learn or verify is required. "
            "If the current user explicitly forbids further checks, or the check cannot run with existing permissions and tools, "
            'record the concrete reason with learning_defer(reason="...", key=STABLE_KEY) and leave the candidate unvalidated. '
            "Do not change permissions or weaken the check. A failed check is recorded without automatic retry for the same evidence. "
            "After the check or deferral, save the handoff. Continue any remaining authorized work; "
            "a handoff does not settle implementation verification or workflow prerequisites."
        )
    if not memory.needs_checkpoint(host, session):
        return None
    return (
        "Neurath needs a durable handoff before this turn ends. Save the actual result, decisions, remaining work, "
        "and useful lessons from failures or user feedback with memory_checkpoint(summary, key, decisions, next_steps, lessons, status). "
        "Use the named MCP task and its current structured input schema. If unavailable, report the missing tool and activation state. "
        "Use concise factual text; do not store secrets, reasoning traces, or claim tests you did not run. "
        "If command recovery candidates exist, use verification_run(check='check'); preserve unsupported policy or tool states without replaying through another transport. "
        "This checkpoint records a report; it never completes a workflow or transfers ownership. "
        "Continue remaining authorized work; finish only when the task's completion conditions are met "
        "or a concrete unresolved constraint requires returning control."
    )
