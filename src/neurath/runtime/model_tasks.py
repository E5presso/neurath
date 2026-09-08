"""Native-bound inventory and plan tasks; no agent-supplied availability evidence."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from neurath.memory.store import canonical, control_root
from neurath.providers.model_planning import (
    Constraints,
    Inventory,
    ModelInfo,
    ModelPlanStore,
    PlanContext,
    PlanProposal,
    Selection,
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
            "source_controls", "target_controls", "policy_mapping_revision")
    native = evidence.get("native_fields", evidence)
    result = {key: native[key] for key in keys if key in native}
    for key in ("source_controls", "target_controls", "policy_mapping_revision"):
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
        **m, "capabilities": tuple(m["capabilities"]), "reasoning": tuple(m["reasoning"])
    }) for m in data["models"])})


class InventoryStore:
    def __init__(self, path):
        self.plans = ModelPlanStore(path)
        with self.plans._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS model_inventories(
                owner TEXT, id TEXT, target TEXT, record TEXT,
                PRIMARY KEY(owner,id))""")

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
    return InventoryStore(control_root(Path(root)) / ".neurath/local/models/plans.sqlite3")


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


def observed_policy(root, identity, expected_turn, verified_policy_evidence):
    from neurath.providers.readiness import inspect_bound_readiness
    from neurath.runtime.task_schema import TaskError
    state = inspect_bound_readiness(root, identity, expected_turn=expected_turn,
                                    verified_policy_evidence=verified_policy_evidence)
    policy = state["stages"]["policy"]
    if policy["status"] != "verified":
        raise TaskError("native-policy-unavailable", "model plans require actual caller policy")
    # Turn IDs are authority evidence, not execution settings. They must not make
    # every follow-up turn stale when the effective policy is unchanged.
    return dict(policy["evidence"])


def refresh_inventory(root, provider, target, *, claude_client=None):
    from neurath.providers.model_inventory import codex_inventory
    if provider == "codex":
        from neurath.providers.stdio import CodexStdio
        transport = CodexStdio(target)
        try:
            return typed_inventory(codex_inventory(transport, host="local"))
        finally:
            transport.close()
    if provider == "claude-code":
        from neurath.providers.model_inventory import claude_inventory_process
        return typed_inventory(claude_inventory_process(target, host="local"))
    raise ValueError("unsupported provider")


def run(root, name, fields, *, identity, expected_turn=None, verified_policy_evidence=None):
    from neurath.runtime.task_schema import TaskError
    from neurath.runtime.tasks import _mcp_execution_policy, _verification_owner
    if identity is None:
        raise TaskError("native-binding-required", "model operations require native identity")
    before = _verification_owner(root, identity)
    target = Path(fields.get("worktree") or root).resolve()
    if control_root(target) != control_root(Path(root)):
        raise TaskError("target-project-mismatch", "model inventory target is outside this Git project")
    store = store_for(root)
    if name == "provider_models":
        if expected_turn is None:
            raise TaskError("native-execution-required", "inventory needs observed host policy")
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
        inventory = refresh_inventory(root, fields["provider"], target)
        result = {**store.save(identity.address, target, inventory), "inventory": asdict(inventory),
                  "freshness": "current-attempt"}
    elif name == "provider_plan":
        fields = {**fields, "worktree": str(target)}
        from neurath.runtime.provider_policy import planning_policy
        policy = observed_policy(root, identity, expected_turn, verified_policy_evidence)
        result = prepare_plan(store, identity, fields, planning_policy(root, identity, fields, policy))
    elif name == "provider_plan_read":
        result = store.plans.read(identity.address, fields["plan_id"], fields["plan_revision"])
    else:
        raise TaskError("invalid-input", "unknown model operation")
    if _verification_owner(root, identity) != before:
        raise TaskError("native-prompt-changed", "model operation owner or prompt changed",
                        state="failed-or-partial")
    return result

def definitions():
    from neurath.runtime.task_schema import choice, count, strings, text_field
    t=text_field
    def obj(properties, required=()):
        return {"type":"object","additionalProperties":False,
                "properties":properties,"required":list(required)}
    execution=obj({
        "mode":choice("inherit","read-only","workspace-write","danger-full-access","native"),
        "approval_policy":choice("never","on-request","untrusted"),
        "approvals_reviewer":choice("user","auto_review"),
        "collaboration_mode":choice("default","plan"),
        "permission_mode":choice("plan","dontAsk","default","acceptEdits","bypassPermissions","auto"),
        "project_id":t(256)})
    constraints=obj({
        "explicit_model":t(256), "allowed_providers":strings(),
        "required_capabilities":strings(),
        "min_context_tokens":{"type":"integer","minimum":0},
        "max_input_price_per_million":{"type":"number","minimum":0},
        "max_latency_ms":{"type":"number","minimum":0}})
    return {
        "provider_models":("model-plan","models",
            ("Observe native model inventory for this authorized project without starting a model turn. "
             "Catalog recommendations are not configured defaults. Unavailable metadata stays unavailable."),
            {"provider":choice("codex","claude-code"),"worktree":t(4096,default="")},False),
        "provider_plan":("model-plan","plan",
            ("Validate and persist a difficulty-aware model proposal against an owned native inventory. "
             "Record task evidence, constraints and rationale. This typed operation owns its persistence; "
             "no separate material_prepare or adaptive workflow is required. Does not create a session or grant authority."),
            {"provider":choice("codex","claude-code"),"worktree":t(4096),
             "assignment":t(),"assignment_revision":count(1,maximum=2147483647),
             "inventory_id":t(128),"execution":execution,
             "selection":obj({"model":t(256),"reasoning":t(100)},("model",)),
             "constraints":{**constraints,"default":{}},
             "difficulty":choice("routine","standard","complex"),
             "evidence":{**strings(),"minItems":1},"confidence":choice("low","medium","high"),
             "rationale":t(),"rejected_alternatives":strings(),
             "replan_triggers":{**strings(),"minItems":1},
             "key":t(512),"plan_id":t(128,default=""),
             "expected_revision":count(0,maximum=2147483647,minimum=0)},False),
        "provider_plan_read":("model-plan","read",
            "Read an owned plan revision; stored evidence is not current model availability or authority.",
            {"plan_id":t(128),"plan_revision":count(1,maximum=2147483647)},True),
    }

