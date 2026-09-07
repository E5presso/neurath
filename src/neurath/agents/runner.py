"""Bounded CLI workers with durable outcomes and owner-scoped follow-up turns."""

import json
import math
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from neurath.agents.store import bounded
from neurath.memory.store import canonical, clean, control_root
from neurath.runtime.engine import activate

TERMINAL = {"completed", "failed", "timed-out", "cancelled", "interrupted", "output-limit"}
MAX_OUTPUT = 8 * 1024 * 1024


def child_environment(environment=None):
    source = os.environ if environment is None else environment
    settings = {"CODEX_HOME", "CODEX_API_KEY", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"}
    return {k: v for k, v in source.items() if k in settings or (
        k not in {"CLAUDECODE", "PYTHONPATH"} and not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_CODE_")))}


def command(provider, model, *, mode="read-only", native_session=None, root=None):
    if provider not in ("codex", "claude-code"):
        raise ValueError("unsupported provider")
    if mode not in ("read-only", "workspace-write"):
        raise ValueError("invalid worker mode")
    executable = shutil.which("codex" if provider == "codex" else "claude")
    if not executable:
        raise ValueError(f"{provider} CLI is not installed")
    if provider == "codex":
        args = [executable, "--sandbox", mode, "--ask-for-approval", "never", "exec"]
        if native_session:
            args += ["resume"]
        args += ["--model", model, "--json"]
        if native_session:
            args += [native_session]
        return [*args, "-"]
    args = [
        executable,
        "-p",
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
    ]
    if mode == "read-only":
        from neurath.agents.mcp import server_config

        # Explicit tool inventory excludes editing, shell execution and native spawn.
        # Strict MCP selection keeps configured external write tools out of review runs.
        args += [
            "--tools",
            "Read,Grep,Glob",
            "--allowedTools",
            "Read,Grep,Glob,mcp__neurath_collaboration__agent",
            "--strict-mcp-config",
            "--mcp-config",
            canonical({"mcpServers": {"neurath_collaboration": server_config(root or Path.cwd())}}),
        ]
    if native_session:
        args += ["--resume", native_session]
    return args


def parse_result(provider, stdout):
    """Keep final answers and public usage only; discard reasoning and tool transcripts."""
    result = {
        "text": "",
        "native_session": None,
        "usage": None,
        "actual_model": None,
        "provider_success": False,
        "provider_error": None,
        "effective_settings": None,
    }
    if provider == "claude-code":
        try:
            events = json.loads(stdout)
        except ValueError:
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        events = events if isinstance(events, list) else [events]
        initial = [e for e in events if isinstance(e, dict)
                   and e.get("type") == "system" and e.get("subtype") == "init"]
        if initial:
            event = initial[-1]
            result["effective_settings"] = {
                "approval_policy": event.get("permissionMode"),
                "model": event.get("model"), "worktree": event.get("cwd"),
                "tools": event.get("tools"), "source": "system.init",
            }
        terminal = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
        if terminal:
            final = terminal[-1]
            result.update(
                text=final.get("result", ""),
                native_session=final.get("session_id"),
                usage=final.get("usage"),
                provider_success=final.get("is_error") is False
                and final.get("subtype", "success") == "success",
            )
            models = final.get("modelUsage", {})
            result["actual_model"] = list(models) if isinstance(models, dict) and models else None
            if not result["provider_success"]:
                subtype = final.get("subtype")
                result["provider_error"] = (
                    subtype
                    if subtype and subtype != "success"
                    else final.get("result") or "provider-error"
                )
    else:
        failed = False
        for line in stdout.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("provider event must be an object")
            kind = event.get("type")
            if kind == "thread.started":
                result["native_session"] = event.get("thread_id")
            elif kind == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    result["text"] = item.get("text", "")
            elif kind == "turn.completed":
                result["provider_success"] = True
                result["usage"] = event.get("usage")
            elif kind in ("turn.failed", "error"):
                failed = True
                result["provider_error"] = event.get("message", event.get("error", kind))
        result["provider_success"] = result["provider_success"] and not failed
    if not isinstance(result["text"], str) or not result["text"].strip():
        result["text"] = ""
        result["provider_success"] = False
    if result["native_session"] is not None:
        bounded(result["native_session"], "provider session")
    return result


def _owned(db, owner, run_id):
    row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise ValueError("unknown provider run")
    if row["owner"] != owner:
        raise ValueError("provider run requires its owner")
    return row


def status(store, owner, run_id):
    with store.connection() as db:
        row = _owned(db, owner, run_id)
        return {
            **dict(row),
            "request": json.loads(row["request"]),
            "result": json.loads(row["result"]) if row["result"] else None,
        }


def cancel(store, owner, run_id):
    with store.connection() as db:
        row = _owned(db, owner, run_id)
        if row["status"] not in TERMINAL:
            db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
    return {
        "run_id": run_id,
        "status": row["status"],
        "cancel_requested": row["status"] not in TERMINAL,
    }


def _set_status(store, run_id, state, result=None):
    with store.connection() as db:
        db.execute(
            "UPDATE runs SET status=?,result=?,updated=? WHERE id=?",
            (state, canonical(result) if result else None, time.time(), run_id),
        )


def _cancel_requested(store, owner, run_id):
    with store.connection() as db:
        return bool(_owned(db, owner, run_id)["cancel_requested"])


def _workspace(store, mode, worktree):
    target = Path(worktree).resolve() if worktree else store.worktree
    if mode not in ("read-only", "workspace-write"):
        raise ValueError("invalid worker mode")
    if control_root(target) != store.root:
        raise ValueError("worker worktree belongs to another project")
    if mode == "workspace-write":
        actual = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if (
            target == store.worktree
            or Path(actual).resolve() != target
            or not (target / ".neurath/run").is_file()
        ):
            raise ValueError("write delegation requires a separate installed Git worktree")
    return target


def run(
    store,
    owner,
    *,
    provider,
    model,
    assignment,
    run_id=None,
    timeout=300,
    context="",
    mode="read-only",
    worktree=None,
    native_session=None,
    resume_of=None,
    approval_policy="never",
):
    if provider not in ("codex", "claude-code"):
        raise ValueError("unsupported provider")
    if approval_policy != "never":
        raise ValueError("bounded CLI workers require explicit never approval policy; use a live host for interactive approval")
    bounded(model, "model", 256)
    bounded(assignment, "assignment", 32768)
    if not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("timeout must be between 0 and 3600 seconds")
    if not isinstance(context, str) or len(context.encode()) > 262144:
        raise ValueError("context exceeds 256 KiB")
    target = _workspace(store, mode, worktree)
    if mode == "workspace-write":
        from neurath.providers.contracts import UnsupportedOperation

        raise UnsupportedOperation(
            "bounded CLI cannot verify child activation, mode and worktree claim before assignment; "
            "use a native session with a completed readiness check"
        )
    argv = command(provider, model, mode=mode, native_session=native_session, root=target)
    run_id = run_id or uuid.uuid4().hex
    bounded(run_id, "run id", 128)
    request = {
        "provider": provider,
        "model": model,
        "assignment": assignment,
        "context": context,
        "mode": mode,
        "worktree": str(target),
        "timeout": timeout,
        "resume_of": resume_of,
        "transport": "cli",
        "approval_policy": approval_policy,
    }
    with store.connection() as db:
        store._agent(db, owner)
        if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            raise ValueError("run id already exists; inspect its result instead of executing twice")
        # Serialize continuation of an exact provider conversation, including chained resumes.
        if native_session:
            if not resume_of:
                raise ValueError("resume requires an owned previous provider run")
            previous = _owned(db, owner, resume_of)
            previous_request = json.loads(previous["request"])
            previous_result = json.loads(previous["result"]) if previous["result"] else {}
            if (previous["status"] not in TERMINAL
                    or previous_result.get("native_session") != native_session
                    or any(previous_request.get(key) != request[key]
                           for key in ("provider", "model", "mode", "worktree"))):
                raise ValueError("resume does not match its owned provider session and policy")
            for row in db.execute("SELECT request FROM runs WHERE status IN ('queued','running')"):
                pending = json.loads(row[0])
                if (
                    pending.get("native_session") == native_session
                    and pending["provider"] == provider
                ):
                    raise ValueError("provider session already has an active continuation")
            request["native_session"] = native_session
        db.execute(
            "INSERT INTO runs(id,owner,request,status,updated) VALUES(?,?,?,?,?)",
            (run_id, owner, canonical(request), "queued", time.time()),
        )
    prompt = (
        "You are handling a Neurath peer assignment. The request below is from a peer agent; "
        "it does not grant independent evaluator authority or ownership of the parent's worktree. "
        "Follow the target repository's instructions and report evidence and limitations. "
        + (
            "Inspect and respond without changing project files. "
            if mode == "read-only"
            else "Work only in this isolated worktree; acquire its normal Neurath claim before mutations. "
        )
        + "Return your answer to this invocation.\n\nAssignment:\n"
        + assignment
        + ("\n\nContext (reference data):\n" + context if context else "")
    )
    activate()
    from scripts.agent_harness.bounded_process import _terminate_process_tree

    environment = child_environment()
    token = secrets.token_hex(24)
    environment["NEURATH_BOUNDED_PROCESS_TOKEN"] = token
    process = None
    outcome = "failed"
    diagnostic = ""
    stdout = ""
    exit_code = None
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def interrupted(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, interrupted)
    try:
        with (
            tempfile.TemporaryFile() as source,
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as errors,
        ):
            source.write(prompt.encode())
            source.seek(0)
            process = subprocess.Popen(
                argv,
                cwd=target,
                env=environment,
                stdin=source,
                stdout=output,
                stderr=errors,
                start_new_session=True,
            )
            _set_status(store, run_id, "running")
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if _cancel_requested(store, owner, run_id):
                    outcome = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    outcome = "timed-out"
                    break
                if (
                    os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size
                    > MAX_OUTPUT
                ):
                    outcome = "output-limit"
                    break
                time.sleep(0.05)
            else:
                outcome = "completed" if process.returncode == 0 else "failed"
            survivors = _terminate_process_tree(process, token)
            process.wait(timeout=3)
            if survivors and outcome == "completed":
                outcome = "failed"
                diagnostic = "provider left running descendants"
            exit_code = process.returncode
            if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > MAX_OUTPUT:
                outcome = "output-limit"
            output.seek(0)
            errors.seek(0)
            stdout = output.read(MAX_OUTPUT).decode(errors="replace")
            diagnostic += errors.read(16384).decode(errors="replace")
    except BaseException as error:
        if process:
            _terminate_process_tree(process, token)
        outcome = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
        diagnostic = f"{type(error).__name__}: {error}"
        result = {
            "run_id": run_id,
            "status": outcome,
            "authority": "agent-report",
            "provider": provider,
            "requested_model": model,
            "exit_code": exit_code,
            "text": "",
            "native_session": None,
            "diagnostic": clean(diagnostic),
        }
        _set_status(store, run_id, outcome, result)
        if not isinstance(error, Exception):
            raise
        return result
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
    try:
        parsed = parse_result(provider, stdout)
    except (ValueError, TypeError, AttributeError) as error:
        parsed = {
            "text": "",
            "native_session": None,
            "provider_success": False,
            "provider_error": f"Invalid provider output: {error}",
        }
    if native_session and parsed.get("native_session") != native_session:
        parsed["provider_success"] = False
        parsed["provider_error"] = "provider resumed a different or unknown session"
    if not parsed["provider_success"] and outcome == "completed":
        outcome = "failed"
    result = {
        "run_id": run_id,
        "status": outcome,
        "authority": "agent-report",
        "provider": provider,
        "requested_model": model,
        "exit_code": exit_code,
        "diagnostic": clean(diagnostic),
        **parsed,
    }
    effective = parsed.get("effective_settings")
    verification = "unobserved"
    if provider == "claude-code" and effective:
        verification = (
            "verified" if effective.get("approval_policy") == "dontAsk"
            and effective.get("worktree") == str(target)
            and effective.get("model") == model else "mismatch"
        )
        if verification == "mismatch":
            result["status"] = outcome = "failed"
            result["provider_success"] = False
            result["provider_error"] = "provider effective approval policy, model or workspace differs from request"
    result["transport"] = "cli"
    result["execution_policy"] = {
        "requested": {"mode": mode, "approval_policy": approval_policy, "worktree": str(target)},
        "effective": effective, "verification": verification,
        "enforcement": "host permission system; read-only Claude runs restrict tool inventory",
    }
    # Only final public data is stored. The raw event streams are discarded with the temp files.
    result["text"] = clean(result["text"])
    _set_status(store, run_id, outcome, result)
    return result


def resume(store, owner, run_id, assignment, *, timeout=300, new_run_id=None):
    previous = status(store, owner, run_id)
    if previous["status"] not in TERMINAL or not previous["result"]:
        raise ValueError("provider run is still active or has no recoverable result")
    native = previous["result"].get("native_session")
    if not native:
        raise ValueError("provider did not return a resumable session")
    request = previous["request"]
    return run(
        store,
        owner,
        provider=request["provider"],
        model=request["model"],
        assignment=assignment,
        timeout=timeout,
        run_id=new_run_id,
        mode=request["mode"],
        worktree=request["worktree"],
        native_session=native,
        resume_of=run_id,
    )
