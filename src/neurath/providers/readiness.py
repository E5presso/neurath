"""Fresh, read-only readiness diagnostics over host and kernel evidence.

A report is never a capability. CLI callers resolve their native identity; MCP
callers use only the identity/turn already verified by the core's invocation
binding. No public tool accepts identity or cached readiness as authority.
"""

import os
from pathlib import Path

from neurath.memory.store import canonical
from neurath.providers.contracts import ExecutionPolicy
from neurath.runtime.engine import activate


class SessionNotReady(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("session is not ready for implementation; inspect stage results")


def _stage(status, reason=None, evidence=None):
    return {"status": status, "reason": reason, "evidence": evidence or {}}


def _assess(stages, *, waiting=None):
    ready = waiting is None and all(stages.get(name, {}).get("status") == "verified"
        for name in ("installation", "activation", "policy", "ownership"))
    policy = stages.get("policy", {}).get("evidence", {})
    can_implement = (
        policy.get("permission_mode") in ("default", "acceptEdits", "dontAsk", "auto", "bypassPermissions")
        or policy.get("sandbox_policy", {}).get("type") in ("workspace-write", "danger-full-access")
    ) and policy.get("collaboration_mode") != "plan"
    return {"authority": "diagnostic", "stages": stages, "waiting": waiting,
            "observation_ready": ready, "implementation_ready": ready and can_implement}


def _claude_policy(evidence, identity, expected_turn):
    if not isinstance(evidence, dict):
        return _stage("unobserved", "policy-unobservable")
    if (evidence.get("host") != "claude-code" or evidence.get("session") != identity.session
            or evidence.get("actor") != identity.actor or evidence.get("turn") != expected_turn
            or not isinstance(evidence.get("tool_use_id"), str) or not evidence["tool_use_id"]
            or not isinstance(evidence.get("permission_mode"), str) or not evidence["permission_mode"]):
        return _stage("failed", "policy-binding-mismatch")
    return _stage("verified", evidence={**evidence, "source": "native-hook",
        "sandbox_observation": "unobserved"})


def _prompt_matches(evidence, turn):
    receipt = turn.user_prompt_receipt
    current = None if receipt is None else {"turn_revision": receipt.turn_revision,
                                            "prompt_digest": receipt.prompt_digest}
    return "user_prompt_receipt" in evidence and evidence["user_prompt_receipt"] == current


def _codex_policy(path, native_turn, root):
    from neurath.hosts.identity import _reverse_native_records

    for record in _reverse_native_records(path, {"turn_context"}):
        if record.get("type") != "turn_context":
            continue
        context = record.get("payload", {})
        if (not isinstance(context, dict) or context.get("turn_id") != native_turn
                or context.get("cwd") != str(root)
                or not isinstance(context.get("sandbox_policy"), dict)
                or not isinstance(context.get("approval_policy"), (str, dict))):
            break
        evidence = {key: context.get(key) for key in (
            "turn_id", "cwd", "approval_policy", "approvals_reviewer", "sandbox_policy")}
        collaboration = context.get("collaboration_mode")
        evidence["collaboration_mode"] = collaboration.get("mode") if isinstance(collaboration, dict) else None
        return _stage("verified", evidence=evidence)
    return _stage("unobserved", "policy-unobservable")


def _installation(root):
    from neurath.doctor import doctor
    from neurath.install.transaction import read_state

    try:
        report = doctor(root, protocol=False)
        record = read_state(root)
        if (not record or report["distribution"]["status"] != "passed"
                or report["placement"]["status"] != "passed"):
            return _stage("failed", "installation-not-ready", report)
        return _stage("verified", evidence={"distribution": record["distribution"],
                                             "placement": report["placement"]["status"]})
    except (OSError, ValueError, RuntimeError) as error:
        return _stage("failed", "installation-not-ready", {"error": str(error)})


def inspect_bound_readiness(root, identity, *, expected_turn, requested_policy=None,
                            verified_policy_evidence=None):
    """Internal core API. The core must verify the native invocation before calling.

    Re-read the kernel/host/claim even for a verified caller. This does not claim a
    workspace, register a session, change a mode, run protocol fixtures, or resume.
    """
    activate(root)
    from neurath.hosts.identity import _transcript, active_connection, native_root_turn, snapshot
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry

    root = Path(root).resolve()
    if requested_policy is not None and not isinstance(requested_policy, ExecutionPolicy):
        raise ValueError("requested_policy must be an ExecutionPolicy")
    stages = {"installation": _installation(root),
              "activation": _stage("unobserved", "activation-unobserved"),
              "policy": _stage("unobserved", "policy-unobservable"),
              "ownership": _stage("unobserved", "claim-unobserved")}
    result = {"provider": identity.host, "native_session": identity.session,
              "actor": identity.actor, "worktree": str(root)}
    try:
        locator = SessionLocator.from_worktree(root)
        kernel = SessionKernel(locator)
        state = kernel.inspect(SessionId(identity.session))
        actor = state.actors.get(identity.actor)
        turn = state.foreground_turns.get(identity.actor)
        if (not identity.is_root or state.session.runtime.value != identity.host
                or state.session.root_actor_id != identity.actor or actor is None
                or actor.parent_actor_id is not None or actor.status.value != "active"
                or state.session.status.value != "active" or turn is None
                or turn.status.value != "active"
                or canonical([turn.generation, turn.vendor_turn_id]) != expected_turn):
            raise ValueError("native session/actor/foreground binding differs or is inactive")
        if verified_policy_evidence is not None and not _prompt_matches(verified_policy_evidence, turn):
            raise ValueError("native user prompt changed after invocation binding")
        data = snapshot(root, identity.session)
        if (data.get("host") != identity.host or not data.get("transcript")
                or not data.get("start_source") or not active_connection(root, identity.session)):
            raise ValueError("native lifecycle connection is not verified")
        # Do not obtain a transcript from arbitrary caller input or project config.
        path = _transcript(identity.host, data["transcript"], os.environ)
        if identity.host == "codex":
            if not native_root_turn(root, path, identity.session, turn.vendor_turn_id):
                raise ValueError("native root turn is not current")
            stages["policy"] = _codex_policy(path, turn.vendor_turn_id, root)
        else:
            # Only the core's verified current native invocation can supply this.
            # permission_mode is distinct from OS sandbox confinement.
            stages["policy"] = _claude_policy(verified_policy_evidence, identity, expected_turn)
        stages["activation"] = _stage("verified", evidence={
            "native_session": identity.session, "actor": identity.actor,
            "native_turn": turn.vendor_turn_id, "generation": turn.generation,
            "kernel_revision": state.revision, "start_source": data["start_source"]})
        result["native_turn"] = turn.vendor_turn_id
        if requested_policy and stages["policy"]["status"] == "verified":
            effective = stages["policy"]["evidence"]
            if (effective.get("approval_policy") != requested_policy.approval
                    or effective.get("sandbox_policy", {}).get("type") != requested_policy.mode
                    or requested_policy.approvals_reviewer is not None
                        and effective.get("approvals_reviewer") != requested_policy.approvals_reviewer
                    or requested_policy.collaboration_mode is not None
                        and effective.get("collaboration_mode") != requested_policy.collaboration_mode):
                stages["policy"] = _stage("failed", "policy-mismatch", effective)
        try:
            worktree = WorktreeIdentityResolver().resolve(root)
            claim = WorktreeRegistry(locator).get(worktree.worktree_id)
            if (claim.path != root or claim.session_id != state.session.id
                    or claim.actor_id != actor.id or claim.status.value != "active"):
                stages["ownership"] = _stage("failed", "claim-conflict")
            else:
                stages["ownership"] = _stage("verified", evidence={
                    "worktree_id": str(claim.worktree_id), "session": str(claim.session_id),
                    "actor": str(claim.actor_id), "lease_epoch": claim.lease_epoch})
        except (OSError, ValueError, RuntimeError) as error:
            stages["ownership"] = _stage("failed", "claim-unavailable", {"error": str(error)})
        if kernel.inspect(state.session.id).revision != state.revision:
            stages["activation"] = _stage("failed", "observation-changed")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        stages["activation"] = _stage("failed", "activation-failed", {"error": str(error)})
    return {**result, **_assess(stages)}


def inspect_readiness(root, *, requested_policy=None):
    """CLI adapter only. A background MCP server must use inspect_bound_readiness."""
    activate(root)
    from neurath.agents.identity import current_agent
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    try:
        identity = current_agent(root)
        state = SessionKernel(SessionLocator.from_worktree(Path(root))).inspect(SessionId(identity.session))
        turn = state.foreground_turns[identity.actor]
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        return _assess({"installation": _installation(Path(root).resolve()),
                        "activation": _stage("failed", "activation-failed", {"error": str(error)}),
                        "policy": _stage("unobserved", "policy-unobservable"),
                        "ownership": _stage("unobserved", "claim-unobserved")})
    return inspect_bound_readiness(root, identity,
        expected_turn=canonical([turn.generation, turn.vendor_turn_id]), requested_policy=requested_policy)


def require_ready(root, *, requested_policy=None):
    report = inspect_readiness(root, requested_policy=requested_policy)
    if not report["implementation_ready"]:
        raise SessionNotReady(report)
    return report


def inspect_owned_session(session):
    """Internal adapter API for an ID returned by its own native thread/start.

    The adapter first checks handle ownership. The ID only locates evidence: host
    root/turn proof and an exact active claim must still pass fresh checks below.
    This must not be exposed as a public identity-accepting tool.
    """
    from neurath.agents.store import AgentIdentity

    root = Path(session.worktree).resolve()
    activate(root)
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    try:
        state = SessionKernel(SessionLocator.from_worktree(root)).inspect(SessionId(session.native_session))
        actor = state.session.root_actor_id
        turn = state.foreground_turns[actor]
        requested = session.policy["requested"]
        return inspect_bound_readiness(root,
            AgentIdentity(session.provider, session.native_session, str(actor), True),
            expected_turn=canonical([turn.generation, turn.vendor_turn_id]),
            requested_policy=ExecutionPolicy(requested["mode"], requested["approval_policy"],
                requested.get("approvals_reviewer"), requested.get("collaboration_mode")))
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        return _assess({"installation": _installation(root),
                        "activation": _stage("failed", "activation-failed", {"error": str(error)}),
                        "policy": _stage("unobserved", "policy-unobservable"),
                        "ownership": _stage("unobserved", "claim-unobserved")})
