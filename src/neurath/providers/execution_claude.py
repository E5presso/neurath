"""Claude-native worker policy, separate from Codex's OS sandbox enums."""

import asyncio
import inspect
import json
import sqlite3
import time
import traceback
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from neurath.agents.delivery import DeliveryService, DeliveryServiceError
from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import MessageStore
from neurath.memory.store import canonical, clean, control_root
from neurath.providers.claude_sdk import ClaudeSession
from neurath.providers.codex_delivery import notification
from neurath.providers.contracts import CreationRejected, text
from neurath.providers.execution import _target


class ClaudeInbox:
    """Event-driven notifications on the existing SDK loop and connection."""

    def __init__(self, adapter):
        if not isinstance(adapter, ClaudeSession) or adapter.session is None:
            raise ValueError("Claude inbox requires an owned observed SDK connection")
        self.adapter = adapter
        self.store = MessageStore(adapter.session.worktree)
        self.address = "claude-code:" + adapter.session.native_session
        self.tasks = TaskLifecycle(self.store)
        self._loop = asyncio.get_running_loop()
        self._changed = asyncio.Event()
        self._sending = asyncio.Lock()
        self._closing = False
        self._failure = None
        self._failure_report = None
        self.service = DeliveryService(self.store, self.address, self._notify,
                                       on_failure=self._service_failed)

    def _service_failed(self, error):
        self._loop.call_soon_threadsafe(self._mark_failed, error)

    def _mark_failed(self, error):
        if self._failure is not None or self._closing:
            return
        self._failure = error
        self._closing = True
        self._failure_report = self._loop.create_task(self.adapter._emit("error",
            reason="delivery-service-failed", error_type=error.error_type, scope="task-supervision"))
        self._changed.set()

    async def raise_if_failed(self):
        terminal_error = getattr(self.service, "terminal_error", None)
        if self._failure is None and terminal_error is not None:
            self._mark_failed(terminal_error)
        if self._failure is None:
            return
        try:
            if self._failure_report is not None:
                await asyncio.shield(self._failure_report)
        except Exception as error:
            self.failure_notification_error = type(error).__name__
        raise self._failure

    def start(self):
        self.service.__enter__()
        return self

    async def _receive(self, message_id):
        async with self._sending:
            try:
                if self._closing:
                    return {"delivery": "unavailable", "reason": "owning connection is closing",
                            "transport": "claude-agent-sdk"}
                if self.adapter.response_active:
                    # The message stays durable. Hold it for the actual native
                    # response-completed event, without writing coalescible input.
                    return {"delivery": "needs-input", "reason": "native-response-active",
                            "transport": "claude-agent-sdk"}
                prompt = notification(message_id)
                result = await self.adapter.query(prompt)
                return {**result, "transport": "claude-agent-sdk"}
            finally:
                self._changed.set()

    def _notify(self, message_id):
        # This executes on DeliveryService's socket thread. Wait only for the
        # input write, never for a model response; the SDK loop remains available.
        future = asyncio.run_coroutine_threadsafe(self._receive(message_id), self._loop)
        return future.result(timeout=self.adapter.rpc_timeout + 1)

    def response_completed(self):
        if self.adapter.response_active:
            raise ValueError("native response iterator is not drained")
        self.service.resume()

    def pending(self):
        with self.store.connection() as db:
            task = db.execute("SELECT 1 FROM task_links WHERE issuer=? "
                "AND state NOT IN ('completed','failed','cancelled') LIMIT 1", (self.address,)).fetchone()
            message = db.execute("SELECT 1 FROM messages m WHERE m.recipient=? "
                "AND m.status IN ('queued','submitted') LIMIT 1", (self.address,)).fetchone()
            return bool(task or message)

    async def wait_for_obligations(self):
        await self.raise_if_failed()
        # Clear before checking durable state: a racing socket event must not be
        # lost between the state read and the event wait. No timer or status loop.
        async with self._sending:
            self._changed.clear()
            if self._closing:
                return False
            if self.adapter.response_active:
                return True
            if not self.pending():
                self._closing = True
                return False
        await self.adapter._emit("waiting", reason="delegated-work-pending", scope="task-supervision")
        await self._changed.wait()
        await self.raise_if_failed()
        return True

    def close(self):
        self._closing = True
        self.service.close()

    async def aclose(self):
        self._closing = True
        # Let an already submitted input finish before SDK disconnect; socket
        # thread cleanup must not block the event loop it is waiting on.
        async with self._sending:
            pass
        await asyncio.to_thread(self.service.close)
        if self._failure_report is not None:
            try:
                await asyncio.shield(self._failure_report)
            except Exception as error:
                self.failure_notification_error = type(error).__name__


