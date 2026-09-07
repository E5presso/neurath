"""Host protocol adapters dispatch into the preserved runtime, without trusting hooks."""

import io
import json
import os
import sys
from pathlib import Path

from neurath.runtime.engine import activate
from neurath.install.projection import EVENTS, HOSTS

MUTATION_TOOLS = {
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "apply_patch",
    "functions.apply_patch",
}
SHELL_TOOLS = {"Bash", "bash", "shell", "exec_command", "functions.exec_command", "unified_exec"}


def _host_hook(root, host, raw, environment=None):
    if host not in HOSTS:
        return 2, {}, "unsupported host"
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError("hook payload must be an object")
        event = payload.get("hook_event_name")
        allowed = EVENTS + (
            ("PostToolUseFailure", "PermissionDenied") if host == "claude-code" else ()
        )
        if event not in allowed:
            raise ValueError("unsupported event")
        cwd = Path(payload.get("cwd", root)).resolve()
        # A root-specific launcher never gains authority over another worktree.
        if cwd != Path(root).resolve() and not cwd.is_relative_to(Path(root).resolve()):
            raise ValueError("hook cwd is outside installed repository")
    except (ValueError, TypeError) as error:
        return 2, {}, str(error)
    activate(root)
    env = dict(os.environ if environment is None else environment)
    env["NEURATH_HOOK_RUNTIME"] = host
    env["PYTHON_BIN"] = sys.executable
    from scripts.agent_harness.session_kernel import SessionRuntime

    runtime = SessionRuntime(host)
    from neurath.hosts.identity import (
        SPAWN_TOOLS,
        finish_tool,
        issue_tool_binding,
        record_start,
        rewrite_tool,
        snapshot,
        spawn_hook,
    )

    if event in {"SessionStart", "SessionEnd", "SubagentStart"}:
        from neurath.hosts.lifecycle import lifecycle_hook

        if event == "SessionStart":
            from neurath.hosts.identity import validate_start

            validate_start(root, host, payload, env)
        result = lifecycle_hook(Path(root), raw, env)
        if result[0] == 0 and event == "SessionStart":
            record_start(root, host, payload, env)
        if result[0] == 0 and event == "SessionEnd":
            from neurath.hosts.identity import record_disconnect

            record_disconnect(root, host, payload)
            from neurath.agents.mcp import retire_calls

            retire_calls(root, host, payload["session_id"])
        return result
    if event == "UserPromptSubmit":
        if payload.get("agent_id"):
            from neurath.hosts.lifecycle import ensure_child

            if not ensure_child(Path(root), host, payload, env):
                # A spawn's return receipt may arrive after child startup. The
                # assignment can be read while tool authority remains gated.
                return 0, {"hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "Neurath child identity is pending host spawn evidence. Stateful tools still require verified child identity.",
                }}, ""
            from neurath.hosts.identity import reconcile_child_prompt

            reconcile_child_prompt(root, host, payload, env)
        from neurath.hosts.identity import resume_foreground

        resume_foreground(root, host, payload, env)
    if event == "PreToolUse":
        from neurath.hosts.identity import validate_tool_foreground

        validate_tool_foreground(root, host, payload, env)
    if event in {"PreToolUse", "PostToolUse"} and payload.get("tool_name") in SPAWN_TOOLS:
        try:
            return 0, spawn_hook(root, host, payload, env), ""
        except (ValueError, KeyError, OSError) as error:
            return 2, {}, str(error)
    if event == "PreToolUse":
        tool = payload.get("tool_name")
        from neurath.agents.mcp import TOOL_NAME, bind_call

        if payload.get("agent_id") is not None and tool in MUTATION_TOOLS | SHELL_TOOLS | {TOOL_NAME}:
            from neurath.hosts.lifecycle import ensure_child

            if not ensure_child(Path(root), host, payload, env):
                return (
                    2,
                    {},
                    (
                        "child-identity-unverified: this child has no verified process binding; "
                        "shell and write tools cannot run with inherited root authority"
                    ),
                )
        if tool == TOOL_NAME:
            return 0, bind_call(root, host, payload), ""
        if tool in SHELL_TOOLS:
            from neurath.hosts.capabilities import capability_policy

            result = capability_policy(Path(root)).run(raw, Path(root))
            if result.exit_code:
                return result.exit_code, {}, result.stderr
        if tool in MUTATION_TOOLS or tool in SHELL_TOOLS:
            from scripts.agent_harness.worktree_hook import WorktreeHookCommand

            code, stdout, stderr = WorktreeHookCommand().run_payload(
                raw, env, Path(root), hook_runtime=runtime
            )
            output = json.loads(stdout or "{}")
            if (
                code == 0
                and host == "claude-code"
                and tool in SHELL_TOOLS
                and payload.get("tool_use_id")
            ):
                token = issue_tool_binding(root, host, payload)
                specific = output.setdefault("hookSpecificOutput", {"hookEventName": "PreToolUse"})
                specific["updatedInput"] = rewrite_tool(payload["tool_input"], token)
            return code, output, stderr
        return 0, {}, ""
    if event in {"PostToolUse", "PostToolUseFailure", "PermissionDenied"}:
        from neurath.agents.mcp import TOOL_NAME, close_call

        if payload.get("tool_name") == TOOL_NAME:
            close_call(root, host, payload)
            return 0, {}, ""
        if payload.get("tool_name") not in MUTATION_TOOLS | SHELL_TOOLS:
            return 0, {}, ""
        from scripts.agent_harness.material_action_runtime_hook import (
            MaterialActionRuntimeHookApplication,
        )

        if payload.get("session_id") and payload.get("tool_use_id"):
            record = snapshot(root, payload["session_id"])["tools"].get(payload["tool_use_id"])
            if record:
                payload = {
                    **payload,
                    "tool_input": {**payload.get("tool_input", {}), "command": record["command"]},
                }
                raw = json.dumps(payload)
                finish_tool(root, host, payload)
        result = MaterialActionRuntimeHookApplication(runtime).run(
            "permission-denied" if event == "PermissionDenied" else "post", raw, env, Path(root)
        )
        return result.exit_code, {}, result.stderr
    from scripts.agent_harness.agent_continuation_hook import AgentContinuationHookCli

    stdout, stderr = io.StringIO(), io.StringIO()
    code = AgentContinuationHookCli().run(
        ["--runtime", host],
        stdin=io.StringIO(raw),
        stdout=stdout,
        stderr=stderr,
        environment=env,
        cwd=Path(root),
    )
    return code, json.loads(stdout.getvalue() or "{}"), stderr.getvalue()


