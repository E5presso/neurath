"""Claude inbox delivery on the owned SDK loop and response connection.

This adapter owns notification serialization and obligation wakeups. Native
preparation and assignment execution belong to execution_claude.
"""

import asyncio

from neurath.agents.delivery import DeliveryService
from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import MessageStore
from neurath.providers.claude_sdk import ClaudeSession
from neurath.providers.codex_delivery import notification


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
        self.service = DeliveryService(
            self.store, self.address, self._notify, on_failure=self._service_failed
        )

    def _service_failed(self, error):
        self._loop.call_soon_threadsafe(self._mark_failed, error)

    def _mark_failed(self, error):
        if self._failure is not None or self._closing:
            return
        self._failure = error
        self._closing = True
        self._failure_report = self._loop.create_task(
            self.adapter._emit(
                "error",
                reason="delivery-service-failed",
                error_type=error.error_type,
                scope="task-supervision",
            )
        )
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
                    return {
                        "delivery": "unavailable",
                        "reason": "owning connection is closing",
                        "transport": "claude-agent-sdk",
                    }
                if self.adapter.response_active:
                    # The message stays durable. Hold it for the actual native
                    # response-completed event, without writing coalescible input.
                    return {
                        "delivery": "needs-input",
                        "reason": "native-response-active",
                        "transport": "claude-agent-sdk",
                    }
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
            task = db.execute(
                "SELECT 1 FROM task_links WHERE issuer=? "
                "AND state NOT IN ('completed','failed','cancelled') LIMIT 1",
                (self.address,),
            ).fetchone()
            message = db.execute(
                "SELECT 1 FROM messages m WHERE m.recipient=? "
                "AND m.status IN ('queued','submitted') LIMIT 1",
                (self.address,),
            ).fetchone()
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
        await self.adapter._emit(
            "waiting", reason="delegated-work-pending", scope="task-supervision"
        )
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
