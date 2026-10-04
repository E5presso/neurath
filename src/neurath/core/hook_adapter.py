"""Native hook ingress and exact-invocation MCP binding for the replacement core.

Hooks are the observation boundary, not an OS security boundary. Host sandbox and
permission enforcement remain the host's responsibility. No transcript parsing,
CWD-derived actors or caller-provided provenance is used here.
"""

from pathlib import Path

from neurath.core.check_observations import CheckObservations
from neurath.core.commands import COMMANDS
from neurath.core.domain import CoreError, require
from neurath.core.host_events import (
    EDIT_TOOLS,
    SHELL_TOOLS,
    context_from_event,
    stop_response,
    write_targets,
)
from neurath.core.invocations import NativeInvocations

CONTROL_TOOLS = frozenset(
    {
        "update_plan",
        "TodoWrite",
        "AskUserQuestion",
        "request_user_input",
        "request_user_input_async",
        "wait_agent",
        "wait",
        "sleep",
        "list_agents",
        "interrupt_agent",
        "TaskOutput",
        "BashOutput",
        "write_stdin",
    }
)


class HookAdapter:
    def __init__(self, core, provider, *, checks=()):
        self.core = core
        self.provider = provider
        self.checks = None if checks is None else tuple(checks)
        self.invocations = NativeInvocations(core.store, provider, core.call)
        self.observations = CheckObservations(core.store, core.provenance, provider)

    def handle(self, event, payload, receipt_id):
        context = context_from_event(self.provider, payload, receipt_id)
        # A shared session ID does not reveal a nested child's direct parent.
        self.core.sessions.observe_actor(
            context.actor_id,
            context.session_id,
            self.provider,
            is_subagent=bool(payload.get("agent_id")),
            activate=event in {"SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse"},
        )
        if event == "SubagentStart":
            from neurath.core.native_delegation import child_started

            require(bool(payload.get("agent_id")), "native-agent-required")
            child_started(self.core, self.provider, context)
            return {}
        if event == "UserPromptSubmit":
            require(isinstance(payload.get("prompt"), str), "native-prompt-required")
            from neurath.core.provider_commands import input_origin

            origin = input_origin(self.core, self.provider, context.session_id, payload["prompt"])
            source = self.core.provenance.observe_input(
                context, payload["prompt"], receipt_id, origin=origin
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"Neurath retained input {source.id}. This is native-input provenance, not human attestation. Use task_list to resume existing obligations; source_read supplies exact text.",
                }
            }
        if event == "SessionStart":
            from neurath.core.provider_commands import observe_start

            observe_start(self.core, self.provider, context)
            return {}
        if event in {"Stop", "SubagentStop"}:
            return stop_response(self.core.sessions.stop(context))
        if event == "SessionEnd":
            self.core.sessions.end(
                context, self.provider, receipt_id, child=bool(payload.get("agent_id"))
            )
            return {}
        if event in {"PostToolUse", "PostToolUseFailure", "PermissionDenied"}:
            from neurath.core.native_delegation import finished

            finished(self.core, self.provider, context, payload, failed=event != "PostToolUse")
            self.invocations.close(context, payload.get("tool_use_id"))
            if "tool_response" in payload and not str(payload.get("tool_name", "")).startswith(
                ("mcp__neurath__", "mcp__neurath_collaboration__")
            ):
                self.core.provenance.observe_output(
                    context,
                    payload,
                    interaction=event == "PostToolUse"
                    and payload.get("tool_name") in {"AskUserQuestion", "request_user_input"}
                    and bool(payload.get("tool_response")),
                )
            from neurath.core.cleanup import finish as finish_cleanup

            finish_cleanup(self.core, context, payload, event)
            self.observations.finish(context, payload, event)
            return {}
        if event != "PreToolUse":
            return {}
        name, values = payload.get("tool_name"), payload.get("tool_input")
        require(isinstance(name, str) and isinstance(values, dict), "native-tool-required")
        command = name.rsplit("__", 1)[-1]
        if (
            name.startswith(("mcp__neurath__", "mcp__neurath_collaboration__"))
            and command in COMMANDS
        ):
            return self.invocations.bind(context, command, values, payload.get("tool_use_id"))
        if name in CONTROL_TOOLS:
            return {}
        try:
            if name == "SubagentHandback":
                result = self.core.sessions.stop(context)
                require(result["allowed"], "assignment-unsettled", pending=result["pending"])
                return {}
            if name in SHELL_TOOLS:
                from neurath.core.checks import authorize_launch as authorize_check
                from neurath.core.provider_commands import authorize_launch

                if authorize_check(self.core.store, context, payload):
                    return {}
                if authorize_launch(self.core.store, context, payload):
                    return {}
                from neurath.core.workspace import worktree_operation

                command = values.get("command", values.get("cmd"))
                directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
                operation = (
                    worktree_operation(command, directory)
                    if isinstance(command, str) and isinstance(directory, str)
                    else None
                )
                if operation is not None:
                    from neurath.core.workspace import checkout

                    checkout(self.core.store.root, operation["repository"])
                    effect = "workspace" if operation["action"] == "add" else "cleanup"
                    with self.core.store.transaction() as tx:
                        lease = tx.lease(operation["target"])
                        require(
                            lease is not None and lease["writer"] == context.actor_id,
                            "writer-lease-required",
                        )
                    if effect == "cleanup":
                        admitted = self.core.ownership.admit_write(
                            context,
                            checkout_path=operation["target"],
                            generation=lease["generation"],
                        )
                        from neurath.core.cleanup import prepare as prepare_cleanup

                        prepare_cleanup(
                            self.core,
                            context,
                            payload.get("tool_use_id"),
                            operation["target"],
                            admitted["task_id"],
                        )
                    return {}
            if self.checks is None and name in SHELL_TOOLS:
                from neurath.core.hooks import configured_checks
                from neurath.core.workspace import checkout

                directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
                try:
                    require(isinstance(directory, str), "check-directory-required")
                    target = checkout(
                        self.core.store.root,
                        Path(payload.get("cwd") or self.core.store.root) / directory,
                    )
                    self.checks = configured_checks(target)
                except CoreError, ValueError, OSError:
                    # No matching observation is not permission to block an
                    # unrelated native command. Explicit check preparation
                    # returns configuration errors through its own command.
                    self.checks = ()
            from neurath.core.native_delegation import FOLLOWUP, SPAWN, prepare

            if name in SPAWN | FOLLOWUP:
                prepare(self.core, self.provider, context, payload)
                return {}
            if name in EDIT_TOOLS:
                from neurath.core.workspace import checkout

                for target in dict.fromkeys(
                    checkout(self.core.store.root, path)
                    for path in write_targets(name, values, payload.get("cwd"))
                ):
                    with self.core.store.transaction() as tx:
                        lease = tx.lease(target)
                    self.core.ownership.admit_write(
                        context,
                        checkout_path=target,
                        generation=None if lease is None else lease["generation"],
                    )
            if name in SHELL_TOOLS:
                command = values.get("command", values.get("cmd"))
                directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
                if isinstance(directory, str) and any(
                    command == check["command"]
                    and Path(check["cwd"]).resolve() == Path(directory).resolve()
                    for check in self.checks or ()
                ):
                    with self.core.store.transaction() as tx:
                        focus = tx.record("focus", context.actor_id)
                    if focus is not None:
                        self.observations.start(
                            context, payload, focus["value"]["task_id"], self.checks
                        )
            # No allow override: the host retains its normal permission decision.
            return {}
        except CoreError as error:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": str(error),
                }
            }

    def call(self, command, values):
        return self.invocations.call(command, values)
