"""Offline v1 adoption at the installer boundary; the old database stays intact."""

import fcntl
import json
import os
import sqlite3
import subprocess
from contextlib import ExitStack, contextmanager
from pathlib import Path

from neurath.core.domain import require
from neurath.core.legacy_work import adopt, preview, snapshot
from neurath.core.store import Store
from neurath.project_paths import control_root

LEGACY_DATABASES = (
    ".neurath/local/memory/project.sqlite3",
    ".neurath/local/agents/messages.sqlite3",
    ".neurath/local/models/plans.sqlite3",
    ".neurath/local/maintenance/calls.sqlite3",
)


def require_cutover(worktree):
    root = control_root(Path(worktree).resolve())
    if any((root / path).is_file() for path in LEGACY_DATABASES):
        raise ValueError(
            "Retained legacy databases require an explicit offline migration before installation"
        )
    if (root / ".neurath/local/cutover-pending.json").exists():
        raise ValueError("Interrupted shared-store cutover requires recovery before installation")


def transition_plan(worktree):
    root = control_root(Path(worktree).resolve())
    path = root / ".neurath/local/core.sqlite3"
    require(not path.is_symlink(), "unsafe-store-path")
    if path.is_file():
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT 1 FROM sqlite_schema WHERE name='records'").fetchone():
                row = db.execute(
                    "SELECT document FROM records WHERE kind='migration' AND id='v1-work'"
                ).fetchone()
                if row and json.loads(row[0]).get("installed"):
                    # Historical data is no longer a live progress authority.
                    return {"adopted": json.loads(row[0])["digest"]}
    document = snapshot(root)
    if document is None or not document["records"]:
        return None
    return preview(document)


def _started(pid):
    if Path("/proc").is_dir():
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return None if fields[0] == "Z" else fields[19]
        except OSError, IndexError:
            return None
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart="],
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _require_offline(root, db, stack):
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,args="], capture_output=True, text=True, check=True
    )
    old_modules = (
        "neurath.agents.mcp",
        "neurath.providers.jobs",
        "neurath.hosts.",
        "scripts.skill_harness.",
    )
    live = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not any(name in fields[1] for name in old_modules):
            continue
        same_project = str(root) in fields[1]
        # The v1 MCP launcher puts its checkout after --root. Reuse the Git
        # common-root identity used by both stores, including linked checkouts.
        if "neurath.agents.mcp --root " in fields[1]:
            argument = fields[1].split("neurath.agents.mcp --root ", 1)[1].strip().strip("\"'")
            try:
                same_project = control_root(Path(argument)) == root
            except OSError, subprocess.CalledProcessError:
                pass
        if same_project:
            live.append(int(fields[0]))
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    processes = []
    if "runtime_records" in tables:
        for (payload,) in db.execute(
            "SELECT payload FROM runtime_records WHERE namespace='host-journal'"
        ):
            value = json.loads(payload)
            processes.extend(
                item.get("process")
                for item in value.get("tools", {}).values()
                if item.get("active")
            )
    if "monitor_jobs" in tables:
        columns = {row[1] for row in db.execute("PRAGMA table_info(monitor_jobs)")}
        if {"pid", "started"} <= columns:
            processes.extend(
                {"pid": p, "started": s}
                for p, s in db.execute("SELECT pid,started FROM monitor_jobs")
            )
    for process in processes:
        if isinstance(process, dict) and type(process.get("pid")) is int:
            if (
                process.get("started") is not None
                and _started(process["pid"]) == process["started"]
            ):
                live.append(process["pid"])
    require(not live, "core-transition-host-active", process_ids=sorted(set(live)))
    # Existing v1 workers hold these locks for their lifetime. Never create a lease.
    directory = root / ".neurath/local/agents/worker-leases"
    require(not directory.is_symlink(), "unsafe-legacy-work-source")
    for path in directory.glob("*.lock"):
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        lock = stack.enter_context(os.fdopen(descriptor, "r+"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            require(False, "core-transition-worker-active")


@contextmanager
def apply_transition(worktree, plan):
    if plan is None or "adopted" in plan:
        yield
        return
    root = control_root(Path(worktree).resolve())
    path = root / ".neurath/local/runtime.sqlite3"
    require(not path.is_symlink(), "unsafe-legacy-work-source")
    with ExitStack() as stack:
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0)
        stack.callback(db.close)
        try:
            db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            require(False, "core-transition-writer-active")
        _require_offline(root, db, stack)
        require(preview(snapshot(root)) == plan, "legacy-work-source-changed")
        store = Store(root)
        adopt(store, expected_digest=plan["digest"])
        yield
        with store.transaction() as tx:
            marker = tx.record("migration", "v1-work")
            tx.put_record(
                "migration", "v1-work", {**marker["value"], "installed": True}, marker["revision"]
            )
            for task in tx.tasks():
                if tx.record("retired-owner", task.owner_actor) is None:
                    tx.put_record(
                        "retired-owner",
                        task.owner_actor,
                        {
                            "source": "offline-installation-observation",
                            "digest": plan["digest"],
                        },
                    )
        # No writes are made to v1. Holding its writer lock spans the file switch.
        db.rollback()
