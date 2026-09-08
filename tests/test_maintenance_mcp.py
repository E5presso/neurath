"""Named maintenance goes through native capability validation, not CLI parsing."""
import argparse
import pytest
from neurath.agents import mcp
from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call


def test_explicit_refresh_uses_native_policy_without_second_consent(sessions, monkeypatch):
    from tests.test_task_tools import claim_fixture
    from neurath.runtime import user_choices
    from neurath.updates import Updates
    root, _ = sessions
    claim_fixture(root)
    gates = []
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *args: gates.append(args))
    monkeypatch.setattr(user_choices, "validate", lambda *a, **kw: pytest.fail("unrequested second consent"))
    monkeypatch.setattr(Updates, "check", lambda self, force=False: {"checked": True, "force": force})
    fields = {"force": True, "key": "explicit-refresh"}
    result = mcp.call_tool(root, bound_call(sessions, "releases_check", fields), name="releases_check")
    assert result == {"checked": True, "force": True}
    assert len(gates) == 1


@pytest.mark.parametrize("host,session", [("codex","api"),("claude-code","ui")])
def test_bound_learning_read_never_uses_cli_parser(sessions, monkeypatch, host, session):
    root,_=sessions
    bound=bound_call(sessions,"learning_pending",{},host=host,session=session)
    monkeypatch.setattr(argparse.ArgumentParser,"parse_args",
                        lambda *a,**kw:pytest.fail("CLI parsing used"))
    assert mcp.call_tool(root,bound,name="learning_pending") == []


def test_maintenance_changed_binding_is_rejected(sessions):
    root,_=sessions
    bound=bound_call(sessions,"learning_history",{"strategy_id":"one"})
    with pytest.raises(ValueError):
        mcp.call_tool(root,{**bound,"strategy_id":"two"},name="learning_history")


def test_consent_preparation_does_not_change_persisted_setting(sessions):
    from neurath.reporting import Reporting
    root,_=sessions
    before=Reporting(root).status()
    fields={"decision":"yes","user_choice_ref":"unattested-prompt","key":"choice"}
    bound=bound_call(sessions,"reporting_consent",fields)
    with pytest.raises(ValueError):
        mcp.call_tool(root,bound,name="reporting_consent")
    assert Reporting(root).status() == before

def test_bound_root_can_defer_own_learning_without_worktree_claim(sessions):
    root,_=sessions
    from tests.test_task_tools import claim_fixture
    claim_fixture(root,host="claude-code",session="ui")
    fields={"reason":"Current worktree belongs to another authorized session","key":"defer"}
    bound=bound_call(sessions,"learning_defer",fields,invocation="defer")
    result=mcp.call_tool(root,bound,name="learning_defer")
    assert result["status"]=="deferred" and result["count"]==0
