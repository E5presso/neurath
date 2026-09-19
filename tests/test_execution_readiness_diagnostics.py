"""Execution denial identifies failed readiness without weakening admission."""
from copy import deepcopy

import pytest

from neurath.runtime.task_schema import TaskError
from neurath.runtime.tasks import _mcp_execution_policy


def report():
    result = {"implementation_ready": True, "is_root": True,
              "stages": {name: {"status": "verified", "evidence": {}, "reason": None}
                         for name in ("installation", "activation", "ownership", "policy")}}
    result["stages"]["policy"]["evidence"] = {"approval_policy": "never",
        "sandbox_policy": {"type": "danger-full-access"}, "approvals_reviewer": "user"}
    return result


@pytest.mark.parametrize("stage,status", [
    ("installation", "failed"), ("installation", "unobserved"),
    ("activation", "failed"), ("ownership", "failed"), ("policy", "failed"),
])
def test_failed_readiness_is_not_reported_as_unsupported_permissions(monkeypatch, stage, status):
    observed = report()
    observed["implementation_ready"] = False
    observed["stages"][stage].update(status=status, reason=stage + "-not-ready")
    before = deepcopy(observed)
    monkeypatch.setattr("neurath.providers.readiness.inspect_bound_readiness", lambda *a, **k: observed)
    with pytest.raises(TaskError) as caught:
        _mcp_execution_policy(None, None, "turn")
    assert caught.value.details["code"] == "execution-readiness-required"
    assert stage in caught.value.details["message"]
    assert caught.value.details["state"] == "not-started"
    assert observed == before


def test_stale_mcp_directs_reconnect_not_repeat_install(monkeypatch):
    observed = report()
    observed["implementation_ready"] = False
    observed["stages"]["installation"].update(status="failed", reason="installation-not-ready",
        evidence={"placement": {"status": "failed", "errors": [
            ".neurath/install.json: running package differs from recorded distribution"]}})
    monkeypatch.setattr("neurath.providers.readiness.inspect_bound_readiness", lambda *a, **k: observed)
    with pytest.raises(TaskError) as caught:
        _mcp_execution_policy(None, None, "turn")
    assert "Reconnect" in caught.value.details["next_action"]
    assert "permissions" in caught.value.details["next_action"]
    from neurath.runtime.tasks import session_status
    monkeypatch.setattr("neurath.providers.readiness.inspect_readiness", lambda *a, **k: observed)
    status = session_status(None, detail="summary")
    assert "Reconnect" in next(item["instruction"] for item in status["next_actions"]
                               if item["stage"] == "installation")


def test_actual_policy_restriction_stays_denied(monkeypatch):
    observed = report()
    observed["stages"]["policy"]["evidence"]["approval_policy"] = "on-request"
    monkeypatch.setattr("neurath.providers.readiness.inspect_bound_readiness", lambda *a, **k: observed)
    with pytest.raises(TaskError) as caught:
        _mcp_execution_policy(None, None, "turn")
    assert caught.value.details["code"] == "native-execution-required"
