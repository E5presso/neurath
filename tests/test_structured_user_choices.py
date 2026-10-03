"""Consent comes from an option selected on its native question tool call."""
import copy
import json
from types import SimpleNamespace

import pytest

from neurath.runtime.user_choices import ChoiceStore
from neurath.runtime import user_choices


def prepared(tmp_path, host="claude-code"):
    subject = {"operation": "reporting_consent", "target_id": "", "snapshot": {"repository": "fixed"},
               "question": "Allow common reporting?", "decisions": ["yes", "no"]}
    store = ChoiceStore(tmp_path / "choices.sqlite3")
    choice = store.prepare("owner", "ask", subject, {"generation": 1, "turn_revision": 1}, host=host)
    return store, subject, choice


def selection(choice, decision="yes", call_id="ask-1"):
    option = next(o for o in choice["options"] if o["decision"] == decision)
    native = choice["native_question"]
    args = copy.deepcopy(native["arguments"])
    question = args["questions"][0]
    result = {"questions": args["questions"], "answers": {question["question"]: option["label"]}}
    return {"tool": native["tool"], "call_id": call_id, "arguments": args, "result": result}


def test_selected_option_not_fresh_prompt_hash_is_consent(tmp_path):
    store, subject, choice = prepared(tmp_path)
    selected = selection(choice)
    # AskUserQuestion returns in the same turn, without a new UserPromptSubmit.
    proof = store.admit_selection("owner", choice["user_choice_ref"], subject, selected, "yes", "apply")
    assert proof["decision"] == "yes"
    assert proof["option_digest"] == choice["options"][0]["digest"]
    assert proof["tool_call_id"] == "ask-1"
    assert proof["authority"] == "native-question-selection"
    assert "prompt_digest" not in proof
    assert store.read("owner", choice["user_choice_ref"])["selection"] == proof
    with pytest.raises(ValueError, match="used"):
        store.admit_selection("owner", choice["user_choice_ref"], subject, selected, "yes", "other")


@pytest.mark.parametrize("mutation", ["question", "label", "description", "decision", "response", "timeout", "multiple", "cancel", "prefilled"])
def test_changed_or_unselected_options_never_authorize(tmp_path, mutation):
    store, subject, choice = prepared(tmp_path)
    picked = selection(choice)
    if mutation == "question": picked["arguments"]["questions"][0]["question"] += "changed"
    if mutation == "label": picked["arguments"]["questions"][0]["options"][0]["label"] = "Different"
    if mutation == "description": picked["arguments"]["questions"][0]["options"][0]["description"] = "Different"
    if mutation == "decision": picked["result"]["answers"][choice["question"]] = "yes, but do not publish"
    if mutation == "response": picked["result"]["response"] = "Do not publish"
    if mutation == "timeout": picked["result"]["afkTimeoutMs"] = 100
    if mutation == "multiple": picked["result"]["answers"][choice["question"]] = [o["label"] for o in choice["options"]]
    if mutation == "cancel": picked["result"]["cancelled"] = True
    if mutation == "prefilled": picked["arguments"]["answers"] = picked["result"]["answers"]
    with pytest.raises(ValueError):
        store.admit_selection("owner", choice["user_choice_ref"], subject, picked, "yes", "apply")
    assert store.read("owner", choice["user_choice_ref"])["status"] == "awaiting-user"


def test_option_hash_binds_target_and_question_instance(tmp_path):
    store, subject, choice = prepared(tmp_path)
    other = store.prepare("owner", "ask-again", subject, {"generation": 1, "turn_revision": 1}, host="claude-code")
    assert choice["options"][0]["digest"] != other["options"][0]["digest"]
    with pytest.raises(ValueError):
        store.admit_selection("owner", other["user_choice_ref"], subject, selection(choice), "yes", "apply")
    with pytest.raises(ValueError, match="target"):
        store.admit_selection("owner", choice["user_choice_ref"], {**subject, "snapshot": {}}, selection(choice), "yes", "apply")


