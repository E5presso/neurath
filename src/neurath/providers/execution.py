"""Worker-side native event consumption with installation/policy/claim handshake.

The caller service must authenticate its native caller and enforce its execution
policy before invoking this function. No actor, token or readiness report is
accepted from tool input. The external session is an independent peer root.
"""

import math
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from neurath.agents.delivery import DeliveryServiceError
from neurath.memory.store import clean, control_root
from neurath.providers.codex import CodexSessions
from neurath.providers.contracts import CreationRejected, ExecutionPolicy, UnsupportedOperation, text
from neurath.providers.readiness import inspect_owned_session
from neurath.providers.stdio import CodexStdio


def _start_inbox(adapter, session):
    from neurath.providers.supervision import SessionInbox

    return SessionInbox(adapter, session).start()


def _target(root, worktree, mode):
    root, target = Path(root).resolve(), Path(worktree).resolve()
    if control_root(root) != control_root(target):
        raise ValueError("provider worktree belongs to another project")
    top = subprocess.run(["git", "-C", str(target), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True).stdout.strip()
    if Path(top).resolve() != target or not (target / ".neurath/run").is_file():
        raise ValueError("provider requires an installed Git worktree root")
    if mode != "read-only" and target == root:
        raise ValueError("write provider requires a separate installed worktree")
    return target


def _prepared(report, mode):
    if mode != "read-only":
        return report.get("implementation_ready") is True
    return report.get("waiting") is None and all(
        report.get("stages", {}).get(name, {}).get("status") == "verified"
        for name in ("installation", "activation", "policy"))


def _cleanup(result, inbox, host, adapter, session):
    errors = []
    def failed(stage, error):
        errors.append({"stage": stage, "diagnostic": clean(f"{type(error).__name__}: {error}")[:2000]})
    try:
        if inbox is not None:
            try:
                inbox.close()
            except Exception as error:
                failed("inbox", error)
    finally:
        # Even an unexpected inbox or cancellation failure cannot skip closing
        # this worker's own server. Keep native completion evidence separately.
        if host is not None:
            try:
                if session is not None and (errors or result["status"] not in ("completed", "not-ready")):
                    try:
                        result["cancellation"] = adapter.cancel(session)
                    except Exception as error:
                        result["cancellation"] = {"status": "unconfirmed", "diagnostic": clean(str(error))[:2000]}
            finally:
                try:
                    host.close()
                    if session is not None:
                        result["closure"] = {"native_session": session.native_session,
                            "transport": session.transport, "connection_closed": True,
                            "native_process_exited": getattr(getattr(host, "process", None), "returncode", None) is not None,
                            "source": "owned-app-server-close", "reason": "transport-closed"}
                except Exception as error:
                    failed("host", error)
                try:
                    result["transport_diagnostic"] = host.diagnostic
                except Exception as error:
                    failed("diagnostic", error)
    if errors:
        result["cleanup_errors"] = errors
        if result["status"] in ("completed", "not-ready"):
            result["status"] = "failed"


def run(root, *, worktree, assignment, model=None, mode="read-only", approval_policy=None,
        approvals_reviewer=None, collaboration_mode=None, timeout=None, event_callback=None,
        provider="codex", permission_mode=None, project_id=None, model_plan=None,
        model_owner=None, run_id=None, reasoning_effort=None, policy_inheritance=None,
        inherited_sandbox=None, restored_session=None):
    if provider == "claude-code":
        if project_id:
            raise ValueError("project_id is only supported for Codex")
        from neurath.providers.execution_claude import run as run_claude

        return run_claude(root, worktree=worktree, assignment=assignment, model=model, mode=mode,
            approval_policy=approval_policy, approvals_reviewer=approvals_reviewer,
            collaboration_mode=collaboration_mode, timeout=timeout, event_callback=event_callback,
            permission_mode=permission_mode, model_plan=model_plan, model_owner=model_owner,
            run_id=run_id, reasoning_effort=reasoning_effort, policy_inheritance=policy_inheritance,
            restored_session=restored_session)
    if provider != "codex" or permission_mode is not None:
        raise ValueError("invalid provider or native permission mode")
    result = {"authority": "agent-report", "transport": "codex-app-server", "status": "failed",
              "retryable": False, "implementation_dispatched": False, "text": "",
              "preparation": "not-started", "delivery": "not-submitted",
              "execution": "unobserved"}
    host, adapter, session, inbox = None, None, None, None
    try:
        text(assignment, "assignment")
        if mode != "read-only" and (not approval_policy or not collaboration_mode):
            return {**result, "status": "settings-required",
                    "diagnostic": "write execution requires explicit approval_policy and collaboration_mode"}
        approval_policy = approval_policy or "never"
        if timeout is not None and (not isinstance(timeout, (int, float)) or not math.isfinite(timeout)
                                   or not 1 <= timeout <= 3600):
            raise ValueError("timeout must be between 1 and 3600 seconds")
        policy = ExecutionPolicy(mode, approval_policy, approvals_reviewer, collaboration_mode)
        if mode != "read-only" and collaboration_mode == "plan":
            raise UnsupportedOperation("plan mode cannot run an implementation assignment")
        target = _target(root, worktree, mode)
        host = CodexStdio(target, timeout=min(timeout, 30) if timeout else 30,
                          experimental=True)
        adapter = CodexSessions(host)
        if restored_session is not None:
            session = adapter.restore(restored_session)
        elif inherited_sandbox is not None:
            session = adapter.create(target, model, policy, project_id,
                                     inherited_sandbox=inherited_sandbox, source_worktree=root)
        else:
            session = adapter.create(target, model, policy, project_id) if project_id else adapter.create(target, model, policy)
        result["created"] = asdict(session)
        if event_callback:
            event_callback("native-created", {"created": result["created"]})
        if model_plan is not None and restored_session is None:
            from neurath.providers.execution_plan import created_plan
            from neurath.providers.model_inventory import codex_inventory
            model_plan = created_plan(root, model_owner, run_id, model_plan, session,
                                      codex_inventory(host, host="local"))
            result["model_plan"] = model_plan
        if reasoning_effort is not None:
            session.policy["requested"]["reasoning_effort"] = reasoning_effort
        result["bootstrap"] = adapter.bootstrap(session)
        result["preparation"] = "submitted"
        if result["bootstrap"].get("delivery") == "needs-input":
            result.update(status="needs-input", preparation="waiting")
            return result
        deadline = time.monotonic() + timeout if timeout is not None else None
        started = False
        prepared_report = None
        while deadline is None or time.monotonic() < deadline:
            try:
                event = host.event(lambda _: True,
                    timeout=min(30, max(0.01, deadline-time.monotonic())) if deadline else None)
            except TimeoutError:
                if deadline is None:
                    raise  # An unbounded event wait cannot expire; this is a transport fault.
                # An event wait timeout is not an ambiguous JSON-RPC mutation.
                # Continue draining until this run's own deadline, then interrupt.
                continue
            name, params = event.get("method"), event.get("params", {})
            if params.get("threadId") not in (None, session.native_session):
                continue
            if "id" in event and "method" in event:
                if event_callback:
                    event_callback("waiting", {"native_session": session.native_session,
                                               "reason": "native client request", "method": name})
                waiting = ("waiting-approval" if "requestApproval" in name else
                           "waiting-input" if "requestUserInput" in name else "unsupported-client-request")
                result.update(status=waiting, server_request={
                    "method": name, "id": event["id"], "response": "rejected-as-unsupported"})
                break
            submitted_turn = (result.get("submission") or {}).get("native_turn")
            if inbox:
                submitted_turn = inbox.expected_turn(submitted_turn)
            if (name == "item/started" and result["implementation_dispatched"] and not started
                    and params.get("turnId") == submitted_turn):
                started = True
                if event_callback:
                    event_callback("started", {"native_session": session.native_session,
                                               "native_turn": submitted_turn})
            if name == "thread/status/changed" and inbox:
                status = params.get("status", {})
                if status.get("type") in {"idle", "active"} and not status.get("activeFlags"):
                    inbox.resume()
            if name == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                    result["text"] = clean(item["text"])[-32768:]
                if not result["implementation_dispatched"] and item.get("type") in {"commandExecution", "mcpToolCall"}:
                    report = inspect_owned_session(session)
                    result["readiness"] = report
                    prepared_report = None
                    if _prepared(report, mode):
                        from neurath.providers.execution_plan import ready_plan
                        result["model_verification"] = ready_plan(model_plan, session, report)
                        result["preparation"] = "verified"
                        prepared_report = report
            if name == "turn/completed":
                turn = params.get("turn", {})
                if not result["implementation_dispatched"]:
                    if turn.get("id") != result["bootstrap"].get("native_turn"):
                        continue
                    result["preparation_completion"] = {
                        key: turn.get(key) for key in ("id", "status", "error")}
                    if turn.get("status") != "completed" or prepared_report is None:
                        result["status"] = "not-ready"
                        break
                    prompt = (
                        f"Preparation turn {turn['id']} completed. This is a new, separate "
                        "authorized assignment turn. The prior preparation-only instruction "
                        "does not scope this turn. Keep the verified permissions and retained "
                        "worktree claim. "
                        + ("Inspect and respond without edits. " if mode == "read-only" else
                           "Follow normal material action prepare, tool result, readback and "
                           "resolve. Release your worktree claim only after this assigned work "
                           "is finished. ")
                        + "Assignment:\n" + assignment)
                    result["submission"] = adapter.start_after_preparation(
                        session, prompt, turn["id"])
                    result["delivery"] = result["submission"]["delivery"]
                    if result["submission"]["delivery"] != "submitted":
                        result["status"] = "needs-input"
                        break
                    result["implementation_dispatched"] = True
                    result["preparation_text"] = result.pop("text", "")
                    result["text"] = ""
                    inbox = _start_inbox(adapter, session)
                    continue
                expected = result["submission"] if result["implementation_dispatched"] else result["bootstrap"]
                if inbox:
                    disposition = inbox.complete_turn(turn.get("id"), expected.get("native_turn"),
                        successful=turn.get("status") == "completed" and result["implementation_dispatched"])
                else:
                    disposition = "terminal" if turn.get("id") == expected.get("native_turn") else "stale"
                if disposition == "stale":
                    continue
                result["completion"] = {key: turn.get(key) for key in ("id", "status", "error")}
                if result["implementation_dispatched"]:
                    result["execution"] = "native-turn-completed"
                result["status"] = ("completed" if turn.get("status") == "completed"
                    and result["implementation_dispatched"] else "not-ready" if
                    not result["implementation_dispatched"] else "failed")
                if disposition == "waiting":
                    result["status"] = "waiting"
                    started = False
                    if event_callback:
                        event_callback("waiting", {"native_session": session.native_session,
                            "reason": "delegated work or required reports remain"})
                    # Keep the owning connection and socket reader alive. A
                    # committed child message starts the next native turn.
                    inbox.resume()
                    continue
                break
        else:
            raise TimeoutError("provider execution deadline exceeded")
    except DeliveryServiceError as error:
        detail = {"reason": "delivery-service-failed", "error_type": error.error_type,
                  "native_session": None if session is None else session.native_session}
        result.update(status="failed", delivery_failure=detail, diagnostic=str(error))
        if event_callback:
            event_callback("error", detail)
    except CreationRejected as error:
        result.update(error.report)
    except UnsupportedOperation as error:
        result.update(status="unsupported", diagnostic=clean(str(error)))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        result.update(status="timed-out" if isinstance(error, TimeoutError) else "failed",
                      diagnostic=clean(f"{type(error).__name__}: {error}")[:4000])
    finally:
        _cleanup(result, inbox, host, adapter, session)
    return result
