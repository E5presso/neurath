"""Readback produces operation-bound publication evidence without publishing anything."""

import subprocess

import pytest

from neurath.core.domain import Condition, CoreError, Evidence, validate_conditions
from neurath.core.publications import observe


def test_git_push_observation_reads_actual_remote_head(tmp_path):
    root, remote = tmp_path / "repo", tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "initial",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(root), "push", "-q", "origin", "HEAD:delivery"], check=True)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    result = observe(
        root,
        {
            "checkout": str(root),
            "publication_kind": "git-push",
            "reference": "delivery",
            "head": head,
        },
    )
    assert result["ok"] and result["operation"] == "git.push"
    wrong = observe(
        root,
        {
            "checkout": str(root),
            "publication_kind": "git-push",
            "reference": "delivery",
            "head": "0" * 40,
        },
    )
    assert not wrong["ok"]


def test_a_successful_push_cannot_substitute_for_merge_observation():
    condition = Condition("merged", frozenset({"publication"}), operation="github.pr.merged")
    pushed = Evidence("e", "publication", "s", "actor", "head", True, "git.push")
    with pytest.raises(CoreError, match="evidence-operation"):
        validate_conditions((condition,), {"merged": (pushed,)}, {})
