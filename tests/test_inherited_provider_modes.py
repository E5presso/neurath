"""Accepted broad execution modes do not depend on app observation."""

import pytest

from neurath.providers.contracts import ExecutionPolicy
from neurath.providers.claude_sdk import ClaudeSession
from neurath.providers.execution import _prepared


def test_native_readiness_does_not_require_app_access():
    assert _prepared({"implementation_ready": True}, "workspace-write")


def test_codex_preserves_authorized_full_access_mode():
    assert ExecutionPolicy("danger-full-access", "never", collaboration_mode="default").requested()["mode"] == "danger-full-access"


@pytest.mark.parametrize("mode", ["bypassPermissions", "auto"])
def test_claude_supports_inherited_native_modes(tmp_path, mode):
    assert ClaudeSession(tmp_path, permission_mode=mode).permission_mode == mode
