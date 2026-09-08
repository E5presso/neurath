"""Remaining communication operations are structured and use native identities."""
import argparse
import pytest
from neurath.agents import mcp
from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call


@pytest.mark.parametrize("host,session", [("codex","api"),("claude-code","ui")])
def test_named_profile_update_preserves_caller_and_avoids_cli(sessions,monkeypatch,host,session):
    root,_=sessions
    fields={"name":"Model implementation","summary":"Bounded model tools"}
    bound=bound_call(sessions,"collaboration_register",fields,host=host,session=session)
    monkeypatch.setattr(argparse.ArgumentParser,"parse_args",lambda *a,**k:pytest.fail("CLI parser"))
    result=mcp.call_tool(root,bound,name="collaboration_register")
    assert result["address"]==host+":"+session and result["name"]==fields["name"]


def test_named_newsroom_revision_and_comment_keep_cas_and_author(sessions):
    root,_=sessions
    publish=bound_call(sessions,"newsroom_publish",{"title":"Initial","body":"First","key":"article"})
    article=mcp.call_tool(root,publish,name="newsroom_publish")
    fields={"article_id":article["id"],"revision":1,"title":"Revised","body":"Second","key":"revise"}
    revised=mcp.call_tool(root,bound_call(sessions,"newsroom_revise",fields,invocation="revise"),
                          name="newsroom_revise")
    assert revised["revision"]==2
    with pytest.raises(ValueError):
        mcp.call_tool(root,bound_call(sessions,"newsroom_revise",{**fields,"key":"stale"},
                                     invocation="stale"),name="newsroom_revise")
    comment={"article_id":article["id"],"revision":2,"body":"Relevant peer note","key":"comment"}
    result=mcp.call_tool(root,bound_call(sessions,"newsroom_comment",comment,invocation="comment",
                                      host="claude-code",session="ui"),name="newsroom_comment")
    assert result["actor"]=="claude-code:ui"


def test_new_communication_schemas_never_take_actor_or_argv():
    from neurath.runtime.task_schema import arguments,definitions
    expected={"collaboration_register","collaboration_conversation","collaboration_close",
              "collaboration_subscribe","collaboration_unsubscribe","collaboration_publish",
              "newsroom_revise","newsroom_comment","newsroom_peers","newsroom_seen"}
    rows={r["name"]:r for r in definitions()}
    assert expected.issubset(rows)
    for name in expected:
        assert "argv" not in rows[name]["inputSchema"]["properties"]
        with pytest.raises(ValueError):
            arguments(name,{"actor":"forged"})


def test_named_subscription_publish_and_unsubscribe_use_existing_store(sessions):
    root,_=sessions
    bound=bound_call(sessions,"collaboration_subscribe",{"to":"codex:api"},
                     invocation="sub",host="claude-code",session="ui")
    assert mcp.call_tool(root,bound,name="collaboration_subscribe")["enabled"] is True
    fields={"message":"Authorized update","key":"update"}
    bound=bound_call(sessions,"collaboration_publish",fields,invocation="pub")
    messages=mcp.call_tool(root,bound,name="collaboration_publish")["messages"]
    assert len(messages)==1 and messages[0]["recipient"]=="claude-code:ui"
    bound=bound_call(sessions,"collaboration_unsubscribe",{"to":"codex:api"},
                     invocation="unsub",host="claude-code",session="ui")
    assert mcp.call_tool(root,bound,name="collaboration_unsubscribe")["enabled"] is False
