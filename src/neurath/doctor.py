"""Separate installation integrity, isolated protocol execution, and host activation."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from neurath.install.projection import host_hooks
from neurath.install.transaction import InstallError, read_state, rebase_shared, snapshot
from neurath.resources import PACKAGE, distribution_id


def passed(report):
    """Local diagnostics only; host activation has its own evidence boundary."""
    return report["placement"]["status"] == report["distribution"]["status"] == "passed" and all(
        check.get("status") != "failed"
        for check in report["protocol"].values()
        if isinstance(check, dict)
    )


def integrity(package=None):
    package = Path(package) if package is not None else PACKAGE
    errors = []
    try:
        spec = json.loads((package / "manifest.json").read_text())
        expected = spec["files"]
        if spec.get("schema") != 1 or not isinstance(expected, dict):
            raise ValueError("invalid manifest")
    except OSError, ValueError, KeyError, TypeError:
        return {"status": "failed", "files": 0, "errors": ["invalid manifest.json"]}
    actual = {
        p.relative_to(package).as_posix(): p
        for p in package.rglob("*")
        if (p.is_file() or p.is_symlink())
        and "__pycache__" not in p.parts
        and p.suffix != ".pyc"
        and p != package / "manifest.json"
    }
    for name in sorted(set(expected) | set(actual)):
        path = actual.get(name)
        if path is None or name not in expected:
            errors.append(name)
            continue
        try:
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
                errors.append(name)
        except OSError:
            errors.append(name)
    return {
        "status": "passed" if not errors else "failed",
        "files": len(expected),
        "errors": errors,
    }


def protocol_smoke():
    results = {}
    with tempfile.TemporaryDirectory(prefix="neurath-doctor-") as temporary:
        root = Path(temporary)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for host in ("codex", "claude-code"):
            path = root / (".codex/hooks.json" if host == "codex" else ".claude/settings.json")
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({"hooks": host_hooks(root, host)}))
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("CODEX_", "CLAUDE_", "NEURATH_"))
            }
            env["CODEX_THREAD_ID" if host == "codex" else "CLAUDE_SESSION_ID"] = f"doctor-{host}"
            payload = {
                "session_id": f"doctor-{host}",
                "hook_event_name": "SessionStart",
                "source": "startup",
                "cwd": str(root),
                "permission_mode": "default",
                "transcript_path": None,
            }
            command = [
                sys.executable,
                "-I",
                "-m",
                "neurath",
                "--root",
                str(root),
                "hook",
                "--host",
                host,
            ]
            process = subprocess.run(
                command,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
                check=False,
            )
            malformed = subprocess.run(
                command,
                input="{invalid",
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
                check=False,
            )
            try:
                valid = isinstance(json.loads(process.stdout), dict) and isinstance(
                    json.loads(malformed.stdout), dict
                )
            except ValueError:
                valid = False
            results[host] = {
                "status": "passed"
                if process.returncode == 0 and malformed.returncode == 2 and valid
                else "failed",
                "startup_exit": process.returncode,
                "malformed_exit": malformed.returncode,
                "diagnostic": process.stderr[-800:],
            }
    return results


def doctor(root, protocol=False):
    state = read_state(root)
    errors, notes = [], []
    if state:
        if state.get("distribution") != distribution_id():
            errors.append(".neurath/install.json: running package differs from recorded distribution")
        for path, record in state["owned"].items():
            if path == ".neurath/project.json":
                continue
            try:
                rebase_shared(path, record, snapshot(root, path))
            except InstallError:
                errors.append(path)
        config = root / ".codex/config.toml"
        if config.is_file():
            try:
                if "hooks" in tomllib.loads(config.read_text()):
                    notes.append(
                        "Codex inline hooks preserved alongside hooks.json; Codex merges both sources"
                    )
            except ValueError:
                errors.append(".codex/config.toml invalid TOML")
    else:
        errors.append("not installed")
    return {
        "distribution": integrity(),
        "placement": {"status": "passed" if not errors else "failed", "errors": errors},
        "protocol": protocol_smoke() if protocol else {"status": "not-run"},
        "host_activation": {
            "status": "unverified",
            "reason": "A local subprocess is not host attestation. Review exact hooks in the host; Codex requires project and hook trust.",
        },
        "notes": notes,
    }
