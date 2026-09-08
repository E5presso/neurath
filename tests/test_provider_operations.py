"""Typed native routes are actionable hints without invented mode/identity grants."""

import pytest

from neurath.providers.operations import BOOTSTRAP, capabilities, route


@pytest.mark.parametrize("provider", ["codex", "claude-code"])
def test_independent_execution_defaults_to_native_policy_inheritance(provider):
    result = route(provider, "create", worktree="/installed", assignment="Implement")
    assert result["next_operation"] == {"tool": "provider_run", "arguments": {
        "provider": provider, "mode": "inherit", "worktree": "/installed", "assignment": "Implement"}}
    assert result["mode"]["effective"] is None
    assert not result["implementation_dispatched"]


def test_create_preserves_host_model_default_and_bootstraps_without_assignment():
    result = route("codex", "create", project_id="discovered-project")
    arguments = result["next_operation"]["arguments"]
    assert arguments["prompt"] == BOOTSTRAP
    assert "model" not in arguments
    assert result["implementation_dispatched"] is False
    assert result["mode"]["effective"] is None
    explicit = route("codex", "create", model="chosen", project_id="discovered-project")
    assert explicit["next_operation"]["arguments"]["model"] == "chosen"


@pytest.mark.parametrize("key,value", [("sandbox", "workspace-write"), ("approval_policy", "on-request"),
    ("approvals_reviewer", "auto_review"), ("collaboration_mode", "plan")])
def test_app_preparation_keeps_expected_settings_without_claiming_them_applied(key, value):
    result = route("codex", "create", project_id="project", requested={key: value})
    assert result["status"] == "preparation-only"
    assert result["next_operation"]["tool"] == "create_thread"
    assert key in result["next_operation"]["arguments"]["prompt"]
    assert value in result["next_operation"]["arguments"]["prompt"]
    assert result["mode"]["requested"] == {key: value}
    assert result["mode"]["effective"] is None
    assert result["implementation_dispatched"] is False
    assert "shared state" in result["after_creation"]


def test_app_preparation_discovers_project_even_with_explicit_expected_settings():
    result = route("codex", "create", requested={"sandbox": "danger-full-access", "approval_policy": "never"})
    assert result["next_operation"]["tool"] == "list_projects"
    assert result["mode"]["verification"] == "unobserved"


def test_missing_project_and_session_are_discovered_before_control():
    assert route("codex", "create")["next_operation"]["tool"] == "list_projects"
    assert route("codex", "status")["next_operation"]["tool"] == "list_threads"
    assert route("codex", "resume", native_session="exact")["next_operation"] == {
        "tool": "read_thread", "arguments": {"threadId": "exact"}}


def test_claude_peer_route_requires_stored_message_and_actual_native_schema():
    assert route("claude-code", "peer")["status"] == "message-storage-required"
    result = route("claude-code", "peer", native_session="exact", message_id="stored")
    assert result["status"] == "discovery-required"
    assert result["next_operation"]["arguments"] is None
    assert result["next_operation"]["schema_source"] == "current-native-host"


def test_capabilities_cannot_accept_declared_tool_inventory_as_proof():
    result = capabilities("codex")
    assert result["inventory_source"] == "not-observed"
    assert all(not op["available"] for row in result["transports"] for op in row["operations"].values())
    with pytest.raises(TypeError):
        capabilities("codex", available_tools=["create_thread"])


def test_claude_execution_uses_native_policy_without_codex_sandbox_equivalence():
    from neurath.runtime.task_schema import arguments, TaskError

    route_result = route("claude-code", "create", worktree="/installed", assignment="Implement",
                         requested={"sandbox": "native", "permission_mode": "dontAsk"})
    request = route_result["next_operation"]
    assert request["tool"] == "provider_run"
    parsed = arguments("provider_run", request["arguments"])
    assert parsed["provider"] == "claude-code" and parsed["permission_mode"] == "dontAsk"
    assert parsed["approval_policy"] == ""
    with pytest.raises(TaskError, match="without Codex"):
        arguments("provider_run", {**request["arguments"], "approval_policy": "never"})
    with pytest.raises(TaskError, match="only supported"):
        arguments("provider_run", {**request["arguments"], "provider": "codex"})
