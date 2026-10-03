"""Shared text history helpers remain separate from maintenance option consent."""
import hashlib
import pytest
from neurath.runtime.user_choices import target, verify_registered_prompt

def test_claude_ask_user_question_is_not_treated_as_a_verified_user_reply(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from neurath.hosts import identity as native_identity
    from neurath.runtime.user_choices import native_messages
    path=tmp_path/"native.jsonl"
    monkeypatch.setattr(native_identity,"snapshot",lambda *a:{"transcript":str(path)})
    records=[
      {"type":"assistant","sessionId":"native","message":{"content":[{"type":"tool_use","id":"ask-1","name":"AskUserQuestion","input":{"questions":[{"question":"Approve?"}]}}]}},
      {"type":"user","sessionId":"native","message":{"content":[{"type":"tool_result","tool_use_id":"ask-1","content":"yes"}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records)+"\n")
    assert native_messages(tmp_path,SimpleNamespace(host="claude-code",session="native"))==[]
    records.extend([
      {"type":"assistant","sessionId":"native","message":{"content":[{"type":"text","text":"Approve?"}]}},
      {"type":"user","sessionId":"native","message":{"content":"동의합니다"}},
    ])
    path.write_text("\n".join(json.dumps(r) for r in records)+"\n")
    assert native_messages(tmp_path,SimpleNamespace(host="claude-code",session="native"))==[
      ("assistant","Approve?"),("user","동의합니다")]

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

def test_registered_prompt_uses_exact_bytes_and_collapses_codex_duplicate_frames(
    tmp_path, monkeypatch,
):
    import json
    from neurath.hosts import identity as native_identity

    path = tmp_path / "native.jsonl"
    text = "  active answer\n"
    records = [
        {"type":"event_msg","payload":{"type":"user_message","message":text}},
        {"type":"response_item","payload":{"type":"message","role":"user",
            "content":[{"type":"input_text","text":text}]}},
    ]
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n")
    monkeypatch.setattr(native_identity, "snapshot", lambda *args: {
        "host":"codex", "transcript":str(path)})
    exact = hashlib.sha256(text.encode("utf-8")).hexdigest()
    proof = verify_registered_prompt(
        tmp_path, "native", f"registered-native-prompt:{exact}", exact)
    assert proof["prompt_digest"] == exact
    stripped = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="unobserved"):
        verify_registered_prompt(
            tmp_path, "native", f"registered-native-prompt:{stripped}", stripped)

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
    assert state["choices"]["offer"]["decision"]=="yes"


def test_update_choice_question_identifies_exact_same_version_asset(monkeypatch):
    offers = {
        "unknown": {"id":"unknown","current":"0.1.0","version":"0.1.0",
                    "sha256":"a"*64,"relation":"same-version-origin-unknown"},
        "distinct": {"id":"distinct","current":"0.1.0","version":"0.1.0",
                     "sha256":"b"*64,"relation":"same-version-distinct-asset"},
    }
    state = {"operation":{"phase":"prepared","offer_id":None,"plan_id":"same-plan",
                          "distribution":"d"*64,
                          "changes":[{"action":"write","path":".neurath/run"}]}}
    class Service:
        def __init__(self, root):
            pass
        def _read(self):
            return state
        def _offer(self, current, offer_id):
            current["operation"]["offer_id"] = offer_id
            return offers[offer_id]
    monkeypatch.setattr("neurath.updates.Updates", Service)

    unknown = target(None, "releases_choose", "unknown")["question"]
    distinct = target(None, "releases_choose", "distinct")["question"]

    assert unknown != distinct
    assert "a"*64 in unknown
    assert "b"*64 in distinct
    assert "origin unknown" in unknown
    assert "distinct from recorded installed asset" in distinct
