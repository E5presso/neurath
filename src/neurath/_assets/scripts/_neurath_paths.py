"""Separate target state from package resources; corpus execution stays unchanged."""
import os
from pathlib import Path

def target_root(fallback):
    selected = os.environ.get("NEURATH_TARGET_ROOT")
    return Path(selected).resolve() if selected else fallback

def state_path(root, relative):
    if os.environ.get("NEURATH_TARGET_ROOT") and (Path(os.environ["NEURATH_TARGET_ROOT"]) / ".neurath/run").is_file():
        return root / ".neurath/local" / relative
    return root / ".agents" / relative

def asset_path(root, relative):
    # Only Neurath-managed targets use the immutable distribution contracts.
    if os.environ.get("NEURATH_TARGET_ROOT") and (root / ".neurath/run").is_file():
        return Path(__file__).resolve().parents[1] / relative
    return root / relative

def repository_head(root, git):
    import subprocess
    if not os.environ.get("NEURATH_TARGET_ROOT"):
        return git(root, ("rev-parse", "HEAD"), allow_failure=False).strip()
    head = git(root, ("rev-parse", "--verify", "HEAD"), allow_failure=True).strip()
    if head:
        return head
    ref = git(root, ("symbolic-ref", "--quiet", "HEAD"), allow_failure=False).strip()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(("git", "-C", str(root), "show-ref", "--verify", "--quiet", ref.decode()), capture_output=True, env=environment, check=False)
    if result.returncode == 1:
        return b"unborn:" + ref
    return git(root, ("rev-parse", "HEAD"), allow_failure=False).strip()
