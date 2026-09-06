"""Public skill names stay concise without changing persisted workflow identities."""

import subprocess
import sys

import pytest

from neurath.install.projection import asset_files

EXPECTED = {
    "audit-spec": "review-spec", "automate-qa": "qa", "autopilot": "autopilot",
    "checkpoint": "checkpoint", "commit": "commit", "create-pr": "create-pr",
    "create-ticket": "create-issue", "create-worktree": "create-worktree",
    "dependency-audit": "audit-deps", "evaluate-harness": "test-harness",
    "explain-code": "explain-code", "explore-ui": "design-ui", "finish-session": "finish-session",
    "graphify": "graphify", "implement-ui": "implement-ui", "investigate": "debug",
    "monitor-pr": "watch-pr", "optimize-harness": "optimize-harness", "plan-issues": "plan",
    "pr-review": "review-pr", "process-ticket": "implement-issue", "promote-memory": "memory-to-rules",
    "review-code": "review-code", "review-ui": "review-ui", "sync-design": "sync-design",
    "sync-dev-docs": "dev-docs", "sync-docs": "sync-docs", "sync-user-docs": "user-docs",
    "triage-comments": "pr-feedback", "update-dependencies": "update-deps",
    "update-project-status": "update-status",
}


def test_public_names_paths_and_calls_are_short_but_contracts_stay_compatible():
    assets = asset_files("generic", ["codex", "claude-code"])
    entries = {path.split("/")[2]: data.decode() for path, (data, _) in assets.items()
               if path.startswith(".agents/skills/") and path.endswith("/SKILL.md")}
    assert set(entries) == set(EXPECTED.values())
    for internal, public in EXPECTED.items():
        assert f"\nname: {public}\n" in entries[public]
        assert f"내장 계약: `{internal}`" in entries[public]
    for path, (data, _) in assets.items():
        if path.endswith(".md"):
            for internal, public in EXPECTED.items():
                if internal != public:
                    assert f".agents/skills/{internal}/" not in data.decode(), path
                    assert f"/{internal}`" not in data.decode(), path


@pytest.mark.parametrize("name", ["watch-pr", "monitor-pr"])
def test_public_script_alias_runs_existing_bundled_script(tmp_path, name):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = subprocess.run(
        [sys.executable, "-m", "neurath", "--root", str(tmp_path), "skill",
         name, "monitor_runtime_readback.py", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_names_do_not_collide_with_each_other_or_existing_contract_ids():
    assert len(set(EXPECTED.values())) == len(EXPECTED)
    assert all(public == internal or public not in EXPECTED for internal, public in EXPECTED.items())
