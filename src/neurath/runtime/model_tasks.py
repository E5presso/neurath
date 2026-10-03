"""Native-bound inventory and plan tasks; no agent-supplied availability evidence."""
import json
from dataclasses import asdict
from pathlib import Path

from neurath.project_paths import control_root
from neurath.providers.model_bindings import (
    digest as digest,
    execution_fields as execution_fields,
    policy_settings as policy_settings,
    context_for as context_for,
    typed_inventory as typed_inventory,
    decode_inventory as decode_inventory,
    InventoryStore as InventoryStore,
    store_for as store_for,
    record_observation as record_observation,
    prepare_plan as prepare_plan,
    admit_plan as admit_plan,
    verify_created_selection as verify_created_selection,
    decode_context as decode_context,
    resolve_created_plan as resolve_created_plan,
)





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
    from neurath.runtime.admission import _mcp_execution_policy, _verification_owner
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
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence,
                              controlled_provider_operation=True)
        inventory = store.session_inventory(
            identity.address, fields["provider"],
            lambda: refresh_inventory(root, fields["provider"], target),
            refresh=fields.get("refresh", False))
        result = {**store.save(identity.address, target, inventory), "inventory": asdict(inventory),
                  "freshness": "session-observation"}
    elif name == "provider_plan":
        fields = {**fields, "worktree": str(target)}
        from neurath.runtime.provider_policy import admit_inheritance, planning_policy
        policy = observed_policy(root, identity, expected_turn, verified_policy_evidence)
        observed = planning_policy(root, identity, fields, policy)
        execution = {"provider": fields["provider"], **execution_fields(fields)}
        if execution["mode"] != "target-native":
            admit_inheritance(identity, execution, observed)
        result = prepare_plan(store, identity, fields, observed)
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
        "mode":choice("inherit","target-native","read-only","workspace-write","danger-full-access","native"),
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
            ("Read the native issuer's cached provider model catalog across turns and worktrees. "
             "Call once for each target worktree to obtain its inventory_id; IDs are target-bound, "
             "while catalog metadata is reused without another provider connection. "
             "The first request observes metadata without a model turn. Use refresh only for an explicit "
             "refresh request or a known availability change. Catalog recommendations are not configured defaults."),
            {"provider":choice("codex","claude-code"),"worktree":t(4096,default=""),
             "refresh":{"type":"boolean","default":False}},False),
        "provider_plan":("model-plan","plan",
            ("Validate and persist a difficulty-aware model proposal against an owned native inventory. "
             "Use the inventory_id returned by provider_models for this exact worktree. "
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
    inventory = store.session_inventory(
        identity.address, fields["provider"],
        lambda: refresh_inventory(root, fields["provider"], fields["worktree"]))
    plan = admit_plan(store, identity, fields, policy, inventory)
    request = {k:v for k,v in fields.items() if k != "key"}
    return {**fields, "model_request": request, "model_plan": plan,
            "model": None if plan["proposal"]["selection"]["model"] == "inherit" else plan["resolved_model_id"],
            "reasoning_effort": plan["proposal"]["selection"]["reasoning"]}


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
    original = request.get("model_request", request)
    # Additive schema defaults must not turn an old accepted request into a new
    # execution. Explicit nondefault intent still conflicts with the saved key.
    for name, default in (("purpose", "task"), ("reason", ""), ("session_basis", "")):
        if name not in original and incoming.get(name) == default:
            incoming.pop(name, None)
    if original != incoming:
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
