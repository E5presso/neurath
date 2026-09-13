"""Canonical task operations. CLI parsing and MCP framing live outside this module.

Identities are supplied only by the native CLI resolver or the MCP capability
validator, never by task input. Persistent authority stays in the existing stores.
"""

import json
import time

from neurath.agents.newsroom import Newsroom
from neurath.agents.store import MessageStore
from neurath.memory.store import ProjectMemory
from neurath.runtime.task_schema import TASKS, TaskError, arguments


def execute(root, name, inputs, *, identity, expected_turn=None, verified_policy_evidence=None):
    fields = arguments(name, inputs)
    domain, action = TASKS[name][:2]
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
    if domain == "provider-execution":
        if action != "run":
            from neurath.providers import jobs

            if identity is None:
                raise TaskError("native-binding-required", "provider control requires its native owner")
            if action == "recover":
                _verification_owner(root, identity)
                _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
                return jobs.recover(root, identity, **fields)
            return getattr(jobs, action)(root, identity, fields["run_id"])
        from neurath.runtime.provider_execution import run

        return run(root, fields, identity=identity, expected_turn=expected_turn,
                   verified_policy_evidence=verified_policy_evidence)
    if domain == "provider":
        return provider_task(name, fields)
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


def provider_task(name, inputs):
    from neurath.providers import operations

    fields = arguments(name, inputs)
    if name == "provider_capabilities":
        return operations.capabilities(fields["provider"])
    from neurath.runtime.model_tasks import planned_route
    planning = {key: fields.pop(key) for key in
                ("plan_id", "plan_revision", "assignment_revision", "reasoning_effort")}
    result = operations.route(fields.pop("provider"), fields.pop("operation"),
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
    if detail == "full":
        report["capabilities"] = [{"transport": "task-mcp", "authority": "diagnostic",
        "operations": {name: {"implemented": True,
            "available": _direct_mcp_execution(report)
                if name in {"verification_run", "provider_run"} else native_active and
                (name != "memory_checkpoint" or root_actor)}
            for name in TASKS}}]
        if report.get("provider"):
            report["capabilities"].append(provider_task("provider_capabilities", {"provider": report["provider"]}))
    actions = []
    for stage, instruction in (
        ("installation", "Run the approved installation/update workflow and inspect its result."),
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
        _verification_owner(root, identity)
    environment = None
    if expected_turn is not None:
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
        import os
        environment = {key: value for key, value in os.environ.items() if not (
            key.startswith(("CODEX_", "CLAUDE_", "NEURATH_")) or key == "PYTHONPATH")}
    # Execution is admitted once. Later conversation does not rewrite its result.
    return verify(root, binding, environment=environment)


def _execution_ready(report, ownership_required=True, placement_required=True):
    if ownership_required and placement_required:
        return report["implementation_ready"]
    # Only a domain with its own persisted ownership-recovery gate may use this.
    return report.get("is_root", False) and all(
        report["stages"][stage]["status"] == "verified"
        for stage in ("activation", "policy", *(("ownership",) if ownership_required else ()),
                      *(("installation",) if placement_required else ())))


def _direct_mcp_execution(report, ownership_required=True, placement_required=True):
    evidence = report["stages"]["policy"]["evidence"]
    # Asking for approval is not evidence that the approval completed.
    return (_execution_ready(report, ownership_required, placement_required)
            and evidence.get("sandbox_policy", {}).get("type") == "danger-full-access"
            and evidence.get("approval_policy") == "never"
            and evidence.get("approvals_reviewer") in (None, "user"))


def _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence=None, *, ownership_required=True, placement_required=True, require_current_prompt=True):
    try:
        from neurath.providers.readiness import inspect_bound_readiness
    except ImportError as error:
        raise TaskError("execution-policy-unavailable", "native execution policy observer is unavailable",
                        next_action="Inspect session_status and diagnostics_project. Restore the native policy observer before retrying this named tool; preserve the current permissions.") from error
    report = inspect_bound_readiness(root, identity, expected_turn=expected_turn,
                                     verified_policy_evidence=verified_policy_evidence,
                                     **({} if require_current_prompt else {"require_current_prompt": False}))
    if not placement_required:
        from neurath.doctor import integrity
        if integrity()["status"] != "passed":
            raise TaskError("distribution-integrity-failed", "Recovery requires an intact running harness package")
    direct = _direct_mcp_execution(report, ownership_required, placement_required)
    if identity is not None and identity.host == "claude-code" and _execution_ready(report, ownership_required, placement_required):
        from neurath.runtime.provider_policy import controls
        evidence = report["stages"]["policy"]["evidence"]
        confinement = controls(root, identity.host, evidence)
        direct = (evidence.get("permission_mode") == "bypassPermissions"
                  and confinement["filesystem"] in {"unrestricted", "unobserved"}
                  and confinement["network"] in {"unrestricted", "unobserved"}
                  and not confinement["tool_denylist"])
    if not direct:
        raise TaskError("native-execution-required", "MCP cannot enforce the caller's observed execution policy",
                        next_action="Inspect session_status for the observed policy and report this operation as unsupported in that mode. Preserve permissions and the worktree claim; do not change settings or replay through another transport.")
    return report


def _verification_owner(root, identity):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry

    from neurath.hosts.identity import _state, active_connection

    if identity is None or not identity.is_root:
        raise TaskError("authority-denied", "verification requires a native root and worktree claim")
    state = _state(root, identity.session)
    actor = state.actors.get(identity.actor)
    turn = state.foreground_turns.get(identity.actor)
    if (state.session.status.value != "active" or actor is None or actor.status.value != "active"
            or turn is None or turn.status.value != "active" or not active_connection(root, identity.session)):
        raise TaskError("authority-denied", "verification requires the current active native turn")
    canonical = WorktreeIdentityResolver().resolve(root)
    claim = WorktreeRegistry(SessionLocator.from_worktree(root)).get(canonical.worktree_id)
    if (state.session.root_actor_id != identity.actor or claim.path != canonical.path
            or str(claim.session_id) != identity.session or str(claim.actor_id) != identity.actor
            or claim.status.value != "active"):
        raise TaskError("authority-denied", "verification requires the current worktree owner")
    receipt = turn.user_prompt_receipt
    return (turn.generation, turn.vendor_turn_id, (claim.lease_epoch, claim.fencing_token),
            None if receipt is None else (receipt.turn_revision, receipt.prompt_digest))
