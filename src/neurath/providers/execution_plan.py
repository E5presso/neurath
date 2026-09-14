"""Validate a durable model plan using metadata from the newly owned connection."""

from dataclasses import replace

from neurath.providers.model_planning import ModelInfo
from neurath.runtime.model_tasks import (
    digest, resolve_created_plan, store_for, typed_inventory, verify_created_selection,
)


def created_plan(root, owner, run_id, plan, session, observation):
    inventory = typed_inventory(observation)
    actual = session.actual_model
    models = inventory.models
    if not any(model.model_id == actual for model in models):
        # Native init attests this actual model, but no unreported capability,
        # price, reasoning option or context size is inferred from that fact.
        models = (*models, ModelInfo(actual))
    resolution=getattr(session,'policy',{}).get('native_model_resolution')
    native_alias=bool(resolution and session.provider=='claude-code'
        and resolution.get('source')=='claude-agent-sdk:system/init'
        and resolution.get('native_session')==session.native_session
        and resolution.get('requested')==session.requested_model
        and resolution.get('actual')==actual
        and plan['proposal']['selection']['model']==session.requested_model)
    if native_alias:
        models=tuple(replace(model,aliases=(session.requested_model,),
            alias_source=resolution['source'],alias_revision=digest(resolution))
            if model.model_id==actual else model for model in models)
    inventory = replace(inventory, models=models, available=True)
    if session.requested_model is None:
        inventory = replace(inventory, default_model=actual, default_source=session.transport + ":native-init",
                            default_revision=digest([session.native_session, actual]))
    store_for(root).save(owner, session.worktree, inventory)
    if plan["proposal"]["selection"]["model"] == "inherit":
        if plan["status"] == "ready" and plan["resolved_model_id"] != actual:
            raise ValueError("native default changed; replan before assignment")
        plan = resolve_created_plan(root, owner, plan, inventory, run_id=run_id)
    elif native_alias:
        plan = resolve_created_plan(root,owner,plan,inventory,run_id=run_id,native_alias=True)
    expected_reasoning = plan["proposal"]["selection"]["reasoning"]
    # Reasoning is configured on the first turn. Do not claim it was observed
    # at creation; the readiness event performs that final comparison.
    if expected_reasoning is None:
        verify_created_selection(plan, actual, inventory=inventory)
    elif plan["status"] != "ready" or plan["resolved_model_id"] != actual:
        raise ValueError("model plan unresolved or native model mismatch")
    return plan


def ready_plan(plan, session, report):
    if plan is None:
        return None
    evidence = report["stages"]["policy"]["evidence"]
    return verify_created_selection(plan, session.actual_model,
                                    actual_reasoning=evidence.get("reasoning_effort"))
