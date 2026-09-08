"""Saved project identity is independent of a thread's worktree and permissions."""

import pytest

from neurath.providers.codex import CodexSessions
from neurath.providers.operations import route
from tests.test_provider_sessions import Host


class ProjectHost(Host):
    def __init__(self):
        super().__init__()
        self.thread["projectId"] = "saved"

    def request(self, method, params):
        if method == "project/read":
            self.calls.append((method, params))
            return {"project": {"id": "saved", "roots": [{"path": "/work"}]}}
        return super().request(method, params)


def test_route_keeps_saved_project_for_independent_assignment():
    result = route("codex", "create", project_id="saved", worktree="/work", assignment="Implement",
                   requested={"sandbox": "workspace-write", "approval_policy": "never",
                              "collaboration_mode": "default"})
    assert result["next_operation"]["arguments"]["project_id"] == "saved"


def test_create_passes_and_reads_back_project_without_dropping_permissions():
    host = ProjectHost()
    session = CodexSessions(host).create("/work", project_id="saved")
    started = next(params for method, params in host.calls if method == "thread/start")
    assert started["projectId"] == "saved"
    assert started["approvalPolicy"] == "never"
    assert started["sandbox"] == "read-only"
    assert session.policy["effective"]["project_id"] == "saved"


@pytest.mark.parametrize("actual", [None, "another"])
def test_wrong_project_withholds_prompts_and_preserves_created_id(actual):
    from neurath.providers.contracts import CreationRejected
    host = ProjectHost()
    host.thread["projectId"] = actual
    with pytest.raises(CreationRejected) as error:
        CodexSessions(host).create("/work", project_id="saved")
    assert error.value.session.native_session == "native-id"
    assert not any(method.startswith("turn/") for method, _ in host.calls)


def test_missing_project_does_not_block_omitted_project_request():
    class Missing(Host):
        def request(self, method, params):
            if method == "project/list":
                return {"data": []}
            return super().request(method, params)
    host = Missing()
    session = CodexSessions(host).create("/work")
    assert session.policy["verification"] == "verified"
    assert session.policy["requested"]["project_id"] is None
    assert [method for method, _ in host.calls] == ["thread/start"]


def test_project_change_after_creation_prevents_assignment():
    host = ProjectHost()
    adapter = CodexSessions(host)
    session = adapter.create("/work", project_id="saved")
    host.thread["projectId"] = "other"
    with pytest.raises(ValueError, match="project changed"):
        adapter.bootstrap(session)
    assert not any(method.startswith("turn/") for method, _ in host.calls)


@pytest.mark.parametrize("projects", [[], [
    {"id": "first", "roots": [{"path": "/work"}]},
    {"id": "second", "roots": [{"path": "/work"}]},
], [{"id": "other", "roots": [{"path": "/work-sibling"}]}]])
def test_explicit_discovery_rejects_missing_ambiguous_and_neighbor_projects(projects):
    class Discovery(Host):
        def request(self, method, params):
            if method == "project/list":
                return {"data": projects}
            return super().request(method, params)
    host = Discovery()
    with pytest.raises(ValueError, match="project"):
        CodexSessions(host).project("/work")
    assert not any(method == "thread/start" for method, _ in host.calls)


def test_discovery_consumes_pages_before_choosing_unique_project():
    class Pages(Host):
        def request(self, method, params):
            if method == "project/list" and not params.get("cursor"):
                return {"data": [], "nextCursor": "page2"}
            return super().request(method, params)
    assert CodexSessions(Pages()).project("/work") == "saved"


def test_claude_rejects_codex_project_condition_before_creation():
    from neurath.providers.execution import run
    from neurath.runtime.task_schema import arguments, TaskError
    with pytest.raises(TaskError, match="only supported for Codex"):
        arguments("provider_run", {"provider": "claude-code", "mode": "native",
            "permission_mode": "dontAsk", "worktree": "/work", "assignment": "Read",
            "project_id": "wrong"})
    with pytest.raises(ValueError, match="only supported for Codex"):
        route("claude-code", "create", project_id="wrong", worktree="/work", assignment="Read",
              requested={"sandbox": "native", "permission_mode": "dontAsk"})
    with pytest.raises(ValueError, match="only supported for Codex"):
        run("/work", provider="claude-code", worktree="/work", assignment="Read",
            mode="native", permission_mode="dontAsk", project_id="wrong")


class LoadedHost(ProjectHost):
    persisted = False
    def request(self, method, params):
        if method == "thread/read":
            return {"thread": {**self.thread, "projectId": None}}
        if method == "thread/list":
            return {"data": [self.thread.copy()] if self.persisted else [], "nextCursor": None}
        return super().request(method, params)


def test_initial_unpersisted_thread_allows_only_fixed_bootstrap():
    host = LoadedHost()
    adapter = CodexSessions(host)
    session = adapter.create("/work", project_id="saved")
    with pytest.raises(ValueError, match="project"):
        adapter.message(session, "implementation")
    assert adapter.bootstrap(session)["delivery"] == "submitted"
    with pytest.raises(ValueError, match="project"):
        adapter.bootstrap(session)


def test_loaded_null_uses_persisted_membership_without_resuming():
    host = LoadedHost()
    host.persisted = True
    adapter = CodexSessions(host)
    session = adapter.create("/work", project_id="saved")
    assert adapter.bootstrap(session)["delivery"] == "submitted"
    host.thread["projectId"] = None
    with pytest.raises(ValueError, match="project"):
        adapter.message(session, "implementation")
    assert not any(method == "thread/resume" for method, _ in host.calls)
