"""Observed recoveries become versioned guidance only after subsequent validation."""

import json
import subprocess

import pytest

from neurath.memory.store import ProjectMemory
from neurath.memory.learning import Learning


@pytest.fixture
def memory(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(
        json.dumps({"verification": {"check": {"argv": ["sh", "check.sh"]}}})
    )
    return ProjectMemory(tmp_path)


def tool(memory, session, source, command, code):
    event = memory.record(
        "codex", session, source, "tool", command, {"exit_code": code, "worktree": str(memory.root)}
    )
    Learning(memory).observe(event)
    return event


def receipt(memory, passed=True):
    return {
        "status": "passed" if passed else "failed",
        "worktree_changed": False,
        "config_sha256": Learning(memory).verifier_digest(),
        "before_fingerprint": "a" * 64,
        "after_fingerprint": "a" * 64,
        "output_sha256": "b" * 64,
        "exit_code": 0 if passed else 1,
        "timed_out": False,
    }


def test_recovery_trial_promotion_and_automatic_regression_rollback(memory):
    tool(memory, "first", "failure", "pytest -q", 127)
    tool(memory, "first", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    assert engine.status()[0]["status"] == "candidate"
    assert not engine.guidance()
    engine.verified("codex", "first", receipt(memory))
    candidate = engine.status()[0]
    assert candidate["status"] == "trial"
    assert "uv run pytest -q" in engine.guidance()
    engine.expose("claude-code", "second")
    observed = memory.record(
        "claude-code",
        "second",
        "trial-success",
        "tool",
        "uv run pytest -q",
        {"exit_code": 0, "worktree": str(memory.root)},
    )
    engine.observe(observed)
    engine.verified("claude-code", "second", receipt(memory))
    assert engine.status()[0]["status"] == "active"
    failure = memory.record(
        "claude-code",
        "third",
        "regression",
        "tool",
        "uv run pytest -q",
        {"exit_code": 2, "worktree": str(memory.root)},
    )
    engine.observe(failure)
    assert engine.status()[0]["status"] == "reverted"
    assert not engine.guidance()
    assert [event["status"] for event in engine.history(candidate["id"])] == [
        "candidate",
        "trial",
        "active",
        "reverted",
    ]


def test_unrelated_success_or_unknown_exit_never_teaches_a_recovery(memory):
    tool(memory, "one", "fail", "pytest -q", 1)
    tool(memory, "one", "unrelated", "echo fine", 0)
    tool(memory, "one", "unknown", "uv run pytest -q", None)
    assert not Learning(memory).status()


def test_check_failure_same_session_and_unexposed_success_do_not_promote(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified("codex", "one", receipt(memory, False))
    assert engine.status()[0]["status"] == "candidate"
    engine.verified("codex", "one", receipt(memory))
    engine.verified("codex", "one", receipt(memory))
    assert engine.status()[0]["status"] == "trial"
    tool(memory, "two", "not-exposed", "uv run pytest -q", 0)
    engine.verified("codex", "two", receipt(memory))
    assert engine.status()[0]["status"] == "trial"


def test_changed_verifier_invalidates_old_guidance(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified("codex", "one", receipt(memory))
    (memory.root / ".neurath/project.json").write_text(
        json.dumps({"verification": {"check": {"argv": ["true"]}}})
    )
    assert not engine.guidance()
    engine.verified("codex", "one", receipt(memory))
    assert engine.status()[0]["status"] == "stale"


def test_different_test_selector_is_not_a_verified_recovery(memory):
    tool(memory, "one", "fail", "pytest tests/test_invoice.py -q", 1)
    tool(memory, "one", "unrelated", "uv run pytest tests/test_users.py -q", 0)
    assert not Learning(memory).status()


def test_incomplete_verification_receipt_cannot_admit_trial(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified(
        "codex",
        "one",
        {"status": "passed", "exit_code": 0, "config_sha256": engine.verifier_digest()},
    )
    assert engine.status()[0]["status"] == "candidate"


def test_trial_project_check_failure_reverts_guidance(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified("codex", "one", receipt(memory))
    engine.expose("codex", "two")
    tool(memory, "two", "use", "uv run pytest -q", 0)
    engine.verified("codex", "two", receipt(memory, False))
    assert engine.status()[0]["status"] == "reverted"


def test_replayed_old_failure_does_not_revert_new_trial(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    old = tool(memory, "one", "old-recovery-fail", "uv run pytest -q", 2)
    tool(memory, "one", "fail-again", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified("codex", "one", receipt(memory))
    engine.observe(old)
    assert engine.status()[0]["status"] == "trial"


def test_only_delivered_lessons_are_exposed_and_guidance_is_bounded(memory):
    engine = Learning(memory)
    for i in range(15):
        tool(memory, "one", f"fail-{i}", f"pytest tests/test_{i}.py", 127)
        tool(memory, "one", f"recover-{i}", f"uv run pytest tests/test_{i}.py", 0)
    engine.verified("codex", "one", receipt(memory))
    guidance = engine.guidance(max_bytes=2000)
    assert len(guidance.encode()) <= 2000
    engine.expose("codex", "two", guidance=guidance)
    with memory.connection() as db:
        exposed = [row[0] for row in db.execute("select lesson from exposures")]
    assert exposed and len(exposed) < 15
    assert all(identity in guidance for identity in exposed)
    assert all(
        (lesson["id"] in exposed) == (lesson["id"] in guidance) for lesson in engine.status()
    )


def test_linked_worktree_uses_its_own_verification_contract(memory, tmp_path):
    subprocess.run(
        [
            "git",
            "-C",
            str(memory.root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    linked = tmp_path.parent / (tmp_path.name + "-linked")
    subprocess.run(
        ["git", "-C", str(memory.root), "worktree", "add", "-b", "linked", str(linked)],
        check=True,
        capture_output=True,
    )
    (linked / ".neurath").mkdir()
    (linked / ".neurath/project.json").write_text(
        json.dumps({"verification": {"check": {"argv": ["sh", "other-check.sh"]}}})
    )
    assert ProjectMemory(linked).path == memory.path
    assert Learning(ProjectMemory(linked)).verifier_digest() != Learning(memory).verifier_digest()


def test_other_worktree_check_does_not_invalidate_source_guidance(memory, tmp_path):
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified("codex", "one", receipt(memory))
    subprocess.run(
        [
            "git",
            "-C",
            str(memory.root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    linked = tmp_path.parent / (tmp_path.name + "-other")
    subprocess.run(
        ["git", "-C", str(memory.root), "worktree", "add", "-b", "other", str(linked)],
        check=True,
        capture_output=True,
    )
    (linked / ".neurath").mkdir()
    (linked / ".neurath/project.json").write_text(
        json.dumps({"verification": {"check": {"argv": ["sh", "other-check.sh"]}}})
    )
    other = ProjectMemory(linked)
    Learning(other).verified("codex", "two", receipt(other))
    assert engine.status()[0]["status"] == "trial"


def test_autonomous_validation_survives_an_already_saved_checkpoint(memory, monkeypatch):
    from types import SimpleNamespace
    from neurath.memory.hooks import checkpoint_request
    import neurath.hosts.identity as identity
    import neurath.runtime.engine as runtime

    memory.record("codex", "one", "prompt", "prompt", "Run the project tests")
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    memory.checkpoint("codex", "one", "done", summary="Tests run")
    transcript = memory.worktree / "native.jsonl"
    transcript.write_text("")
    monkeypatch.setattr(runtime, "activate", lambda root: None)
    monkeypatch.setattr(
        identity,
        "_state",
        lambda root, session: SimpleNamespace(
            session=SimpleNamespace(runtime=SimpleNamespace(value="codex"))
        ),
    )
    monkeypatch.setattr(
        identity, "snapshot", lambda root, session: {"host": "codex", "transcript": str(transcript)}
    )
    result = checkpoint_request(
        memory.worktree, "codex", {"hook_event_name": "Stop", "session_id": "one"}
    )
    assert result and "verification_run(check='check')" in result
    assert ".neurath/run" not in result
    assert Learning(memory).pending("codex", "one")


def test_automatic_checks_follow_real_candidate_and_independent_trial_use(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    recovery = tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    assert engine.pending("codex", "one")[0]["observation"] == recovery
    assert not engine.pending("codex", "unrelated")
    engine.verified("codex", "one", receipt(memory))
    assert not engine.pending("codex", "one")
    engine.expose("codex", "two")
    assert not engine.pending("codex", "two")
    tool(memory, "two", "use", "uv run pytest -q", 0)
    assert engine.pending("codex", "two")
    engine.verified("codex", "two", receipt(memory))
    assert not engine.pending("codex", "two")
    assert engine.status()[0]["status"] == "active"


def test_failed_or_deferred_check_does_not_create_an_automatic_retry_loop(memory):
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    engine = Learning(memory)
    engine.verified("codex", "one", {"status": "passed", "exit_code": 0})
    assert engine.pending("codex", "one"), "fabricated receipt must not discharge pending work"
    engine.verified("codex", "one", receipt(memory, False))
    assert not engine.pending("codex", "one")
    assert engine.status()[0]["status"] == "candidate"
    tool(memory, "two", "fail", "pytest -q", 127)
    tool(memory, "two", "recovery", "uv run pytest -q", 0)
    assert engine.pending("codex", "two"), "new recovery evidence must rearm validation"
    with pytest.raises(ValueError):
        engine.defer("codex", "two", "")
    assert engine.defer("codex", "two", "Current user forbids running further checks") == 1
    assert not engine.pending("codex", "two")
    assert engine.status()[0]["status"] == "candidate"
    assert engine.history(engine.status()[0]["id"])[-1]["reason"] == "automatic-check-deferred"


def test_unbound_verifier_never_starts_an_automatic_check(memory):
    (memory.worktree / ".neurath/project.json").write_text("{}")
    tool(memory, "one", "fail", "pytest -q", 127)
    tool(memory, "one", "recovery", "uv run pytest -q", 0)
    assert not Learning(memory).pending("codex", "one")
