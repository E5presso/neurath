"""Pure message identity, bounded inputs and collaboration lifecycle vocabulary.

These values validate data only. They do not open stores, admit native actors,
change task ownership or grant permission to send a message.
"""

import hashlib
from dataclasses import dataclass

MAX_BULK_ITEMS = 32
MAX_BULK_RECIPIENTS = 32
MAX_BULK_DELIVERIES = 100
MAX_MESSAGE_BYTES = 32768
MAX_BULK_BODY_BYTES = 262144

TERMINAL = frozenset({"completed", "failed", "cancelled"})
STATES = TERMINAL | {"assigned", "starting", "started", "waiting", "error", "disconnected"}


def bounded(value, label, limit=512):
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\0" in value
        or len(value.encode()) > limit
    ):
        raise ValueError(f"{label} must be nonempty text within {limit} bytes")
    return value



def bulk_messages(messages):
    """Validate the entire bounded batch before opening a delivery transaction."""
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_BULK_ITEMS:
        raise ValueError("messages must contain one to 32 items")
    normalized, keys = [], set()
    deliveries = body_bytes = 0
    for item in messages:
        if (not isinstance(item, dict) or set(item) - {"to", "message", "key", "kind"}
                or not {"to", "message", "key"}.issubset(item)):
            raise ValueError("bulk item requires to, message and key only, with optional kind")
        key = bounded(item["key"], "idempotency key")
        body = bounded(item["message"], "message", MAX_MESSAGE_BYTES)
        kind = item.get("kind", "question")
        if kind not in {"question", "proposal", "update", "result"}:
            raise ValueError("invalid message kind")
        recipients = item["to"]
        if (not isinstance(recipients, list) or not 1 <= len(recipients) <= MAX_BULK_RECIPIENTS
                or any(not isinstance(recipient, str) for recipient in recipients)
                or len(set(recipients)) != len(recipients)):
            raise ValueError("bulk recipients must be one to 32 distinct addresses")
        for recipient in recipients:
            bounded(recipient, "recipient")
        if key in keys:
            raise ValueError("bulk item keys must be unique")
        keys.add(key)
        deliveries += len(recipients)
        body_bytes += len(body.encode()) * len(recipients)
        normalized.append((key, body, kind, tuple(recipients)))
    if deliveries > MAX_BULK_DELIVERIES or body_bytes > MAX_BULK_BODY_BYTES:
        raise ValueError("bulk recipient or durable body byte limit exceeded")
    return normalized



@dataclass(frozen=True)
class AgentIdentity:
    host: str
    session: str
    actor: str
    is_root: bool = True

    def __post_init__(self):
        if self.host not in ("codex", "claude-code"):
            raise ValueError("unsupported agent host")
        bounded(self.session, "session")
        bounded(self.actor, "actor")

    @property
    def address(self):
        suffix = "" if self.is_root else ":" + hashlib.sha256(self.actor.encode()).hexdigest()[:24]
        return f"{self.host}:{self.session}{suffix}"
