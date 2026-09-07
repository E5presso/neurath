"""Canonical task operations. CLI parsing and MCP framing live outside this module.

Identities are supplied only by the native CLI resolver or the MCP capability
validator, never by task input. Persistent authority stays in the existing stores.
"""

import json
import time

from neurath.agents.newsroom import Newsroom
from neurath.agents.store import MessageStore
from neurath.memory.store import ProjectMemory, clean
from neurath.runtime.task_schema import TASKS, TaskError, arguments


def execute(root, name, inputs, *, identity, expected_turn=None, verified_policy_evidence=None):
    fields = arguments(name, inputs)
    domain, action = TASKS[name][:2]
    if domain == "provider-execution":
        from neurath.runtime.provider_execution import run

        return run(root, fields, identity=identity, expected_turn=expected_turn,
                   verified_policy_evidence=verified_policy_evidence)
    if domain == "provider":
        return provider_task(name, fields)
    if domain == "session":
        return session_status(root, identity=identity, expected_turn=expected_turn,
                              verified_policy_evidence=verified_policy_evidence)
    if domain == "agent":
        return peer(root, action, fields, identity=identity)
    if domain == "newsroom":
        return newsroom(root, action, fields, identity=identity)
    if domain == "memory":
        if action == "recall":
            return recall(root, **fields)
        return checkpoint(root, identity=identity, **fields)
    return verification(root, fields["check"], identity=identity, require_owner=True,
                        expected_turn=expected_turn, verified_policy_evidence=verified_policy_evidence)


def provider_task(name, inputs):
    from neurath.providers import operations

    fields = arguments(name, inputs)
    if name == "provider_capabilities":
        return operations.capabilities(fields["provider"])
    return operations.route(fields.pop("provider"), fields.pop("operation"),
                            **{key: value or None for key, value in fields.items()})


def session_status(root, *, identity=None, expected_turn=None, verified_policy_evidence=None):
    from neurath.providers.readiness import inspect_bound_readiness, inspect_readiness

    report = (inspect_readiness(root) if identity is None else inspect_bound_readiness(
        root, identity, expected_turn=expected_turn, verified_policy_evidence=verified_policy_evidence))
    evidence = report["stages"]["policy"]["evidence"]
    report["mode"] = {"requested": None, "requested_status": "not-recorded-by-this-invocation",
                      "effective": evidence, "status": report["stages"]["policy"]["status"]}
    native_active = identity is not None or report["stages"]["activation"]["status"] == "verified"
    root_actor = identity.is_root if identity is not None else native_active
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
        return store.send(actor, fields["to"], fields["message"], key=fields["key"],
                          kind=fields.get("kind", "question"), max_messages=fields.get("max_messages", 32),
                          ttl=fields.get("ttl", 86400))
    if action == "reply":
        return store.reply(actor, fields["message_id"], fields["message"], key=fields["key"])
    if action == "ack":
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
    owner_before = _verification_owner(root, identity) if require_owner else None
    environment = None
    if expected_turn is not None:
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
        # A background server's environment is not the caller's identity. Never
        # lend it to a check or manufacture a caller environment from arguments.
        import os

        environment = {key: value for key, value in os.environ.items() if not (
            key.startswith(("CODEX_", "CLAUDE_", "NEURATH_")) or key == "PYTHONPATH")}
    result = verify(root, binding, environment=environment)
    try:
        if require_owner and _verification_owner(root, identity) != owner_before:
            raise TaskError("native-prompt-changed", "verification finished after its native turn, user prompt or claim changed")
        if expected_turn is not None:
            # A completed process cannot lend its result to a different native turn.
            _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    except Exception as error:
        # The process already returned. A failed observer must not erase its
        # result or label this as an unstarted execution that is safe to retry.
        return {**result, "verification_status": result.get("status"),
                "status": "caller-authority-changed", "retryable": False,
                "diagnostic": clean(str(error)),
                "next_action": "Inspect the completed check before deciding whether the current task needs another execution. No learning authority was recorded."}
    if check == "check" and identity is not None and identity.is_root:
        from neurath.hosts.identity import snapshot
        from neurath.memory.learning import Learning
        from neurath.memory.transcript import synchronize

        memory = ProjectMemory(root)
        synchronize(memory, root, identity.host, identity.session, snapshot(root, identity.session))
        Learning(memory).verified(identity.host, identity.session, result)
    return result


def _direct_mcp_execution(report):
    evidence = report["stages"]["policy"]["evidence"]
    # Asking for approval is not evidence that the approval completed.
    return (report["implementation_ready"]
            and evidence.get("sandbox_policy", {}).get("type") == "danger-full-access"
            and evidence.get("approval_policy") == "never"
            and evidence.get("approvals_reviewer") in (None, "user"))


def _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence=None):
    try:
        from neurath.providers.readiness import inspect_bound_readiness
    except ImportError as error:
        raise TaskError("execution-policy-unavailable", "native execution policy observer is unavailable",
                        next_action="Use the same task through the native host shell so its sandbox and approvals apply.") from error
    report = inspect_bound_readiness(root, identity, expected_turn=expected_turn,
                                     verified_policy_evidence=verified_policy_evidence)
    if not _direct_mcp_execution(report):
        raise TaskError("native-execution-required", "MCP cannot enforce the caller's observed execution policy",
                        next_action="Use the same task through the native host shell. Preserve the actual mode, approvals and worktree claim; do not change settings to retry.")


def _verification_owner(root, identity):
    from neurath.hosts.identity import _state, active_connection
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry

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
    return (turn.generation, turn.vendor_turn_id, claim.lease_epoch,
            None if receipt is None else (receipt.turn_revision, receipt.prompt_digest))
