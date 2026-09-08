"""Owned Claude sessions over the official SDK's asynchronous control protocol.

The SDK itself uses a Claude Code subprocess. This adapter does not shell out to
a one-shot runner, attach to another session, or put a deadline on model work.
Its caller authenticates the issuer and checks native readiness before sending
an assignment. SDK permission modes are not an OS sandbox attestation.
"""

import asyncio
import inspect
import math
import shutil
from dataclasses import asdict
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookEventMessage,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
)

from neurath.providers.contracts import CreationRejected, Session, text

BOOTSTRAP = (
    "Prepare this Neurath session only. Read repository instructions. Use the named "
    "session_inspect MCP task tool. Use the native CLI compatibility route only if the named tool is unavailable. "
    "Call the Neurath session_status MCP task tool so its native hook records the current policy. "
    "Report actual installation, native activation and effective permission mode. "
    "This is only the preparation phase: retain any claim you obtain for the separate assignment "
    "that follows this response. Do not release it or finish the whole session here. "
    "Defer pending peer requests and task execution, including replies, until that assignment; "
    "a hook notification does not replace this preparation instruction. "
    "Do not implement changes, edit source files, synthesize lifecycle state, override a "
    "conflicting claim or change permissions. Stop and report any failed prerequisite."
)


class ClaudeSession:
    """One fresh SDK connection, with explicit native mode and no identity input.

    connect/close must run in the same asyncio task because the SDK owns an AnyIO
    task group. Inputs are serialized across complete response boundaries because
    mid-response query writes can coalesce. Events describe native responses, not
    task acceptance; a stdin write does not acknowledge a separately queued turn.
    """

    def __init__(self, worktree, *, permission_mode, model=None, rpc_timeout=30,
                 event_callback=None, restored_session=None):
        if permission_mode not in {"default", "dontAsk", "plan", "acceptEdits", "bypassPermissions", "auto"}:
            raise ValueError("unsupported Claude permission mode")
        if (isinstance(rpc_timeout, bool) or not isinstance(rpc_timeout, (int, float))
                or not math.isfinite(rpc_timeout) or not 1 <= rpc_timeout <= 120):
            raise ValueError("rpc_timeout must be between 1 and 120 seconds")
        self.worktree = str(Path(worktree).resolve())
        if not Path(self.worktree).is_dir():
            raise ValueError("worktree does not exist")
        self.permission_mode = permission_mode
        self.model = None if model is None else text(model, "model", 256)
        self.rpc_timeout = rpc_timeout
        self.event_callback = event_callback
        self.session = None
        self._startup_session = None
        self._client = None
        self._owner = None
        self._connected = False
        self._receiving = False
        self._submitted = False
        self._started = False
        self._phase = None
        self._cancel_requested = False
        self._sequence = 0
        self._pending = 0
        self._writing = False
        self._preparation_complete = False
        self.inventory = None
        if restored_session is not None and (not isinstance(restored_session, Session)
                or restored_session.provider != "claude-code" or restored_session.worktree != self.worktree
                or restored_session.actual_model != self.model
                or restored_session.policy["requested"]["permission_mode"] != permission_mode):
            raise ValueError("recovery requires the persisted Claude model, policy and workspace")
        self._restored_session = restored_session

    async def _emit(self, state, **detail):
        if self.event_callback is not None:
            result = self.event_callback(state, {
                "transport": "claude-agent-sdk", "scope": "native-response",
                "phase": self._phase,
                "native_session": self.session.native_session if self.session else None,
                **detail,
            })
            if inspect.isawaitable(result):
                await result

    async def _permission(self, tool_name, _input, _context):
        # Do not send tool arguments, paths or permission suggestions to status
        # messages. No allow decision is inferred from the assignment or callback.
        await self._emit("waiting", reason="approval-required", tool=tool_name)
        return PermissionResultDeny(
            message="Neurath has no interactive approval response on this connection.",
            interrupt=True,
        )

    async def connect(self):
        if self._client is not None:
            raise ValueError("connection already created")
        self._owner = asyncio.current_task()
        options = ClaudeAgentOptions(
            cwd=self.worktree, permission_mode=self.permission_mode, model=self.model,
            cli_path=shutil.which("claude"),
            system_prompt={"type": "preset", "preset": "claude_code"},
            setting_sources=["user", "project", "local"],
            include_partial_messages=True, can_use_tool=self._permission,
            resume=self._restored_session.native_session if self._restored_session else None,
        )
        self._client = ClaudeSDKClient(options=options)
        try:
            # wait_for would move connect into another task and break SDK cleanup.
            async with asyncio.timeout(self.rpc_timeout):
                await self._client.connect()
            self._connected = True
            from neurath.providers.model_inventory import claude_inventory
            self.inventory = await claude_inventory(self._client, host="local")
        except Exception as error:
            await self._emit("failed", reason="connection-failed", error=type(error).__name__)
            raise
        return {"status": "connected", "transport": "claude-agent-sdk",
                "native_session": None, "authority": "agent-report"}

    def _require_connected(self):
        if not self._connected:
            raise ValueError("connection is not open")

    async def bootstrap(self, *, claim_worktree=False):
        self._require_connected()
        if self.session is not None or self._submitted:
            raise ValueError("bootstrap requires a fresh connection")
        if claim_worktree and self.permission_mode == "plan":
            raise ValueError("plan preparation cannot claim an implementation worktree")
        prompt = BOOTSTRAP
        if claim_worktree:
            prompt = prompt.replace("Call the Neurath session_status", "Obtain this worktree's normal claim with "
                "the named worktree_claim MCP task tool. Call the Neurath session_status")
        return await self._submit(prompt, phase="preparation")

    async def dispatch(self, prompt):
        """Submit a separate assignment only after the preparation Result is drained."""
        self._require_connected()
        if (self.session is None or self._phase != "preparation" or not self._preparation_complete
                or self.response_active):
            raise ValueError("dispatch requires a completed and drained preparation response")
        self._started = False
        return await self._submit(prompt, phase="assignment")

    async def query(self, prompt):
        """Submit after the caller checks this session's native readiness."""
        self._require_connected()
        if self.session is None:
            raise ValueError("native session policy has not been observed")
        if self.response_active:
            raise ValueError("response or query write is active; defer until its native Result is drained")
        return await self._submit(prompt, phase="assignment")

    async def steer(self, prompt):
        """Defer active input; query() writes have no separately acknowledged turn identity."""
        self._require_connected()
        text(prompt, "prompt")
        if self.session is None or not self.response_active:
            raise ValueError("steering requires an observed active response")
        return {"delivery": "needs-input", "reason": "native-response-active",
                "native_session": self.session.native_session, "native_turn": None,
                "steering": False, "authority": "agent-report"}

    async def _submit(self, prompt, *, phase, steering=False):
        text(prompt, "prompt")
        if self.response_active:
            raise ValueError("another response or query write is active")
        self._writing = True
        # Reserve before yielding to the transport: the concurrent reader can
        # receive a native result before the write coroutine returns.
        self._sequence += 1
        self._pending += 1
        self._phase = phase
        self._submitted = True
        if not steering:
            self._started = False
            self._cancel_requested = False
        try:
            async with asyncio.timeout(self.rpc_timeout):
                # The default session_id routes the client-owned stream; it is not
                # a claimed native UUID. Read native identity only from CLI events.
                await self._client.query(prompt)
        except Exception as error:
            # A timed-out write might already have reached the provider. Retain
            # pending state, report ambiguity, and never retry it automatically.
            await self._emit("error", reason="submission-unconfirmed", error=type(error).__name__)
            raise
        finally:
            self._writing = False
        return {"delivery": "submitted", "sequence": self._sequence,
                "native_session": self.session.native_session if self.session else None,
                "native_turn": None, "steering": steering, "authority": "agent-report"}

    def _observe_init(self, data):
        native = text(data.get("session_id"), "native session", 256)
        if self._restored_session is not None and native != self._restored_session.native_session:
            raise ValueError("SDK restored a different native session")
        if self._startup_session is not None and native != self._startup_session:
            raise ValueError("SDK startup hook belongs to a different session")
        effective = {"permission_mode": data.get("permissionMode"),
                     "model": data.get("model"), "worktree": data.get("cwd"),
                     "sandbox_observation": "unobserved"}
        matched = (effective["permission_mode"] == self.permission_mode
                   and effective["worktree"] == self.worktree
                   and isinstance(effective["model"], str) and bool(effective["model"])
                   and (self.model is None or self.model == effective["model"]))
        session = Session("claude-code", "claude-agent-sdk", native, self.worktree,
            self.model, effective["model"], {
                "requested": {"permission_mode": self.permission_mode},
                "effective": effective, "verification": "verified" if matched else "mismatch"})
        if not matched or self.session is not None and self.session != session:
            raise CreationRejected(session)
        self.session = session

    async def receive_response(self):
        """Yield SDK messages through a result; no timeout surrounds this iterator."""
        self._require_connected()
        if self._receiving:
            raise ValueError("only one response reader is permitted")
        if not self._submitted:
            raise ValueError("no submitted response")
        self._receiving = True
        result_seen = False
        try:
            async for message in self._client.receive_response():
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    self._observe_init(message.data)
                native = getattr(message, "session_id", None)
                if self.session is None and isinstance(message, HookEventMessage):
                    # SessionStart hooks may precede init. Retain correlation,
                    # but do not create a Session or grant policy from a hook.
                    if native is not None:
                        native = text(native, "startup session", 256)
                        if self._startup_session not in (None, native):
                            raise ValueError("SDK startup hooks disagree on session")
                        self._startup_session = native
                    yield message
                    continue
                if native is not None and (self.session is None
                                           or native != self.session.native_session):
                    raise ValueError("SDK event belongs to an unobserved or different session: "
                                     + type(message).__name__)
                if isinstance(message, (AssistantMessage, StreamEvent)):
                    if self.session is None:
                        raise ValueError("SDK response started before native policy observation")
                    if not self._started:
                        self._started = True
                        await self._emit("started")
                    if isinstance(message, AssistantMessage) and message.error:
                        await self._emit("error", reason=message.error)
                if isinstance(message, ResultMessage):
                    result_seen = True
                    if self._pending < 1:
                        raise RuntimeError("native Result has no reserved serial query")
                    self._pending -= 1
                    self._submitted = self._pending > 0
                    if message.permission_denials or message.deferred_tool_use:
                        state = "waiting"
                    elif (message.stop_reason in {"interrupt", "interrupted", "cancelled"}
                          or message.terminal_reason in {"interrupt", "interrupted", "cancelled"}):
                        state = "cancelled"
                    else:
                        state = "failed" if message.is_error else "completed"
                    if self._phase == "preparation":
                        self._preparation_complete = state == "completed"
                    await self._emit(state, reason=message.subtype,
                                     cancellation_requested=self._cancel_requested,
                                     result_acceptance=False)
                    self._started = False
                yield message
            if not result_seen:
                raise RuntimeError("SDK stream ended without a native result")
        except asyncio.CancelledError:
            # Python task cancellation is not a confirmed native interruption.
            await self._emit("disconnected", reason="response-consumer-cancelled")
            raise
        except Exception as error:
            await self._emit("failed", reason="response-failed", error=type(error).__name__)
            raise
        finally:
            self._receiving = False

    async def confirm_connection(self):
        """Confirm the existing owned process with a read-only SDK control RPC."""
        self._require_connected()
        if self.response_active:
            raise ValueError("response must be drained before the readiness control RPC")
        async with asyncio.timeout(self.rpc_timeout):
            await self._client.get_mcp_status()
        return {"status": "confirmed", "source": "owned-sdk-control", "operation": "mcp_status"}

    async def interrupt(self):
        self._require_connected()
        async with asyncio.timeout(self.rpc_timeout):
            await self._client.interrupt()
        self._cancel_requested = True
        return {"status": "interrupt-requested",
                "native_session": self.session.native_session if self.session else None,
                "authority": "agent-report"}

    async def close(self):
        if self._client is None:
            return
        if asyncio.current_task() is not self._owner:
            raise ValueError("close must run in the SDK connection's owning asyncio task")
        # The official SDK bounds subprocess cleanup itself. Do not abandon its
        # AnyIO cancellation scopes by moving disconnect into another task.
        await self._client.disconnect()
        was_active = self._submitted
        self._connected = False
        self._submitted = False
        self._pending = 0
        if was_active:
            await self._emit("disconnected", reason="connection-closed-before-result")

    def observed(self):
        return None if self.session is None else asdict(self.session)

    @property
    def pending_responses(self):
        """Submitted queries whose ResultMessage has not yet been consumed."""
        return self._pending

    @property
    def response_active(self):
        """A serial query owns its boundary until both write and response iterator settle."""
        return self._pending > 0 or self._receiving or self._writing
