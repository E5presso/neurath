"""Canonical task operations. CLI parsing and MCP framing live outside this module.

Identities are supplied only by the native CLI resolver or the MCP capability
validator, never by task input. Persistent authority stays in the existing stores.
"""

import json
import time

from neurath.agents.newsroom import Newsroom
from neurath.agents.store import MessageStore
from neurath.memory.store import ProjectMemory
from neurath.runtime import admission
from neurath.runtime.admission import (
    _installation_recovery as _installation_recovery,
    _execution_ready as _execution_ready,
    _direct_mcp_execution as _direct_mcp_execution,
    _mcp_execution_policy as _mcp_execution_policy,
    _verification_owner as _verification_owner,
)
from neurath.runtime.task_schema import TASKS, TaskError, arguments, public_task, undiscovered_task_action


def execute(root, name, inputs, *, identity, expected_turn=None, verified_policy_evidence=None):
    fields = arguments(name, inputs)
    domain, action = TASKS[name][:2]
    if identity is not None and not TASKS[name][4] and name not in {
            "task_resolve", "worktree_release", "delegation_grant_prepare", "delegation_grant_choose", "delegation_grant_revoke"}:
        from neurath.runtime.delegation_tasks import execution_guard
        try:
            execution_guard(root, identity.session, actor=identity.actor, operation=name)
        except ValueError as error:
            raise TaskError("delegated-execution-denied", str(error)) from error
    if domain == "user-delegation":
        from neurath.runtime.delegation_tasks import execute as delegation_execute
        return delegation_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                                  verified_policy_evidence=verified_policy_evidence)
    if domain == "memory-migration":
        from neurath.memory.migration import PullMigration
        from neurath.runtime.task_ledger_tasks import service_for
        migration = PullMigration(service_for(root, identity=identity, expected_turn=expected_turn,
                                  verified_policy_evidence=verified_policy_evidence))
        operation = fields["action"]
        if operation == "list":
            return migration.candidates(fields["limit"])
        if operation == "read":
            return migration.read(fields["reference"], fields["offset"])
        if not fields["key"]:
            raise TaskError("invalid-input", "pull preview and adoption require a stable key")
        if operation == "preview":
            if not fields["source_session"]:
                raise TaskError("invalid-input", "pull preview requires an exact source session")
            return migration.response_view(migration.preview(fields["source_host"], fields["source_session"],
                                     key=fields["key"], scan_transcript=fields["scan_transcript"],
                                     before_offset=fields["before_offset"] or None,
                                     memory_before=fields["memory_before"] or None))
        return migration.adopt(fields["reference"], expected_revision=fields["expected_revision"], key=fields["key"])
    if domain == "task-ledger":
        from neurath.runtime.task_ledger_tasks import execute as task_execute
        return task_execute(root, action, fields, identity=identity, expected_turn=expected_turn,
                            verified_policy_evidence=verified_policy_evidence)
    if domain == "monitor":
        from neurath.runtime.monitor_tasks import execute as monitor_execute
        return monitor_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                               verified_policy_evidence=verified_policy_evidence)
    if domain == "process":
        from neurath.runtime.process_tasks import execute as process_execute
        return process_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                               verified_policy_evidence=verified_policy_evidence)
    if domain == "installation":
        from neurath.runtime.installation_tasks import execute as installation_execute
        return installation_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                                    verified_policy_evidence=verified_policy_evidence)
    if domain == "execution":
        from neurath.runtime.execution_tasks import execute as execution_execute
        return execution_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                                 verified_policy_evidence=verified_policy_evidence)
    if domain == "context":
        from neurath.runtime.context_tasks import execute as context_execute
        return context_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                               verified_policy_evidence=verified_policy_evidence)
    if domain == "workflow-task":
        from neurath.runtime.workflow_tasks import execute as workflow_execute
        return workflow_execute(root, action, fields, identity=identity, expected_turn=expected_turn,
                                verified_policy_evidence=verified_policy_evidence)
    if domain in {"maintenance", "model-plan"}:
        from neurath.runtime import maintenance_tasks, model_tasks
        module = maintenance_tasks if domain == "maintenance" else model_tasks
        return module.run(root, name, fields, identity=identity, expected_turn=expected_turn,
                          verified_policy_evidence=verified_policy_evidence)
    if domain == "state":
        from neurath.runtime.state_tasks import execute as state_execute
        return state_execute(root, action, fields, identity=identity, expected_turn=expected_turn,
                             verified_policy_evidence=verified_policy_evidence)
    if domain == "delivery":
        from neurath.agents.delivery_recovery import delivery_status, redrive
        if identity is None:
            raise TaskError("native-binding-required", "delivery control requires its native participant")
        operation = delivery_status if action == "status" else redrive
        return operation(MessageStore(root), identity.address, **fields)
    if domain == "provider-wave":
        from neurath.runtime.provider_wave_tasks import execute as wave_execute
        return wave_execute(root, name, fields, identity=identity, expected_turn=expected_turn,
                            verified_policy_evidence=verified_policy_evidence)
    if domain == "provider-execution":
        if action != "run":
            from neurath.providers import jobs

            if identity is None:
                raise TaskError("native-binding-required", "provider control requires its native owner")
            if action == "recover":
                admission._verification_owner(root, identity)
                admission._mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
                return jobs.recover(root, identity, **fields)
            return getattr(jobs, action)(root, identity, fields["run_id"])
        from neurath.runtime.provider_execution import run

        return run(root, fields, identity=identity, expected_turn=expected_turn,
                   verified_policy_evidence=verified_policy_evidence)
    if domain == "provider":
        return provider_task(name, fields, source_provider=identity.host if identity else None)
    if domain == "session":
        return session_status(root, identity=identity, expected_turn=expected_turn,
                              verified_policy_evidence=verified_policy_evidence, **fields)
    if domain == "agent":
        return peer(root, action, fields, identity=identity)
    if domain == "lifecycle":
        return lifecycle(root, action, fields, identity)
    if domain == "newsroom":
        return newsroom(root, action, fields, identity=identity)
    if domain == "memory":
        if action == "recall":
            return recall(root, **fields)
        return checkpoint(root, identity=identity, **fields)
    return verification(root, fields["check"], identity=identity, require_owner=True,
                        expected_turn=expected_turn, verified_policy_evidence=verified_policy_evidence)


