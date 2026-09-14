"""A finished denial is not an outstanding approval request."""
import asyncio

import pytest
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import DeferredToolUse

from neurath.providers.claude_sdk import ClaudeSession
from neurath.providers.execution_claude import _result_status
from tests.test_claude_sdk import wire  # noqa: F401


@pytest.mark.parametrize("denied,deferred,interrupted,expected", [
    (False, False, False, "completed"),
    (True, False, False, "failed"),
    (False, True, False, "waiting-approval"),
    (True, True, False, "waiting-approval"),
    (True, False, True, "cancelled"),
])
def test_terminal_status_keeps_denial_and_pending_approval_distinct(denied, deferred, interrupted, expected):
    message = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
        is_error=False, num_turns=1, session_id="fixture",
        permission_denials=[{"tool_name": "Write", "tool_use_id": "denied"}] if denied else [],
        deferred_tool_use=DeferredToolUse("pending", "Write", {}) if deferred else None,
        stop_reason="interrupted" if interrupted else None)
    assert _result_status(message) == expected


def test_sdk_emits_finished_denial_without_claiming_approval_is_pending(wire):
    async def exercise():
        events = []
        adapter = ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        await adapter.connect()
        try:
            await adapter.bootstrap()
            await wire.response(denials=[{"tool_name": "Write"}])
            [m async for m in adapter.receive_response()]
            assert events[-1][0] == "failed"
            assert events[-1][1]["approval_pending"] is False
            assert events[-1][1]["permission_denial_count"] == 1
            assert events[-1][1]["result_acceptance"] is False
        finally:
            await adapter.close()
    asyncio.run(exercise())
