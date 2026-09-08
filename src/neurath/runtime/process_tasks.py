"""MCP faces for process evidence, isolated worktrees, and merge cleanup."""
import subprocess
from pathlib import Path


def definitions():
    from neurath.runtime.task_schema import choice, document_field, text_field
    key = {"key": text_field(512)}
    workflow = {"workflow_id": text_field(256)}
    entries = {
        "process_evidence_record": ("Record an existing structured event result in the exact workflow. Copy the event result into value; merged uses {} and verifies the registered PR itself. Monitor subscriptions retain live process checks; report-only fields do not certify completion.", {
            **workflow, "field": choice("commit_done", "push_done", "pr_opened", "failed", "merged",
                                       "monitor_event_subscription", "monitor_started"),
            "value": document_field(), **key}, False),
        "worktree_isolation": ("Validate the existing issue-worktree topology and clean distinct root, then claim the current worktree. Does not create or switch worktrees.", {
            "issue_number": {"type": "integer", "minimum": 1, "maximum": 2**31-1},
            "initialize": {"type": "boolean", "default": False}, **key}, False),
        "worktree_cleanup": ("Complete or recover an authorized merged-worktree cleanup through its persisted intent, exact Git refs and ownership fences. May remove the completed worktree and branch.", {
            **workflow, "base_branch": text_field(256), "remote_ref": text_field(256), **key}, False),
    }
    return {name: ("process", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence):
    from neurath.agents.store import MessageStore
    from scripts.agent_harness.session_kernel import SessionLocator
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.workflow_tasks import _guarded_handle, _request, _save
    from neurath.runtime.tasks import _mcp_execution_policy
    bound = _handle(root, identity, expected_turn, verified_policy_evidence)
    control_root = SessionLocator.from_worktree(root).control_root if name == "worktree_cleanup" else None
    result_store = MessageStore(root)
    handle = _guarded_handle(root, bound, identity, expected_turn, verified_policy_evidence,
                             connection_root=control_root)
    if name == "worktree_cleanup":
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence, ownership_required=False)
    elif name == "process_evidence_record" and fields["field"] in {"merged", "monitor_event_subscription"}:
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    previous = _request(root, identity.address, name, fields)
    if previous is not None:
        return previous
    result = _dispatch(Path(root), name, fields, handle)
    _save(root, identity.address, name, fields["key"], result, store=result_store)
    return result


def _dispatch(root, name, fields, handle):
    from scripts.agent_harness.session_kernel import SessionLocator, WorkflowId
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry, WorktreeClaim
    from neurath.runtime.bundled_services import service
    identity = WorktreeIdentityResolver().resolve(root)
    locator = SessionLocator.from_worktree(root)
    if identity.repository_control_root != locator.control_root:
        raise ValueError("worktree and session control roots differ")
    if name == "process_evidence_record":
        resources = service("monitor_resources").MonitorRuntimeResources(binding=handle._binding, worktree=identity)
        result = service("process").ProcessStateEvidenceApplication().apply_bound(
            handle=handle, workflow_id=WorkflowId(fields["workflow_id"]), resources=resources,
            field=fields["field"], value=fields["value"])
        import json
        return json.loads(result.stdout)
    if name == "worktree_cleanup":
        return service("cleanup").MergeCleanupApplication().run_bound(handle=handle, cwd=root,
            workflow_id=WorkflowId(fields["workflow_id"]), base_branch=fields["base_branch"],
            remote_ref=fields["remote_ref"])
    _isolation(root, locator.control_root)
    claim = WorktreeRegistry(locator).claim(WorktreeClaim(worktree_id=identity.worktree_id,
        path=identity.path, session_id=handle.session_id, actor_id=handle.actor_id))
    return {"status": "isolation-ok", "issue_number": fields["issue_number"],
            "mode": "init" if fields["initialize"] else "check", "claim": claim.to_payload()}


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("isolation Git read-back failed: " + result.stderr[-1000:])
    return result.stdout.strip()


def _isolation(worktree, root):
    if worktree.resolve() == root.resolve():
        raise ValueError("isolation-failed: cwd-is-root")
    branch = _git(worktree, "branch", "--show-current")
    root_branch = _git(root, "branch", "--show-current")
    if not branch or not root_branch or branch == root_branch:
        raise ValueError("isolation-failed: root and task branches must be distinct attached branches")
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true" or _git(root, "rev-parse", "--is-bare-repository") != "false":
        raise ValueError("isolation-failed: root worktree is invalid")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("isolation-failed: root worktree has uncommitted changes")
