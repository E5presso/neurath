"""Model-plan value conversion, inventory persistence and worker verification.

Native permission observation and task admission belong to runtime.model_tasks.
This layer accepts already observed metadata and never starts a provider session.
"""

import fcntl
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from neurath.serialization import canonical
from neurath.project_paths import control_root
from neurath.providers.model_planning import (
    Constraints, Inventory, ModelInfo, ModelPlanStore, PlanContext, PlanProposal, Selection,
)
from neurath.providers.permission_inheritance import MAPPING_REVISION

EXECUTION_FIELDS = ("mode", "approval_policy", "approvals_reviewer", "collaboration_mode",
                    "permission_mode", "project_id")


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()



def execution_fields(fields):
    source = fields.get("execution", fields)
    result = {k: source[k] for k in EXECUTION_FIELDS if source.get(k) not in ("", None)}
    result.setdefault("mode", "inherit")
    return result



def policy_settings(evidence):
    keys = ("approval_policy", "approvals_reviewer", "sandbox_policy", "sandbox_observation",
            "collaboration_mode", "permission_mode", "allowed_tools", "denied_tools",
            "permission_rules", "network_policy", "filesystem_policy",
            "source_controls", "target_controls", "target_native_settings", "policy_mapping_revision")
    native = evidence.get("native_fields", evidence)
    result = {key: native[key] for key in keys if key in native}
    for key in ("source_controls", "target_controls", "target_native_settings", "policy_mapping_revision"):
        if key in evidence:
            result[key] = evidence[key]
    if "mapping_revision" in evidence:
        result["policy_mapping_revision"] = evidence["mapping_revision"]
    return result



def context_for(fields, policy):
    constraints = dict(fields.get("constraints", {}))
    for key in ("allowed_providers", "required_capabilities"):
        if key in constraints:
            constraints[key] = tuple(constraints[key])
    return PlanContext(
        digest(fields["assignment"]), fields.get("assignment_revision", 1),
        fields["provider"], "local",
        digest({"effective": policy_settings(policy), "requested": execution_fields(fields),
                "worktree": str(Path(fields["worktree"]).resolve())}),
        policy_settings(policy).get("policy_mapping_revision", MAPPING_REVISION), Constraints(**constraints))



def typed_inventory(observation):
    models = tuple(ModelInfo(
        item["id"], tuple("input:" + v for v in (item.get("input_modalities") or [])),
        tuple(item.get("reasoning_efforts") or [])) for item in observation["models"])
    content = {k: v for k, v in observation.items() if k != "observed_at"}
    return Inventory(observation["provider"], observation["host"], observation["source"],
                     digest(content), models, observation.get("default_model"),
                     observation.get("default_source"),
                     observation.get("default_observation_revision"),
                     observation["status"] == "observed", observation["observed_at"])



def decode_inventory(data):
    return Inventory(**{**data, "models": tuple(ModelInfo(**{
        **m, "capabilities": tuple(m["capabilities"]), "reasoning": tuple(m["reasoning"]),
        "aliases": tuple(m.get("aliases", ()))
    }) for m in data["models"])})