def _policy_context(root, identity, expected_turn):
    """Read a native-hook observation; never replay its invocation capability."""
    from neurath.runtime.database import RuntimeDatabase

    with RuntimeDatabase(control_root(root)).connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collaboration_calls'").fetchone():
            return None
        row = db.execute("""SELECT context,invocation,expires FROM collaboration_calls
            WHERE root=? AND host='claude-code' AND session=? AND actor=? AND is_root=1 AND turn=?
            ORDER BY rowid DESC LIMIT 1""",
            (str(Path(root).resolve()), identity.session, identity.actor, expected_turn)).fetchone()
    if row is None or row["expires"] <= time.time():
        return None
    context = json.loads(row["context"])
    if (not isinstance(context, dict) or context.get("host") != "claude-code"
            or context.get("session") != identity.session or context.get("actor") != identity.actor
            or context.get("turn") != expected_turn or not context.get("tool_use_id")
            or "user_prompt_receipt" not in context
            or row["invocation"] != canonical(["claude-code", identity.session, identity.actor,
                                                context["tool_use_id"]])):
        raise ValueError("native policy observation binding differs")
    return context


def _readiness(session):
    """Read native state only for the UUID observed on this owned SDK stream.

    SDK init is not substituted for policy authority. The current native MCP
    hook's context is revalidated by the core against the foreground and receipt.
    """
    from neurath.agents.store import AgentIdentity
    from neurath.providers.readiness import inspect_bound_readiness
    from neurath.runtime.engine import activate

    root = Path(session.worktree)
    activate(root)
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    try:
        state = SessionKernel(SessionLocator.from_worktree(root)).inspect(SessionId(session.native_session))
        actor = state.session.root_actor_id
        turn = state.foreground_turns[actor]
        identity = AgentIdentity("claude-code", session.native_session, str(actor), True)
        expected_turn = canonical([turn.generation, turn.vendor_turn_id])
        context = _policy_context(root, identity, expected_turn)
        report = inspect_bound_readiness(root, identity, expected_turn=expected_turn,
                                        verified_policy_evidence=context)
        effective = report.get("stages", {}).get("policy", {}).get("evidence", {})
        if effective.get("permission_mode") != session.policy["requested"]["permission_mode"]:
            report["stages"]["policy"] = {"status": "failed", "reason": "policy-mismatch", "evidence": effective}
            report["implementation_ready"] = False
        return report
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error) as error:
        return {"authority": "diagnostic", "implementation_ready": False,
                "waiting": None, "stages": {}, "reason": type(error).__name__}


