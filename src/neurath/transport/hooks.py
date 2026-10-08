"""Translate host events into trusted application input and conservative work guards."""

import json
import sys
from pathlib import Path
from uuid import uuid4

from neurath.domain.errors import AuthorizationError
from neurath.transport.binding import bind, observe_session
from neurath.transport.recovery import bypass
from neurath.transport.runtime import application, database

READ_TOOLS = {"Read", "Glob", "Grep", "read_file", "list_directory", "view_image", "web.run"}
CONTROL_TOOLS = {
    "request_user_input",
    "request_user_input_async",
    "update_plan",
    "TodoWrite",
    "AskUserQuestion",
    "wait",
    "wait_agent",
    "list_agents",
    "sleep",
}


def process(root, provider, payload):
    if not isinstance(payload, dict):
        raise ValueError("A native event object is required")
    event = payload.get("hook_event_name")
    name = payload.get("tool_name", "")
    if (event == "PreToolUse" and name == "mcp__neurath__harness_bypass") or bypass(root)[
        "enabled"
    ]:
        return {}
    if event == "PreToolUse" and name in READ_TOOLS | CONTROL_TOOLS:
        return {}
    session = observe_session(root, provider, payload)
    actor = session["id"]
    app = application(root)
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("Native prompt text is required")
        # A native prompt retains provenance; this does not assert human approval.
        source = app.register_source(
            session_id=actor, event_id=str(payload.get("event_id") or uuid4()), text=prompt
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": f"Neurath source_id={source['id']}; session_id={actor}. Preserve unfinished work; native input is not automatic approval.",
            }
        }
    if event in {"Stop", "SubagentStop"}:
        with database(root).uow() as uow:
            pending = [
                task.id
                for task in uow.repo("task").list(owner_id=actor)
                if task.status not in {"completed", "withdrawn"}
            ]
            pending += [
                item.id
                for item in uow.repo("delegation").list(recipient_id=actor)
                if item.status in {"prepared", "active", "rejected"}
            ]
        if pending:
            if payload.get("stop_hook_active") is True:
                return {
                    "systemMessage": "Unfinished Neurath work remains recorded for recovery: "
                    + ", ".join(pending)
                }
            return {
                "decision": "block",
                "reason": "Unfinished Neurath work is preserved: "
                + ", ".join(pending)
                + ". Continue actionable work or report the concrete blocker; do not claim completion.",
            }
        return {}
    if event == "SessionEnd":
        with database(root).uow() as uow:
            current = uow.repo("session").get(actor)
            previous = current.revision
            current.status = "ended"
            current.changed()
            uow.repo("session").save(current, previous)
            uow.commit()
        return {}
    if event == "PreToolUse":
        if name.startswith("mcp__neurath__"):
            bind(root, provider, payload)
            return {}
        if name.startswith("mcp__"):
            return {}  # External service permissions belong to the native host.
        with database(root).uow() as uow:
            active = [
                task for task in uow.repo("task").list(owner_id=actor) if task.status == "active"
            ]
            leases = [
                lease
                for lease in uow.repo("lease").list(owner_id=actor)
                if lease.active and lease.resource == str(Path(root).resolve())
            ]
        if not active or not leases:
            raise AuthorizationError(
                "An active owned task and current checkout writer lease are required for native changes"
            )
        from neurath.transport.verification import observe_start

        observe_start(root, actor, payload)
    elif event in {"PostToolUse", "PostToolUseFailure"}:
        from neurath.transport.verification import observe_finish

        observe_finish(root, actor, payload, failed=event != "PostToolUse")
    return {}


def legacy_provider(payload):
    """Resolve old hook callbacks only from provider-specific native envelope fields."""
    if not isinstance(payload, dict):
        raise ValueError("A native event object is required")
    transcript = payload.get("transcript_path")
    parts = Path(transcript).parts if isinstance(transcript, str) else ()
    codex = bool(isinstance(payload.get("turn_id"), str) and payload["turn_id"]) or ".codex" in parts
    claude = ".claude" in parts
    if codex == claude:
        raise AuthorizationError("Legacy hook provider is ambiguous; reconnect using --provider")
    return "codex" if codex else "claude-code"


def run(root, provider):
    payload = {}
    try:
        raw = sys.stdin.read(1048577)
        if len(raw.encode()) > 1048576:
            raise ValueError("Native event exceeds limit")
        payload = json.loads(raw)
        recovery = isinstance(payload, dict) and payload.get("hook_event_name") == "PreToolUse" and payload.get("tool_name") in {
            "mcp__neurath__harness_bypass", "mcp__neurath_collaboration__harness_bypass"
        }
        if bypass(root)["enabled"] or recovery:
            result = {}
        else:
            result = process(root, provider or legacy_provider(payload), payload)
    except Exception as error:
        event = payload.get("hook_event_name") if isinstance(payload, dict) else None
        if event == "PreToolUse":
            result = {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": str(error),
                }
            }
        elif event in {"Stop", "SubagentStop"}:
            result = {"decision": "block", "reason": str(error)}
        else:
            print(str(error), file=sys.stderr)
            raise SystemExit(2) from error
    print(json.dumps(result, ensure_ascii=False))
