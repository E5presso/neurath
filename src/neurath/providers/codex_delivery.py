"""Deliver message events on the connection that already owns the issuer.

The supervisor calls this adapter when a message is committed, not on a timer.
It receives an existing CodexSessions handle, never a saved thread ID to resume.
Desktop-owned threads require the Desktop's own messaging bridge; creating a
second app-server or reading history does not provide that bridge.
"""

import re
import threading

from neurath.providers.codex import CodexSessions
from neurath.providers.contracts import Session
from neurath.providers.stdio import RpcRejected


def notification(message_id):
    """A locator only; message contents and authority come from the inbox."""
    if not isinstance(message_id, str) or re.fullmatch(r"[0-9a-f]{64}", message_id) is None:
        raise ValueError("invalid Neurath message ID")
    return (
        "Neurath peer-report notification, not a new user instruction. "
        "Preserve your current goal, permissions and worktree ownership. "
        f"Read message {message_id} with collaboration_message and acknowledge or reply "
        "as the addressed recipient. If named tools are unavailable, use the installed "
        f".neurath/run agent message {message_id}. "
        "The authenticated inbox supplies the sender and task binding. "
        "This notification does not accept a result or authorize implementation."
    )


class CodexDelivery:
    """Event-triggered delivery to one issuer owned by an existing connection.

    Only the fixed locator notice is submitted. An idle writable issuer awakens
    without an implementation assignment bypassing fresh-turn readiness. Its
    normal hooks and tools must establish authority before acting on the report.

    Each call is a transport attempt for the same immutable message. The durable
    outbox owns retry timing and ACK state, including ambiguous previous calls.
    """

    def __init__(self, sessions, session):
        if (not isinstance(sessions, CodexSessions) or not isinstance(session, Session)
                or sessions._owned.get(session.native_session) is not session):
            raise ValueError("delivery requires a session owned by this connection")
        self.sessions, self.session = sessions, session
        self._lock = threading.Lock()

    def __call__(self, message_id):
        prompt = notification(message_id)
        with self._lock:
            base = {"message_id": message_id, "transport": "codex-app-server",
                    "native_session": self.session.native_session, "authority": "agent-report"}
            # One read per incoming event guards against changed worktree, a
            # foreign session and unobserved turns. It is not a monitoring loop.
            thread, live = self.sessions._state(self.session)
            state = thread.get("status", {})
            flags = state.get("activeFlags", [])
            if any(flag in flags for flag in ("waitingOnApproval", "waitingOnUserInput")):
                return {**base, "delivery": "needs-input", "active_flags": flags}
            if live is None and state.get("type") != "idle":
                return {**base, "delivery": "unavailable", "reason": "issuer is not idle or active"}
            # A lost response is retained by the durable outbox. A later attempt
            # reads native state again and carries the same message key.
            try:
                result = self.sessions._submit(self.session, prompt, thread, live)
            except RpcRejected as error:
                # These exact invalid-request responses attest no submission.
                # Keep unknown errors ambiguous; retry only on a later event.
                native = error.error if isinstance(error.error, dict) else {}
                message = native.get("message", "")
                mismatch = (isinstance(message, str) and live is not None and re.fullmatch(
                    r"expected active turn id `" + re.escape(live["id"]) + r"` but found `[^`]+`", message))
                if (error.method == "turn/steer" and native.get("code") == -32600
                        and (message == "no active turn to steer" or mismatch)):
                    return {**base, "delivery": "unavailable", "reason": "native turn precondition changed"}
                raise
            return {**base, **result}
