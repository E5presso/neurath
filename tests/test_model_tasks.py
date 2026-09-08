"""Plans bind adapter observations, owner, assignment, target and execution settings."""
import dataclasses
from types import SimpleNamespace
import pytest
from neurath.providers.model_planning import Inventory, ModelInfo
from neurath.runtime.model_tasks import InventoryStore, context_for, prepare_plan, admit_plan

IDENTITY=SimpleNamespace(address="codex:owner")
OBS=Inventory("codex","local","native:model/list","rev",models=(ModelInfo("exact"),))
FIELDS={"provider":"codex","worktree":"/tmp/assigned","assignment":"bounded task",
        "assignment_revision":1,"execution":{"mode":"read-only","approval_policy":"never"},
        "selection":{"model":"exact"},"difficulty":"routine","evidence":["direct diff"],
        "confidence":"high","rationale":"sufficient","rejected_alternatives":[],
        "replan_triggers":["scope changed"],"constraints":{}}


def test_inventory_is_owned_and_target_scoped(tmp_path):
    store=InventoryStore(tmp_path/"model.sqlite3")
    saved=store.save("owner","/tmp/a",OBS)
    assert store.read("owner",saved["inventory_id"],"/tmp/a") == OBS
    with pytest.raises(ValueError):
        store.read("other",saved["inventory_id"],"/tmp/a")
    with pytest.raises(ValueError):
        store.read("owner",saved["inventory_id"],"/tmp/b")


def test_plan_binds_assignment_target_and_policy_and_rejects_unobserved_model(tmp_path):
    store=InventoryStore(tmp_path/"model.sqlite3")
    saved=store.save(IDENTITY.address,FIELDS["worktree"],OBS)
    fields={**FIELDS,**saved,"key":"plan"}
    plan=prepare_plan(store,IDENTITY,fields,{"sandbox_policy":{"type":"read-only"}})
    run={"provider":"codex","worktree":FIELDS["worktree"],"assignment":FIELDS["assignment"],
         "mode":"read-only","approval_policy":"never","plan_id":plan["plan_id"],
         "plan_revision":plan["revision"],"assignment_revision":1,"model":"exact"}
    assert admit_plan(store,IDENTITY,run,{"sandbox_policy":{"type":"read-only"}},OBS)["resolved_model_id"]=="exact"
    for delta in ({"assignment":"changed"},{"worktree":"/tmp/other"},{"permission_mode":"acceptEdits"},
                  {"model":"other"}):
        with pytest.raises(ValueError):
            admit_plan(store,IDENTITY,{**run,**delta},{"sandbox_policy":{"type":"read-only"}},OBS)
    with pytest.raises(ValueError):
        admit_plan(store,IDENTITY,run,{"sandbox_policy":{"type":"workspace-write"}},OBS)
    with pytest.raises(ValueError):
        admit_plan(store,IDENTITY,run,{"sandbox_policy":{"type":"read-only"}},dataclasses.replace(OBS,models=()))


def test_context_ignores_time_but_includes_effective_and_requested_policy():
    a=context_for(FIELDS,{"permission_mode":"plan"})
    assert a == context_for(dict(FIELDS),{"permission_mode":"plan"})
    assert a != context_for(FIELDS,{"permission_mode":"acceptEdits"})


def test_policy_binding_ignores_invocation_identity_but_not_limits():
    from neurath.runtime.model_tasks import policy_settings
    a={"permission_mode":"dontAsk","tool_use_id":"a","turn":"one","actor":"A",
       "user_prompt_receipt":{"prompt_digest":"a"},"denied_tools":["Bash"]}
    b={**a,"tool_use_id":"b","turn":"two","user_prompt_receipt":{"prompt_digest":"b"}}
    assert policy_settings(a)==policy_settings(b)
    assert policy_settings(a)!=policy_settings({**b,"denied_tools":[]})


def test_latest_claude_observation_does_not_borrow_another_owner_or_provider(tmp_path):
    store=InventoryStore(tmp_path/"plans.sqlite3")
    claude=dataclasses.replace(OBS,provider="claude-code")
    store.save("a","/tmp/a",claude)
    store.save("b","/tmp/a",dataclasses.replace(claude,revision="other"))
    store.save("a","/tmp/a",OBS)
    assert store.latest("a","/tmp/a","claude-code")==claude
    assert store.latest("a","/tmp/b","claude-code") is None

def test_native_selection_cannot_dispatch_unresolved_model_or_reasoning(tmp_path):
    from neurath.runtime.model_tasks import verify_created_selection
    store=InventoryStore(tmp_path/"model.sqlite3")
    saved=store.save(IDENTITY.address,FIELDS["worktree"],OBS)
    plan=prepare_plan(store,IDENTITY,{**FIELDS,**saved,"key":"plan"},{"sandbox_policy":{"type":"read-only"}})
    assert verify_created_selection(plan,"exact")["status"]=="verified"
    for actual in (None,"other"):
        with pytest.raises(ValueError):
            verify_created_selection(plan,actual)
    with pytest.raises(ValueError):
        verify_created_selection({**plan,"status":"preparation-only","resolved_model_id":None},"exact")
    p={**plan,"proposal":{**plan["proposal"],"selection":{"model":"exact","reasoning":"high"}}}
    with pytest.raises(ValueError):
        verify_created_selection(p,"exact")

