"""App membership is an observed record, never execution authority."""
import json
from copy import deepcopy

import pytest

from tests.test_execution_readiness_diagnostics import report


@pytest.fixture
def app_state(tmp_path, monkeypatch):
    monkeypatch.setattr("neurath.hosts.app_projects.host_storage", lambda *_: tmp_path / "sessions")
    path = tmp_path / ".codex-global-state.json"
    data = {"thread-project-assignments": {
        "current": {"projectKind": "local", "projectId": "app-project"},
        "other": {"projectKind": "local", "projectId": "private-project"}},
        "local-projects": {"app-project": {"id": "app-project", "name": "Private label"}},
        "projectless-thread-ids": []}
    path.write_text(json.dumps(data))
    return path, data


def test_membership_is_read_only_and_omits_other_app_data(app_state):
    from neurath.hosts.app_projects import observe_app_project
    path, _ = app_state
    before = path.read_bytes()
    result = observe_app_project("current")
    assert result["status"] == "assigned" and result["project_id"] == "app-project"
    assert result["authority"] == "diagnostic"
    assert "Private label" not in json.dumps(result) and "private-project" not in json.dumps(result)
    assert path.read_bytes() == before


@pytest.mark.parametrize("condition", ["missing-file", "invalid-json", "missing-thread", "deleted-project", "conflict"])
def test_missing_or_inconsistent_records_are_unobserved(app_state, condition):
    from neurath.hosts.app_projects import observe_app_project
    path, data = app_state
    if condition == "missing-file":
        path.unlink()
    elif condition == "invalid-json":
        path.write_text("not JSON")
    else:
        if condition == "missing-thread": data["thread-project-assignments"].pop("current")
        if condition == "deleted-project": data["local-projects"].clear()
        if condition == "conflict": data["projectless-thread-ids"].append("current")
        path.write_text(json.dumps(data))
    assert observe_app_project("current")["status"] == "unobserved"


def test_explicit_projectless_is_not_missing_evidence(app_state):
    from neurath.hosts.app_projects import observe_app_project
    path, data = app_state
    data["thread-project-assignments"].pop("current")
    data["projectless-thread-ids"].append("current")
    path.write_text(json.dumps(data))
    assert observe_app_project("current")["status"] == "unassigned"


@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("recorded", [True, False])
def test_session_status_reports_membership_without_changing_execution_readiness(app_state, monkeypatch, ready, recorded):
    from neurath.runtime.tasks import session_status
    observed = report()
    observed.update(provider="codex", native_session="current")
    observed["implementation_ready"] = ready
    if not ready:
        observed["stages"]["ownership"]["status"] = "unobserved"
    if not recorded:
        app_state[0].unlink()
    before = deepcopy(observed)
    monkeypatch.setattr("neurath.providers.readiness.inspect_readiness", lambda *_: observed)
    result = session_status(None, detail="summary")
    assert result["app_project"]["status"] == ("assigned" if recorded else "unobserved")
    assert result["implementation_ready"] is ready
    assert result["stages"] == before["stages"]


@pytest.mark.parametrize("root_active", [False, True])
def test_unverified_root_or_subagent_does_not_read_app_state(monkeypatch, root_active):
    from neurath.runtime.tasks import session_status
    observed = report()
    observed.update(provider="codex", native_session="current", is_root=root_active)
    if root_active:
        observed["stages"]["activation"]["status"] = "unobserved"
    monkeypatch.setattr("neurath.providers.readiness.inspect_readiness", lambda *_: observed)
    monkeypatch.setattr("neurath.hosts.app_projects.observe_app_project",
                        lambda *_: pytest.fail("App state read without a verified native root"))
    assert "app_project" not in session_status(None, detail="summary")
