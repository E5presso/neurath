"""Skill retirement and unprefixed installation preserve existing project assets."""

import json
import os
import subprocess

import pytest

from neurath.install import transaction as installer
from neurath.install.projection import asset_files, project_text, skills
from neurath.resources import BUNDLE
from neurath.skill_names import public_name

RETIRED = {
    "create-package", "local-dev", "onboard", "refactor-code",
    "impact-analysis", "improve-coverage", "property-test",
}
RETAINED = {
    "audit-spec", "automate-qa", "autopilot", "checkpoint", "commit", "create-pr",
    "create-ticket", "create-worktree", "dependency-audit", "evaluate-harness",
    "explain-code", "explore-ui", "finish-session", "graphify", "implement-ui",
    "investigate", "monitor-pr", "optimize-harness", "plan-issues", "pr-review",
    "process-ticket", "promote-memory", "review-code", "review-ui", "sync-design",
    "sync-dev-docs", "sync-docs", "sync-user-docs", "triage-comments",
    "update-dependencies", "update-project-status",
}
LEGACY_BLOCK = (
    "\n<!-- neurath:managed -->\n## Neurath\n\n"
    "Read `.neurath/policy.md` and `.neurath/project.json` for the generic profile.\n"
    "Use the `neurath-` skills in `.agents/skills`; execute through `.neurath/run`.\n"
    "<!-- /neurath:managed -->\n"
)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def install_legacy(repo, prefix="neurath-"):
    """A minimal v1 fixture records the old names without importing an old installer."""
    owned = {}
    for name in RETAINED | RETIRED:
        path = f".agents/skills/{prefix}{name}/SKILL.md"
        value = installer.file_value(f"---\nname: neurath-{name}\n---\nLegacy skill\n".encode())
        installer._write(repo, path, value)
        owned[path] = {"original": None, "installed": value}
        path = f".claude/skills/{prefix}{name}"
        value = {"kind": "symlink", "target": f"../../.agents/skills/{prefix}{name}"}
        installer._write(repo, path, value)
        owned[path] = {"original": None, "installed": value}
    original = installer.file_value(b"# Project rules\n")
    installed = installer.file_value(b"# Project rules\n" + LEGACY_BLOCK.encode())
    installer._write(repo, "AGENTS.md", installed)
    owned["AGENTS.md"] = {"original": original, "installed": installed}
    state = {
        "schema": 1, "version": "0.1.0", "distribution": "legacy-test-distribution",
        "profile": "generic", "hosts": ["claude-code", "codex"], "owned": owned,
    }
    installer._write(repo, installer.STATE, installer.file_value(json.dumps(state).encode(), 0o600))


def contents(repo):
    """Compare product bytes and validated install state, excluding private runtime history."""
    return {
        str(p.relative_to(repo)): ("link", os.readlink(p)) if p.is_symlink() else (
            installer.canonical(installer.read_state(repo)).encode()
            if p == repo / installer.STATE else p.read_bytes())
        for p in repo.rglob("*")
        if ".git" not in p.relative_to(repo).parts and not p.is_relative_to(repo / ".neurath/local")
        and (p.is_file() or p.is_symlink())
    }


def test_inventory_retires_only_the_seven_approved_skills():
    assert set(skills()) == RETAINED
    contracts = json.loads((BUNDLE / ".agents/skills/contracts.json").read_text())["skills"]
    assert set(contracts) == RETAINED - {"explain-code", "graphify"}
    cases = json.loads((BUNDLE / ".agents/skills/intent-routing-evals.json").read_text())["cases"]
    for case in cases:
        assert case.get("expected_selected_skill") not in RETIRED
        assert not (set(case.get("expected_rejected_skills", [])) & RETIRED)


@pytest.mark.parametrize("hosts", [["codex"], ["claude-code"], ["codex", "claude-code"]])
def test_install_uses_unprefixed_names_paths_and_references(repo, hosts):
    installer.apply_plan(repo, installer.make_plan(repo, hosts=hosts))
    assert {p.parent.name for p in (repo / ".agents/skills").glob("*/SKILL.md")} == {public_name(s) for s in RETAINED}
    for name in RETAINED:
        name = public_name(name)
        content = (repo / f".agents/skills/{name}/SKILL.md").read_text()
        assert f"\nname: {name}\n" in content
        assert "/neurath-" not in content
        if "claude-code" in hosts:
            assert (repo / f".claude/skills/{name}").resolve() == repo / f".agents/skills/{name}"
    assert not installer.make_plan(repo, hosts=hosts)["changes"]


def test_script_and_catalog_references_keep_canonical_names():
    text = "bash .agents/skills/process-ticket/scripts/assert_worktree_isolation.sh --init 1\n/commit"
    assert project_text(text, "generic") == (
        ".neurath/run skill implement-issue assert_worktree_isolation.sh --init 1\n/commit"
    )
    audit = asset_files("generic", ["codex"])[".neurath/reference/HARNESS_AUDIT.md"][0].decode()
    assert "../../.agents/skills/debug/SKILL.md" in audit
    assert "/neurath-" not in audit


