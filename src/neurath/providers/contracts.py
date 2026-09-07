"""Explicit execution requests and host-observed session references."""

from dataclasses import asdict, dataclass
from typing import Protocol


class UnsupportedOperation(ValueError):
    """The selected transport cannot perform the requested operation."""


class CreationRejected(ValueError):
    """The host created a session, but its observed settings did not match."""

    def __init__(self, session):
        self.session = session
        self.report = {"status": "policy-mismatch", "session": asdict(session),
                       "prompt_submitted": False}
        super().__init__(f"host policy/model mismatch for created session {session.native_session}")


class SessionTransport(Protocol):
    def request(self, method: str, params: dict) -> dict: ...


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str = "read-only"
    approval: str = "never"
    approvals_reviewer: str | None = None
    collaboration_mode: str | None = None

    def __post_init__(self):
        if self.mode not in ("read-only", "workspace-write"):
            raise ValueError("unsupported access mode")
        if self.approval not in ("never", "on-request", "untrusted"):
            raise ValueError("unsupported approval policy")
        if self.approvals_reviewer not in (None, "user", "auto_review"):
            raise ValueError("unsupported approval reviewer")
        if self.collaboration_mode not in (None, "default", "plan"):
            raise ValueError("unsupported collaboration mode")

    def requested(self):
        return {"mode": self.mode, "approval_policy": self.approval,
                "approvals_reviewer": self.approvals_reviewer, "collaboration_mode": self.collaboration_mode}


@dataclass(frozen=True)
class Session:
    provider: str
    transport: str
    native_session: str
    worktree: str
    requested_model: str | None
    actual_model: str | None
    policy: dict


def text(value, field, limit=32768):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise ValueError(f"invalid {field}")
    return value
