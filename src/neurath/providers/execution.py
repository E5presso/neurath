"""Bounded native execution with installation/activation/policy/claim handshake.

The caller service must authenticate its native caller and enforce its execution
policy before invoking this function. No actor, token or readiness report is
accepted from tool input. The external session is an independent peer root.
"""

import math
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from neurath.memory.store import clean, control_root
from neurath.providers.codex import CodexSessions
from neurath.providers.contracts import CreationRejected, ExecutionPolicy, UnsupportedOperation, text
from neurath.providers.readiness import inspect_owned_session
from neurath.providers.stdio import CodexStdio


def _target(root, worktree, mode):
    root, target = Path(root).resolve(), Path(worktree).resolve()
    if control_root(root) != control_root(target):
        raise ValueError("provider worktree belongs to another project")
    top = subprocess.run(["git", "-C", str(target), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True).stdout.strip()
    if Path(top).resolve() != target or not (target / ".neurath/run").is_file():
        raise ValueError("provider requires an installed Git worktree root")
    if mode == "workspace-write" and target == root:
        raise ValueError("write provider requires a separate installed worktree")
    return target


def _prepared(report, mode):
    if mode == "workspace-write":
        return report.get("implementation_ready") is True
    return report.get("waiting") is None and all(
        report.get("stages", {}).get(name, {}).get("status") == "verified"
        for name in ("installation", "activation", "policy"))


def run(root, *, worktree, assignment, model=None, mode="read-only", approval_policy="never",
        approvals_reviewer=None, collaboration_mode=None, timeout=300):
    result = {"authority": "agent-report", "transport": "codex-app-server", "status": "failed",
              "retryable": False, "implementation_dispatched": False, "text": ""}
    host, adapter, session = None, None, None
    try:
        text(assignment, "assignment")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 3600:
            raise ValueError("timeout must be between 1 and 3600 seconds")
        policy = ExecutionPolicy(mode, approval_policy, approvals_reviewer, collaboration_mode)
        if mode == "workspace-write" and collaboration_mode == "plan":
            raise UnsupportedOperation("plan mode cannot run an implementation assignment")
        target = _target(root, worktree, mode)
        host = CodexStdio(target, timeout=min(timeout, 30), experimental=collaboration_mode is not None)
        adapter = CodexSessions(host)
        session = adapter.create(target, model, policy)
        result["created"] = asdict(session)
        result["bootstrap"] = adapter.bootstrap(session)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = host.event(lambda _: True, timeout=min(30, max(0.01, deadline-time.monotonic())))
            except TimeoutError:
                # An event wait timeout is not an ambiguous JSON-RPC mutation.
                # Continue draining until this run's own deadline, then interrupt.
                continue
            name, params = event.get("method"), event.get("params", {})
            if params.get("threadId") not in (None, session.native_session):
                continue
            if "id" in event and "method" in event:
                result.update(status="unsupported-client-request", server_request={
                    "method": name, "id": event["id"], "response": "rejected-as-unsupported"})
                break
            if name == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                    result["text"] = clean(item["text"])[-32768:]
                if not result["implementation_dispatched"] and item.get("type") in {"commandExecution", "mcpToolCall"}:
                    report = inspect_owned_session(session)
                    result["readiness"] = report
                    if _prepared(report, mode):
                        prompt = ("Neurath peer assignment within the authorized task. Preparation is verified. "
                                  "Keep current permissions and worktree ownership. " +
                                  ("Inspect and respond without edits. " if mode == "read-only" else
                                   "Follow normal material action prepare, tool result, readback and resolve. "
                                   "Release your own worktree claim normally when all assigned work is finished. ") +
                                  "Assignment:\n" + assignment)
                        result["submission"] = adapter.message(session, prompt)
                        if result["submission"]["delivery"] == "submitted":
                            result["implementation_dispatched"] = True
                        else:
                            result["status"] = "needs-input"
                            break
            if name == "turn/completed":
                turn = params.get("turn", {})
                expected = result["submission"] if result["implementation_dispatched"] else result["bootstrap"]
                if turn.get("id") != expected.get("native_turn"):
                    continue
                result["completion"] = {key: turn.get(key) for key in ("id", "status", "error")}
                result["status"] = ("completed" if turn.get("status") == "completed"
                    and result["implementation_dispatched"] else "not-ready" if
                    not result["implementation_dispatched"] else "failed")
                break
        else:
            raise TimeoutError("provider execution deadline exceeded")
    except CreationRejected as error:
        result.update(error.report)
    except UnsupportedOperation as error:
        result.update(status="unsupported", diagnostic=clean(str(error)))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        result.update(status="timed-out" if isinstance(error, TimeoutError) else "failed",
                      diagnostic=clean(f"{type(error).__name__}: {error}")[:4000])
    finally:
        if host is not None:
            if session is not None and result["status"] not in ("completed", "not-ready"):
                try:
                    result["cancellation"] = adapter.cancel(session)
                except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                    result["cancellation"] = {"status": "unconfirmed", "diagnostic": clean(str(error))[:2000]}
            host.close()
            result["transport_diagnostic"] = host.diagnostic
    return result
