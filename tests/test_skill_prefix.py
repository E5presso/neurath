"""Explicit namespaces preserve user skills and bundled runtime contracts."""
import copy
import json
import subprocess
import sys

import pytest

from neurath.install.projection import asset_files, project_text, skills
from neurath.install.transaction import InstallError, apply_plan, make_plan, read_state
from neurath.skill_names import public_name


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "target repository"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def files(root):
    result = {}
    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts:
            continue
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = ("symlink", str(path.readlink()))
        elif path.is_file():
            result[relative] = (path.read_bytes(), path.stat().st_mode & 0o777)
    return result


@pytest.mark.parametrize("shared_adapter", [False, True])
@pytest.mark.parametrize("prefix", ["neurath-", "team-kit-"])
def test_prefix_preserves_user_files_through_repeat_update_uninstall(repo, shared_adapter, prefix):
    (repo / "AGENTS.md").write_bytes(b"# User rules\r\nUse /autopilot.\r\n")
    user = repo / ".agents/skills/autopilot/SKILL.md"
    user.parent.mkdir(parents=True)
    user.write_bytes(b"User /autopilot procedure\r\n")
    user.chmod(0o640)
    (user.parent / "notes.md").write_text("Keep supporting material.\n")
    (repo / ".claude").mkdir()
    settings = {"permissions": {"deny": ["Bash(rm *)"]}, "env": {"KEEP": "yes"}}
    (repo / ".claude/settings.json").write_text(json.dumps(settings))
    if shared_adapter:
        (repo / "CLAUDE.md").symlink_to("AGENTS.md")
        (repo / ".claude/skills").symlink_to("../.agents/skills")
    before = files(repo)
    with pytest.raises(InstallError, match="unowned skill"):
        make_plan(repo)
    plan = make_plan(repo, skill_prefix=prefix)
    assert plan["skill_prefix"] == prefix
    apply_plan(repo, json.loads(json.dumps(plan)))
    state = read_state(repo)
    assert state["skill_prefix"] == prefix
    receipt = json.loads((repo / ".git/neurath-receipts" / (plan["id"] + ".json")).read_text())
    assert receipt["skill_prefix"] == prefix
    assert not any(path.startswith(".agents/skills/autopilot/") for path in state["owned"])
    assert user.read_bytes() == before[".agents/skills/autopilot/SKILL.md"][0]
    assert user.stat().st_mode & 0o777 == 0o640
    for internal in skills():
        name = public_name(internal, prefix)
        assert (repo / f".agents/skills/{name}/SKILL.md").is_file()
        assert (repo / f".claude/skills/{name}").resolve() == (repo / f".agents/skills/{name}").resolve()
    assert make_plan(repo)["changes"] == []
    assert make_plan(repo, action="update")["changes"] == []
    apply_plan(repo, make_plan(repo, action="uninstall"))
    assert files(repo) == before


def test_prefix_restore_uses_saved_record_after_uninstall(repo):
    apply_plan(repo, make_plan(repo, skill_prefix="neurath-"))
    first = files(repo)
    changed = apply_plan(repo, make_plan(repo, action="update", hosts=["codex"]))
    apply_plan(repo, make_plan(repo, action="restore", receipt=changed["id"]))
    assert files(repo) == first
    removed = apply_plan(repo, make_plan(repo, action="uninstall"))
    assert read_state(repo) is None
    restored = make_plan(repo, action="restore", receipt=removed["id"])
    assert restored["skill_prefix"] == "neurath-"
    apply_plan(repo, restored)
    assert files(repo) == first
    assert make_plan(repo)["changes"] == []


@pytest.mark.parametrize("field,value", [("skill_prefix", "other-"), ("changes", [])])
def test_restore_rejects_modified_saved_record(repo, field, value):
    apply_plan(repo, make_plan(repo, skill_prefix="neurath-"))
    removed = apply_plan(repo, make_plan(repo, action="uninstall"))
    path = repo / ".git/neurath-receipts" / (removed["id"] + ".json")
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    before = files(repo)
    with pytest.raises(InstallError, match="record integrity"):
        make_plan(repo, action="restore", receipt=removed["id"])
    assert files(repo) == before


@pytest.mark.parametrize("prefix", ["other-", ""])
def test_installed_prefix_cannot_be_changed_by_update(repo, prefix):
    apply_plan(repo, make_plan(repo, skill_prefix="neurath-"))
    before = files(repo)
    with pytest.raises(InstallError, match="prefix differs"):
        make_plan(repo, action="update", skill_prefix=prefix)
    assert files(repo) == before


@pytest.mark.parametrize("prefix", ["../", "path/", "Neurath-", "missing-hyphen", "-", "a b-", 1, True])
def test_invalid_prefix_is_refused_without_writes(repo, prefix):
    before = files(repo)
    with pytest.raises(InstallError, match="prefix"):
        make_plan(repo, skill_prefix=prefix)
    assert files(repo) == before


def test_legacy_record_without_prefix_keeps_default_names(repo):
    apply_plan(repo, make_plan(repo))
    path = repo / ".neurath/install.json"
    state = json.loads(path.read_text())
    state.pop("skill_prefix", None)
    path.write_text(json.dumps(state))
    plan = make_plan(repo, action="update")
    assert plan["skill_prefix"] == ""
    apply_plan(repo, plan)
    assert (repo / ".agents/skills/debug/SKILL.md").is_file()
    assert not (repo / ".agents/skills/neurath-debug").exists()
    assert make_plan(repo)["changes"] == []


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_matching_prefix_never_adopts_unowned_assets(repo, kind):
    path = repo / ".agents/skills/neurath-autopilot"
    path.parent.mkdir(parents=True)
    if kind == "file":
        path.mkdir()
        (path / "SKILL.md").write_text("User asset already using this prefix\n")
    else:
        target = repo / "custom"
        target.mkdir()
        path.symlink_to(target, target_is_directory=True)
    before = files(repo)
    with pytest.raises(InstallError, match="conflict"):
        make_plan(repo, skill_prefix="neurath-")
    assert files(repo) == before


