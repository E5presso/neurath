"""Typed native routes are actionable hints without invented mode/identity grants."""

import pytest

from neurath.providers.operations import BOOTSTRAP, capabilities, route


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
def test_app_setting_unavailable_does_not_create_or_silently_drop_request(key, value):
    result = route("codex", "create", project_id="project", requested={key: value})
    assert result["status"] == "unsupported-setting"
    assert result["next_operation"] is None
    assert result["mode"]["requested"] == {key: value}


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
