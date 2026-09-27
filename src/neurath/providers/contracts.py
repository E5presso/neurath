"""Explicit execution requests and host-observed session references."""

from dataclasses import asdict, dataclass
from typing import Protocol


class UnsupportedOperation(ValueError):
    """The selected transport cannot perform the requested operation."""


class ProviderCancelled(Exception):
    """An explicit owner cancellation delivered to a running provider worker."""


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
        if self.mode not in ("read-only", "workspace-write", "danger-full-access"):
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


def codex_completion_link(native_session: str, submission: dict, completed_turn: str,
                          disposition: str) -> dict[str, str]:
    """Describe an event already correlated by the owned execution runtime.

    Inbox supervision can complete a later turn on the same native session.
    This record retains both turn IDs; it does not infer native event authority.
    """
    if not isinstance(submission, dict) or submission.get('delivery') != 'submitted':
        raise ValueError('completion linkage requires a submitted assignment')
    if disposition not in {'waiting', 'terminal'}:
        raise ValueError('completion linkage requires a non-stale native event')
    return {'native_session': text(native_session, 'native session', 1024),
            'submitted_turn': text(submission.get('native_turn'), 'submitted native turn', 1024),
            'completed_turn': text(completed_turn, 'completed native turn', 1024),
            'disposition': disposition}


def implementation_completed(request: dict, result: dict, generation: int) -> bool:
    """Require the first assignment generation and its provider-native completion proof."""
    if generation != 1 or result.get('implementation_dispatched') is not True:
        return False
    created, completion = result.get('created'), result.get('completion')
    if not isinstance(created, dict) or not isinstance(completion, dict) or not created.get('native_session'):
        return False
    provider = request.get('provider', 'codex')
    if created.get('provider') != provider:
        return False
    if provider == 'codex':
        try:
            link = codex_completion_link(created['native_session'], result.get('submission'),
                                         completion.get('id'), 'terminal')
        except ValueError:
            return False
        return (result.get('completion_link') == link and result.get('execution') == 'native-turn-completed' and bool(completion.get('id'))
                and completion.get('status') == 'completed' and completion.get('error') is None)
    if provider == 'claude-code':
        return (result.get('execution') == 'native-response-completed' and completion.get('subtype') == 'success'
                and completion.get('is_error') is False and not completion.get('permission_denial_count')
                and not completion.get('approval_pending')
                and completion.get('native_session') == created['native_session'])
    return False
