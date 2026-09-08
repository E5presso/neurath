"""Authenticate the issuer before accepting a detached native session request."""

from neurath.runtime.task_schema import TaskError, arguments


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
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    if previous is not None:
        if _verification_owner(root, identity) != before:
            raise TaskError("native-prompt-changed", "caller changed before initial reconciliation")
        result = reconcile_admission(root, identity, fields["key"], fields)
    else:
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
            _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    except (OSError, ValueError, RuntimeError) as error:
        # Preserve any created native ID and partial outcome for reconciliation.
        return {**result, "provider_status": result.get("status"),
                "status": "caller-authority-changed", "retryable": False,
                "diagnostic": str(error),
                "next_action": "Inspect the returned native session and result before any new run. This result grants no current task authority."}
    return result
