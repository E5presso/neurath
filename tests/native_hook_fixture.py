"""Native hook subprocess fixture, never a claim of real host activation."""
import json
import subprocess
import sys


def invoke(root, provider, session, event, **fields):
    return subprocess.run(
        [sys.executable, "-I", "-m", "neurath.core.hooks", "--root", str(root), "--provider", provider],
        input=json.dumps({"session_id": session, "hook_event_name": event, "cwd": str(root), **fields}),
        text=True, capture_output=True, check=False,
    )