class InventoryStore:
    def __init__(self, path=None, *, database=None):
        self.plans = ModelPlanStore(path, database=database)
        with self.plans._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS model_inventories(
                owner TEXT, id TEXT, target TEXT, record TEXT,
                PRIMARY KEY(owner,id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS session_model_inventories(
                owner TEXT NOT NULL, provider TEXT NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(owner,provider))""")

    def session_inventory(self, owner, provider, discover, *, refresh=False):
        """Reuse provider metadata for one native issuer, across turns/worktrees.

        Only explicit refresh replaces the observation. A per-issuer/provider
        mutex serializes discovery without holding the shared database writer.
        Target and execution policy admission remain separate checks on every use.
        """
        if provider not in {"codex", "claude-code"} or type(refresh) is not bool:
            raise ValueError("invalid provider inventory request")
        def cached():
            with self.plans._db() as db:
                row = db.execute(
                    "SELECT record FROM session_model_inventories WHERE owner=? AND provider=?",
                    (owner, provider)).fetchone()
                return None if row is None else decode_inventory(json.loads(row["record"]))
        previous = cached()
        if previous is not None and not refresh:
            return previous
        lock_path = self.plans.path.parent / ("catalog-" + digest([owner, provider]) + ".lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = cached()
            if previous is not None and not refresh:
                return previous
            inventory = discover()
            if not isinstance(inventory, Inventory) or inventory.provider != provider:
                raise ValueError("discovered inventory provider mismatch")
            with self.plans._db() as db:
                db.execute(
                    "INSERT INTO session_model_inventories VALUES(?,?,?) "
                    "ON CONFLICT(owner,provider) DO UPDATE SET record=excluded.record",
                    (owner, provider, canonical(asdict(inventory))))
            return inventory

    def save(self, owner, target, inventory):
        target = str(Path(target).resolve())
        record = canonical(asdict(inventory))
        identifier = digest([owner, target, record])
        with self.plans._db() as db:
            db.execute("INSERT OR IGNORE INTO model_inventories VALUES(?,?,?,?)",
                       (owner, identifier, target, record))
        return {"inventory_id": identifier}

    def latest(self, owner, target, provider):
        with self.plans._db() as db:
            row = db.execute(
                "SELECT record FROM model_inventories WHERE owner=? AND target=? "
                "AND json_extract(record, '$.provider')=? ORDER BY rowid DESC LIMIT 1",
                (owner, str(Path(target).resolve()), provider)).fetchone()
        return None if row is None else decode_inventory(json.loads(row[0]))

    def read(self, owner, identifier, target):
        with self.plans._db() as db:
            row = db.execute("SELECT record FROM model_inventories WHERE owner=? AND id=? AND target=?",
                             (owner, identifier, str(Path(target).resolve()))).fetchone()
        if row is None:
            raise ValueError("model inventory missing or owner/target mismatch")
        return decode_inventory(json.loads(row[0]))



def store_for(root):
    from neurath.runtime.database import RuntimeDatabase

    root = control_root(Path(root))
    return InventoryStore(database=RuntimeDatabase(root))



def record_observation(root, owner, target, observation):
    """Internal adapter entry point; never exposed with observation as tool input."""
    inventory = typed_inventory(observation)
    return {**store_for(root).save(owner, target, inventory), "inventory": asdict(inventory)}



def prepare_plan(store, identity, fields, policy):
    inventory = store.read(identity.address, fields["inventory_id"], fields["worktree"])
    proposal = PlanProposal(context_for(fields, policy), Selection(**fields["selection"]),
                            fields["difficulty"], tuple(fields["evidence"]), fields["confidence"],
                            fields["rationale"], tuple(fields["rejected_alternatives"]),
                            tuple(fields["replan_triggers"]))
    return store.plans.prepare(identity.address, fields["key"], proposal, inventory,
                               plan_id=fields.get("plan_id") or None,
                               expected_revision=fields.get("expected_revision") or None,
                               request_reference=fields["inventory_id"])



def admit_plan(store, identity, fields, policy, inventory):
    record = store.plans.read(identity.address, fields["plan_id"], fields["plan_revision"])
    request_model = fields.get("model") or "inherit"
    planned = record["proposal"]["selection"]
    if request_model != planned["model"] and request_model != record["resolved_model_id"]:
        raise ValueError("requested model differs from selection plan")
    if (fields.get("reasoning_effort") or None) != planned["reasoning"]:
        raise ValueError("requested reasoning differs from selection plan")
    current = {**fields, "constraints": record["proposal"]["context"]["constraints"]}
    result = store.plans.validate(identity.address, fields["plan_id"], fields["plan_revision"],
                                  context_for(current, policy), inventory)
    return {**record, **result}



def verify_created_selection(plan, actual_model, *, actual_reasoning=None, inventory=None):
    """Validate native metadata on the accepted worker before any work is sent.

    For inherit resolution the worker must supply CURRENT native inventory with
    default provenance and persist a new plan revision through resolve_created_plan.
    This function alone does not resolve an unknown plan or grant dispatch.
    """
    if not isinstance(actual_model, str) or not actual_model:
        raise ValueError("actual model is unobserved")
    if plan["status"] != "ready" or plan["resolved_model_id"] != actual_model:
        raise ValueError("model plan unresolved or native model mismatch")
    expected = plan["proposal"]["selection"]["reasoning"]
    if expected is not None and expected != actual_reasoning:
        raise ValueError("native reasoning setting is unobserved or mismatched")
    if inventory is not None:
        # Check actual native inventory again; cached catalog access is not proof
        # that the newly owned provider connection supports the assignment.
        context = decode_context(plan["proposal"]["context"])
        from neurath.providers.model_planning import _selection
        _selection(context, Selection(**plan["proposal"]["selection"]), inventory)
    return {"plan_id":plan["plan_id"],"revision":plan["revision"],
            "actual_model":actual_model,"actual_reasoning":actual_reasoning,
            "status":"verified"}



def decode_context(value):
    constraints = dict(value["constraints"])
    for name in ("allowed_providers","required_capabilities"):
        constraints[name] = tuple(constraints[name])
    return PlanContext(**{**value,"constraints":Constraints(**constraints)})



def resolve_created_plan(root, owner, plan, current_inventory, *, run_id, native_alias=False):
    """Internal accepted-worker transition, not a public native-identity input."""
    if plan["proposal"]["selection"]["model"] != "inherit" and not native_alias:
        return plan
    proposal = plan["proposal"]
    typed = PlanProposal(decode_context(proposal["context"]), Selection(**proposal["selection"]),
                         proposal["difficulty"], tuple(proposal["evidence"]),
                         proposal["confidence"], proposal["rationale"],
                         tuple(proposal["rejected_alternatives"]), tuple(proposal["replan_triggers"]))
    return store_for(root).plans.prepare(owner, "resolve:"+run_id, typed, current_inventory,
                                          plan_id=plan["plan_id"], expected_revision=plan["revision"])
