"""Observe wire contracts and request-local discovery without bypassing authority."""

import subprocess

import pytest

from neurath import project_paths
from neurath.agents import mcp


@pytest.mark.parametrize("operation", ["task_define", "task_start", "task_resolve", "task_list"])
def test_mcp_task_wire_projection_preserves_revisions_and_todo(operation, monkeypatch):
    task = {"id": "task-one", "revision": 3, "status": "succeeded",
            "definition": {"goal": "retained in ledger"}, "evidence": {"reference": "proof"}}
    todo = {"task_ids": ["task-one"], "display_instruction": "Display the native TODO."}
    ledger = {"revision": 7, "all_terminal": True, "all_succeeded": True,
              "tasks": [task], "native_todo": todo}
    monkeypatch.setattr(mcp, "call_tool", lambda *args, **kwargs: ledger)
    wire = mcp.response(None, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": operation, "arguments": {}}})["result"]
    result = wire["structuredContent"]["result"]
    assert not wire["isError"]
    assert result["revision"] == 7
    assert result["native_todo"] == todo
    assert "Display the native TODO." in wire["content"][0]["text"]
    if operation == "task_list":
        assert result == ledger
    else:
        assert set(result) == {"revision", "all_terminal", "tasks", "native_todo"}
        assert result["tasks"] == [{"id": "task-one", "revision": 3, "status": "succeeded"}]
    assert ledger["tasks"][0]["definition"]["goal"] == "retained in ledger"


def _repository(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_discovery_reuses_git_lookup_only_inside_current_scope(tmp_path, monkeypatch):
    for key in tuple(project_paths.os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_PAGER", "cat")
    root = _repository(tmp_path / "repo")
    observed = []
    discover = project_paths._discover_control_root

    def record(path):
        observed.append(path)
        return discover(path)

    monkeypatch.setattr(project_paths, "_discover_control_root", record)
    with project_paths.discovery_scope():
        for _ in range(4):
            assert project_paths.control_root(root) == root
        assert len(observed) == 1
    with pytest.raises(RuntimeError, match="interrupted"):
        with project_paths.discovery_scope():
            assert project_paths.control_root(root) == root
            raise RuntimeError("interrupted")
    assert project_paths.control_root(root) == root
    assert project_paths.control_root(root) == root
    assert len(observed) == 4


def test_discovery_observes_git_layout_changes_inside_and_between_events(tmp_path):
    first = _repository(tmp_path / "first")
    second = _repository(tmp_path / "second")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    marker = worktree / ".git"
    marker.write_text(f"gitdir: {first / '.git'}\n")
    with project_paths.discovery_scope():
        assert project_paths.control_root(worktree) == first
        marker.write_text(f"gitdir: {second / '.git'}\n")
        assert project_paths.control_root(worktree) == second
    marker.write_text(f"gitdir: {first / '.git'}\n")
    with project_paths.discovery_scope():
        assert project_paths.control_root(worktree) == first


def test_discovery_observes_commondir_change_in_current_event(tmp_path):
    first = _repository(tmp_path / "first")
    second = _repository(tmp_path / "second")
    with project_paths.discovery_scope():
        assert project_paths.control_root(first) == first
        (first / ".git/commondir").write_text(str(second / ".git"))
        assert project_paths.control_root(first) == second


def test_discovery_environment_override_does_not_reuse_cached_root(tmp_path, monkeypatch):
    first = _repository(tmp_path / "first")
    second = _repository(tmp_path / "second")
    with project_paths.discovery_scope():
        assert project_paths.control_root(first) == first
        monkeypatch.setenv("GIT_COMMON_DIR", str(second / ".git"))
        assert project_paths.control_root(first) == second


def test_discovery_observes_symlinked_commondir_target_content_change(tmp_path):
    worktree = _repository(tmp_path / "worktree")
    first = _repository(tmp_path / "first")
    second = _repository(tmp_path / "second")
    pointer = tmp_path / "common-directory"
    pointer.write_text(str(first / ".git"))
    (worktree / ".git/commondir").symlink_to(pointer)
    with project_paths.discovery_scope():
        assert project_paths.control_root(worktree) == first
        pointer.write_text(str(second / ".git"))
        assert project_paths._discover_control_root(worktree) == second
        assert project_paths.control_root(worktree) == second
