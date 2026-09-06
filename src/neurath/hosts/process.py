"""Bind hook-issued identity to the actual native shell and its live descendants."""

import os
import subprocess
import sys
from pathlib import Path


def process_identity(pid):
    if Path("/proc").is_dir():
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                raise ValueError("native tool process is no longer alive")
            return int(fields[1]), fields[19]
        except (OSError, IndexError) as error:
            raise ValueError("native tool process is no longer alive") from error
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "ppid=", "-o", "lstart="],
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
    )
    fields = result.stdout.strip().split(maxsplit=1)
    if result.returncode or len(fields) != 2:
        raise ValueError("native tool process is no longer alive")
    return int(fields[0]), fields[1]


def verify_process(receipt):
    process = receipt.get("process")
    if not isinstance(process, dict):
        raise ValueError("tool process has not bound its native shell")
    pid = os.getpid()
    for _ in range(64):
        parent, started = process_identity(pid)
        if pid == process["pid"] and started == process["started"]:
            return
        if parent <= 1 or parent == pid:
            break
        pid = parent
    raise ValueError("tool token is outside its live native process tree")


def bind_tool_process(environment):
    from neurath.hosts.identity import resolve_binding, journal

    resolve_binding(environment, require_process=False)
    session, nonce = environment["NEURATH_TOOL_BINDING"].rsplit(":", 1)
    pid = os.getppid()
    if pid <= 1:
        raise ValueError("native shell ended before process binding")
    _, started = process_identity(pid)
    process = {"pid": pid, "started": started}
    with journal(os.environ["NEURATH_TARGET_ROOT"], session) as data:
        record = next(r for r in data["tools"].values() if r["nonce"] == nonce)
        if not record["active"] or record.get("process", process) != process:
            raise ValueError("tool receipt is already bound to another process")
        record["process"] = process


def main():
    from neurath.runtime.engine import activate

    activate(Path(sys.argv[1]))
    try:
        bind_tool_process(os.environ)
    except (ValueError, OSError, KeyError) as error:
        print(f"Neurath native tool process rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