def run(root, *, worktree, assignment, model=None, mode="read-only", approval_policy=None,
        approvals_reviewer=None, collaboration_mode=None, permission_mode=None,
        timeout=None, event_callback=None, model_plan=None, model_owner=None, run_id=None,
        reasoning_effort=None, policy_inheritance=None, restored_session=None):
    """Synchronous detached-worker boundary; no model-lifetime timeout."""
    result = {"authority": "agent-report", "transport": "claude-agent-sdk", "status": "failed",
              "retryable": False, "implementation_dispatched": False, "text": "",
              "preparation": "not-started", "delivery": "not-submitted", "execution": "unobserved"}
    try:
        text(assignment, "assignment")
        if timeout is not None:
            return {**result, "status": "unsupported", "diagnostic": "Claude SDK session work has no execution timeout"}
        if mode != "native":
            return {**result, "status": "unsupported",
                    "diagnostic": "Claude SDK requires mode=native; permissionMode is not a Codex OS sandbox"}
        if permission_mode not in {"plan", "dontAsk", "default", "acceptEdits", "bypassPermissions", "auto"}:
            return {**result, "status": "settings-required",
                    "diagnostic": "Claude native execution requires an explicit supported permission_mode"}
        if any(value is not None for value in (approval_policy, approvals_reviewer, collaboration_mode)):
            return {**result, "status": "unsupported",
                    "diagnostic": "Claude native execution uses permission_mode, not Codex approval or collaboration fields"}
        target = _target(root, worktree, "read-only" if permission_mode == "plan" else "workspace-write")
        if reasoning_effort is not None:
            raise ValueError("Claude reasoning setting requires an observed supported native mapping")
        return asyncio.run(_run(target, assignment, model, permission_mode, event_callback, result,
                                model_plan=model_plan, model_owner=model_owner, run_id=run_id,
                                restored_session=restored_session))
    except DeliveryServiceError as error:
        return {**result, "status": "failed", "diagnostic": str(error),
                "delivery_failure": {"reason": "delivery-service-failed", "error_type": error.error_type}}
    except CreationRejected as error:
        return {**result, **error.report}
    except Exception as error:  # noqa: BLE001 - SDK control failures include plain Exception.
        # Provider errors can contain private prompt/output. Report their class;
        # stderr belongs to the private worker log, not creator status messages.
        traceback.print_exc()
        return {**result, "status": "failed", "diagnostic": type(error).__name__}


def _result_status(message):
    if message.permission_denials or message.deferred_tool_use:
        return "waiting-approval"
    if (message.stop_reason in {"interrupt", "interrupted", "cancelled"}
            or message.terminal_reason in {"interrupt", "interrupted", "cancelled"}):
        return "cancelled"
    return "failed" if message.is_error else "completed"


def _ready(report, permission_mode):
    ready = report.get("waiting") is None and all(
        report.get("stages", {}).get(name, {}).get("status") == "verified"
        for name in ("installation", "activation", "policy"))
    return ready and (permission_mode == "plan" or report.get("implementation_ready") is True)


def _same_preparation_policy(left, right):
    fields = ("host", "session", "actor", "turn", "permission_mode", "user_prompt_receipt")
    return all(left.get(field) == right.get(field) for field in fields)


def _same_preparation(fresh, prepared, permission_mode):
    if prepared is None or not _ready(prepared, permission_mode):
        return False
    try:
        before, after = prepared["stages"], fresh["stages"]
        keys = ("native_session", "actor", "native_turn", "generation")
        return (all(before["activation"]["evidence"][key] == after["activation"]["evidence"][key] for key in keys)
            and _same_preparation_policy(before["policy"]["evidence"], after["policy"]["evidence"])
            and before["installation"] == after["installation"]
            and (permission_mode == "plan" or before["ownership"] == after["ownership"]))
    except (KeyError, TypeError):
        return False


