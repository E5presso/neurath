"""Native hook ingress and exact-invocation MCP binding for the replacement core.

Hooks are the observation boundary, not an OS security boundary. Host sandbox and
permission enforcement remain the host's responsibility. No transcript parsing,
CWD-derived actors or caller-provided provenance is used here.
"""

from hashlib import sha256
from pathlib import Path

from neurath.core.codec import encode
from neurath.core.domain import CoreError, require
from neurath.core.host_events import (
    SHELL_TOOLS,
    context_from_event,
    effect_target,
    effects_for_tool,
    stop_response,
    write_targets,
)
from neurath.core.service import COMMANDS, Context

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
    }
)


class HookAdapter:
    def __init__(self, core, provider, *, checks=()):
        self.core = core
        self.provider = provider
        self.checks = None if checks is None else tuple(checks)

    def handle(self, event, payload, receipt_id):
        context = context_from_event(self.provider, payload, receipt_id)
        # A shared session ID does not reveal a nested child's direct parent.
        self.core.observe_actor(
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
            source = self.core.observe_input(context, payload["prompt"], receipt_id, origin=origin)
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
            return stop_response(self.core.stop(context))
        if event == "SessionEnd":
            # Advisory event: preserve unfinished obligations across interruption.
            with self.core.store.transaction() as tx:
                actor = tx.record("actor", context.actor_id)
                tx.put_record(
                    "actor",
                    context.actor_id,
                    {**actor["value"], "status": "stopped"},
                    actor["revision"],
                )
                for record in tx.records("native-invocation"):
                    value = record["value"]
                    if (
                        value["provider"] == self.provider
                        and value["session_id"] == context.session_id
                        and value["active"]
                        and (not payload.get("agent_id") or value["actor_id"] == context.actor_id)
                    ):
                        tx.put_record(
                            "native-invocation",
                            record["id"],
                            {**value, "active": False},
                            record["revision"],
                        )
            return {}
        if event in {"PostToolUse", "PostToolUseFailure", "PermissionDenied"}:
            from neurath.core.native_delegation import finished

            finished(self.core, self.provider, context, payload, failed=event != "PostToolUse")
            from neurath.core.terminal import observe as observe_terminal

            observe_terminal(self.core, context, payload)
            self._close(context, payload.get("tool_use_id"))
            if "tool_response" in payload and not str(payload.get("tool_name", "")).startswith(
                ("mcp__neurath__", "mcp__neurath_collaboration__")
            ):
                self.core.observe_output(
                    context,
                    payload,
                    interaction=event == "PostToolUse"
                    and payload.get("tool_name") in {"AskUserQuestion", "request_user_input"}
                    and bool(payload.get("tool_response")),
                )
            from neurath.core.cleanup import finish as finish_cleanup

            finish_cleanup(self.core, context, payload, event)
            self._finish_check(context, payload, event)
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
            return self._bind(context, command, values, payload.get("tool_use_id"))
        if name in CONTROL_TOOLS:
            return {}
        try:
            if name == "write_stdin":
                from neurath.core.terminal import admit as admit_terminal

                admit_terminal(self.core, context, values)
                return {}
            if name in SHELL_TOOLS:
                from neurath.core.checks import authorize_launch as authorize_check
                from neurath.core.provider_commands import authorize_launch

                if authorize_check(self.core, context, payload):
                    return {}
                if authorize_launch(self.core, context, payload):
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
                    self.core.admit(context, {effect}) if effect == "workspace" else None
                    with self.core.store.transaction() as tx:
                        lease = tx.lease(operation["target"])
                        require(
                            lease is not None and lease["writer"] == context.actor_id,
                            "writer-lease-required",
                        )
                    if effect == "cleanup":
                        admitted = self.core.admit(
                            context,
                            {effect},
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
                require(isinstance(directory, str), "check-directory-required")
                target = checkout(
                    self.core.store.root,
                    Path(payload.get("cwd") or self.core.store.root) / directory,
                )
                self.checks = configured_checks(target)
            effects = effects_for_tool(
                name, values, checks=self.checks or (), cwd=payload.get("cwd")
            )
            from neurath.core.native_delegation import FOLLOWUP, SPAWN, prepare

            if name in SPAWN | FOLLOWUP:
                prepare(self.core, self.provider, context, payload)
                return {}
            publication = (
                effect_target(name, values, payload.get("cwd"))
                if effects & {"publish", "decision"}
                else None
            )
            if effects & {"edit", "git", "cleanup"} or name in SHELL_TOOLS and "execute" in effects:
                from neurath.core.workspace import checkout

                targets = tuple(
                    dict.fromkeys(
                        checkout(self.core.store.root, path)
                        for path in write_targets(name, values, payload.get("cwd"))
                    )
                )
                for target in targets:
                    with self.core.store.transaction() as tx:
                        lease = tx.lease(target)
                        generation = lease["generation"] if lease else None
                    admitted = self.core.admit(
                        context,
                        effects,
                        checkout_path=target,
                        generation=generation,
                        effect_target=publication,
                    )
            else:
                admitted = self.core.admit(context, effects, effect_target=publication)
            if "check" in effects:
                self._start_check(context, payload, admitted["task_id"])
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

    def _bind(self, context, command, values, native_tool_id):
        require(isinstance(native_tool_id, str) and bool(native_tool_id), "native-tool-id-required")
        call_id = values.get("_call_id")
        require(isinstance(call_id, str) and 1 <= len(call_id) <= 128, "native-call-id-required")
        identity = encode([self.provider, context.session_id, context.actor_id, native_tool_id])
        identifier = sha256(call_id.encode()).hexdigest()
        arguments = {key: value for key, value in values.items() if key != "_call_id"}
        value = {
            "provider": self.provider,
            "actor_id": context.actor_id,
            "session_id": context.session_id,
            "invocation_id": identity,
            "request": sha256(encode([command, arguments]).encode()).hexdigest(),
            "active": True,
        }
        native_id = sha256(identity.encode()).hexdigest()
        with self.core.store.transaction() as tx:
            previous = tx.record("native-invocation", identifier)
            if previous:
                require(previous["value"] == value, "native-call-id-reused")
            else:
                require(tx.record("native-call", native_id) is None, "native-invocation-rebound")
                tx.put_record("native-invocation", identifier, value)
                tx.put_record("native-call", native_id, {"id": identifier})
        # Correlation is already in the original input. Host permission handling
        # is unchanged: never issue an allow override to transport identity.
        return {}

    def call(self, command, values):
        require(isinstance(values, dict), "invalid-input")
        call_id = values.get("_call_id")
        require(isinstance(call_id, str) and bool(call_id), "native-invocation-required")
        identifier = sha256(call_id.encode()).hexdigest()
        arguments = {key: value for key, value in values.items() if key != "_call_id"}
        request = sha256(encode([command, arguments]).encode()).hexdigest()

        def authenticate(tx):
            record = tx.record("native-invocation", identifier)
            require(record is not None, "native-invocation-required")
            binding = record["value"]
            require(binding["active"], "native-invocation-closed")
            require(binding["provider"] == self.provider, "provider-binding-mismatch")
            actor = tx.record("actor", binding["actor_id"])
            require(
                actor is not None and actor["value"]["status"] == "active", "native-session-stopped"
            )
            require(binding["request"] == request, "invocation-mismatch")
            return Context(binding["actor_id"], binding["session_id"], binding["invocation_id"])

        with self.core.store.transaction() as tx:
            context = authenticate(tx)
        return self.core.call(context, command, arguments, guard=authenticate)

    def _close(self, context, native_tool_id):
        if not isinstance(native_tool_id, str):
            return
        identity = encode([self.provider, context.session_id, context.actor_id, native_tool_id])
        with self.core.store.transaction() as tx:
            link = tx.record("native-call", sha256(identity.encode()).hexdigest())
            if link:
                identifier = link["value"]["id"]
                record = tx.record("native-invocation", identifier)
                if record["value"]["active"]:
                    tx.put_record(
                        "native-invocation",
                        identifier,
                        {**record["value"], "active": False},
                        record["revision"],
                    )

    def _execution_id(self, context, tool_id):
        require(isinstance(tool_id, str) and bool(tool_id), "native-tool-id-required")
        return sha256(
            encode([self.provider, context.session_id, context.actor_id, tool_id]).encode()
        ).hexdigest()

    def _start_check(self, context, payload, task_id):
        from neurath.core.workspace import checkout, source_subject

        values = payload["tool_input"]
        directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
        require(isinstance(directory, str), "check-directory-required")
        directory = Path(directory).resolve()
        target = checkout(self.core.store.root, directory)
        identifier = self._execution_id(context, payload.get("tool_use_id"))
        value = {
            "task_id": task_id,
            "actor_id": context.actor_id,
            "checkout": target,
            "subject": source_subject(target),
            "tool": payload["tool_name"],
            "input": values,
            "state": "running",
            "definition": next(
                check
                for check in self.checks
                if check["command"] == values.get("command", values.get("cmd"))
                and Path(check["cwd"]).resolve() == directory
            ),
        }
        with self.core.store.transaction() as tx:
            value["execution_scope"] = [list(item) for item in tx.task(task_id).observation_scope()]
            previous = tx.record("check-execution", identifier)
            if previous:
                require(previous["value"] == value, "invocation-mismatch")
            else:
                tx.put_record("check-execution", identifier, value)

    def _finish_check(self, context, payload, event):
        from neurath.core.native_results import check_result

        if not payload.get("tool_use_id"):
            return
        identifier = self._execution_id(context, payload["tool_use_id"])
        with self.core.store.transaction() as tx:
            record = tx.record("check-execution", identifier)
        if record is None:
            return
        value = record["value"]
        result = check_result(payload) if event == "PostToolUse" else None
        if result is None:
            with self.core.store.transaction() as tx:
                tx.put_record(
                    "check-execution",
                    identifier,
                    {
                        **value,
                        "state": "outcome-unavailable"
                        if event == "PostToolUse"
                        else "failed-to-execute",
                        "last_response": payload.get("tool_response"),
                        "last_event": event,
                    },
                    record["revision"],
                )
            return
        definition = value["definition"]
        marker = definition.get("stdout_contains")
        output = result["native_response"].get("stdout", result["native_response"].get("output"))
        if marker is not None and not isinstance(output, str):
            with self.core.store.transaction() as tx:
                tx.put_record(
                    "check-execution",
                    identifier,
                    {
                        **value,
                        "state": "outcome-unavailable",
                        "last_response": result,
                        "reason": "Required check output was not observable",
                    },
                    record["revision"],
                )
            return
        result["passed"] = result["exit_code"] in definition.get("success_codes", [0]) and (
            marker is None or marker in output
        )
        evidence = self.core.observe_tool(
            context,
            value["task_id"],
            "check:" + identifier,
            result,
            kind="check",
            subject=value["subject"],
            checkout_path=value["checkout"],
            execution_scope=value["execution_scope"],
        )
        if value["state"] == "completed":
            require(value["evidence_id"] == evidence.id, "native-result-changed")
            return
        with self.core.store.transaction() as tx:
            tx.put_record(
                "check-execution",
                identifier,
                {**value, "state": "completed", "evidence_id": evidence.id},
                record["revision"],
            )
