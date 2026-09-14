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

def test_owned_native_alias_resolves_plan_before_assignment(tmp_path,monkeypatch):
    import pytest
    from neurath.providers.contracts import Session
    from neurath.runtime import model_tasks
    store=InventoryStore(tmp_path/'plans.sqlite3')
    monkeypatch.setattr(execution_plan,'store_for',lambda root:store)
    monkeypatch.setattr(model_tasks,'store_for',lambda root:store)
    observed=Inventory('claude-code','local','sdk','rev',models=(ModelInfo('sonnet'),))
    ref=store.save('owner',str(tmp_path),observed)
    fields={'provider':'claude-code','worktree':str(tmp_path),'assignment':'work',
        'execution':{'mode':'target-native'},'selection':{'model':'sonnet'},
        'difficulty':'routine','evidence':['bounded work'],'confidence':'high','rationale':'sufficient',
        'rejected_alternatives':[],'replan_triggers':['scope changes'],
        'constraints':{'explicit_model':'sonnet'},'key':'plan',**ref}
    plan=prepare_plan(store,SimpleNamespace(address='owner'),fields,{'permission_mode':'auto'})
    resolution={'requested':'sonnet','actual':'native-resolved-model',
        'source':'claude-agent-sdk:system/init','native_session':'native'}
    session=Session('claude-code','claude-agent-sdk','native',str(tmp_path),'sonnet',
        'native-resolved-model',{'native_model_resolution':resolution})
    observation={'provider':'claude-code','host':'local','source':'sdk','status':'observed',
        'observed_at':1,'models':[{'id':'sonnet'}]}
    resolved=execution_plan.created_plan(tmp_path,'owner','run',plan,session,observation)
    assert resolved['revision']==plan['revision']+1
    assert resolved['proposal']['selection']['model']=='sonnet'
    assert resolved['resolved_model_id']=='native-resolved-model'
    assert model_tasks.verify_created_selection(resolved,'native-resolved-model')['status']=='verified'
    with pytest.raises(ValueError,match='mismatch'):
        model_tasks.verify_created_selection(resolved,'different')
    assert store.latest('owner',str(tmp_path),'claude-code').default_model is None
