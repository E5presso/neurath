"""Opaque installation plans over the existing CLI transaction engine."""
import json
import re
from pathlib import Path


def definitions():
    from neurath.runtime.task_schema import choice, text_field
    key = {"key": text_field(512)}
    entries = {
        "installation_plan": ("Prepare install/update/uninstall/restore for this exact worktree. Return an opaque plan reference and change summary, never original file contents. Preparation does not apply it.", {
            "action": {"type": "string", "enum": ["install", "update", "uninstall", "restore"], "default": "install"},
            "profile": {"type": "string", "enum": ["", "generic"], "default": ""},
            "hosts": {"type": "array", "items": choice("codex", "claude-code"), "maxItems": 2, "default": []},
            "installation_id": text_field(64, default=""), "skill_prefix": text_field(128, default=""), **key}, False),
        "installation_apply": ("Apply an authorized exact plan prepared by this actor. Preserve existing transaction conflicts, journals, configuration and native execution policy.", {
            "plan_ref": text_field(71), **key}, False),
        "installation_recover": ("Recover this worktree's interrupted installation journal through the existing conservative recovery service.", key, False),
    }
    return {name: ("installation", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence):
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.workflow_tasks import _guarded_handle, _request, _save, _require_owner
    from neurath.runtime.tasks import _mcp_execution_policy
    from neurath.install.transaction import apply_plan, make_plan, recover
    handle = _guarded_handle(root, _handle(root, identity, expected_turn, verified_policy_evidence),
                             identity, expected_turn, verified_policy_evidence)
    _require_owner(root, handle)
    if name != "installation_plan":
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence,
                              placement_required=name != "installation_recover")
    prepared = None
    def preflight():
        nonlocal prepared
        if name == "installation_plan":
            prepared = _installation_call(make_plan, root, action=fields["action"], profile=fields["profile"] or None,
                hosts=fields["hosts"] or None, receipt=fields["installation_id"] or None,
                skill_prefix=fields["skill_prefix"] or None)
        elif name == "installation_apply":
            prepared = _load_plan(root, identity, fields["plan_ref"])
    previous = _request(root, identity.address, name, fields, before_reserve=preflight)
    if previous is not None:
        return previous
    if name == "installation_plan":
        result = _store_plan(root, identity, handle, prepared)
    elif name == "installation_apply":
        handle.inspect()
        result = _installation_call(apply_plan, root, prepared)
    else:
        handle.inspect()
        result = _installation_call(recover, root)
    _save(root, identity.address, name, fields["key"], result)
    return result


def _installation_call(operation, *args, **kwargs):
    from neurath.install.transaction import InstallError
    from neurath.runtime.task_schema import TaskError
    try:
        return operation(*args, **kwargs)
    except InstallError as error:
        if str(error) == "interrupted transaction: run neurath recover":
            raise TaskError("installation-recovery-required", "An interrupted installation journal requires recovery",
                state="recovery-required", next_action="Use installation_recover with a stable key, then inspect diagnostics_project before preparing a new plan.") from error
        raise


def _store_plan(root, identity, handle, plan):
    from neurath.install.plan import write_plan
    from neurath.agents.store import MessageStore
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    path = write_plan(root, plan)
    wrapper = {"schema": "neurath.installation-task-plan.v1", "plan_id": plan["id"],
               "root": str(Path(root).resolve()), "actor": identity.actor, "filename": path.name}
    reference = SessionArtifactStore(handle).put_json(wrapper).reference
    with MessageStore(root).connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS installation_task_plans "
                   "(actor TEXT,reference TEXT,root TEXT,filename TEXT,plan_id TEXT,PRIMARY KEY(actor,reference))")
        db.execute("INSERT OR IGNORE INTO installation_task_plans VALUES (?,?,?,?,?)",
                   (identity.actor, reference, str(Path(root).resolve()), path.name, plan["id"]))
    return {"plan_ref": reference, "plan_id": plan["id"], "action": plan["action"],
            "changes": [{"path": c["path"], "action": "remove" if c["after"] is None else "write"} for c in plan["changes"]]}


def _load_plan(root, identity, reference):
    from neurath.agents.store import MessageStore
    from neurath.install.transaction import git_dir
    from neurath.runtime.task_schema import TaskError
    with MessageStore(root).connection() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='installation_task_plans'").fetchone()
        row = None if not exists else db.execute(
            "SELECT * FROM installation_task_plans WHERE actor=? AND reference=?", (identity.actor, reference)).fetchone()
    if row is None or row["root"] != str(Path(root).resolve()):
        raise TaskError("plan-unavailable", "Use a plan prepared for this native actor and worktree")
    if re.fullmatch(r"[0-9a-f]{64}-[0-9a-f]{32}\.json", row["filename"]) is None:
        raise TaskError("invalid-plan-reference", "Stored plan filename is invalid")
    directory = git_dir(root) / "neurath-plans"
    path = directory / row["filename"]
    if directory.is_symlink() or path.is_symlink():
        raise TaskError("invalid-plan-reference", "Stored installation plan cannot be a symlink")
    value = json.loads(path.read_text())
    if value.get("id") != row["plan_id"]:
        raise TaskError("plan-changed", "The private installation plan changed")
    return value
