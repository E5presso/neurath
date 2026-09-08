"""Owned PR monitor automation launched from an authenticated MCP invocation.

A protected single-use grant authorizes one service worker. It is not a native
agent registration, host attestation, or evaluator capability.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

from neurath.agents.store import MessageStore
from neurath.hosts.process import process_identity
from neurath.memory.store import canonical
from neurath.resources import BUNDLE, distribution_id

ACTIVE = ("accepted", "starting", "started", "cancelling")
TERMINAL = ("completed", "failed", "cancelled")


def _store(root):
    store = MessageStore(root)
    with store.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS monitor_jobs (
            run_id TEXT PRIMARY KEY, actor TEXT NOT NULL, session TEXT NOT NULL, host TEXT NOT NULL,
            address TEXT NOT NULL, workflow TEXT NOT NULL, worktree TEXT NOT NULL,
            request TEXT NOT NULL, source TEXT NOT NULL, policy TEXT NOT NULL,
            secret_hash TEXT NOT NULL, generation INTEGER NOT NULL, state TEXT NOT NULL,
            pid INTEGER, started TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
            result TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(monitor_jobs)")}
        for name in ("control_path", "control_token"):
            if name not in columns:
                db.execute(f"ALTER TABLE monitor_jobs ADD COLUMN {name} TEXT")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS monitor_one_active_workflow
            ON monitor_jobs(actor,workflow,worktree)
            WHERE state IN ('accepted','starting','started','cancelling')""")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS monitor_one_active_worktree
            ON monitor_jobs(worktree) WHERE state IN ('accepted','starting','started','cancelling')""")
    return store


def _row(store, run_id):
    if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("invalid monitor grant ID")
    with store.connection() as db:
        row = db.execute("SELECT * FROM monitor_jobs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("monitor grant is unavailable")
    return dict(row)


def _owned(store, identity, run_id):
    row = _row(store, run_id)
    if row["actor"] != identity.actor or row["session"] != identity.session:
        raise ValueError("monitor run belongs to another native owner")
    if row["worktree"] != str(store.worktree):
        raise ValueError("monitor run belongs to another worktree")
    return row


def _alive(row):
    if not row["pid"] or not row["started"]:
        return False
    try:
        return process_identity(row["pid"])[1] == row["started"]
    except ValueError:
        return False


def status(root, identity, run_id):
    row = _owned(_store(root), identity, run_id)
    return _public(row)


def _public(row):
    return {"run_id": row["run_id"], "generation": row["generation"], "state": row["state"],
            "process_alive": _alive(row), "cancel_requested": bool(row["cancel_requested"]),
            "workflow_id": row["workflow"], "result": json.loads(row["result"]) if row["result"] else None}


def _notice(store, row, state, detail="", *, _db=None, _tasks=None):
    from neurath.agents.lifecycle import TaskLifecycle
    tasks = _tasks if _tasks is not None else TaskLifecycle(store)
    with store.connection() if _db is None else nullcontext(_db) as db:
        task = tasks.bind(row["address"], row["address"],
            key=f"monitor:{row['run_id']}:{row['generation']}", transport="monitor-service", _db=db)
        details = canonical({"run_id": row["run_id"], "generation": row["generation"],
                             "detail": detail, "authority": "automation-result"})
        return tasks.emit(row["address"], task["id"], state,
            key=state + ":" + hashlib.sha256(details.encode()).hexdigest(), detail=details, _db=db)


@contextmanager
def _launch_lock(store):
    path = store.directory / ("monitor-launch-" + hashlib.sha256(str(store.worktree).encode()).hexdigest() + ".lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def start(root, identity, handle, fields, policy):
    store = _store(root)
    with _launch_lock(store):
        return _start(root, identity, handle, fields, policy, store)


def _start(root, identity, handle, fields, policy, store):
    from scripts.agent_harness.session_kernel import WorkflowId
    from scripts.agent_harness.skill_state_store import SkillStateStore
    from neurath.runtime.bundled_services import service
    root = Path(root).resolve()
    workflow = WorkflowId(fields["workflow_id"])
    state = handle.inspect()
    owned = state.workflows.get(workflow)
    if owned is None or owned.owner_actor_id != handle.actor_id or owned.status.value != "active":
        raise ValueError("monitor requires an active owned workflow")
    with store.connection() as db:
        existing = db.execute("SELECT run_id FROM monitor_jobs WHERE worktree=? "
            "AND state IN ('accepted','starting','started','cancelling')", (str(root),)).fetchone()
        if existing:
            raise ValueError("monitor already active; inspect run " + existing["run_id"])
    skill = SkillStateStore(handle, workflow)
    snapshot = skill.read()
    if "owner_lifecycle" not in snapshot.skill_state:
        turn = state.foreground_turns[handle.actor_id]
        if not turn.vendor_turn_id:
            raise ValueError("monitor requires an observed owner turn")
        lifecycle = {"state": "active", "owner_session_id": str(handle.session_id),
                     "turn_id": turn.vendor_turn_id, "updated_at_epoch": time.time()}
        skill.compare_and_update(snapshot.workflow_revision, lambda current: {**current, "owner_lifecycle": lifecycle})
    service("monitor").MonitorWorkflowDocument(skill.read().skill_state, str(handle.session_id))
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver
    handoff = service("monitor_handoff")
    handoff.MonitorRuntimeHandoffService(handle=handle, workflow_id=workflow,
        paths=handoff.MonitorRuntimePaths(WorktreeIdentityResolver().resolve(root))).prepare(
            expected_label=f"com.neurath.pr{fields['pr_number']}.local-monitor", user_id=os.getuid())
    from neurath.agents.lifecycle import TaskLifecycle
    tasks = TaskLifecycle(store)
    run_id, secret, now = uuid.uuid4().hex, secrets.token_hex(32), time.time()
    with store.connection() as db:
        existing = db.execute("SELECT run_id FROM monitor_jobs WHERE actor=? AND workflow=? AND worktree=? "
            "AND state IN ('accepted','starting','started','cancelling')",
            (identity.actor, fields["workflow_id"], str(root))).fetchone()
        if existing:
            raise ValueError("monitor already active; inspect run " + existing["run_id"])
        db.execute("INSERT INTO monitor_jobs (run_id,actor,session,host,address,workflow,worktree,request,source,policy,"
            "secret_hash,generation,state,pid,started,cancel_requested,result,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, identity.actor, identity.session, identity.host, identity.address, fields["workflow_id"],
             str(root), canonical(fields), distribution_id(), canonical(policy),
             hashlib.sha256(secret.encode()).hexdigest(), 1, "accepted", None, None, 0, None, now, now))
        tasks.bind(identity.address, identity.address, key=f"monitor:{run_id}:1", transport="monitor-service", _db=db)
    _launch(store, run_id, secret)
    return {"status": "accepted", "run_id": run_id, "generation": 1,
            "next_event": "monitor-service-result", "delivery_mode": "observe-only" if fields["observe_only"] else "resume"}


def _launch(store, run_id, secret, *, before_secret=None):
    from neurath.agents.runner import child_environment
    row = _row(store, run_id)
    fields = json.loads(row["request"])
    directory = store.directory / "monitor-runs"
    if directory.is_symlink():
        raise ValueError("monitor log directory must not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    log_path = directory / (run_id + ".log")
    if log_path.is_symlink():
        raise ValueError("monitor log must not be a symlink")
    command = [sys.executable, "-I", str(BUNDLE / ".agents/skills/monitor-pr/scripts/local_pr_monitor.py"),
        "--repo", fields["repo"], "--pr-number", str(fields["pr_number"]),
        "--workflow-id", fields["workflow_id"], "--runtime-id", f"{run_id}-{row['generation']}",
        "--poll-interval-seconds", str(fields["poll_interval_seconds"]), "--mcp-launch-id", run_id]
    if fields["once"]:
        command.append("--once")
    process = None
    try:
        with log_path.open("a") as log:
            os.chmod(log_path, 0o600)
            process = subprocess.Popen(command, cwd=store.worktree, env=child_environment(),
                stdin=subprocess.PIPE, stdout=log, stderr=log, text=True, start_new_session=True)
        parent, started = process_identity(process.pid)
        if parent != os.getpid():
            raise ValueError("monitor launch process is not the actual child")
        with store.connection() as db:
            changed = db.execute("UPDATE monitor_jobs SET pid=?,started=?,updated=? "
                "WHERE run_id=? AND generation=? AND state='accepted'",
                (process.pid, started, time.time(), run_id, row["generation"])).rowcount
            if changed != 1:
                raise ValueError("monitor launch grant changed before process binding")
        if before_secret is not None:
            before_secret()
        process.stdin.write(secret + "\n")
        process.stdin.close()
        threading.Thread(target=_observe_exit, args=(store, row, process), daemon=True).start()
    except BaseException:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        current = _row(store, run_id)
        if current["generation"] == row["generation"] and current["cancel_requested"]:
            _finish(store, row, "cancelled", {"reason": "cancelled-before-binding"})
        else:
            _finish(store, row, "failed", {"reason": "launch-failed"})
        raise


def _observe_exit(store, launched, process):
    code = process.wait()
    current = _row(store, launched["run_id"])
    if (current["generation"] == launched["generation"] and current["pid"] == process.pid
            and current["state"] not in TERMINAL):
        _finish(store, current, "cancelled" if current["cancel_requested"] else "failed",
                {"reason":"owned-worker-exited-before-terminal-result", "exit_code":code})


def cancel(root, identity, run_id):
    store = _store(root)
    row = _owned(store, identity, run_id)
    if row["state"] in TERMINAL:
        return _public(row)
    with store.connection() as db:
        changed = db.execute("UPDATE monitor_jobs SET cancel_requested=1,state='cancelling',updated=? "
                   "WHERE run_id=? AND generation=? AND state IN ('accepted','starting','started','cancelling')",
                   (time.time(), run_id, row["generation"])).rowcount
    if not changed:
        return _public(_row(store, run_id))
    if _alive(row) and row.get("control_path") and row.get("control_token"):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(row["control_path"])
                client.sendall((canonical({"run_id": run_id, "generation": row["generation"],
                                          "token": row["control_token"]}) + "\n").encode())
        except (OSError, TimeoutError):
            pass  # Durable cancellation is checked before startup and each next poll.
    elif not _alive(row) and row["pid"]:
        _finish(store, row, "cancelled", {"reason": "owned-process-already-exited"})
    return _public(_row(store, run_id))


def recover(root, identity, handle, run_id, policy):
    store = _store(root)
    with _launch_lock(store):
        return _recover(root, identity, handle, run_id, policy, store)


def _recover(root, identity, handle, run_id, policy, store):
    old = _owned(store, identity, run_id)
    if _alive(old):
        raise ValueError("monitor is still running; do not launch a second worker")
    from scripts.agent_harness.session_kernel import WorkflowId
    workflow = handle.inspect().workflows.get(WorkflowId(old["workflow"]))
    if workflow is None or workflow.owner_actor_id != handle.actor_id or workflow.status.value != "active":
        raise ValueError("monitor recovery requires its active owned workflow")
    directory = store.directory / "monitor-leases"
    if directory.is_symlink():
        raise ValueError("monitor lease directory is invalid")
    directory.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(directory / (run_id + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    def release_reservation():
        nonlocal fd
        if fd is not None:
            os.close(fd)
            fd = None
    try:
        return _recover_locked(root, identity, run_id, policy, store, old, release_reservation)
    finally:
        release_reservation()


def _recover_locked(root, identity, run_id, policy, store, old, release_reservation):
    from neurath.agents.lifecycle import TaskLifecycle
    tasks = TaskLifecycle(store)
    if old["state"] not in TERMINAL:
        _finish(store, old, "failed", {"reason": "owned-process-exited-before-result"})
    secret = secrets.token_hex(32)
    with store.connection() as db:
        changed = db.execute("UPDATE monitor_jobs SET generation=generation+1,state='accepted',pid=NULL,started=NULL,"
            "cancel_requested=0,result=NULL,control_path=NULL,control_token=NULL,source=?,policy=?,secret_hash=?,created=?,updated=? "
            "WHERE run_id=? AND generation=?",
            (distribution_id(), canonical(policy), hashlib.sha256(secret.encode()).hexdigest(),
             time.time(), time.time(), run_id, old["generation"])).rowcount
        if changed != 1:
            raise ValueError("monitor recovery generation changed")
        tasks.bind(identity.address, identity.address, key=f"monitor:{run_id}:{old['generation']+1}",
                   transport="monitor-service", _db=db)
    _launch(store, run_id, secret, before_secret=release_reservation)
    return {"status": "accepted", "run_id": run_id, "generation": old["generation"] + 1}


class GrantLease:
    def __init__(self, store, row, fd):
        self.store, self.row, self.fd = store, row, fd

    def current(self):
        if self.fd is None:
            raise ValueError("monitor grant lease has been released")
        row = _row(self.store, self.row["run_id"])
        if row["generation"] != self.row["generation"] or row["state"] not in ACTIVE or not _alive(row):
            raise ValueError("monitor grant is no longer current")
        return row

    def close(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def accept_grant(root, run_id, secret):
    store = _store(root)
    row = _row(store, run_id)
    if (row["pid"] != os.getpid() or not _alive(row) or row["state"] not in {"accepted", "cancelling"}
            or row["secret_hash"] != hashlib.sha256(secret.encode()).hexdigest()
            or row["worktree"] != str(Path(root).resolve())):
        raise ValueError("monitor grant does not authorize this process")
    if row["source"] != distribution_id():
        raise ValueError("monitor grant source changed before worker admission")
    policy = json.loads(row["policy"])
    if (not policy.get("implementation_ready") or not policy.get("is_root")
            or policy.get("actor") != row["actor"] or policy.get("native_session") != row["session"]
            or policy.get("worktree") != row["worktree"] or policy.get("provider") != row["host"]):
        raise ValueError("monitor grant has no matching native execution policy")
    if row["cancel_requested"]:
        _finish(store, row, "cancelled", {"reason": "cancelled-before-start"})
        raise ValueError("monitor grant was cancelled before admission")
    directory = store.directory / "monitor-leases"
    if directory.is_symlink():
        raise ValueError("monitor grant lease directory is invalid")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (run_id + ".lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with store.connection() as db:
            changed = db.execute("UPDATE monitor_jobs SET state='starting',secret_hash='',updated=? "
                "WHERE run_id=? AND generation=? AND state='accepted' AND secret_hash=? AND cancel_requested=0",
                (time.time(), run_id, row["generation"], row["secret_hash"])).rowcount
        if changed != 1:
            current = _row(store, run_id)
            if current["generation"] == row["generation"] and current["cancel_requested"]:
                _finish(store, row, "cancelled", {"reason": "cancelled-before-grant-consumption"})
            raise ValueError("monitor grant was consumed or cancelled")
        return GrantLease(store, row, fd)
    except BaseException:
        os.close(fd)
        raise


class ScopedMonitorHandle:
    """An automation grant can update only this workflow's monitor namespace."""
    ALLOWED = {"owner_lifecycle", "monitor_mailbox", "monitor_started", "monitor_event_subscription", "updated_at"}

    def __init__(self, bound, lease):
        self.bound, self.lease = bound, lease

    def __getattr__(self, name):
        return getattr(self.bound, name)

    def inspect(self):
        from scripts.agent_harness.session_kernel import WorkflowId
        self.lease.current()
        state = self.bound.inspect()
        workflow = state.workflows.get(WorkflowId(self.lease.row["workflow"]))
        if (state.session.status.value != "active" or workflow is None or workflow.status.value != "active"
                or workflow.owner_actor_id != self.bound.actor_id
                or state.session.root_actor_id != self.bound.actor_id):
            raise ValueError("monitor automation owner or workflow is no longer active")
        return state

    def apply(self, event, expected_revision=None):
        from scripts.agent_harness.session_kernel import WorkflowAdvanced, WorkflowId
        state = self.inspect()
        if type(event) is not WorkflowAdvanced or str(event.workflow_id) != self.lease.row["workflow"]:
            raise ValueError("monitor grant forbids this state transition")
        old = state.workflows[WorkflowId(self.lease.row["workflow"])].payload
        new = event.payload
        if {k:v for k,v in old.items() if k != "skill_state"} != {k:v for k,v in new.items() if k != "skill_state"}:
            raise ValueError("monitor grant cannot change workflow phases or other state")
        old_skill, new_skill = old.get("skill_state", {}), new.get("skill_state", {})
        if new_skill.get("updated_at") != old_skill.get("updated_at"):
            from datetime import datetime
            value = new_skill.get("updated_at")
            if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("monitor evidence timestamp must be a timezone-aware server timestamp")
        if {k:v for k,v in old_skill.items() if k not in self.ALLOWED} != {k:v for k,v in new_skill.items() if k not in self.ALLOWED}:
            raise ValueError("monitor grant cannot change non-monitor skill state")
        return self.bound.apply(event, expected_revision=state.revision if expected_revision is None else expected_revision)


