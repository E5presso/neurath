"""Preserve user provider settings without copying the caller's native identity."""

import os


def child_environment(environment=None):
    source = os.environ if environment is None else environment
    identity = {
        "CLAUDECODE",
        "PYTHONPATH",
        "CODEX_THREAD_ID",
        "CODEX_TURN_ID",
        "CODEX_AGENT_ID",
        "CODEX_PARENT_THREAD_ID",
        "CODEX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
    }
    return {
        key: value
        for key, value in source.items()
        if key not in identity and not key.startswith("NEURATH_")
    }
