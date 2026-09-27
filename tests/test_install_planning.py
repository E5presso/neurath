"""Plan observations must bind one coherent distribution and all source reads."""

import subprocess

import pytest

from neurath.install import transaction


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_plan_binds_one_distribution_observation(repo, monkeypatch):
    observations = iter(["first-distribution", "changed-during-planning"])
    monkeypatch.setattr(transaction, "distribution_id", lambda: next(observations))

    plan = transaction.make_plan(repo, hosts=["codex"])

    assert plan["distribution"] == plan["after_state"]["distribution"] == "first-distribution"
    assert next(observations) == "changed-during-planning"


def test_untouched_project_bindings_are_still_plan_preconditions(repo):
    project = repo / ".neurath/project.json"
    project.parent.mkdir()
    project.write_text('{"schema": 1, "documents": {}, "verification": {}}\n')
    plan = transaction.make_plan(repo, hosts=["codex"])
    assert all(item["path"] != ".neurath/project.json" for item in plan["changes"])

    edited = '{"schema": 1, "documents": {"intent": "PRODUCT.md"}, "verification": {}}\n'
    project.write_text(edited)
    with pytest.raises(transaction.InstallError, match="stale plan: .neurath/project.json"):
        transaction.apply_plan(repo, plan)
    assert project.read_text() == edited
    assert not (repo / "AGENTS.md").exists()