def test_previous_admission_returns_recorded_outcome_without_catalog_or_new_creation(tmp_path, monkeypatch):
    import json
    import sqlite3
    from contextlib import contextmanager
    from neurath.providers import jobs
    from neurath.runtime.model_tasks import digest, previous_admission
    path=tmp_path/"jobs.sqlite3"
    class Store:
        @contextmanager
        def connection(self):
            db=sqlite3.connect(path); db.row_factory=sqlite3.Row
            try:
                with db: yield db
            finally: db.close()
    store=Store()
    fields={"provider":"codex","assignment":"work","worktree":"/now/missing",
            "plan_id":"plan","plan_revision":1,"key":"run"}
    original={k:v for k,v in fields.items() if k!="key"}
    with store.connection() as db:
        db.execute("CREATE TABLE provider_jobs(id TEXT,owner TEXT,request TEXT,status TEXT,result TEXT)")
        db.execute("INSERT INTO provider_jobs VALUES(?,?,?,?,?)",
                   (digest([IDENTITY.address,"run"]),IDENTITY.address,
                    json.dumps({"model_request":original}),"completed",json.dumps({"answer":"saved"})))
    monkeypatch.setattr(jobs,"_store",lambda root:store)
    result=previous_admission(tmp_path,IDENTITY,"run",fields)
    assert result["replayed"] and result["result"]=={"answer":"saved"}
    with pytest.raises(ValueError,match="changed"):
        previous_admission(tmp_path,IDENTITY,"run",{**fields,"assignment":"different"})


def test_control_or_mapping_change_invalidates_model_plan(tmp_path):
    store=InventoryStore(tmp_path/"model.sqlite3")
    saved=store.save(IDENTITY.address,FIELDS["worktree"],OBS)
    policy={"permission_mode":"plan","source_controls":{"tool_denylist":["Bash"]},
            "target_controls":{"hooks":["hook-v1"]},"policy_mapping_revision":"map-1"}
    plan=prepare_plan(store,IDENTITY,{**FIELDS,**saved,"key":"p"},policy)
    run={"provider":"codex","worktree":FIELDS["worktree"],"assignment":FIELDS["assignment"],
         "mode":"read-only","approval_policy":"never","plan_id":plan["plan_id"],
         "plan_revision":1,"assignment_revision":1,"model":"exact"}
    for changed in ({"source_controls":{"tool_denylist":[]}},
                    {"target_controls":{"hooks":["hook-v2"]}},
                    {"policy_mapping_revision":"map-2"}):
        with pytest.raises(ValueError,match="stale"):
            admit_plan(store,IDENTITY,run,{**policy,**changed},OBS)

def test_plan_key_cannot_change_inventory_reference(tmp_path):
    store=InventoryStore(tmp_path/"model.sqlite3")
    first=store.save(IDENTITY.address,FIELDS["worktree"],OBS)
    second=store.save(IDENTITY.address,FIELDS["worktree"],dataclasses.replace(OBS,revision="different"))
    prepare_plan(store,IDENTITY,{**FIELDS,**first,"key":"same"},{"permission_mode":"plan"})
    with pytest.raises(ValueError,match="changed"):
        prepare_plan(store,IDENTITY,{**FIELDS,**second,"key":"same"},{"permission_mode":"plan"})

def test_route_carries_plan_reference_only_to_owned_provider_execution():
    from neurath.runtime.model_tasks import planned_route
    route={"status":"native-tool-required","next_operation":{"tool":"provider_run",
           "arguments":{"provider":"codex","worktree":"/tmp/a","assignment":"work"}}}
    fields={"plan_id":"p","plan_revision":2,"assignment_revision":3,"reasoning_effort":"high"}
    result=planned_route(route,fields)
    assert result["next_operation"]["arguments"]["plan_id"]=="p"
    assert result["next_operation"]["arguments"]["plan_revision"]==2
    assert result["next_operation"]["arguments"]["reasoning_effort"]=="high"
    assert "plan_id" not in route["next_operation"]["arguments"]
    blocked=planned_route(route,{})
    assert blocked["status"]=="model-plan-required" and blocked["next_operation"] is None

def test_nested_planning_policy_preserves_modes_mapping_and_observation_input(monkeypatch):
    from neurath.runtime.model_tasks import policy_settings, observed_policy
    from neurath.providers import readiness
    evidence={"permission_mode":"dontAsk","tool_use_id":"ephemeral",
              "configuration_observation":{"status":"verified","source":"native"},
              "target_configuration_observation":{"status":"verified","source":"target"}}
    monkeypatch.setattr(readiness,"inspect_bound_readiness",
        lambda *a,**kw:{"stages":{"policy":{"status":"verified","evidence":evidence}}})
    assert observed_policy(".",IDENTITY,"turn",{})["configuration_observation"]==evidence["configuration_observation"]
    source={"native_fields":{"permission_mode":"dontAsk"},"mapping_revision":"map-2",
            "source_controls":{"hooks":[]},"target_controls":{"hooks":[]}}
    normalized=policy_settings(source)
    assert normalized["permission_mode"]=="dontAsk"
    assert normalized["policy_mapping_revision"]=="map-2"
    assert "tool_use_id" not in normalized
