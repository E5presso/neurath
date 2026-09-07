"""Shared caller authority around a provider-owned bounded native run."""

from neurath.runtime.task_schema import TaskError, arguments


def run(root, inputs, *, identity=None, expected_turn=None, verified_policy_evidence=None):
    from neurath.runtime.tasks import _mcp_execution_policy, _verification_owner

    fields = arguments("provider_run", inputs)
    if identity is None and fields["mode"] != "read-only":
        raise TaskError("authority-denied", "terminal automation can only start read-only provider work")
    before = _verification_owner(root, identity) if identity is not None else None
    if expected_turn is not None:
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    from neurath.providers.execution import run as execute

    for key in ("model", "approvals_reviewer", "collaboration_mode"):
        fields[key] = fields[key] or None
    result = execute(root, **fields)
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
