"""Plans contain original settings and must stay private until explicitly handled."""

import json
import stat
import subprocess
import sys

import pytest

from neurath.install.transaction import git_dir


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "AGENTS.md").write_text("Keep this rule.\n")
    return root


def invoke(repo, *args, input=None):
    return subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "--root", str(repo), *args],
        input=input, text=True, capture_output=True, check=False, cwd=repo,
    )


def test_wizard_default_plan_is_private_and_outside_git_candidates(repo):
    result = invoke(repo, "wizard", input="generic\ncodex\nn\n")
    assert result.returncode == 0, result.stderr
    plans = list((git_dir(repo) / "neurath-plans").glob("*.json"))
    assert len(plans) == 1
    assert stat.S_IMODE(plans[0].stat().st_mode) == 0o600
    assert not (repo / "neurath-plan.json").exists()
    assert json.loads(plans[0].read_text())["root"] == str(repo)
    applied = invoke(repo, "apply", str(plans[0]))
    assert applied.returncode == 0, applied.stderr


@pytest.mark.parametrize("command", ["plan", "wizard"])
def test_explicit_plan_has_private_permissions(repo, command):
    output = repo.parent / "private-plan.json"
    result = invoke(repo, command, "--output", str(output), input="generic\ncodex\nn\n")
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["file", "symlink", "hardlink"])
def test_plan_does_not_overwrite_an_existing_output_or_its_target(repo, kind):
    original = repo.parent / "original.txt"
    original.write_text("Do not replace me.\n")
    output = repo.parent / "plan.json"
    if kind == "symlink":
        output.symlink_to(original)
    elif kind == "hardlink":
        output.hardlink_to(original)
    else:
        output.write_bytes(original.read_bytes())
    result = invoke(repo, "plan", "--output", str(output))
    assert result.returncode != 0
    assert original.read_text() == "Do not replace me.\n"
    assert output.read_text() == "Do not replace me.\n"