def admitted_request(root, identity, fields, policy):
    """Validate a NEW request before host policy inheritance normalizes its fields.

    The provider job must keep model_request unchanged for keyed outcome lookup,
    strip model_request/model_plan from adapter kwargs, and validate the native
    created model with verify_created_selection before substantive dispatch.
    """
    from neurath.runtime.task_schema import TaskError
    if not fields.get("plan_id") or not fields.get("plan_revision"):
        raise TaskError("model-plan-required", "Plan the model before creating an independent session",
                        next_action="Use provider_models then provider_plan for this assignment.")
    from neurath.runtime.provider_policy import planning_policy
    policy = planning_policy(root, identity, fields, policy)
    store = store_for(root)
    inventory = refresh_inventory(root, fields["provider"], fields["worktree"])
    plan = admit_plan(store, identity, fields, policy, inventory)
    request = {k:v for k,v in fields.items() if k != "key"}
    return {**fields, "model_request": request, "model_plan": plan,
            "model": None if plan["proposal"]["selection"]["model"] == "inherit" else plan["resolved_model_id"],
            "reasoning_effort": plan["proposal"]["selection"]["reasoning"]}


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


def resolve_created_plan(root, owner, plan, current_inventory, *, run_id):
    """Internal accepted-worker transition, not a public native-identity input."""
    if plan["proposal"]["selection"]["model"] != "inherit":
        return plan
    proposal = plan["proposal"]
    typed = PlanProposal(decode_context(proposal["context"]), Selection(**proposal["selection"]),
                         proposal["difficulty"], tuple(proposal["evidence"]),
                         proposal["confidence"], proposal["rationale"],
                         tuple(proposal["rejected_alternatives"]), tuple(proposal["replan_triggers"]))
    return store_for(root).plans.prepare(owner, "resolve:"+run_id, typed, current_inventory,
                                          plan_id=plan["plan_id"], expected_revision=plan["revision"])

def previous_admission(root, identity, key, fields):
    """Return a prior exact accepted request before revalidating new-creation prerequisites."""
    if not key:
        return None
    from neurath.providers.jobs import _store
    identifier = digest([identity.address, key])
    with _store(root).connection() as db:
        row = db.execute("SELECT request,status,result FROM provider_jobs WHERE id=? AND owner=?",
                         (identifier,identity.address)).fetchone()
    if row is None:
        return None
    request = json.loads(row["request"])
    incoming = {k:v for k,v in fields.items() if k != "key"}
    if request.get("model_request", request) != incoming:
        raise ValueError("provider request key changed request")
    result = json.loads(row["result"]) if row["result"] else None
    return {"run_id":identifier,"status":row["status"],"replayed":True,
            "implementation_dispatched":False,"delivery":"durable-events",
            "reconciliation_required":row["status"] == "accepted" and "created" not in (result or {}),
            "result":result}


def reconcile_admission(root, identity, key, fields):
    """Internal write after CURRENT caller execution authorization; no new plan."""
    from neurath.providers.jobs import _store, start
    previous = previous_admission(root, identity, key, fields)
    if previous is None:
        raise ValueError("accepted provider request disappeared")
    if not previous["reconciliation_required"]:
        return previous
    with _store(root).connection() as db:
        row = db.execute("SELECT request FROM provider_jobs WHERE id=? AND owner=?",
                         (previous["run_id"], identity.address)).fetchone()
    return start(root, identity, json.loads(row["request"]), key=key)

def planned_route(result, fields):
    """Carry plan bindings through a routing-only result; admission still validates them."""
    operation = result.get("next_operation") or {}
    if operation.get("tool") != "provider_run":
        return result
    if not fields.get("plan_id"):
        return {**result, "status":"model-plan-required", "next_operation":None,
                "reason":"Use provider_models and provider_plan before a new independent execution."}
    planning = {k:fields[k] for k in ("plan_id","plan_revision","assignment_revision","reasoning_effort")
                if fields.get(k) not in ("",None)}
    return {**result, "next_operation":{**operation,
            "arguments":{**operation["arguments"],**planning}}}
