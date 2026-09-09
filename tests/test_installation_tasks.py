"""Installation MCP faces retain the existing conservative transaction boundary."""
import pytest
from neurath.runtime.task_schema import arguments
from tests.test_workflow_tasks import call
pytest_plugins = ["tests.test_agent_hooks"]


def test_installation_face_has_no_plan_path_or_cli_argv():
    arguments("installation_plan", {"action": "uninstall", "key": "prepare"})
    for extra in ({"root": "/foreign"}, {"argv": ["install"]}, {"output": "/foreign/plan.json"}):
        with pytest.raises(ValueError):
            arguments("installation_plan", {"action": "uninstall", "key": "prepare", **extra})


def test_installation_plan_is_private_and_does_not_apply(sessions):
    root, _ = sessions
    call(sessions, "worktree_claim", {})
    before = (root / ".neurath/install.json").read_bytes()
    result = call(sessions, "installation_plan", {"action": "uninstall", "key": "prepare"})
    assert result["plan_ref"].startswith("sha256:")
    assert result["action"] == "uninstall"
    assert result["changes"]
    assert (root / ".neurath/install.json").read_bytes() == before
    assert "before" not in result and "plan" not in result
    with pytest.raises(ValueError, match="policy|native|MCP"):
        call(sessions, "installation_apply", {"plan_ref": result["plan_ref"], "key": "apply"})
    assert (root / ".neurath/install.json").read_bytes() == before


def test_installation_plan_can_be_loaded_and_applied_by_its_owner(sessions, monkeypatch):
    root, _ = sessions
    call(sessions, "worktree_claim", {})
    result = call(sessions, "installation_plan", {"action": "uninstall", "key": "prepare"})
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    applied = call(sessions, "installation_apply", {"plan_ref": result["plan_ref"], "key": "apply"})
    assert applied["id"] == result["plan_id"]
    assert applied["changed"] > 0
    assert not (root / ".neurath/install.json").exists()


def test_recovery_face_reaches_real_journal_with_degraded_placement(sessions, monkeypatch):
    from neurath.install.transaction import make_plan, _write
    from neurath.install.state_store import InstallStateStore
    from neurath.providers import readiness
    root, _ = sessions
    call(sessions, "worktree_claim", {})
    plan = make_plan(root, action="uninstall")
    item = next(c for c in plan["changes"] if c["path"].startswith(".agents/skills/") and c["path"].endswith("SKILL.md"))
    InstallStateStore(root, create=True).begin(plan)
    _write(root, item["path"], item["after"])
    assert not (root / item["path"]).exists()
    # The native protocol fixture is authenticated above. This controlled policy
    # observation isolates recovery admission, not real OS/host attestation.
    monkeypatch.setattr(readiness, "inspect_bound_readiness", lambda *a, **k: {
        "is_root": True, "implementation_ready": False,
        "stages": {"installation": {"status": "failed"}, "activation": {"status": "verified"},
                   "ownership": {"status": "verified"}, "policy": {"status": "verified", "evidence": {
                       "sandbox_policy": {"type": "danger-full-access"}, "approval_policy": "never",
                       "approvals_reviewer": "user"}}}})
    monkeypatch.setattr("neurath.doctor.integrity", lambda: {"status": "passed"})
    result = call(sessions, "installation_recover", {"key": "recover"})
    assert result["recovered"] is True
    assert (root / item["path"]).exists()
    assert InstallStateStore(root).journal() is None


def test_interrupted_plan_names_mcp_recovery_without_poisoning_key(sessions,monkeypatch):
    from neurath.install.transaction import InstallError
    from neurath.runtime.task_schema import TaskError
    from neurath.agents.store import MessageStore
    root,_=sessions
    call(sessions,"worktree_claim",{})
    def interrupted(*a,**k):
        raise InstallError("interrupted transaction: run neurath recover")
    monkeypatch.setattr("neurath.install.transaction.make_plan",interrupted)
    with pytest.raises(TaskError) as caught:
        call(sessions,"installation_plan",{"key":"interrupted"})
    assert "installation_recover" in caught.value.details["next_action"]
    assert "run neurath recover" not in str(caught.value)
    with MessageStore(root).connection() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_task_requests'").fetchone()
        if exists:
            row=db.execute("SELECT 1 FROM workflow_task_requests WHERE operation='installation_plan' AND key='interrupted'").fetchone()
            assert row is None
