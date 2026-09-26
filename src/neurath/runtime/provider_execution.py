"""Authenticate the issuer before accepting a detached native session request."""

from neurath.runtime.task_schema import TaskError, arguments


def _worktree_worker_preflight(root, fields):
    """Keep root ticket routing separate from an ordinary same-checkout child."""
    from pathlib import Path
    from neurath.providers.execution import _target
    from neurath.runtime.process_tasks import _git, _isolation
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import (
        WorktreeIdentityResolver, WorktreeNotClaimed, WorktreeRegistry,
    )

    source = Path(root).resolve()
    locator = SessionLocator.from_worktree(source)
    if source != locator.control_root:
        raise TaskError("root-worktree-required", "worktree-worker is only for a repository-root ticket entry")
    target = _target(source, fields["worktree"], "workspace-write")
    _isolation(target, source)
    if _git(target, "status", "--porcelain=v1", "--untracked-files=all"):
        raise TaskError("target-worktree-dirty", "worktree-worker target has uncommitted changes")
    worktree = WorktreeIdentityResolver().resolve(target)
    try:
        WorktreeRegistry(locator).get(worktree.worktree_id)
    except WorktreeNotClaimed:
        return
    raise TaskError("target-worktree-claimed", "worktree-worker target already has an owner")


def run(root, inputs, *, identity=None, expected_turn=None, verified_policy_evidence=None):
    from neurath.runtime.tasks import _mcp_execution_policy, _verification_owner

    fields = arguments("provider_run", inputs)
    if identity is None:
        raise TaskError("native-binding-required", "asynchronous work requires a native issuing session")
    before = _verification_owner(root, identity) if identity is not None else None
    from neurath.memory.store import canonical
    from neurath.runtime.model_tasks import (
        admitted_request,
        observed_policy,
        previous_admission,
        reconcile_admission,
    )
    from neurath.runtime.provider_policy import resolve_policy
    previous = previous_admission(root, identity, fields["key"], fields)
    if previous is not None and not previous["reconciliation_required"]:
        return previous
    if expected_turn is not None:
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence,
                              **({"controlled_provider_operation": True} if fields.get("mode") == "target-native" else {}))
    if previous is not None:
        if _verification_owner(root, identity) != before:
            raise TaskError("native-prompt-changed", "caller changed before initial reconciliation")
        result = reconcile_admission(root, identity, fields["key"], fields)
    else:
        from neurath.providers.collaboration_policy import select
        selection = select(identity.host, fields["provider"], fields.get("purpose", "task"), fields.get("reason", ""))
        if selection["kind"] == "native-subagent":
            raise TaskError("native-subagent-required", "Use delegation_prepare and the native child tool for work owned by this session")
        if fields.get("purpose") == "worktree-worker":
            _worktree_worker_preflight(root, fields)
        policy = observed_policy(root, identity, expected_turn or canonical(list(before[:2])), verified_policy_evidence)
        fields = admitted_request(root, identity, fields, policy)
        fields = resolve_policy(root, identity, fields, policy)
        from neurath.providers.jobs import start

        for key in ("model", "approval_policy", "approvals_reviewer", "collaboration_mode", "permission_mode", "project_id"):
            fields[key] = fields[key] or None
        key = fields.pop("key")
        result = start(root, identity, fields, key=key)
    try:
        if identity is not None and _verification_owner(root, identity) != before:
            raise TaskError("native-prompt-changed", "caller turn, prompt or worktree claim changed")
        if expected_turn is not None:
            _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence,
                                  **({"controlled_provider_operation": True} if inputs.get("mode") == "target-native" else {}))
    except (OSError, ValueError, RuntimeError) as error:
        # Preserve any created native ID and partial outcome for reconciliation.
        return {**result, "provider_status": result.get("status"),
                "status": "caller-authority-changed", "retryable": False,
                "diagnostic": str(error),
                "next_action": "Inspect the returned native session and result before any new run. This result grants no current task authority."}
    return result