def test_prefix_keeps_managed_modification_protection(repo):
    apply_plan(repo, make_plan(repo, skill_prefix="neurath-"))
    path = repo / ".agents/skills/neurath-debug/SKILL.md"
    path.write_text("Locally changed managed policy\n")
    before = files(repo)
    for action in ("update", "uninstall"):
        with pytest.raises(InstallError, match="modified|conflict"):
            make_plan(repo, action=action)
    assert files(repo) == before


def test_prefix_plan_tampering_is_rejected_before_target_mutation(repo):
    plan = make_plan(repo, skill_prefix="neurath-")
    tampered = copy.deepcopy(plan)
    tampered["skill_prefix"] = "other-"
    with pytest.raises(InstallError, match="stale or modified"):
        apply_plan(repo, tampered)
    assert files(repo) == {}
    apply_plan(repo, json.loads(json.dumps(plan)))
    assert read_state(repo)["skill_prefix"] == "neurath-"


def test_prefix_projects_calls_links_policy_and_preserves_contract_ids():
    prefix = "neurath-"
    projected = asset_files("generic", ["codex", "claude-code"], prefix)
    default = asset_files("generic", ["codex", "claude-code"])
    entries = {path.split("/")[2]: data.decode() for path, (data, _) in projected.items()
               if path.startswith(".agents/skills/") and path.endswith("/SKILL.md")}
    assert set(entries) == {public_name(name, prefix) for name in skills()}
    for internal in skills():
        name = public_name(internal, prefix)
        assert f"\nname: {name}\n" in entries[name]
        assert f"내장 계약: `{internal}`" in entries[name]
        assert "명명 MCP 도구" in entries[name]
        assert ".neurath/run skill" not in entries[name]
    policy = projected[".neurath/policy.md"][0].decode()
    assert "/neurath-debug" in policy and "/neurath-qa" in policy
    assert "/debug`" not in policy
    before = json.loads(default[".neurath/reference/contracts.json"][0])
    after = json.loads(projected[".neurath/reference/contracts.json"][0])
    assert before["skills"].keys() == after["skills"].keys()
    sample = "/review-code `review-code` .agents/skills/review-code/SKILL.md ../sync-docs/doc-format.md .neurath/run skill watch-pr x.py"
    assert project_text(sample, "generic", prefix) == (
        "/neurath-review-code `review-code` .agents/skills/neurath-review-code/SKILL.md "
        "../neurath-sync-docs/doc-format.md .neurath/run skill neurath-watch-pr x.py"
    )
    audit = projected[".neurath/reference/HARNESS_AUDIT.md"][0].decode()
    assert "../../.agents/skills/neurath-review-code/SKILL.md" in audit
    exports = projected[".agents/skills/neurath-graphify/references/exports.md"][0].decode()
    assert "`graphify`" in exports
    assert "`neurath-graphify`" not in exports


def run_skill(root, name):
    return subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "--root", str(root), "skill", name,
         "monitor_runtime_readback.py", "--help"], capture_output=True, text=True,
    )


def test_engine_uses_recorded_alias_and_bundled_contract(repo):
    assert run_skill(repo, "neurath-watch-pr").returncode == 2
    user = repo / ".agents/skills/watch-pr/scripts/monitor_runtime_readback.py"
    user.parent.mkdir(parents=True)
    user.write_text("raise RuntimeError('USER_SCRIPT_MUST_NOT_RUN')\n")
    apply_plan(repo, make_plan(repo, skill_prefix="neurath-"))
    for name in ("neurath-watch-pr", "watch-pr", "monitor-pr"):
        result = run_skill(repo, name)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout
        assert "USER_SCRIPT_MUST_NOT_RUN" not in result.stderr
    assert run_skill(repo, "other-watch-pr").returncode == 2
    assert run_skill(repo, "neurath-monitor-pr").returncode == 2
    path = repo / ".neurath/install.json"
    state = json.loads(path.read_text())
    state["skill_prefix"] = "other-"
    path.write_text(json.dumps(state))
    assert run_skill(repo, "other-watch-pr").returncode == 2


def test_cli_plan_apply_and_setup_dry_run_preserve_prefix(repo, tmp_path, capsys, monkeypatch):
    from neurath import cli, doctor

    user = repo / ".agents/skills/autopilot/SKILL.md"
    user.parent.mkdir(parents=True)
    user.write_text("Keep the user procedure.\n")
    before = files(repo)
    monkeypatch.setattr(doctor, "integrity", lambda: {"status": "passed"})
    assert cli.main(["setup", str(repo), "--skill-prefix", "neurath-", "--dry-run", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["skill_prefix"] == "neurath-"
    assert report["status"] == "planned"
    assert files(repo) == before
    output = tmp_path / "private-plan.json"
    assert cli.main(["--root", str(repo), "plan", "--skill-prefix", "neurath-", "--output", str(output)]) == 0
    capsys.readouterr()
    assert json.loads(output.read_text())["skill_prefix"] == "neurath-"
    assert output.stat().st_mode & 0o777 == 0o600
    assert cli.main(["--root", str(repo), "apply", str(output)]) == 0
    capsys.readouterr()
    assert cli.main(["--root", str(repo), "update"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] == 0
    assert cli.main(["--root", str(repo), "uninstall"]) == 0
    capsys.readouterr()
    assert files(repo) == before