class MonitorCancelled(ValueError):
    """The current generation has received a cancellation request."""


def _current_resume_policy(handle, lease):
    """Read the owner's latest native policy, including after its turn becomes idle."""
    from neurath.hosts.identity import _transcript, snapshot
    from neurath.providers.readiness import _codex_policy
    row = lease.current()
    if row["cancel_requested"]:
        raise MonitorCancelled("monitor cancelled before resume")
    state = handle.inspect()
    turn = state.foreground_turns.get(handle.actor_id)
    data = snapshot(Path(row["worktree"]), row["session"])
    if turn is None or row["host"] != "codex" or data.get("host") != row["host"] or not data.get("transcript"):
        raise ValueError("monitor cannot observe current native resume policy")
    path = _transcript(row["host"], data["transcript"], os.environ)
    current = _codex_policy(path, turn.vendor_turn_id, Path(row["worktree"]))
    granted = json.loads(row["policy"]).get("stages", {}).get("policy", {})
    keys = ("approval_policy", "approvals_reviewer", "sandbox_policy", "collaboration_mode")
    if (current.get("status") != "verified" or granted.get("status") != "verified"
            or any(current.get("evidence", {}).get(key) != granted.get("evidence", {}).get(key) for key in keys)):
        raise ValueError("native resume policy changed or is unobserved; recover through monitor_recover")


