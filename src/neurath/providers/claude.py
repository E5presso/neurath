"""Read official Claude agent-view metadata without opening or resuming sessions."""

import json
import shutil
import subprocess
from pathlib import Path

from neurath.providers.contracts import UnsupportedOperation


def discover(worktree, *, include_completed=False):
    from neurath.agents.runner import child_environment

    executable = shutil.which("claude")
    if executable is None:
        raise UnsupportedOperation("Claude Code CLI is not installed")
    root = str(Path(worktree).resolve())
    argv = [executable, "agents", "--json", "--cwd", root]
    if include_completed:
        argv.append("--all")
    output = subprocess.run(argv, cwd=root, env=child_environment(), capture_output=True,
                            text=True, timeout=15, check=True).stdout
    if len(output.encode()) > 2 * 1024 * 1024:
        raise ValueError("Claude agent listing exceeds 2 MiB")
    return normalize_listing(output, root)


def normalize_listing(output, worktree):
    rows = json.loads(output)
    if not isinstance(rows, list):
        raise ValueError("Claude agent listing must be an array")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("cwd"), str):
            raise ValueError("Claude agent listing lacks a workspace")
        if Path(row["cwd"]).resolve() != Path(worktree).resolve():
            continue
        if row.get("kind") not in ("interactive", "background"):
            raise ValueError("unknown Claude session kind")
        result.append({
            "provider": "claude-code", "transport": "claude-background",
            "native_session": row.get("sessionId"), "job_id": row.get("id"),
            "worktree": row["cwd"], "kind": row["kind"], "name": row.get("name"),
            "state": row.get("state"), "process_status": row.get("status"),
            "waiting_for": row.get("waitingFor"), "pid": row.get("pid"),
            "started_at": row.get("startedAt"),
            "policy": {"requested": None, "effective": None, "verification": "unobserved"},
            "authority": "host-observation",
        })
    return result