def _quiescent_readiness(adapter, prepared):
    """Revalidate the owned, drained preparation without claiming an idle turn is active."""
    from neurath.agents.store import AgentIdentity
    from neurath.providers.readiness import _assess, _claude_policy, _installation, _prompt_matches, _stage
    from neurath.runtime.engine import activate

    session = adapter.session
    if session is None or adapter.response_active or not adapter._connected:
        return {"implementation_ready": False, "stages": {}, "reason": "preparation-not-drained"}
    fresh = _readiness(session)
    if _ready(fresh, adapter.permission_mode) and _same_preparation(fresh, prepared, adapter.permission_mode):
        return fresh
    root = Path(session.worktree)
    activate(root)
    from neurath.hosts.identity import _transcript, active_connection, snapshot
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry
    stages = {"installation": _installation(root), "activation": _stage("unobserved", "quiescence-unverified"),
              "policy": _stage("unobserved", "policy-unobservable"), "ownership": _stage("unobserved", "claim-unobserved")}
    try:
        if prepared is None or not _ready(prepared, adapter.permission_mode):
            raise ValueError("no verified active preparation observation")
        prior = prepared["stages"]
        state = SessionKernel(SessionLocator.from_worktree(root)).inspect(SessionId(session.native_session))
        actor = state.actors[state.session.root_actor_id]
        turn = state.foreground_turns[actor.id]
        activation = prior["activation"]["evidence"]
        if (state.session.runtime.value != "claude-code" or state.session.status.value != "active"
                or actor.parent_actor_id is not None or actor.status.value not in {"active", "idle"}
                or turn.status.value != "closed" or turn.generation != activation["generation"]
                or turn.vendor_turn_id != activation["native_turn"] or str(actor.id) != activation["actor"]
                or session.native_session != activation["native_session"]):
            raise ValueError("owned preparation identity/turn is not the same closed turn")
        native = snapshot(root, session.native_session)
        if (native.get("host") != "claude-code" or not native.get("start_source")
                or not active_connection(root, session.native_session)):
            raise ValueError("owned native connection is no longer registered")
        import os
        _transcript("claude-code", native["transcript"], os.environ)
        identity = AgentIdentity("claude-code", session.native_session, str(actor.id), True)
        expected = canonical([turn.generation, turn.vendor_turn_id])
        context = _policy_context(root, identity, expected)
        stages["policy"] = _claude_policy(context, identity, expected)
        if (not isinstance(context, dict) or not _prompt_matches(context, turn)
                or context.get("permission_mode") != session.policy["requested"]["permission_mode"]
                or not _same_preparation_policy(stages["policy"]["evidence"], prior["policy"]["evidence"])):
            raise ValueError("preparation policy or native user prompt changed")
        if stages["installation"] != prior["installation"] or stages["installation"]["status"] != "verified":
            raise ValueError("installation changed after preparation")
        try:
            canonical_worktree = WorktreeIdentityResolver().resolve(root)
            claim = WorktreeRegistry(SessionLocator.from_worktree(root)).get(canonical_worktree.worktree_id)
            if (claim.path != root or claim.session_id != state.session.id or claim.actor_id != actor.id
                    or claim.status.value != "active" or claim.lease_epoch != prior["ownership"]["evidence"]["lease_epoch"]):
                raise ValueError("prepared worktree ownership changed")
            stages["ownership"] = prior["ownership"]
        except (OSError, ValueError, RuntimeError, KeyError):
            if adapter.permission_mode != "plan":
                raise
        if SessionKernel(SessionLocator.from_worktree(root)).inspect(state.session.id).revision != state.revision:
            raise ValueError("native preparation changed during quiescence readback")
        stages["activation"] = _stage("verified", evidence={**activation, "kernel_revision": state.revision,
            "source": "owned-sdk-quiescent-readback", "foreground_status": "closed"})
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        stages["activation"] = _stage("failed", "quiescence-unverified", {"error_type": type(error).__name__})
    return {**_assess(stages), "native_session": session.native_session, "scope": "owned-quiescent-session"}