def _bookkeeping_failure(output, event, component, error):
    from neurath.memory.store import clean

    diagnostic = f"Neurath {component} bookkeeping deferred: {type(error).__name__}: " + clean(str(error))[:2000]
    result = dict(output)
    if event in {"SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}:
        specific = dict(result.get("hookSpecificOutput", {}))
        specific.setdefault("hookEventName", event)
        previous = specific.get("additionalContext", "")
        specific["additionalContext"] = previous + ("\n\n" if previous else "") + diagnostic
        result["hookSpecificOutput"] = specific
    return result, diagnostic


def _dispatch_hook(root, host, raw, environment=None):
    try:
        request = json.loads(raw)
    except ValueError, TypeError:
        request = {}
    readonly = _readonly_root_stop(root, host, request, environment)
    if readonly is not None:
        return readonly
    diagnostics = []
    if isinstance(request, dict) and request.get("hook_event_name") == "Stop":
        from neurath.memory.hooks import checkpoint_request

        try:
            reason = checkpoint_request(root, host, request)
        except Exception as error:
            _, diagnostic = _bookkeeping_failure({}, "Stop", "memory", error)
            diagnostics.append(diagnostic)
            reason = None
        if reason:
            return 2, {}, reason
    code, output, diagnostic = _host_hook(root, host, raw, environment)
    if diagnostic:
        diagnostics.append(diagnostic)
    if code == 0:
        import importlib

        for module, name, component in (
            ("neurath.memory.hooks", "project_event", "memory"),
            ("neurath.agents.hooks", "peer_event", "mailbox"),
        ):
            try:
                enrich = getattr(importlib.import_module(module), name)
                output = enrich(root, host, request, output)
            except Exception as error:
                output, diagnostic = _bookkeeping_failure(output, request["hook_event_name"], component, error)
                diagnostics.append(diagnostic)
    return code, output, "\n".join(diagnostics)


def _readonly_root_stop(root, host, request, environment):
    """Late Stop events cannot retire a new turn or revive an ended session."""
    if (host not in HOSTS or not isinstance(request, dict)
            or request.get("hook_event_name") != "Stop"):
        return None
    activate(root)
    from scripts.agent_harness.session_kernel import (
        ActorStatus, SessionKernel, SessionLocator, SessionRuntime, SessionStatus,
    )
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver

    try:
        binding = RuntimeEnvironmentResolver().resolve_hook_actor(
            os.environ if environment is None else environment,
            request.get("agent_id"), request.get("session_id"), hook_runtime=SessionRuntime(host),
        )
        if not binding.is_root:
            return None
        if (any(request.get(key) is not None for key in (
                "actor_id", "parent_actor_id", "parent_thread_id", "parent_session_id"))
                or request.get("thread_id") not in (None, request.get("session_id"))
                or request.get("runtime") not in (None, host)
                or not isinstance(request.get("cwd"), str)
                or Path(request["cwd"]).resolve() != Path(root).resolve()):
            return 2, {}, "Neurath Stop root identity or worktree mismatch; state is unchanged."
        state = SessionKernel(SessionLocator.from_worktree(Path(root))).inspect(binding.session_id)
        actor = state.actors.get(binding.actor_id)
        if (state.session.runtime is not binding.runtime
                or state.session.root_actor_id != binding.actor_id
                or actor is None or actor.parent_actor_id is not None):
            return 2, {}, "Neurath Stop root binding mismatch; state is unchanged."
    except (OSError, ValueError, RuntimeError):
        return 2, {}, "Neurath Stop lacks a valid root binding; state is unchanged."
    if state.session.status is SessionStatus.ENDED and actor.status is ActorStatus.RETIRED:
        return 0, {}, (
            "Neurath logical session is already ended; Stop acknowledged without "
            "state changes or execution authority. Continue in a new native session."
        )
    turn = state.foreground_turns.get(binding.actor_id)
    if (host != "codex" or state.session.status is not SessionStatus.ACTIVE
            or turn is None or not turn.vendor_turn_id or not request.get("turn_id")
            or turn.vendor_turn_id == request["turn_id"]):
        return None
    from neurath.hosts.identity import (
        _transcript, _validate_root_transcript, native_root_turn, snapshot,
    )

    try:
        data = snapshot(root, request["session_id"])
        path = _transcript(host, request["transcript_path"],
                           os.environ if environment is None else environment)
        _validate_root_transcript(root, host, request, path, data)
        current = bool(data.get("transcript")) and native_root_turn(
            root, path, request["session_id"], turn.vendor_turn_id,
        )
    except (OSError, ValueError, KeyError, TypeError):
        current = False
    if current:
        return 0, {}, "Neurath stale Stop acknowledged; the current native turn is unchanged."
    return 2, {}, "Neurath Stop turn mismatch lacks current native proof; state is unchanged."


def hook(root, host, raw, environment=None):
    """Human input delivery is independent of successful harness bookkeeping.

    Only root UserPromptSubmit has this boundary. A failed reconciliation never
    runs memory/peer admission, and cannot manufacture execution authority.
    All lifecycle, ownership and tool gates retain their rejecting behavior.
    """
    try:
        request = json.loads(raw)
    except ValueError, TypeError:
        request = None
    human_input = (
        host in HOSTS
        and isinstance(request, dict)
        and request.get("hook_event_name") == "UserPromptSubmit"
        and not request.get("agent_id")
        and isinstance(request.get("prompt"), str)
    )
    if not human_input:
        return _dispatch_hook(root, host, raw, environment)
    try:
        code, output, diagnostic = _dispatch_hook(root, host, raw, environment)
        if code == 0:
            return code, output, diagnostic
    except Exception as error:
        # This delivery boundary also covers unavailable optional stores/plugins.
        # SystemExit/interrupts are intentionally not swallowed.
        diagnostic = f"{type(error).__name__}: {error}"
    from neurath.memory.store import clean

    diagnostic = "Neurath prompt bookkeeping deferred: " + clean(diagnostic)[:2000]
    context = (
        "The user input was delivered. Neurath bookkeeping is deferred; no new "
        "state or execution authority is confirmed by this diagnostic. Existing "
        "tool and ownership checks still apply.\n" + diagnostic
    )
    return (
        0,
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        },
        diagnostic,
    )


def run_hook(root, host):
    try:
        code, payload, diagnostic = hook(root, host, sys.stdin.read())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        code, payload, diagnostic = 2, {}, f"Neurath hook rejected: {type(error).__name__}: {error}"
    print(json.dumps(payload, ensure_ascii=False))
    if diagnostic:
        print(diagnostic, file=sys.stderr)
    return code
