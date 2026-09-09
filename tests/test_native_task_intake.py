import pytest

pytest_plugins = ["tests.test_agent_hooks"]


def test_new_native_root_workflow_requires_task_intake_without_poisoning_key(sessions):
    from neurath.agents.store import MessageStore
    from tests.test_workflow_tasks import call
    call(sessions, "worktree_claim", {})
    fields = {"workflow_id": "new-native-work", "skill": "commit", "north_star": "Review authorized work",
              "run_id": "new-run", "key": "start-after-intake"}
    with pytest.raises(ValueError, match="registered nonterminal measurable task"):
        call(sessions, "phase_start", fields, invocation="missing-intake")
    with MessageStore(sessions[0]).connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_task_requests WHERE key='start-after-intake'").fetchone()[0] == 0
    call(sessions, "task_define", {"tasks": [{"key": "authorized-work", "title": "Review authorized work",
        "goal": fields["north_star"], "sources": [], "acceptance": ["Review completed with stated evidence"],
        "evidence_contract": fields["workflow_id"], "dependencies": []}], "expected_revision": 0,
        "key": "intake-before-workflow"}, invocation="define-native-task")
    started = call(sessions, "phase_start", fields, invocation="registered-intake")
    assert started["current_phase"]["id"] == 1


def test_existing_native_workflow_does_not_infer_or_require_a_legacy_task_list(sessions):
    from neurath.hosts.identity import _state
    from neurath.runtime.workflow_tasks import _require_new_root_task_intake
    from scripts.agent_harness import session_kernel as sk
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    root, _ = sessions
    state = _state(root, "api")
    locator = sk.SessionLocator.from_worktree(root)
    handle = StateHandle.attach(locator, RuntimeIdentityBinding(runtime=state.session.runtime,
        session_id=state.session.id, actor_id=state.session.root_actor_id,
        root_actor_id=state.session.root_actor_id))
    handle.apply(sk.WorkflowStarted(session_id=state.session.id, owner_actor_id=handle.actor_id,
        workflow_id=sk.WorkflowId("legacy-work"), kind="checkpoint", goal="Continue legacy work",
        payload={}, idempotency_key="legacy-work"))
    _require_new_root_task_intake(root, {"workflow_id": "legacy-work"}, handle)
    from scripts.agent_harness.task_service import TaskService
    assert TaskService(handle).list()["tasks"] == []