async def _run(target, assignment, model, permission_mode, event_callback, result, *,
               model_plan=None, model_owner=None, run_id=None, restored_session=None):
    async def events(state, detail):
        if state == "completed" or not result["implementation_dispatched"] and state == "started":
            return
        if state == "failed":
            state = "error"
        if event_callback is not None:
            value = event_callback(state, detail)
            if inspect.isawaitable(value):
                await value

    options = {"permission_mode": permission_mode, "model": model, "event_callback": events}
    if restored_session is not None:
        options["restored_session"] = restored_session
    adapter = ClaudeSession(target, **options)
    inbox = None
    created = False
    prepared = None
    preparation_result = None
    try:
        await adapter.connect()
        result["bootstrap"] = await adapter.bootstrap(claim_worktree=permission_mode != "plan")
        result["preparation"] = "submitted"
        # A stdin write during this response may be coalesced by Claude. Drain
        # its actual Result and iterator before sending any assignment input.
        async for message in adapter.receive_response():
            if adapter.session is not None:
                result["created"] = adapter.observed()
                if not created:
                    created = True
                    if event_callback:
                        event_callback("native-created", {"created": result["created"]})
                    if model_plan is not None and restored_session is None:
                        from neurath.providers.execution_plan import created_plan
                        model_plan = created_plan(target, model_owner, run_id, model_plan,
                                                  adapter.session, adapter.inventory)
                        result["model_plan"] = model_plan
                if not isinstance(message, ResultMessage):
                    observed = _readiness(adapter.session)
                    result["readiness"] = observed
                    if _ready(observed, permission_mode):
                        prepared = observed
            if isinstance(message, ResultMessage):
                preparation_result = message
        if preparation_result is None:
            raise RuntimeError("preparation ended without its native Result")
        result["preparation_completion"] = {"subtype": preparation_result.subtype,
            "is_error": preparation_result.is_error, "native_session": preparation_result.session_id}
        status = _result_status(preparation_result)
        if status != "completed":
            result.update(status=status, preparation="waiting" if status == "waiting-approval" else "failed")
            return result
        result["preparation_transport"] = await adapter.confirm_connection()
        report = _quiescent_readiness(adapter, prepared)
        result["readiness"] = report
        if not _ready(report, permission_mode):
            result.update(status="not-ready", preparation="unverified")
            return result
        from neurath.providers.execution_plan import ready_plan
        result["model_verification"] = ready_plan(model_plan, adapter.session, report)
        result["preparation"] = "verified"
        result["submission"] = await adapter.dispatch(
            "Neurath authorized peer assignment. Keep native permissions. "
            + ("Inspect without edits. " if permission_mode == "plan" else
               "Follow normal material actions and release your own claim after completion. ")
            + "Assignment:\n" + assignment)
        result["delivery"] = "submitted"
        result["implementation_dispatched"] = True
        inbox = ClaudeInbox(adapter).start()
        while True:
            async for message in adapter.receive_response():
                await inbox.raise_if_failed()
                if isinstance(message, AssistantMessage):
                    result["text"] = clean("\n".join(
                        block.text for block in message.content if isinstance(block, TextBlock)))[-32768:]
                if isinstance(message, ResultMessage):
                    result["status"] = _result_status(message)
                    result["execution"] = "native-response-completed"
                    result["completion"] = {"subtype": message.subtype, "is_error": message.is_error,
                        "native_session": message.session_id, "result_acceptance": False}
                    if message.result is not None:
                        result["text"] = clean(message.result)[-32768:]
            if result["status"] != "completed":
                break
            # The iterator has closed; release inputs held for this exact native
            # response boundary, then supervise durable obligations as before.
            inbox.response_completed()
            if not await inbox.wait_for_obligations():
                break
        return result
    finally:
        try:
            if inbox is not None:
                await inbox.aclose()
        finally:
            try:
                if adapter.pending_responses:
                    try:
                        result["cancellation"] = await adapter.interrupt()
                    except Exception as error:  # noqa: BLE001 - SDK control errors are untyped.
                        result["cancellation"] = {"status": "unconfirmed", "diagnostic": type(error).__name__}
            finally:
                await adapter.close()
                if adapter.session is not None:
                    result["closure"] = {"native_session": adapter.session.native_session,
                        "transport": "claude-agent-sdk", "connection_closed": True,
                        "native_process_exited": True, "source": "owned-sdk-disconnect",
                        "reason": "transport-closed"}