def test_claude_reader_pairs_tool_use_with_structured_result_not_prose(tmp_path, monkeypatch):
    _, _, choice = prepared(tmp_path)
    picked = selection(choice)
    path = tmp_path / "native.jsonl"
    from neurath.hosts import identity
    monkeypatch.setattr(identity, "snapshot", lambda *a: {"transcript": str(path)})
    events = [
        {"type": "assistant", "sessionId": "native", "message": {"content": [
            {"type": "tool_use", "id": "ask-1", "name": "AskUserQuestion", "input": picked["arguments"]}]}},
        {"type": "user", "sessionId": "native", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "unrelated", "content": "yes"}]}},
        {"type": "user", "sessionId": "native", "toolUseResult": picked["result"], "message": {"content": [
            {"type": "tool_result", "tool_use_id": "ask-1", "content": "Host display text with a newline\n"}]}},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events))
    observed = user_choices.native_selection(tmp_path, SimpleNamespace(host="claude-code", session="native"), choice)
    assert observed == picked
    events[-1]["message"]["content"][0]["tool_use_id"] = "wrong"
    path.write_text("\n".join(json.dumps(e) for e in events))
    with pytest.raises(ValueError):
        user_choices.native_selection(tmp_path, SimpleNamespace(host="claude-code", session="native"), choice)


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
@pytest.mark.parametrize("mutation", [None, "unrelated", "text", "cancel", "before-call", "duplicate-call", "sidechain", "changed-option"])
def test_native_reader_requires_exact_correlated_human_selection(tmp_path, monkeypatch, host, session, mutation):
    from tests.test_user_choices_mcp import question_events
    from neurath.hosts import identity
    _, _, choice = prepared(tmp_path, host)
    events = question_events(choice, host, session)
    if mutation == "unrelated":
        if host == "codex": events[0]["payload"]["call_id"] = "other"
        else: events[0]["message"]["content"][0]["id"] = "other"
    elif mutation == "text":
        if host == "codex": events[-1]["payload"]["content"][0]["text"] = "yes\n"
        else: events[-1] = {"type": "user", "sessionId": session, "message": {"content": "yes\n"}}
    elif mutation == "cancel":
        if host == "codex": events[1]["payload"]["output"] = '{"accepted":false}'
        else: events[-1]["message"]["content"][0]["is_error"] = True
    elif mutation == "before-call": events = list(reversed(events))
    elif mutation == "duplicate-call":
        duplicate = copy.deepcopy(events[0])
        if host == "codex": duplicate["payload"]["call_id"] = "second-question"
        else: duplicate["message"]["content"][0]["id"] = "second-question"
        events.append(duplicate)
    elif mutation == "sidechain":
        if host == "codex": events[-1]["payload"]["role"] = "assistant"
        else: events[-1]["isSidechain"] = True
    elif mutation == "changed-option":
        if host == "codex":
            args = json.loads(events[0]["payload"]["arguments"])
            args["questions"][0]["options"][0] = "Not that action"
            events[0]["payload"]["arguments"] = json.dumps(args)
        else: events[0]["message"]["content"][0]["input"] = {"questions": []}
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events))
    monkeypatch.setattr(identity, "snapshot", lambda *a: {"transcript": str(path)})
    actor = SimpleNamespace(host=host, session=session)
    if mutation:
        with pytest.raises(ValueError): user_choices.native_selection(tmp_path, actor, choice)
    else:
        result = user_choices.native_selection(tmp_path, actor, choice)
        assert user_choices.verify_selection(choice, result)["decision"] == "yes"


def test_option_digest_owner_and_requested_decision_are_checked(tmp_path):
    store, subject, choice = prepared(tmp_path)
    picked = selection(choice)
    with pytest.raises(ValueError, match="owner"):
        store.admit_selection("other", choice["user_choice_ref"], subject, picked, "yes", "apply")
    with pytest.raises(ValueError, match="differs"):
        store.admit_selection("owner", choice["user_choice_ref"], subject, picked, "no", "apply")
    choice["options"][0]["digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        user_choices.verify_selection(choice, picked)


def test_transport_linebreaks_do_not_change_selected_option_digest(tmp_path):
    _, _, choice = prepared(tmp_path)
    picked = selection(choice)
    picked["result"]["answers"][choice["question"]] += "\r\n"
    assert user_choices.verify_selection(choice, picked)["option_digest"] == choice["options"][0]["digest"]


def test_legacy_pending_text_choice_cannot_be_used_as_selected_option(tmp_path):
    _, _, choice = prepared(tmp_path)
    picked = selection(choice)
    choice.pop("selection_schema")
    with pytest.raises(ValueError, match="legacy"):
        user_choices.verify_selection(choice, picked)


def test_zero_duration_auto_resolution_is_not_human_approval(tmp_path):
    _, _, choice = prepared(tmp_path)
    picked = selection(choice)
    picked["result"]["afkTimeoutMs"] = 0
    with pytest.raises(ValueError, match="automatic"):
        user_choices.verify_selection(choice, picked)


def test_malformed_question_identifier_is_unsupported_not_a_parser_crash():
    from neurath.runtime.choice_selection import _async_replies
    row = {"questionItemId": json.dumps([{}, "call", 0]), "question": "Q", "answer": "A"}
    assert _async_replies("<send_user_message_question_reply>" + json.dumps([row]) +
                          "</send_user_message_question_reply>") == []