class BoundResumeAdapter:
    """Call the existing resume service with verified resources, not worker env."""
    _command = None

    def __init__(self, resources, enabled, *, policy_guard=None):
        self.resources, self.enabled = resources, enabled
        self.policy_guard = policy_guard

    @property
    def available(self):
        return self.enabled

    def _args(self, **extra):
        if self.policy_guard is None:
            raise ValueError("bound resume requires current native policy verification")
        self.policy_guard()
        return SimpleNamespace(thread_id=self.resources.session_id, cwd=str(self.resources.worktree),
            socket_path=str(self.resources.app_server_socket_path), turn_timeout_seconds=5,
            expected_head_sha=None, preserve_native_policy=True, **extra)

    def probe(self):
        from neurath.runtime.bundled_services import service
        if not self.available:
            return {"probe_status": "unsupported"}
        return service("monitor_resume").probe_thread(self._args())

    def resume(self, event):
        from neurath.runtime.bundled_services import service
        if not self.available:
            return {"resume_status": "queued-no-adapter"}
        base = service("monitor").ResumeAdapter(None)
        args = self._args()
        args.expected_head_sha = event.get("snapshot", {}).get("headRefOid")
        return service("monitor_resume").resume_thread(args, base._resume_prompt(event))

    def inspect_turn(self, turn_id):
        from neurath.runtime.bundled_services import service
        if not self.available:
            return {"inspect_status": "unsupported"}
        return service("monitor_resume").inspect_turn(self._args(), turn_id)

    def find_claimed_turn(self, claim_id, event_id):
        from neurath.runtime.bundled_services import service
        if not self.available:
            return {"recovery_status": "unsupported"}
        return service("monitor_resume").find_claimed_turn(self._args(), claim_id, event_id)


