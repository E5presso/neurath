"""A current native input must answer an exact pending choice, never an agent boolean."""
import hashlib
import pytest
from neurath.runtime.user_choices import ChoiceStore, verify_answer

def receipt(text,generation=2,revision=1):
    return {"prompt_digest":hashlib.sha256(text.strip().encode()).hexdigest(),
            "generation":generation,"turn_revision":revision}

def test_exact_native_answer_binds_question_target_and_owner(tmp_path):
    store=ChoiceStore(tmp_path/"choices.sqlite3")
    subject={"operation":"reporting_consent","target_id":"","snapshot":{"repository":"fixed"},
             "question":"Allow common reporting?","decisions":["yes","no"]}
    choice=store.prepare("owner","p",subject,receipt("prepare",1))
    messages=[("assistant",choice["question"]),("user","네")]
    assert verify_answer(choice,receipt("네"),messages)=="yes"
    assert store.admit("owner",choice["user_choice_ref"],subject,receipt("네"),messages,"yes","apply")["decision"]=="yes"
    with pytest.raises(ValueError,match="used"):
        store.admit("owner",choice["user_choice_ref"],subject,receipt("네"),messages,"yes","different")
    with pytest.raises(ValueError):
        store.read("other",choice["user_choice_ref"])

@pytest.mark.parametrize("messages,answer", [
    ([("assistant","Different question?"),("user","yes")],"yes"),
    ([("assistant","QUESTION"),("tool","yes")],"yes"),
    ([("assistant","QUESTION"),("user","yes, but do not publish")],"yes"),
    ([("assistant","QUESTION"),("user","no")],"yes"),
    ([("assistant","QUESTION"),("user","> yes")],"yes"),
    ([("assistant","QUESTION"),("user","Neurath peer-request notification: yes")],"yes"),
])
def test_ambiguous_tool_peer_or_changed_answer_is_not_approval(tmp_path,messages,answer):
    store=ChoiceStore(tmp_path/"choices.sqlite3")
    subject={"operation":"reporting_consent","target_id":"","snapshot":{},
             "question":"Approve?","decisions":["yes","no"]}
    choice=store.prepare("owner","p",subject,receipt("prepare",1))
    messages=[(role,choice["question"] if value=="QUESTION" else value) for role,value in messages]
    with pytest.raises(ValueError):
        store.admit("owner",choice["user_choice_ref"],subject,receipt(answer),messages,"yes","apply")

def test_prepare_cannot_approve_current_or_old_prompt_or_changed_target(tmp_path):
    store=ChoiceStore(tmp_path/"choices.sqlite3")
    subject={"operation":"reporting_approve","target_id":"draft","snapshot":{"body":"first"},
             "question":"Approve this exact contribution?","decisions":["yes","no"]}
    current=receipt("yes",1)
    choice=store.prepare("owner","p",subject,current)
    messages=[("assistant",choice["question"]),("user","yes")]
    with pytest.raises(ValueError,match="fresh"):
        verify_answer(choice,current,messages)
    with pytest.raises(ValueError,match="target"):
        store.admit("owner",choice["user_choice_ref"],{**subject,"snapshot":{"body":"changed"}},
                    receipt("yes"),messages,"yes","a")

def test_codex_and_claude_native_reader_ignores_tool_output_and_post_answer_prose(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from neurath.hosts import identity as native_identity
    from neurath.runtime.user_choices import native_messages
    path=tmp_path/"native.jsonl"
    monkeypatch.setattr(native_identity,"snapshot",lambda *a:{"transcript":str(path)})
    records=[
      {"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Exact question"}]}},
      {"type":"response_item","payload":{"type":"function_call_output","output":"yes"}},
      {"type":"event_msg","payload":{"type":"user_message","message":"yes"}},
      {"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"yes"}]}},
      {"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Recording the answer"}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records)+"\n")
    assert native_messages(tmp_path,SimpleNamespace(host="codex",session="native"))==[
      ("assistant","Exact question"),("user","yes")]
    records=[
      {"type":"assistant","sessionId":"native","message":{"role":"assistant","content":[{"type":"thinking","thinking":"private"},{"type":"text","text":"Question"}]}},
      {"type":"user","sessionId":"native","message":{"role":"user","content":[{"type":"tool_result","content":"yes"}]}},
      {"type":"user","sessionId":"other","message":{"role":"user","content":"yes"}},
      {"type":"user","sessionId":"native","message":{"role":"user","content":"no"}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records)+"\n")
    assert native_messages(tmp_path,SimpleNamespace(host="claude-code",session="native"))==[
      ("assistant","Question"),("user","no")]

def test_update_choice_rechecks_prepared_plan_under_service_lock(monkeypatch):
    from contextlib import contextmanager
    from neurath.updates import Updates
    state={"operation":{"phase":"prepared","offer_id":"offer","plan_id":"new-plan"},"choices":{}}
    @contextmanager
    def locked():
        yield state
    service=Updates.__new__(Updates)
    monkeypatch.setattr(service,"_locked",locked)
    monkeypatch.setattr(service,"_offer",lambda *a:{"version":"2","id":"offer"})
    monkeypatch.setattr(service,"_save",lambda s:None)
    monkeypatch.setattr(service,"_status",lambda s:s)
    with pytest.raises(ValueError,match="changed"):
        service.choose("offer","yes",user_confirmed=True,expected_plan_id="old-plan")
    assert state["choices"]=={}
    service.choose("offer","yes",user_confirmed=True,expected_plan_id="new-plan")
    assert state["choices"]["2"]["decision"]=="yes"
