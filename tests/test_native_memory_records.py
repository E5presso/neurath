import json

from neurath.memory.transcript import command_records
from neurath.memory.hooks import tool_result


def test_stdout_json_is_not_a_process_exit_receipt():
    assert tool_result({"tool_response": '{"exit_code":0,"status":"passed"}'}) is None


def test_codex_records_use_native_exit_code_and_exact_session(tmp_path):
    p = tmp_path / "host.jsonl"

    def row(session, code):
        return {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": session,
                "item": {
                    "type": "CommandExecution",
                    "id": session,
                    "command": ["/bin/zsh", "-lc", "pytest -q"],
                    "cwd": tmp_path.as_uri(),
                    "status": "completed",
                    "exit_code": code,
                    "stdout": '{"exit_code":0}',
                },
            },
        }

    p.write_text("\n".join(json.dumps(row(s, c)) for s, c in [("own", 7), ("other", 0)]))
    assert list(command_records(p, "codex", "own", tmp_path)) == [("own", "pytest -q", 7)]


def test_claude_matches_native_tool_id_and_ignores_background(tmp_path):
    p = tmp_path / "host.jsonl"
    events = [
        {
            "type": "assistant",
            "sessionId": "own",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "one",
                        "name": "Bash",
                        "input": {"command": "pytest -q"},
                    },
                    {
                        "type": "tool_use",
                        "id": "two",
                        "name": "Bash",
                        "input": {"command": "sleep 10"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "sessionId": "own",
            "cwd": str(tmp_path),
            "toolUseResult": {"stdout": "exit_code=0", "stderr": "failed", "interrupted": False},
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "one",
                        "is_error": True,
                        "content": "failed",
                    }
                ]
            },
        },
        {
            "type": "user",
            "sessionId": "own",
            "cwd": str(tmp_path),
            "toolUseResult": {"backgroundTaskId": "task"},
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "two",
                        "is_error": False,
                        "content": "started",
                    }
                ]
            },
        },
    ]
    p.write_text("\n".join(map(json.dumps, events)))
    assert list(command_records(p, "claude-code", "own", tmp_path)) == [("one", "pytest -q", 1)]


def test_reflection_captures_visible_answer_and_never_reasoning(tmp_path):
    from neurath.memory.hooks import _last_assistant

    p = tmp_path / "host.jsonl"
    events = [
        {
            "type": "response_item",
            "payload": {
                "role": "assistant",
                "channel": "final",
                "content": [{"type": "output_text", "text": "CSV works; PDF remains."}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "role": "assistant",
                "channel": "analysis",
                "content": [{"type": "output_text", "text": "PRIVATE REASONING"}],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "PRIVATE THINKING"}],
            },
        },
    ]
    p.write_text("\n".join(map(json.dumps, events)))
    assert _last_assistant(p) == "CSV works; PDF remains."


def test_claude_native_failure_string_uses_is_error_metadata(tmp_path):
    p = tmp_path / "host.jsonl"
    events = [
        {
            "type": "assistant",
            "sessionId": "own",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "failure",
                        "name": "Bash",
                        "input": {"command": "uv run pytest -q"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "sessionId": "own",
            "cwd": str(tmp_path),
            "toolUseResult": "Error: Exit code 7\nnot json",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "failure",
                        "is_error": True,
                        "content": "Exit code 7",
                    }
                ]
            },
        },
    ]
    p.write_text("\n".join(map(json.dumps, events)))
    assert list(command_records(p, "claude-code", "own", tmp_path)) == [
        ("failure", "uv run pytest -q", 1)
    ]
