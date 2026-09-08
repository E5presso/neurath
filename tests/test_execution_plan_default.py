"""Explicit model selection is not evidence of the target host default."""
from types import SimpleNamespace
from neurath.providers import execution_plan
from neurath.providers.model_planning import Inventory,ModelInfo
from neurath.runtime.model_tasks import InventoryStore,prepare_plan

def test_explicit_created_model_does_not_become_target_default(tmp_path,monkeypatch):
    store=InventoryStore(tmp_path/"plans.sqlite3")
    identity=SimpleNamespace(address="owner")
    observed=Inventory("claude-code","local","sdk","rev",models=(ModelInfo("exact"),))
    ref=store.save("owner",str(tmp_path),observed)
    fields={"provider":"claude-code","worktree":str(tmp_path),"assignment":"work",
            "assignment_revision":1,"execution":{"mode":"native","permission_mode":"dontAsk"},
            "selection":{"model":"exact"},"difficulty":"routine","evidence":["check"],
            "confidence":"high","rationale":"sufficient","rejected_alternatives":[],
            "replan_triggers":["change"],"constraints":{},"key":"p",**ref}
    plan=prepare_plan(store,identity,fields,{"permission_mode":"dontAsk"})
    session=SimpleNamespace(actual_model="exact",requested_model="exact",transport="claude-agent-sdk",
                            native_session="native",worktree=str(tmp_path))
    observation={"provider":"claude-code","host":"local","source":"sdk","status":"observed",
                 "observed_at":1,"models":[{"id":"exact"}],"default_model":None}
    monkeypatch.setattr(execution_plan,"store_for",lambda root:store)
    execution_plan.created_plan(tmp_path,"owner","run",plan,session,observation)
    assert store.latest("owner",str(tmp_path),"claude-code").default_model is None