def test_legacy_update_restore_and_uninstall_preserve_user_content(repo):
    install_legacy(repo)
    note = repo / ".agents/skills/neurath-investigate/notes.txt"
    note.write_text("Keep user notes")
    before = contents(repo)
    record = installer.apply_plan(repo, installer.make_plan(repo, action="update"))
    for name in RETAINED | RETIRED:
        assert not (repo / f".agents/skills/neurath-{name}/SKILL.md").exists()
        assert not (repo / f".claude/skills/neurath-{name}").is_symlink()
        if name != "investigate":
            assert not (repo / f".agents/skills/neurath-{name}").exists()
    assert note.read_text() == "Keep user notes"
    assert {p.parent.name for p in (repo / ".agents/skills").glob("*/SKILL.md")} == {public_name(s) for s in RETAINED}
    assert not installer.make_plan(repo)["changes"]
    installer.apply_plan(repo, installer.make_plan(repo, action="restore", receipt=record["id"]))
    assert contents(repo) == before
    installer.apply_plan(repo, installer.make_plan(repo, action="update"))
    installer.apply_plan(repo, installer.make_plan(repo, action="uninstall"))
    assert (repo / "AGENTS.md").read_text() == "# Project rules\n"
    assert note.read_text() == "Keep user notes"
    assert not list((repo / ".agents/skills").glob("*/SKILL.md"))


@pytest.mark.parametrize("path", [
    ".agents/skills/debug/SKILL.md",
    ".agents/skills/debug/README.md",
    ".claude/skills/debug",
])
def test_legacy_update_refuses_unowned_same_name_without_writes(repo, path):
    install_legacy(repo)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("User-owned skill")
    before = contents(repo)
    with pytest.raises(installer.InstallError, match="conflict"):
        installer.make_plan(repo, action="update")
    assert contents(repo) == before


@pytest.mark.parametrize("name", ["investigate", "local-dev"])
def test_legacy_update_preserves_edited_managed_skills(repo, name):
    install_legacy(repo)
    (repo / f".agents/skills/neurath-{name}/SKILL.md").write_text("Local changes")
    before = contents(repo)
    with pytest.raises(installer.InstallError, match="modified"):
        installer.make_plan(repo, action="update")
    assert contents(repo) == before


def test_migration_failure_rolls_back_old_names_and_links(repo, monkeypatch):
    install_legacy(repo)
    before = contents(repo)
    real_write = installer._write
    failed = False

    def fail_during_retirement(root, path, value):
        nonlocal failed
        if path == ".agents/skills/neurath-investigate/SKILL.md" and value is None and not failed:
            failed = True
            raise OSError("injected migration failure")
        return real_write(root, path, value)

    monkeypatch.setattr(installer, "_write", fail_during_retirement)
    with pytest.raises(OSError, match="injected"):
        installer.apply_plan(repo, installer.make_plan(repo, action="update"))
    assert failed
    assert contents(repo) == before


def test_legacy_shared_claude_directory_link_survives_update_and_restore(repo):
    install_legacy(repo)
    state = installer.read_state(repo)
    for path in list(state["owned"]):
        if path.startswith(".claude/skills/"):
            (repo / path).unlink()
            del state["owned"][path]
    (repo / ".claude/skills").rmdir()
    (repo / ".claude/skills").symlink_to("../.agents/skills", target_is_directory=True)
    installer._write(repo, installer.STATE, installer.file_value(json.dumps(state).encode(), 0o600))
    before = contents(repo)
    result = installer.apply_plan(repo, installer.make_plan(repo, action="update"))
    assert (repo / ".claude/skills").is_symlink()
    assert {p.parent.name for p in (repo / ".claude/skills").glob("*/SKILL.md")} == {public_name(s) for s in RETAINED}
    assert not installer.make_plan(repo)["changes"]
    installer.apply_plan(repo, installer.make_plan(repo, action="restore", receipt=result["id"]))
    assert contents(repo) == before


def test_unprefixed_previous_names_migrate_and_restore(repo):
    install_legacy(repo, prefix="")
    before = contents(repo)
    result = installer.apply_plan(repo, installer.make_plan(repo, action="update"))
    assert {p.parent.name for p in (repo / ".agents/skills").glob("*/SKILL.md")} == {public_name(s) for s in RETAINED}
    assert not (repo / ".agents/skills/automate-qa").exists()
    assert (repo / ".claude/skills/qa/SKILL.md").is_file()
    assert not installer.make_plan(repo)["changes"]
    installer.apply_plan(repo, installer.make_plan(repo, action="restore", receipt=result["id"]))
    assert contents(repo) == before


@pytest.mark.parametrize("edited", [False, True])
def test_public_legacy_managed_block_migrates_only_when_exact(repo, edited):
    original = "# Project rules\n" + LEGACY_BLOCK
    if edited:
        original = original.replace("Read `.neurath/policy.md`", "Ignore `.neurath/policy.md`")
    (repo / "AGENTS.md").write_text(original)
    if edited:
        with pytest.raises(installer.InstallError, match="unowned managed block conflict"):
            installer.make_plan(repo)
        assert (repo / "AGENTS.md").read_text() == original
    else:
        installer.apply_plan(repo, installer.make_plan(repo))
        assert "`neurath-` skills" not in (repo / "AGENTS.md").read_text()
        assert not installer.make_plan(repo)["changes"]
        installer.apply_plan(repo, installer.make_plan(repo, action="uninstall"))
        assert (repo / "AGENTS.md").read_text() == original
