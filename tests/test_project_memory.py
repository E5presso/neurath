"""Cross-session knowledge is shared; execution authority never is."""

import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from neurath.memory.store import ProjectMemory, MemoryConflict


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_new_host_recalls_goal_and_checkpoint_without_taking_ownership(repo):
    memory = ProjectMemory(repo)
    memory.record(
        "codex", "first", "prompt-1", "prompt", "Build work log export with UTF-8 filenames"
    )
    memory.checkpoint(
        "codex",
        "first",
        "checkpoint-1",
        summary="CSV export works; PDF remains",
        decisions=["Use UTF-8"],
        next_steps=["Implement PDF export"],
    )
    recalled = ProjectMemory(repo).recall("work log export", session="second", host="claude-code")
    assert "PDF remains" in str(recalled)
    assert "Use UTF-8" in str(recalled)
    assert recalled["authority"] == "reference-only"
    assert not (repo / ".neurath/local/runs/second/.process-state.json").exists()


def test_source_records_are_idempotent_and_conflicting_replay_is_rejected(repo):
    memory = ProjectMemory(repo)
    first = memory.record("codex", "one", "same", "prompt", "Remember this")
    assert memory.record("codex", "one", "same", "prompt", "Remember this") == first
    with pytest.raises(MemoryConflict):
        memory.record("codex", "one", "same", "prompt", "Replace original")
    assert len(memory.history("codex", "one")) == 1


def test_concurrent_sessions_preserve_every_entry(repo):
    def record(i):
        return ProjectMemory(repo).record("codex", str(i), str(i), "prompt", f"Goal {i}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert len(set(pool.map(record, range(24)))) == 24
    assert ProjectMemory(repo).count() == 24


def test_different_repository_does_not_inherit_memory(repo, tmp_path):
    other = tmp_path / "unrelated"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    ProjectMemory(repo).record("codex", "one", "prompt", "prompt", "Private work log design")
    assert not ProjectMemory(other).recall("work log")["entries"]


def test_worktrees_share_reference_memory(repo, tmp_path):
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    worktree = tmp_path / "other-worktree"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-qb", "other", str(worktree)], check=True
    )
    ProjectMemory(repo).record("codex", "one", "prompt", "prompt", "Work log export decision")
    assert "Work log export decision" in str(ProjectMemory(worktree).recall("work log"))


def test_recall_budget_keeps_sources_and_does_not_delete_history(repo):
    memory = ProjectMemory(repo)
    for i in range(20):
        memory.record("codex", str(i), "prompt", "prompt", "work log " + ("detail " * 300))
    result = memory.context("work log", max_bytes=3000)
    assert len(result.encode()) <= 3000
    assert "reference-only" in result
    assert memory.count() == 20


def test_secrets_are_redacted_before_persistence(repo):
    memory = ProjectMemory(repo)
    memory.record(
        "codex",
        "one",
        "prompt",
        "prompt",
        "API_KEY=super-private-token password=secret123 Bearer abcdefghijklmnop",
    )
    raw = memory.path.read_bytes()
    for secret in (b"super-private-token", b"secret123", b"abcdefghijklmnop"):
        assert secret not in raw


def test_checkpoint_required_only_after_work_and_cleared_by_current_summary(repo):
    memory = ProjectMemory(repo)
    memory.record("codex", "one", "prompt", "prompt", "Implement work logs")
    assert not memory.needs_checkpoint("codex", "one")
    memory.record("codex", "one", "tool", "tool", "pytest -q", {"exit_code": 1})
    assert memory.needs_checkpoint("codex", "one")
    memory.checkpoint(
        "codex",
        "one",
        "save",
        summary="CSV done; PDF pending",
        lessons=["Use project test environment"],
    )
    assert not memory.needs_checkpoint("codex", "one")
    assert "Use project test environment" in memory.context("work log")
    memory.record("codex", "one", "prompt2", "prompt", "Now implement PDF")
    memory.record("codex", "one", "tool2", "tool", "pytest -q", {"exit_code": 0})
    assert memory.needs_checkpoint("codex", "one")
