"""Read authoritative Git/GitHub state; caller expectations never become evidence."""

import json
import re
import subprocess

from neurath.core.domain import require
from neurath.core.workspace import checkout


def _run(argv, cwd):
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=True, timeout=60)
    return result.stdout


def _repo(root):
    remote = _run(["git", "remote", "get-url", "origin"], root).strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?",
        remote,
    )
    require(match is not None, "github-remote-required")
    return match[1]


def observe(root, values):
    target = checkout(root, values["checkout"])
    kind = values["publication_kind"]
    require(
        kind in {"git-push", "pull-request", "pr-merge", "issue-closed", "release"},
        "publication-kind",
    )
    head = values.get("head")
    require(
        head is None or isinstance(head, str) and re.fullmatch(r"[a-f0-9]{40}", head),
        "expected-head",
    )
    reference = values["reference"]
    require(
        isinstance(reference, str) and reference and not reference.startswith("-"),
        "publication-reference",
    )
    if kind == "git-push":
        require(head is not None, "expected-head")
        _run(["git", "check-ref-format", "refs/heads/" + reference], target)
        local = _run(["git", "rev-parse", "--verify", "HEAD"], target).strip()
        lines = _run(
            ["git", "ls-remote", "--heads", "origin", "refs/heads/" + reference], target
        ).splitlines()
        remote = lines[0].split()[0] if len(lines) == 1 else None
        return {
            "ok": local == remote == head,
            "operation": "git.push",
            "subject": head,
            "local_head": local,
            "remote_head": remote,
            "branch": reference,
        }
    repo = _repo(target)

    def api(path):
        return json.loads(_run(["gh", "api", "repos/" + repo + "/" + path], target))

    if kind in {"pull-request", "pr-merge", "issue-closed"}:
        require(reference.isdigit(), "publication-reference")
        data = api(("issues/" if kind == "issue-closed" else "pulls/") + reference)
        if kind == "issue-closed":
            return {
                "ok": data.get("state") == "closed" and "pull_request" not in data,
                "operation": "github.issue.closed",
                "subject": reference,
                "observed": data,
            }
        require(head is not None, "expected-head")
        matched = data.get("head", {}).get("sha") == head
        if kind == "pr-merge":
            matched = matched and data.get("merged") is True and bool(data.get("merge_commit_sha"))
        return {
            "ok": matched,
            "operation": "github.pr.merged" if kind == "pr-merge" else "github.pr",
            "subject": head,
            "observed": data,
        }
    require(
        head is not None
        and isinstance(values.get("asset_sha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", values["asset_sha256"]),
        "release-expectation",
    )
    require(re.fullmatch(r"v\d+\.\d+\.\d+", reference), "release-tag")
    data = api("releases/tags/" + reference)
    ref = api("git/ref/tags/" + reference)["object"]
    for _ in range(5):
        if ref["type"] == "commit":
            break
        require(ref["type"] == "tag", "release-tag-object")
        ref = api("git/tags/" + ref["sha"])["object"]
    expected_digest = "sha256:" + values["asset_sha256"]
    assets = [
        item
        for item in data.get("assets", [])
        if item.get("digest") == expected_digest and item.get("state") == "uploaded"
    ]
    return {
        "ok": ref.get("type") == "commit"
        and ref.get("sha") == head
        and not data.get("draft")
        and not data.get("prerelease")
        and len(assets) == 1,
        "operation": "github.release",
        "subject": head,
        "observed": data,
        "tag_object": ref,
        "asset_sha256": values["asset_sha256"],
    }
