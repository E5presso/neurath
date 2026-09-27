"""Admit native operations using observed policy, live ownership and exact turns.

Domain handlers depend on this boundary, never on the task dispatcher. Recovery
exceptions are explicit parameters and retain their existing domain-specific gates.
"""

from neurath.runtime.task_schema import TaskError


def _installation_recovery(report):
    installation = report.get("stages", {}).get("installation", {}).get("evidence", {})
    placement = installation.get("placement", {})
    errors = placement.get("errors", []) if isinstance(placement, dict) else []
    if any("running package differs from recorded distribution" in str(error)
           for error in errors):
        return ("Reconnect the MCP host to load the installed distribution; do not repeatedly reinstall "
                "or change permissions to repair a stale connection.")
    return "Run the approved installation/update workflow and inspect its result."



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



def _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence=None, *, ownership_required=True, placement_required=True, require_current_prompt=True, controlled_provider_operation=False):
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
        if controlled_provider_operation:
            # Only fixed model observation or exact-plan target-native delegation
            # uses this path. Neither executes arbitrary project commands under
            # MCP or translates away the caller's native rules.
            direct = (evidence.get("permission_mode") in {
                "default", "dontAsk", "acceptEdits", "auto", "bypassPermissions"}
                and confinement["filesystem"] in {"unrestricted", "unobserved"}
                and confinement["network"] in {"unrestricted", "unobserved"})
    if not direct:
        required = ("activation", "policy", *(("ownership",) if ownership_required else ()),
                    *(("installation",) if placement_required else ()))
        failed = [name for name in required
                  if report.get("stages", {}).get(name, {}).get("status") in {"failed", "unverified", "unobserved"}]
        if failed:
            action = (_installation_recovery(report) if "installation" in failed else
                      "Inspect session_status and recover the failed readiness stages through their supported "
                      "native workflows. Preserve permissions and ownership; do not replay through another transport.")
            raise TaskError("execution-readiness-required",
                            "MCP execution readiness failed: " + ", ".join(failed), next_action=action)
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
