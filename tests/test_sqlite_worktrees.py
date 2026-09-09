"""Durable worktree leases and release receipts share the runtime database."""
import pytest


@pytest.fixture
def ownership(tmp_path):
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness import session_kernel as sk
    from scripts.agent_harness import worktree_registry as wr
    locator = sk.SessionLocator(tmp_path)
    kernel = sk.SessionKernel(locator)
    for session in ("one", "two"):
        kernel.apply(sk.SessionStarted(session_id=sk.SessionId(session), resume_id=sk.ResumeId(session),
            root_actor_id=sk.ActorId(session), runtime=sk.SessionRuntime.CODEX, idempotency_key=session))
    def claim(session="one"):
        return wr.WorktreeClaim(worktree_id=sk.WorktreeId("resource"), path=tmp_path,
                                session_id=sk.SessionId(session), actor_id=sk.ActorId(session))
    return wr.WorktreeRegistry(locator), claim, wr, locator


def test_sqlite_worktree_claim_is_exclusive_without_json_state(ownership):
    registry, claim, wr, locator = ownership
    first = registry.claim(claim())
    assert registry.get(first.worktree_id).to_payload() == first.to_payload()
    assert not (locator.worktree_registry_root / "resource.json").exists()
    with pytest.raises(wr.WorktreeAlreadyClaimed):
        registry.claim(claim("two"))


def test_sqlite_worktree_release_keeps_receipt_and_monotonic_epoch(ownership):
    registry, claim, wr, _ = ownership
    first = registry.claim(claim())
    registry.release(first)
    proof = registry.release_receipt(first.worktree_id)
    assert proof["claim"] == first.to_payload()
    with pytest.raises(wr.WorktreeNotClaimed):
        registry.get(first.worktree_id)
    second = registry.claim(claim())
    assert second.lease_epoch == first.lease_epoch + 1
    assert second.fencing_token != first.fencing_token
    assert registry.release_receipt(first.worktree_id) is None
    with pytest.raises(wr.WorktreeLeaseConflict):
        registry.release(first)
    registry.release(second)
    assert registry.release_receipt(second.worktree_id)["revision"] > proof["revision"]
