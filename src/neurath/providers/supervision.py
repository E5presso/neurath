"""Keep an owned provider connection available while its delegated work returns."""

import threading

from neurath.agents.delivery import DeliveryService
from neurath.agents.lifecycle import TaskLifecycle
from neurath.agents.store import MessageStore
from neurath.providers.codex_delivery import CodexDelivery


class SessionInbox:
    def __init__(self, sessions, session):
        self.store = MessageStore(session.worktree)
        self.address = "codex:" + session.native_session
        self.tasks = TaskLifecycle(self.store)
        self.deliver = CodexDelivery(sessions, session)
        self._lock = threading.RLock()
        self._closing = False
        self.turn = None
        self._transport = sessions.transport
        self._failure = None
        self.service = DeliveryService(self.store, self.address, self._notify,
                                       on_failure=self._service_failed)

    def _service_failed(self, error):
        with self._lock:
            self._failure = error
            self._closing = True
        self._transport.fail_owned_dependency(error)

    def _notify(self, message_id):
        # The event consumer takes this lock only to correlate completion. It
        # never holds it during event waits, so bidirectional RPC remains live.
        with self._lock:
            if self._closing:
                return {"delivery": "unavailable", "reason": "owning connection is closing"}
            result = self.deliver(message_id)
            if result.get("delivery") == "submitted":
                self.turn = result.get("native_turn")
            return result

    def start(self):
        self.service.__enter__()
        return self

    def expected_turn(self, original):
        with self._lock:
            return self.turn or original

    def pending(self):
        """Read obligations once at native turn completion, never on a timer."""
        with self._lock, self.store.connection() as db:
            task = db.execute("SELECT 1 FROM task_links WHERE issuer=? "
                "AND state NOT IN ('completed','failed','cancelled') LIMIT 1", (self.address,)).fetchone()
            message = db.execute("SELECT 1 FROM messages m WHERE m.recipient=? "
                "AND m.status IN ('queued','submitted') LIMIT 1", (self.address,)).fetchone()
            return bool(task or message)

    def complete_turn(self, turn_id, original, *, successful):
        """Correlate completion and fence new notifications in one transition.

        A receiver may have started a newer native turn since the event loop's
        previous observation. Its report must finish before this owner closes.
        Once terminal is selected, a later notification remains queued instead
        of starting a turn on the connection being shut down.
        """
        with self._lock:
            failure = getattr(self, "_failure", None) or getattr(self.service, "terminal_error", None)
            if failure is not None:
                raise failure
            if turn_id != (self.turn or original):
                return "stale"
            if successful and self.pending():
                return "waiting"
            self._closing = True
            return "terminal"

    def resume(self):
        self.service.resume()

    def close(self):
        with self._lock:
            self._closing = True
        # Do not hold the notification lock while joining the socket receiver.
        self.service.close()
