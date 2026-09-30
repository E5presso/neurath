"""Schedule and clean up one bounded macOS Codex app relaunch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


BUNDLE_ID = "com.openai.codex"
LABEL_PREFIX = "com.openai.neurath.reconnect"
THREAD_ID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
KEY = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


class RelaunchError(ValueError):
    """The requested relaunch cannot be safely scheduled or cleaned up."""


def _identity(thread_id: str, key: str) -> str:
    if THREAD_ID.fullmatch(thread_id) is None or KEY.fullmatch(key) is None:
        raise RelaunchError("thread ID or stable key is invalid")
    digest = hashlib.sha256(f"{thread_id}\0{key}".encode()).hexdigest()[:20]
    return f"{LABEL_PREFIX}.{digest}"


def _paths(label: str) -> tuple[Path, Path, Path]:
    home = Path.home()
    return (
        home / "Library/LaunchAgents" / f"{label}.plist",
        home / "Library/Logs/Neurath" / f"{label}.out",
        home / "Library/Logs/Neurath" / f"{label}.err",
    )


def _app_executable(pid: int) -> Path:
    if pid <= 1:
        raise RelaunchError("app PID must be a live positive process")
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "args="],
        capture_output=True, text=True, check=False, timeout=10,
    )
    value = result.stdout.strip()
    if result.returncode or not value or "\n" in value:
        raise RelaunchError("exact Codex app process is unavailable")
    executable = Path(value)
    if executable.parent.name != "MacOS" or not executable.is_file():
        raise RelaunchError("PID does not identify an app main executable")
    info = executable.parent.parent / "Info.plist"
    try:
        with info.open("rb") as handle:
            bundle = plistlib.load(handle).get("CFBundleIdentifier")
    except (OSError, ValueError, TypeError) as error:
        raise RelaunchError("app bundle identity is unavailable") from error
    if bundle != BUNDLE_ID:
        raise RelaunchError("PID does not belong to the Codex app")
    return executable


def _command(executable: Path, pid: int, thread_id: str, delay: int) -> str:
    if not 10 <= delay <= 300:
        raise RelaunchError("relaunch delay must be between 10 and 300 seconds")
    expected = shlex.quote(str(executable))
    thread_url = shlex.quote(f"codex://threads/{thread_id}")
    still_old = (
        f"/bin/ps -p {pid} -o args= | /usr/bin/grep -Fxq -- {expected}"
    )
    return (
        f"/bin/sleep {delay}; "
        f"if {still_old}; then /bin/kill -TERM {pid} || exit 1; fi; "
        "/bin/sleep 15; "
        f"if {still_old}; then exit 1; fi; "
        f"/usr/bin/open -b {BUNDLE_ID} || exit 1; "
        f"/bin/sleep 6; /usr/bin/open {thread_url}"
    )


def _plist(label: str, executable: Path, pid: int, thread_id: str, delay: int) -> dict:
    _, stdout, stderr = _paths(label)
    return {
        "Label": label,
        "ProgramArguments": ["/bin/zsh", "-c", _command(executable, pid, thread_id, delay)],
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(stdout),
        "StandardErrorPath": str(stderr),
    }


def _launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *arguments],
        capture_output=True, text=True, check=False, timeout=15,
    )


def schedule(thread_id: str, pid: int, key: str, delay: int, execute: bool) -> dict:
    if sys.platform != "darwin":
        raise RelaunchError("one-shot Codex relaunch supports macOS only")
    label = _identity(thread_id, key)
    executable = _app_executable(pid)
    path, stdout, stderr = _paths(label)
    desired = _plist(label, executable, pid, thread_id, delay)
    result = {
        "label": label,
        "plist": str(path),
        "old_pid": pid,
        "thread_id": thread_id,
        "status": "planned",
    }
    if not execute:
        return result
    if path.exists():
        try:
            with path.open("rb") as handle:
                existing = plistlib.load(handle)
        except (OSError, ValueError, TypeError) as error:
            raise RelaunchError("existing relaunch plan cannot be verified") from error
        if existing != desired:
            raise RelaunchError("stable key identifies a different relaunch plan")
        return {**result, "status": "already-scheduled"}
    path.parent.mkdir(parents=True, exist_ok=True)
    stdout.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{label}.", delete=False) as tmp:
        temporary = Path(tmp.name)
        plistlib.dump(desired, tmp)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    started = _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    if started.returncode:
        path.unlink(missing_ok=True)
        raise RelaunchError(f"LaunchAgent bootstrap failed: {started.stderr.strip()[-400:]}")
    observed = _launchctl("print", f"gui/{os.getuid()}/{label}")
    if observed.returncode or "state = running" not in observed.stdout:
        # launchctl may accept bootstrap before the job is visible to print.
        # Preserve the one-shot plan so a caller can inspect it after startup;
        # treating this as a scheduling failure could provoke a second restart.
        return {**result, "status": "scheduled-unverified"}
    return {**result, "status": "scheduled"}


def cleanup(thread_id: str, key: str) -> dict:
    if sys.platform != "darwin":
        raise RelaunchError("one-shot Codex relaunch supports macOS only")
    label = _identity(thread_id, key)
    path, stdout, stderr = _paths(label)
    if not path.exists():
        return {"label": label, "status": "absent"}
    try:
        with path.open("rb") as handle:
            existing = plistlib.load(handle)
    except (OSError, ValueError, TypeError) as error:
        raise RelaunchError("relaunch plan cannot be verified for cleanup") from error
    if existing.get("Label") != label:
        raise RelaunchError("relaunch plan label differs from the requested key")
    _launchctl("bootout", f"gui/{os.getuid()}/{label}")
    for owned in (path, stdout, stderr):
        owned.unlink(missing_ok=True)
    return {"label": label, "status": "cleaned"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("schedule", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("--thread-id", required=True)
        command.add_argument("--key", required=True)
        if name == "schedule":
            command.add_argument("--pid", type=int, required=True)
            command.add_argument("--delay-seconds", type=int, default=45)
            command.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            schedule(args.thread_id, args.pid, args.key, args.delay_seconds, args.execute)
            if args.operation == "schedule"
            else cleanup(args.thread_id, args.key)
        )
    except RelaunchError as error:
        parser.exit(2, f"reconnect-host: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
