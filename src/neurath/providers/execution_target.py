"""Installed project/worktree boundary shared by native provider executors."""

import subprocess
from pathlib import Path

from neurath.project_paths import control_root


def target_worktree(root, worktree, mode):
    root, target = Path(root).resolve(), Path(worktree).resolve()
    if control_root(root) != control_root(target):
        raise ValueError("provider worktree belongs to another project")
    top = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if Path(top).resolve() != target or not (target / ".neurath/run").is_file():
        raise ValueError("provider requires an installed Git worktree root")
    if mode != "read-only" and target == root:
        raise ValueError("write provider requires a separate installed worktree")
    return target
