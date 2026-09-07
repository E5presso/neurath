"""Repository-selected argv checks using the original bounded process primitive."""

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from neurath.runtime.engine import activate


class VerificationError(RuntimeError):
    """Invalid verifier configuration or unavailable repository evidence."""


def fingerprint(root):
    def git(*args, required=True):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
        if required and result.returncode:
            raise VerificationError("Git read-back failed")
        return result.stdout

    digest = hashlib.sha256()
    digest.update(git("rev-parse", "HEAD", required=False))
    digest.update(git("ls-files", "--stage", "-z"))
    inventory = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    for name in sorted(set(filter(None, inventory.split(b"\0")))):
        relative = os.fsdecode(name)
        if relative.startswith((".agents/runs/", ".neurath/local/")):
            continue
        path = root / relative
        digest.update(len(name).to_bytes(8, "big") + name)
        if path.is_symlink():
            content = b"link:" + os.fsencode(os.readlink(path))
        elif path.is_file():
            content = path.read_bytes()
            digest.update(str(path.stat().st_mode & 0o777).encode())
        else:
            content = b"missing"
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


def verify(root, config, *, environment=None):
    root = Path(root).resolve()
    argv = config.get("argv")
    cwd_value = config.get("cwd", ".")
    codes = config.get("success_codes", [0])
    timeout = config.get("timeout_seconds", 300)
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(x, str) or not x or "\0" in x for x in argv)
    ):
        raise VerificationError(
            "argv must be a nonempty string array; shell expressions are not accepted"
        )
    if not isinstance(cwd_value, str) or Path(cwd_value).is_absolute():
        raise VerificationError("cwd must be repository relative")
    cwd = (root / cwd_value).resolve()
    if not cwd.is_relative_to(root) or not cwd.is_dir():
        raise VerificationError("cwd escapes repository or does not exist")
    if (
        not isinstance(codes, list)
        or not codes
        or any(type(code) is not int or code < 0 or code > 123 for code in codes)
    ):
        raise VerificationError(
            "success_codes must contain normal nonnegative exit codes below 124"
        )
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise VerificationError("timeout_seconds must be positive and at most 3600")
    expected = config.get("stdout_contains")
    if expected is not None and (not isinstance(expected, str) or not expected):
        raise VerificationError("stdout_contains must be a nonempty string")
    before = fingerprint(root)
    activate()
    from scripts.agent_harness.bounded_process import run_bounded_process

    try:
        result = run_bounded_process(argv, cwd=cwd, timeout_seconds=timeout, environment=environment)
        exit_code = result.returncode
        output = result.stdout + b"\0" + result.stderr
        passed = (
            exit_code in codes
            and not result.timed_out
            and (expected is None or expected.encode() in result.stdout)
        )
        timed_out = result.timed_out
        error = None
    except OSError as exception:
        exit_code, output, passed, timed_out = None, str(exception).encode(), False, False
        error = type(exception).__name__
    after = fingerprint(root)
    return {
        "schema": "neurath.project-verification-receipt.v1",
        "status": "passed" if passed and before == after else "failed",
        "argv": argv,
        "cwd": cwd_value,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "before_fingerprint": before,
        "after_fingerprint": after,
        "worktree_changed": before != after,
        "exit_code": exit_code,
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "timed_out": timed_out,
        "error": error,
    }
