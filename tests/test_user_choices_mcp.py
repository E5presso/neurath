"""Protocol fixture for a complete native-bound pending user decision."""
from neurath.agents import mcp
from neurath.reporting import Reporting
from neurath.runtime import user_choices
from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call,claim_fixture


def test_choice_prepare_then_fresh_user_answer_records_consent_once(sessions,monkeypatch):
    root,invoke=sessions
    claim_fixture(root)
    fields={"operation":"reporting_consent","target_id":"","key":"ask"}
    question=mcp.call_tool(root,bound_call(sessions,"maintenance_choice_prepare",fields),
                           name="maintenance_choice_prepare")
    assert Reporting(root).status()["auto_report"] is None
    from pathlib import Path
    from neurath.hosts.identity import snapshot
    from tests.test_identity import native_turn_started
    transcript=Path(snapshot(root,"api")["transcript"])
    native_turn_started(transcript,"answer-turn")
    assert invoke("codex","api","UserPromptSubmit",prompt="yes",turn_id="answer-turn")[0]==0
    monkeypatch.setattr(user_choices,"native_messages",lambda *a:[
        ("assistant",question["question"]),("user","yes")])
    answer={"decision":"yes","user_choice_ref":question["user_choice_ref"],"key":"apply"}
    result=mcp.call_tool(root,bound_call(sessions,"reporting_consent",answer,invocation="answer"),
                         name="reporting_consent")
    assert result["auto_report"] is True
    # A completed keyed result is a historical result; replay cannot overwrite
    # a later preference or mint a second decision from another native prompt.
    Reporting(root).consent(False)
    native_turn_started(transcript,"status-turn")
    assert invoke("codex","api","UserPromptSubmit",prompt="status",turn_id="status-turn")[0]==0
    replay=mcp.call_tool(root,bound_call(sessions,"reporting_consent",answer,invocation="replay"),
                         name="reporting_consent")
    assert replay==result and Reporting(root).status()["auto_report"] is False
