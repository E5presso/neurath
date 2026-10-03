"""Native-bound choices consume selected options even without a new prompt."""
import json
from pathlib import Path

import pytest

from neurath.agents import mcp
from neurath.reporting import Reporting
from neurath.hosts.identity import snapshot
from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call, claim_fixture


def question_events(choice, host, session, decision="yes"):
    native = choice["native_question"]
    args = native["arguments"]
    label = next(o["label"] for o in choice["options"] if o["decision"] == decision)
    if host == "claude-code":
        return [
            {"type": "assistant", "sessionId": session, "message": {"content": [
                {"type": "tool_use", "id": "ask-native", "name": "AskUserQuestion", "input": args}]}},
            {"type": "user", "sessionId": session, "toolUseResult": {
                "questions": args["questions"], "answers": {choice["question"]: label}}, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "ask-native", "content": "Display serialization\n"}]}},
        ]
    reply = [{"questionItemId": json.dumps(["request_user_input_async", "ask-native", 0]),
              "question": choice["question"], "answer": label}]
    return [
        {"type": "response_item", "payload": {"type": "function_call", "call_id": "ask-native",
            "name": "request_user_input_async", "arguments": json.dumps(args)}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "ask-native",
            "output": json.dumps({"accepted": True})}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{
            "type": "input_text", "text": "<send_user_message_question_reply>\n" + json.dumps(reply) +
                "\n</send_user_message_question_reply>"}]}},
    ]


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
@pytest.mark.parametrize("decision", ["yes", "no"])
def test_native_option_records_consent_once_in_same_turn(sessions, host, session, decision):
    root, _ = sessions
    claim_fixture(root, host, session)
    def call(name, fields, invocation):
        return mcp.call_tool(root, bound_call(sessions, name, fields, invocation=invocation,
                                             host=host, session=session), name=name)
    choice = call("maintenance_choice_prepare", {"operation": "reporting_consent", "key": "ask"}, "prepare")
    assert "native_question.tool" in choice["next_action"]
    assert Reporting(root).status()["auto_report"] is None
    transcript = Path(snapshot(root, session)["transcript"])
    with transcript.open("a") as stream:
        for event in question_events(choice, host, session, decision):
            stream.write(json.dumps(event) + "\n")
    # No fabricated UserPromptSubmit or mocked transcript reader.
    answer = {"decision": decision, "user_choice_ref": choice["user_choice_ref"], "key": "apply"}
    result = call("reporting_consent", answer, "answer")
    assert result["auto_report"] is (decision == "yes")
    saved = call("maintenance_choice_read", {"user_choice_ref": choice["user_choice_ref"]}, "read")
    assert saved["selection"]["tool_call_id"] == "ask-native"
    assert saved["application_status"] == "completed"
    Reporting(root).consent(decision != "yes")
    assert call("reporting_consent", answer, "replay") == result
    assert Reporting(root).status()["auto_report"] is (decision != "yes")
