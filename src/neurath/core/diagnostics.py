"""Installation comparison is diagnostic; it does not gate reads or invent activation."""

import subprocess

from neurath.install.file_values import InstallError
from neurath.install.records import read_state


def installation_status(worktree, runtime_info):
    try:
        state = read_state(worktree)
    except InstallError, ValueError, OSError, subprocess.SubprocessError:
        return {"status": "unavailable", "matches_running": None}
    if state is None:
        return {"status": "not-installed", "matches_running": None}
    running = None if runtime_info is None else runtime_info["distribution"]
    recorded = state.get("distribution")
    return {
        "status": "recorded",
        "distribution": recorded,
        "matches_running": None if running is None else running == recorded,
        "activation": "matching-native-mcp" if running and running == recorded else "unverified",
    }