class CancelEndpoint:
    """Private generation-bound IPC; cancellation never signals an unowned PID."""
    def __init__(self, lease, stop):
        self.lease, self.stop = lease, stop
        self.directory = tempfile.TemporaryDirectory(prefix="neurath-monitor-")
        self.path = str(Path(self.directory.name) / "control")
        self.token = secrets.token_hex(32)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.path)
        os.chmod(self.path, 0o600)
        self.socket.listen(2)
        self.socket.settimeout(0.5)
        with lease.store.connection() as db:
            db.execute("UPDATE monitor_jobs SET control_path=?,control_token=? WHERE run_id=? AND generation=?",
                       (self.path, self.token, lease.row["run_id"], lease.row["generation"]))
        self.closed = False
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def _listen(self):
        while not self.closed:
            try:
                client, _ = self.socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with client:
                client.settimeout(1)
                try:
                    value = json.loads(client.recv(4096))
                    if value == {"run_id": self.lease.row["run_id"], "generation": self.lease.row["generation"], "token": self.token}:
                        self.stop.set()
                except (OSError, ValueError):
                    pass

    def close(self):
        self.closed = True
        self.socket.close()
        self.thread.join(timeout=2)
        self.directory.cleanup()


def _bound(row, lease):
    from neurath.runtime.engine import activate
    activate(Path(row["worktree"]))
    from scripts.agent_harness.session_kernel import SessionLocator, SessionRuntime, SessionId, ActorId
    from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle
    binding = RuntimeIdentityBinding(runtime=SessionRuntime(row["host"]), session_id=SessionId(row["session"]),
        actor_id=ActorId(row["actor"]), root_actor_id=ActorId(row["actor"]))
    # Identity comes only from the protected, PID-bound, consumed launch grant.
    bound = StateHandle.attach(SessionLocator.from_worktree(Path(row["worktree"])), binding)
    return ScopedMonitorHandle(bound, lease)