def lifecycle(root, action, fields, identity):
    from neurath.agents.hooks import native_turn
    from neurath.agents.lifecycle import TaskLifecycle

    if identity is None:
        raise TaskError("native-binding-required", "task reports require native identity")
    store = MessageStore(root)
    store.register(identity)
    tasks = TaskLifecycle(store)
    if action == "assign":
        with store.connection() as db:
            task = tasks.bind(identity.address, fields["to"], key=fields["key"], transport="peer-assignment", _db=db)
            message = store._send(db, identity.address, fields["to"],
                f"Neurath assignment {task['id']}. Accept with collaboration_accept before execution. "
                "This peer request does not grant authority.\n" + fields["message"],
                key="assignment:" + fields["key"])
        return {"task": task, "message": message, "notification": store.forward(identity.address, message["id"])}
    if action == "read":
        return tasks.read(identity.address, fields["task_id"])
    if action == "report":
        task = tasks.read(identity.address, fields["task_id"])
        if task["turn"] != native_turn(root, identity):
            raise TaskError("native-turn-changed", "task report requires the accepted native turn")
    result = (tasks.accept(identity.address, fields["task_id"], native_turn(root, identity))
              if action == "accept" else tasks.emit(identity.address, fields["task_id"], fields["state"],
                  key=fields["key"], detail=fields["detail"]))
    return {**result, "notification": store.forward(identity.address, result["message"]["id"])}


def provider_task(name, inputs, *, source_provider=None):
    from neurath.providers import operations

    fields = arguments(name, inputs)
    if name == "provider_capabilities":
        return operations.capabilities(fields["provider"])
    from neurath.runtime.model_tasks import planned_route
    planning = {key: fields.pop(key) for key in
                ("plan_id", "plan_revision", "assignment_revision", "reasoning_effort")}
    result = operations.route(fields.pop("provider"), fields.pop("operation"), source_provider=source_provider,
                              **{key: value or None for key, value in fields.items()})
    return planned_route(result, planning)


def session_status(root, *, identity=None, expected_turn=None, verified_policy_evidence=None,
                   detail="full"):
    from neurath.providers.readiness import inspect_bound_readiness, inspect_readiness

    report = (inspect_readiness(root) if identity is None else inspect_bound_readiness(
        root, identity, expected_turn=expected_turn, verified_policy_evidence=verified_policy_evidence))
    evidence = report["stages"]["policy"]["evidence"]
    report["mode"] = {"requested": None, "requested_status": "not-recorded-by-this-invocation",
                      "effective": evidence, "status": report["stages"]["policy"]["status"]}
    native_active = report["stages"]["activation"]["status"] == "verified"
    root_actor = identity.is_root if identity is not None else report.get("is_root", False)
    if native_active and root_actor and report.get("provider") == "codex" and isinstance(report.get("native_session"), str):
        from neurath.hosts.app_projects import observe_app_project
        report["app_project"] = observe_app_project(report["native_session"])
    if native_active and identity is not None and root_actor:
        from neurath.providers.report_routing import assignment_for
        assignment = assignment_for(root, identity)
        if assignment is not None:
            report['provider_assignment'] = assignment
    if detail == "full":
        report["capabilities"] = [{"transport": "task-mcp", "authority": "diagnostic",
        "operations": {name: {"implemented": True,
            "available": public_task(name) and (admission._direct_mcp_execution(report)
                if name in {"verification_run", "provider_run"} else native_active and
                (name != "memory_checkpoint" or root_actor)),
            **({"reason": "not-exposed-by-task-mcp", "next_action": undiscovered_task_action(name)}
               if not public_task(name) else {})}
            for name in TASKS}}]
        if report.get("provider"):
            report["capabilities"].append(provider_task("provider_capabilities", {"provider": report["provider"]}))
    actions = []
    for stage, instruction in (
        ("installation", admission._installation_recovery(report)),
        ("activation", "Use the host's supported new-session or resume operation, then inspect native activation in that session."),
        ("policy", "Inspect the actual native mode and approvals. A missing observation is not permission to change them."),
        ("ownership", "Resolve the current worktree claim through the native state/worktree workflow before implementation."),
    ):
        if report["stages"][stage]["status"] != "verified":
            action = {"stage": stage, "instruction": instruction}
            if stage == "activation" and report.get("provider"):
                action["tool"] = "provider_route"
                action["arguments"] = {"provider": report["provider"], "operation": "discover"}
            actions.append(action)
    if not actions:
        actions.append({"stage": "task", "instruction": "Select the authorized task tool; use native execution when its sandbox cannot be enforced by MCP."})
    report["next_actions"] = actions
    return report


