"""The replacement wire surface exposes closed work commands only."""

import json
import subprocess
import sys

import pytest

from neurath.core.mcp import response
from neurath.core.service import COMMANDS
from neurath.core.tool_schema import definitions


def test_every_command_has_closed_schema_without_public_identity():
    schemas = definitions()
    assert {s["name"] for s in schemas} == set(COMMANDS)
    for schema in schemas:
        assert schema["inputSchema"]["additionalProperties"] is False
        assert not {"actor_id", "session_id", "origin", "argv"} & set(
            schema["inputSchema"]["properties"]
        )


def test_jsonrpc_validation_does_not_crash_on_non_object_params():
    assert (
        response(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []})["error"][
            "code"
        ]
        == -32602
    )


def test_actual_stdio_process_lists_new_core_tools_and_rejects_unbound_call(tmp_path):
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "session_status", "arguments": {}},
        },
    ]
    run = subprocess.run(
        [sys.executable, "-m", "neurath.core.mcp", "--root", str(tmp_path), "--provider", "codex"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        text=True,
        capture_output=True,
        check=True,
    )
    replies = [json.loads(line) for line in run.stdout.splitlines()]
    assert len(replies) == 3
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert len(replies[1]["result"]["tools"]) == len(COMMANDS)
    assert (
        replies[2]["result"]["structuredContent"]["error"]["code"] == "native-invocation-required"
    )


def test_hook_process_and_mcp_process_share_observed_native_input(tmp_path):
    hook_args = [
        sys.executable,
        "-m",
        "neurath.core.hooks",
        "--root",
        str(tmp_path),
        "--provider",
        "codex",
    ]
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "native-root",
        "prompt": "Implement this behavior.",
    }
    prompt = subprocess.run(
        hook_args, input=json.dumps(payload), text=True, capture_output=True, check=True
    )
    assert (
        "native-input provenance"
        in json.loads(prompt.stdout)["hookSpecificOutput"]["additionalContext"]
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "native-root",
        "tool_use_id": "task-list",
        "tool_name": "mcp__neurath_collaboration__task_list",
        "tool_input": {"_call_id": "task-list-1"},
    }
    binding = subprocess.run(
        hook_args, input=json.dumps(payload), text=True, capture_output=True, check=True
    )
    assert json.loads(binding.stdout) == {}
    arguments = payload["tool_input"]
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "task_list", "arguments": arguments},
    }
    mcp = subprocess.run(
        [sys.executable, "-m", "neurath.core.mcp", "--root", str(tmp_path), "--provider", "codex"],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(mcp.stdout)["result"]["structuredContent"]
    assert result["ok"] is True
    assert result["result"]["current_input"]["source_id"].startswith("source-")
    assert result["result"]["native_todo"]["tool"] == "update_plan"


def test_native_reads_and_failure_reporting_do_not_depend_on_valid_check_configuration(tmp_path):
    from neurath.core.hooks import invoke

    directory = tmp_path / ".neurath"
    directory.mkdir()
    (directory / "project.json").write_text("{invalid json")
    assert (
        invoke(
            tmp_path,
            "codex",
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s",
                "tool_name": "Read",
                "tool_input": {"file_path": "source.py"},
            },
        )
        == {}
    )
    assert (
        invoke(
            tmp_path,
            "codex",
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s",
                "tool_name": "update_plan",
                "tool_input": {"plan": []},
            },
        )
        == {}
    )
    bound = invoke(
        tmp_path,
        "codex",
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "tool_use_id": "report",
            "tool_name": "mcp__neurath_collaboration__report_record",
            "tool_input": {
                "_call_id": "report-failure",
                "key": "failure",
                "task_id": "existing-task",
                "body": "Observed blocker",
                "passed": False,
            },
        },
    )
    assert bound == {}


def test_registered_read_command_keeps_check_admission_in_process_adapter(tmp_path):
    from neurath.core.hooks import invoke

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    directory = tmp_path / ".neurath"
    directory.mkdir()
    (directory / "project.json").write_text(
        json.dumps({"verification": {"diff": {"argv": ["git", "diff", "--check"], "cwd": "."}}})
    )
    response = invoke(
        tmp_path,
        "codex",
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "cwd": str(tmp_path),
            "tool_use_id": "check",
            "tool_name": "Bash",
            "tool_input": {"command": "git diff --check"},
        },
    )
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "task-focus-required" in response["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize(
    "config",
    [
        {"verification": []},
        {"verification": {"check": []}},
        {"verification": {"check": {"argv": ["true"], "cwd": []}}},
    ],
)
def test_wrong_check_config_types_preserve_known_shell_reads(tmp_path, config):
    from neurath.core.hooks import invoke

    directory = tmp_path / ".neurath"
    directory.mkdir()
    (directory / "project.json").write_text(json.dumps(config))
    assert (
        invoke(
            tmp_path,
            "codex",
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s",
                "tool_name": "Bash",
                "tool_input": {"command": "cat README"},
            },
        )
        == {}
    )


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(2, ["git", "remote", "get-url", "origin"]),
        subprocess.TimeoutExpired(["gh", "api"], 60),
    ],
)
def test_failed_external_read_returns_error_without_losing_followup_diagnostics(failure):
    class Adapter:
        def call(self, name, arguments):
            if name == "publication_read":
                raise failure
            return {"ready": True}

    adapter = Adapter()
    first = response(
        adapter,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "publication_read", "arguments": {}},
        },
    )
    assert first["result"]["isError"] is True
    second = response(
        adapter,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "session_status", "arguments": {}},
        },
    )
    assert second["result"]["structuredContent"]["result"] == {"ready": True}
