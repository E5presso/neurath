"""A native actor may own another linked checkout without moving its identity."""

import subprocess
from pathlib import Path

import pytest

from neurath.core.commands import Context
from neurath.core.domain import CoreError
from neurath.core.service import Core


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_same_actor_claims_linked_checkout_without_new_session(tmp_path):
    root, linked = tmp_path / "repo", tmp_path / "linked"
    root.mkdir()
    git(root, "init", "-q")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    git(root, "worktree", "add", "-qb", "task", str(linked))
    service = Core(root)
    service.sessions.observe_actor("root", "same-session", "codex")
    service.sessions.observe_actor("reader", "same-session", "codex", parent="root")
    context = Context("root", "same-session", "native-call")
    source = service.provenance.observe_user(
        context, "Work in the selected checkout", "original-user-event"
    )
    task = service.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Implement result",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
        },
    )["task"]
    claimed = service.call(
        context, "worktree_claim", {"key": "claim", "task_id": task["id"], "checkout": str(linked)}
    )["lease"]
    linked_service = Core(linked)
    assert linked_service.store.path == service.store.path
    assert (
        linked_service.call(context, "task_read", {"task_id": task["id"]})["task"]["id"]
        == task["id"]
    )
    assert claimed["writer"] == "root" and Path(claimed["checkout"]) == linked
    status = service.call(context, "session_status", {})
    assert status["actor"]["session_id"] == "same-session"
    read = service.call(
        Context("reader", "same-session", "read"), "worktree_read", {"checkout": str(linked)}
    )
    assert read["lease"] == claimed
    service.call(
        context,
        "worktree_release",
        {"key": "release", "checkout": str(linked), "generation": claimed["generation"]},
    )


def test_an_unrelated_checkout_does_not_gain_write_membership(tmp_path):
    root, foreign = tmp_path / "repo", tmp_path / "foreign"
    root.mkdir()
    foreign.mkdir()
    git(root, "init", "-q")
    git(foreign, "init", "-q")
    service = Core(root)
    service.sessions.observe_actor("root", "session", "codex")
    with pytest.raises(CoreError, match="foreign-project-checkout"):
        service.call(
            Context("root", "session", "read"), "worktree_read", {"checkout": str(foreign)}
        )


def test_source_subject_changes_with_work_and_ignores_progress_storage(tmp_path):
    from neurath.core.workspace import source_subject

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.py").write_text("first\n")
    first = source_subject(tmp_path)
    local = tmp_path / ".neurath/local"
    local.mkdir(parents=True)
    (local / "core.sqlite3").write_bytes(b"progress")
    assert source_subject(tmp_path) == first
    (tmp_path / "source.py").write_text("changed\n")
    assert source_subject(tmp_path) != first


def test_committing_the_checked_bytes_does_not_invalidate_check_subject(tmp_path):
    from neurath.core.workspace import source_subject

    git(tmp_path, "init", "-q")
    (tmp_path / "source.py").write_text("checked bytes\n")
    checked = source_subject(tmp_path)
    git(tmp_path, "add", "source.py")
    assert source_subject(tmp_path) == checked
    git(
        tmp_path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "record checked source",
    )
    assert source_subject(tmp_path) == checked
    (tmp_path / "source.py").write_text("different bytes\n")
    assert source_subject(tmp_path) != checked


def test_source_subject_hashes_symlink_target_without_reading_external_file(tmp_path):
    from neurath.core.workspace import source_subject

    root = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    secret = tmp_path / "outside"
    secret.write_text("first")
    (root / "link").symlink_to(secret)
    first = source_subject(root)
    secret.write_text("second")
    assert source_subject(root) == first


def test_future_worktree_can_be_reserved_and_released_without_existing_git_directory(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    core = Core(root)
    core.sessions.observe_actor("root", "session", "codex")
    context = Context("root", "session", "call")
    source = core.provenance.observe_input(context, "Use an isolated checkout", "input")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Change delivered",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
        },
    )["task"]
    target = tmp_path / "future"
    lease = core.call(
        context,
        "worktree_claim",
        {"key": "reserve", "task_id": task["id"], "checkout": str(target), "create": True},
    )["lease"]
    assert not target.exists()
    read = core.call(context, "worktree_read", {"checkout": str(target)})
    assert read["lease"] == lease and read["exists"] is False
    core.call(
        context,
        "worktree_release",
        {"key": "release", "checkout": str(target), "generation": lease["generation"]},
    )
    assert core.sessions.stop(context)["allowed"] is False


def test_linked_checkout_uses_its_own_registered_check_profile(tmp_path):
    import json
    import shlex

    from neurath.core.domain import Phase, Skill
    from neurath.core.hooks import invoke
    from neurath.core.mcp import server_config

    root, linked = tmp_path / "root", tmp_path / "linked"
    root.mkdir()
    git(root, "init", "-q")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    git(root, "worktree", "add", "-qb", "issue", str(linked))
    (linked / ".neurath").mkdir()
    argv = ["python", "-c", "print(42)"]
    (linked / ".neurath/project.json").write_text(
        json.dumps({"verification": {"focused": {"argv": argv, "cwd": "."}}})
    )
    core = Core(
        root, skills={"check": Skill("check", "1", (Phase("check", effects=frozenset({"check"})),))}
    )
    context = Context("codex:session:actual", "actual", "setup")
    core.sessions.observe_actor(context.actor_id, context.session_id, "codex")
    source = core.provenance.observe_input(
        context, "Run the registered linked-checkout check", "input"
    )
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Checked result",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
        },
    )["task"]
    for name, extra in [("task_start", {}), ("skill_start", {"skill": "check"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **extra},
        )["task"]
    result = invoke(
        root,
        "codex",
        {
            "hook_event_name": "PreToolUse",
            "session_id": "actual",
            "tool_name": "Bash",
            "tool_use_id": "native-check",
            "cwd": str(root),
            "tool_input": {"command": shlex.join(argv), "workdir": str(linked)},
        },
    )
    assert result == {}, result
    records = core.call(context, "evidence_list", {"task_id": task["id"]})["checks"]
    assert records[0]["checkout"] == str(linked)
    server = server_config(linked, "codex")
    assert server["args"][server["args"].index("--root") + 1] == str(root)