def _resources(root, handle):
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver
    from neurath.runtime.bundled_services import service
    return service("monitor_resources").MonitorRuntimeResources(binding=handle._binding,
        worktree=WorktreeIdentityResolver().resolve(root))


def readback(root, identity, handle, run_id):
    row = _owned(_store(root), identity, run_id)
    if not _alive(row) or row["state"] != "started":
        raise ValueError("monitor has no current live startup readback; inspect monitor_status")
    return _readback(root, row, handle)


def _readback(root, row, handle):
    from neurath.runtime.bundled_services import service
    run_id = row["run_id"]
    fields = json.loads(row["request"])
    resources = _resources(root, handle)
    mode = "unavailable" if fields["observe_only"] else "app-server"
    module = service("monitor_readback")
    expected = module.ExpectedMonitorRuntime(repo=fields["repo"], pr_number=fields["pr_number"],
        workflow_id=row["workflow"], runtime_id=f"{run_id}-{row['generation']}", resume_adapter=mode,
        pid=row["pid"], manager_pid=None, minimum_heartbeat_at_epoch=row["created"],
        poll_interval_seconds=fields["poll_interval_seconds"])
    manager = {"session_id": resources.session_id, "worktree_id": resources.worktree_id,
               "observation_resource": resources.observation_resource(), "launcher": "mcp-worker", "pid": row["pid"]}
    return module.MonitorRuntimeReadback(resources, expected).bundle(manager=manager,
        poll_interval_seconds=fields["poll_interval_seconds"])