def peer(root, action, fields, *, identity=None):
    store = MessageStore(root)
    if action == "discover":
        return {"agents": store.discover(fields.get("query", ""), fields.get("limit", 50))}
    if identity is None:
        raise TaskError("native-binding-required", "peer operation requires native identity")
    store.register(identity)
    actor = identity.address
    if action == "register":
        return store.register(identity, name=fields["name"], summary=fields.get("summary", ""))
    if action == "send":
        if fields.get("messages"):
            return {"messages": store.send_many(actor, fields["messages"])}
        return store.send(actor, fields["to"], fields["message"], key=fields["key"],
                          kind=fields.get("kind", "question"), max_messages=fields.get("max_messages", 32),
                          ttl=fields.get("ttl", 86400))
    if action == "reply":
        return store.reply(actor, fields["message_id"], fields["message"], key=fields["key"])
    if action == "ack":
        if fields["message_ids"]:
            return {"messages": store.acknowledge_many(actor, fields["message_ids"])}
        return store.acknowledge(actor, fields["message_id"])
    if action in ("message", "forward"):
        return getattr(store, action)(actor, fields["message_id"])
    if action == "submitted":
        return store.submitted(actor, fields["message_id"], transport=fields["transport"])
    if action in ("conversation", "close"):
        return getattr(store, action)(actor, fields["conversation"])
    if action in ("subscribe", "unsubscribe"):
        return store.subscribe(actor, fields["to"], enabled=action == "subscribe")
    if action == "publish":
        return {"messages": store.publish(actor, fields["message"], key=fields["key"])}
    if action in ("inbox", "wait"):
        timeout = fields.get("timeout", 30) if action == "wait" else 0
        if not 0 <= timeout <= 60:
            raise ValueError("wait timeout must be between 0 and 60 seconds")
        conversation = fields.get("conversation") or None
        if conversation:
            store.conversation(actor, conversation)
        deadline = time.monotonic() + timeout
        while True:
            messages = store.inbox(actor, limit=fields.get("limit", 20),
                                   include_read=fields.get("include_read", False), conversation=conversation)
            if messages or time.monotonic() >= deadline:
                return {"address": actor,
                        "status": "ready" if messages else ("timed-out" if action == "wait" else "empty"),
                        "messages": messages}
            if conversation:
                current = store.conversation(actor, conversation)
                if current["status"] != "open" or current["expires"] <= time.time():
                    return {"address": actor, "status": "closed", "messages": []}
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise ValueError("unknown agent operation")


def newsroom(root, action, fields, *, identity):
    if action not in {"publish", "revise", "comment", "read", "headlines", "peers", "seen"}:
        raise ValueError("unknown newsroom operation")
    result = getattr(Newsroom(MessageStore(root)), action)(identity.address, **fields)
    return {action: result} if isinstance(result, list) else result


def recall(root, query="", limit=12):
    return ProjectMemory(root).recall(query, limit=limit)


def checkpoint(root, *, identity, summary, key, decisions=(), next_steps=(), lessons=(), status="paused"):
    if not identity.is_root:
        raise TaskError("authority-denied", "project checkpoints require the root actor")
    record = ProjectMemory(root).checkpoint(identity.host, identity.session, "checkpoint:" + key,
        summary=summary, decisions=decisions, next_steps=next_steps, lessons=lessons, status=status)
    return {"status": "saved", "id": record, "host": identity.host, "session": identity.session,
            "authority": "agent-report"}


def verification(root, check, *, identity=None, require_owner=False, expected_turn=None,
                 verified_policy_evidence=None):
    from neurath.runtime.verification import VerificationError, verify

    config = json.loads((root / ".neurath/project.json").read_text())
    binding = config.get("verification", {}).get(check)
    if binding is None:
        raise VerificationError(f"unbound verifier: {check}; configure project.json verification")
    if require_owner:
        admission._verification_owner(root, identity)
    environment = None
    if expected_turn is not None:
        admission._mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
        import os
        environment = {key: value for key, value in os.environ.items() if not (
            key.startswith(("CODEX_", "CLAUDE_", "NEURATH_")) or key == "PYTHONPATH")}
    # Execution is admitted once. Later conversation does not rewrite its result.
    return verify(root, binding, environment=environment)
