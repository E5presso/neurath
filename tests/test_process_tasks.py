"""Process helper faces use typed services without CLI parsing or identity injection."""
import pytest
from neurath.runtime.task_schema import arguments
from tests.test_workflow_tasks import call, start
pytest_plugins = ["tests.test_agent_hooks"]


def test_process_helper_schemas_expose_data_not_commands():
    cases = {
        "process_evidence_record": {"workflow_id": "phase", "field": "failed", "value": {"reason": "Observed failure"}, "key": "record"},
        "worktree_isolation": {"issue_number": 1, "key": "claim"},
        "worktree_cleanup": {"workflow_id": "phase", "base_branch": "main", "remote_ref": "origin/main", "key": "cleanup"},
    }
    for name, inputs in cases.items():
        arguments(name, inputs)
        for extra in ({"environment": {}}, {"root": "/foreign"}, {"argv": []}):
            with pytest.raises(ValueError):
                arguments(name, {**inputs, **extra})


def test_process_evidence_uses_bound_handle_without_parser(sessions, monkeypatch):
    from neurath.runtime.bundled_services import service
    module = service("process")
    monkeypatch.setattr(module.ProcessStateEvidenceApplication, "_parser", lambda *a: pytest.fail("CLI parser"))
    call(sessions, "worktree_claim", {})
    start(sessions)
    result = call(sessions, "process_evidence_record", {
        "workflow_id": "phase", "field": "failed", "value": {"reason": "Observed fixture error"}, "key": "record"})
    assert result["failed"] == {"reason": "Observed fixture error"}
    state = call(sessions, "session_inspect", {})
    assert state["workflows"]["phase"]["payload"]["skill_state"]["failed"] == {"reason": "Observed fixture error"}


def test_isolation_checks_root_topology_before_claim(sessions):
    with pytest.raises(ValueError, match="root|isolat"):
        call(sessions, "worktree_isolation", {"issue_number": 1, "key": "claim"})


def test_cleanup_keeps_guard_and_result_store_after_actual_worktree_removal(monkeypatch):
    import json
    from neurath.agents.store import AgentIdentity, MessageStore
    from neurath.runtime import process_tasks
    import importlib.util
    from neurath.resources import BUNDLE
    original_spec=importlib.util.spec_from_file_location
    with monkeypatch.context() as imports:
        imports.setattr(importlib.util,"spec_from_file_location",lambda name,path,*a,**k:
            original_spec(name,BUNDLE/".agents/skills/process-ticket/scripts/merge_cleanup.py"
                if name=="process_ticket_merge_cleanup" else path,*a,**k))
        from tests.runtime.skill_harness.test_merge_cleanup import MergeCleanupFixture
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
    with MergeCleanupFixture() as fixture:
        fixture.publish_trunk_commit()
        fixture.claim_worktree()
        with (fixture.repo/".git/info/exclude").open("a") as stream:
            stream.write("\n.neurath/\n")
        binding=RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID":"owner-thread"})
        handle=StateHandle.attach(SessionLocator.from_worktree(fixture.worktree),binding)
        identity=AgentIdentity("codex","owner-thread",str(handle.actor_id),True)
        # Isolate wrapper persistence from native activation. Git deletion,
        # kernel transitions and cleanup ownership fences remain real.
        monkeypatch.setattr("neurath.runtime.state_tasks._handle",lambda *a:handle)
        monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy",lambda *a,**k:None)
        monkeypatch.setattr("neurath.agents.hooks.participation",lambda *a:(True,"fixture-turn"))
        monkeypatch.setattr("neurath.agents.mcp._prompt_receipt",lambda *a:None)
        monkeypatch.setattr("neurath.hosts.identity.active_connection",lambda root,session:
            SessionLocator.from_worktree(root).control_root==fixture.repo.resolve())
        result=process_tasks.execute(fixture.worktree,"worktree_cleanup",{
            "workflow_id":"process-ticket-128","base_branch":"trunk","remote_ref":"origin/trunk","key":"cleanup"},
            identity=identity,expected_turn="fixture-turn",verified_policy_evidence={"user_prompt_receipt":None})
        assert result["worktree_removed"] and not fixture.worktree.exists()
        state=handle.inspect().workflows["process-ticket-128"].payload["skill_state"]
        assert not state.get("merge_cleanup_intent")
        assert state["merge_cleanup_receipt"]==result
        with MessageStore(fixture.repo).connection() as db:
            saved=db.execute("SELECT result FROM workflow_task_requests WHERE operation='worktree_cleanup' AND key='cleanup'").fetchone()
            assert json.loads(saved[0])==result