def _finish(store, row, state, result):
    from neurath.agents.lifecycle import TaskLifecycle
    tasks = TaskLifecycle(store)
    with store.connection() as db:
        current = db.execute("SELECT state,generation FROM monitor_jobs WHERE run_id=?", (row["run_id"],)).fetchone()
        if current is None or current["generation"] != row["generation"] or current["state"] in TERMINAL:
            return
        db.execute("CREATE TABLE IF NOT EXISTS monitor_job_events "
            "(run_id TEXT,generation INTEGER,state TEXT,result TEXT,created REAL,PRIMARY KEY(run_id,generation,state))")
        db.execute("INSERT OR IGNORE INTO monitor_job_events VALUES (?,?,?,?,?)",
                   (row["run_id"], row["generation"], state, canonical(result), time.time()))
        db.execute("UPDATE monitor_jobs SET state=?,result=?,updated=? WHERE run_id=? AND generation=?",
                   (state, canonical(result), time.time(), row["run_id"], row["generation"]))
        _notice(store, row, state, result.get("reason", ""), _db=db, _tasks=tasks)


def _started(store, row, detail):
    from neurath.agents.lifecycle import TaskLifecycle
    tasks = TaskLifecycle(store)
    with store.connection() as db:
        changed = db.execute("UPDATE monitor_jobs SET state='started',result=NULL,updated=? "
            "WHERE run_id=? AND generation=? AND state='starting' AND cancel_requested=0",
            (time.time(), row["run_id"], row["generation"])).rowcount
        if changed:
            _notice(store, row, "started", detail, _db=db, _tasks=tasks)
        return changed == 1


