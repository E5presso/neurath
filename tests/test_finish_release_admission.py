"""Only exact release evidence authorizes post-release finish metadata."""
import subprocess
from dataclasses import replace

import pytest

pytest_plugins = ["tests.test_agent_hooks"]


@pytest.fixture
def finish(tmp_path):
    from neurath.runtime.engine import activate
    activate()
    from neurath.resources import BUNDLE
    from scripts.agent_harness import session_kernel as sk
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeClaim, WorktreeIdentityResolver
    from scripts.skill_harness.phase_runner import PhaseRunState, SkillContractRepository
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".neurath/local/\n.agents/runs/\n.agents/resources/\n")
    (tmp_path / "source.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
    locator = sk.SessionLocator(tmp_path)
    kernel = sk.SessionKernel(locator)
    kernel.apply(sk.SessionStarted(session_id=sk.SessionId("one"), root_actor_id=sk.ActorId("owner"),
        resume_id=sk.ResumeId("resume"), runtime=sk.SessionRuntime.CODEX, idempotency_key="start"))
    handle = StateHandle.attach(locator, RuntimeIdentityBinding(runtime=sk.SessionRuntime.CODEX,
        session_id=sk.SessionId("one"), actor_id=sk.ActorId("owner"), root_actor_id=sk.ActorId("owner")))
    phase = PhaseRunState.initialize(SkillContractRepository(BUNDLE).get("finish-session"), "finish", "Finish approved work")
    phase = replace(phase, current_phase_id=6, phases=tuple(
        replace(item, status="completed", summary="fixture", evidence=("fixture",)) if item.id < 6 else item
        for item in phase.phases))
    kernel.apply(sk.WorkflowStarted(session_id=handle.session_id, workflow_id=sk.WorkflowId("finish"),
        owner_actor_id=handle.actor_id, kind="finish-session", goal=phase.north_star,
        payload={"phase_run": phase.as_payload()}, idempotency_key="finish"))
    identity = WorktreeIdentityResolver().resolve(tmp_path)
    registry = WorktreeRegistry(locator)
    claim = registry.claim(WorktreeClaim(worktree_id=identity.worktree_id, path=identity.path,
        session_id=handle.session_id, actor_id=handle.actor_id))
    return tmp_path, handle, registry, claim


def test_released_finish_workflow_completes_through_named_mcp(sessions, monkeypatch):
    from tests.test_workflow_tasks import call
    from neurath.hosts.identity import _state
    from neurath.resources import BUNDLE
    from scripts.agent_harness import session_kernel as sk
    from scripts.skill_harness.phase_runner import PhaseRunState, SkillContractRepository
    root, _ = sessions
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "Fixture installation"], cwd=root, check=True)
    claim = call(sessions, "worktree_claim", {})
    state = _state(root, "api")
    phase = PhaseRunState.initialize(SkillContractRepository(BUNDLE).get("finish-session"),
                                    "finish", "Finish approved work")
    # Prior five phases are an explicit fixture; exercise actual final admission,
    # release observation, evidence preparation and terminal transition below.
    phase = replace(phase, current_phase_id=6, phases=tuple(
        replace(item, status="completed", summary="fixture", evidence=("fixture",)) if item.id < 6 else item
        for item in phase.phases))
    sk.SessionKernel(sk.SessionLocator.from_worktree(root)).apply(sk.WorkflowStarted(
        session_id=state.session.id, workflow_id=sk.WorkflowId("finish"),
        owner_actor_id=state.session.root_actor_id, kind="finish-session", goal=phase.north_star,
        payload={"phase_run": phase.as_payload(), "skill_state": {}}, idempotency_key="finish-fixture"))
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    released = call(sessions, "worktree_release", {"expected_lease_epoch": claim["lease_epoch"],
                                                  "fencing_token": claim["fencing_token"]})
    assert released["released"]
    evidence = call(sessions, "phase_evidence_prepare", {"workflow_id": "finish", "expected_revision": 0,
        "labels": ["worktree_release_receipt"], "notes": [], "key": "release-evidence"})
    final = call(sessions, "phase_complete", {"workflow_id": "finish", "expected_revision": 0,
        "phase_id": 6, "status": "completed", "summary": "Claim release verified",
        "terminal_state": "finished", "evidence_refs": [evidence["reference"]], "key": "finish-complete"})
    assert final["terminal_state"] == "finished"
    assert call(sessions, "worktree_inspect", {})["claim"] is None


def test_release_context_allows_only_final_finish_metadata(finish):
    from neurath.runtime.finish_release import capture_finish_context, post_release_admission
    root, handle, registry, claim = finish
    context = capture_finish_context(root, handle)
    registry.release(claim, context=context)
    fields = {"workflow_id": "finish", "expected_revision": 0, "phase_id": 6,
              "status": "completed", "terminal_state": "finished"}
    with post_release_admission(root, handle, "phase_complete", fields) as guarded:
        assert guarded.inspect().session.id == handle.session_id
    with pytest.raises(ValueError):
        with post_release_admission(root, handle, "adaptive_replace", fields):
            pytest.fail("unrelated mutation admitted")


def test_later_claim_then_release_invalidates_original_finish_context(finish):
    from neurath.runtime.finish_release import capture_finish_context, post_release_admission
    root, handle, registry, claim = finish
    registry.release(claim, context=capture_finish_context(root, handle))
    reacquired = registry.claim(claim)
    registry.release(reacquired)
    with pytest.raises(ValueError):
        with post_release_admission(root, handle, "phase_evidence_prepare",
            {"workflow_id": "finish", "labels": ["worktree_release_receipt"], "notes": []}):
            pytest.fail("stale release admitted")


def test_source_change_after_release_cannot_finalize_finish(finish):
    from neurath.runtime.finish_release import capture_finish_context, post_release_admission
    root, handle, registry, claim = finish
    registry.release(claim, context=capture_finish_context(root, handle))
    (root / "source.py").write_text("value = 2\n")
    with pytest.raises(ValueError):
        with post_release_admission(root, handle, "phase_complete",
            {"workflow_id": "finish", "phase_id": 6, "status": "completed", "terminal_state": "finished"}):
            pytest.fail("changed source admitted")