def _poll_error(store, row, error):
    from neurath.agents.lifecycle import TaskLifecycle
    tasks = TaskLifecycle(store)
    detail = str(error)[:2000]
    with store.connection() as db:
        current = db.execute("SELECT state,generation,result FROM monitor_jobs WHERE run_id=?", (row["run_id"],)).fetchone()
        if current is None or current["generation"] != row["generation"] or current["state"] in TERMINAL:
            return
        result = canonical({"stage": "snapshot", "error": detail})
        if current["result"] == result:
            return
        db.execute("UPDATE monitor_jobs SET result=?,updated=? WHERE run_id=? AND generation=?",
                   (result, time.time(), row["run_id"], row["generation"]))
        _notice(store, row, "error", detail, _db=db, _tasks=tasks)


def worker(root, run_id, namespace):
    from neurath.runtime.bundled_services import service
    from scripts.agent_harness.session_kernel import WorkflowId
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver
    secret = sys.stdin.readline(130).strip()
    lease = accept_grant(root, run_id, secret)
    row, stop = lease.row, threading.Event()
    endpoint = CancelEndpoint(lease, stop)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        fields = json.loads(row["request"])
        if (namespace.workflow_id != row["workflow"] or namespace.repo != fields["repo"]
                or namespace.pr_number != fields["pr_number"]
                or namespace.runtime_id != f"{run_id}-{row['generation']}"):
            raise ValueError("monitor callback arguments differ from its grant")
        handle = _bound(row, lease)
        resources = _resources(root, handle)
        enabled = not fields["observe_only"]
        adapter = BoundResumeAdapter(resources, enabled, policy_guard=lambda: _current_resume_policy(handle, lease))
        if enabled:
            if row["host"] != "codex":
                raise ValueError("the configured resume backend does not support this host; use explicit observe-only mode")
            adapter.probe()
        module = service("monitor")
        monitor = module.LocalPrMonitor(handle=handle, workflow_id=WorkflowId(row["workflow"]),
            worktree=WorktreeIdentityResolver().resolve(root), runtime_id=namespace.runtime_id,
            repo=fields["repo"], pr_number=fields["pr_number"], poll_interval_seconds=fields["poll_interval_seconds"],
            resume_command=None, launcher="mcp-worker", resume_adapter=adapter,
            resume_unavailable_reason="explicit-observe-only" if fields["observe_only"] else "")
        first = True
        while not stop.is_set():
            current = lease.current()
            if current["cancel_requested"]:
                break
            if distribution_id() != row["source"]:
                raise ValueError("monitor source changed; recover with the current installed version")
            handle.inspect()
            try:
                snapshot = module.GitHubSnapshotClient(fields["repo"], fields["pr_number"]).load()
            except (json.JSONDecodeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                monitor._record_poll_error(error)
                if fields["once"]:
                    _finish(lease.store, row, "failed", {"reason": str(error)[:2000], "stage": "snapshot"})
                    return 1
                _poll_error(lease.store, row, error)
                stop.wait(fields["poll_interval_seconds"])
                continue
            if stop.is_set() or lease.current()["cancel_requested"]:
                break
            event = monitor.run_once(snapshot)
            if first:
                # Existing liveness validation is additional to the grant/PID lease.
                bundle = _readback(root, row, handle)
                process = service("process").ProcessStateEvidenceApplication()
                for field, value in (("monitor_event_subscription", bundle["subscription"]), ("monitor_started", bundle["receipt"])):
                    process.apply_bound(handle=handle, workflow_id=WorkflowId(row["workflow"]),
                        resources=resources, field=field, value=value)
                if not _started(lease.store, row, "observe-only" if fields["observe_only"] else "resume-ready"):
                    break
                first = False
            if fields["once"] or monitor._should_stop_after_event(event):
                _finish(lease.store, row, "completed", {"reason": "single-observation" if fields["once"] else "terminal-monitor-event",
                    "event": monitor._state.read().get("last_event"), "observe_only": fields["observe_only"]})
                return 0
            stop.wait(fields["poll_interval_seconds"])
        _finish(lease.store, row, "cancelled", {"reason": "cancelled"})
        return 0
    except MonitorCancelled:
        _finish(lease.store, row, "cancelled", {"reason": "cancelled-before-resume"})
        return 0
    except BaseException as error:
        _finish(lease.store, row, "failed", {"reason": str(error)[:2000]})
        return 1
    finally:
        endpoint.close()
        lease.close()
