"""False-positive native driver regressions: narrative/exit zero cannot substitute."""

import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "native_evidence", Path(__file__).resolve().parents[1] / "tools/native_evidence.py"
)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def ending(turn="turn"):
    return {
        "method": "turn/completed",
        "params": {
            "threadId": "thread",
            "turn": {"id": turn, "status": "completed", "error": None},
        },
    }


def item(kind, **fields):
    return {
        "method": "item/completed",
        "params": {"threadId": "thread", "turnId": "turn", "item": {"type": kind, **fields}},
    }


@pytest.mark.parametrize(
    "events",
    [
        [ending()],
        [ending(), item("agentMessage", text="close helper exit 0 CLOSED")],
        [
            ending(),
            item("commandExecution", command="helper close", exitCode=1, aggregatedOutput="CLOSED"),
        ],
        [
            ending(),
            item("commandExecution", command="helper close", exitCode=0, aggregatedOutput=""),
        ],
        [
            ending(),
            item("commandExecution", command="helper close", exitCode=0, aggregatedOutput=None),
        ],
        [
            ending("old"),
            item("commandExecution", command="helper close", exitCode=0, aggregatedOutput="CLOSED"),
        ],
    ],
)
def test_completed_narrative_or_wrong_execution_is_not_success(events):
    with pytest.raises(AssertionError):
        evidence.codex_turn(events, "thread", "turn", [("helper close", "CLOSED")])


def test_admission_denial_cannot_be_mistaken_for_expected_protection():
    events = [
        ending(),
        {
            "method": "hook/completed",
            "params": {
                "threadId": "thread",
                "turnId": "turn",
                "run": {
                    "eventName": "userPromptSubmit",
                    "status": "blocked",
                    "entries": [{"kind": "block", "text": "conflicting provenance"}],
                },
            },
        },
    ]
    with pytest.raises(AssertionError):
        evidence.codex_turn(events, "thread", "turn", protected_denial=True)


def test_compaction_item_is_not_the_compact_turn_completion():
    with pytest.raises(AssertionError):
        evidence.codex_turn(
            [item("contextCompaction"), ending("old")], "thread", "turn", compact=True
        )
    assert evidence.codex_turn(
        [item("contextCompaction"), ending()], "thread", "turn", compact=True
    )["completed"]


def test_claude_success_narrative_does_not_substitute_for_helper():
    with pytest.raises(AssertionError):
        evidence.claude_commands(
            [
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "CLOSED exit 0",
                }
            ],
            [("helper close", "CLOSED")],
        )


@pytest.mark.parametrize("command", [
    "false # helper close\nprintf CLOSED",
    "echo helper close; printf CLOSED",
    "helper close; printf CLOSED",
    "helper close || printf CLOSED",
    "/bin/sh -c 'false # helper close\nprintf CLOSED'",
    "helper close-extra",
])
def test_unrelated_or_compound_native_command_cannot_prove_required_execution(command):
    events = [ending(), item("commandExecution", command=command,
                             exitCode=0, aggregatedOutput="CLOSED")]
    with pytest.raises(AssertionError):
        evidence.codex_turn(events, "thread", "turn", [("helper close", "CLOSED")])
    claude = [
        {"type": "result", "subtype": "success", "is_error": False},
        {"message": {"content": [
            {"type": "tool_use", "id": "run", "name": "Bash", "input": {"command": command}},
            {"type": "tool_result", "tool_use_id": "run", "content": "CLOSED"},
        ]}},
    ]
    with pytest.raises(AssertionError):
        evidence.claude_commands(claude, [("helper close", "CLOSED")])


@pytest.mark.parametrize("command", ["helper close", "/bin/zsh -lc 'helper close'",
                                      "helper 'close'"])
def test_exact_native_command_accepts_host_shell_envelope(command):
    events = [ending(), item("commandExecution", command=command,
                             exitCode=0, aggregatedOutput="CLOSED")]
    assert evidence.codex_turn(events, "thread", "turn", [("helper close", "CLOSED")])["completed"]


def test_unquoted_newline_is_a_command_boundary():
    assert not evidence._exact_command("echo\necho CLOSED", "echo echo CLOSED")
    assert not evidence._exact_command("/bin/sh -c 'echo\necho CLOSED'", "echo echo CLOSED")
    assert evidence._exact_command("printf '%s' 'a\nb'", "printf '%s' 'a\nb'")


@pytest.mark.parametrize(
    "invocations,expected",
    [
        ([], False),
        ([{"status": "started", "receipt": None}], False),
        ([{"status": "observed", "receipt": {"outcome": "succeeded"}}], True),
        (
            [
                {"status": "observed", "receipt": {"outcome": "succeeded"}},
                {"status": "started", "receipt": None},
            ],
            False,
        ),
    ],
)
def test_native_interrupt_waits_for_receipt_not_invocation_start(invocations, expected):
    s = {
        "session": {"root_actor_id": "root"},
        "material_actions": {"root": {"status": "open", "invocations": invocations}},
    }
    assert evidence.observed_open_batch(s) == expected


def test_background_completion_requires_the_exact_native_output_file():
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "start",
                        "name": "Bash",
                        "input": {"command": "helper complete", "run_in_background": True},
                    },
                    {
                        "type": "tool_use",
                        "id": "read",
                        "name": "Read",
                        "input": {"file_path": "/tmp/other.output"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "start",
                        "content": "Output is being written to: /tmp/actual.output.",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "read",
                        "content": "[exited with code 0]",
                    },
                ]
            },
        },
    ]
    with pytest.raises(AssertionError):
        evidence.claude_background_completion(events, "helper complete", {})


def background_fixture():
    import json

    state = {"session": {"id": "session"}, "delegations": {"live-evaluator": {
        "assignment": json.dumps({"candidate_ref": "candidate"}),
        "result": {"outcome_ref": "outcome"}}}}
    output = json.dumps({"premature_completion_rejected": "AdaptiveControlAuthorityNotFound"})
    output += "\n" + json.dumps({"status": "completed", "independent_authority": True,
        "decision": "complete", "candidate_ref": "candidate", "outcome_ref": "outcome",
        "session_id": "session"})
    events = [
        {"type": "assistant", "session_id": "session", "message": {"content": [
            {"type": "tool_use", "id": "start", "name": "Bash",
             "input": {"command": "helper complete", "run_in_background": True}}]}},
        {"type": "system", "subtype": "task_started", "session_id": "session",
         "task_id": "task", "tool_use_id": "start", "task_type": "local_bash",
         "is_backgrounded": True},
        {"type": "assistant", "session_id": "session", "message": {"content": [
            {"type": "tool_use", "id": "retrieve", "name": "TaskOutput",
             "input": {"task_id": "task", "block": True}}]}},
        {"type": "user", "session_id": "session", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "retrieve", "content": output}]},
         "tool_use_result": {"retrieval_status": "success", "task": {
             "task_id": "task", "task_type": "local_bash", "status": "completed",
             "exitCode": 0, "output": output}}},
    ]
    return events, state


def test_background_completion_uses_native_task_exit_and_output():
    events, state = background_fixture()
    result = evidence.claude_background_completion(events, "helper complete", state)
    assert result["exit_code"] == 0
    assert result["task_id"] == "task"


@pytest.mark.parametrize("corruption", ["read-file", "task", "session", "failed", "no-exit", "order"])
def test_forged_background_output_cannot_replace_native_task_result(corruption):
    events, state = background_fixture()
    task = events[-1]["tool_use_result"]["task"]
    if corruption == "read-file":
        events[2]["message"]["content"][0]["name"] = "Read"
    elif corruption == "task":
        task["task_id"] = "unrelated"
    elif corruption == "session":
        events[-1]["session_id"] = "unrelated"
    elif corruption == "failed":
        task["exitCode"] = 7
    elif corruption == "no-exit":
        del task["exitCode"]
    else:
        events = [events[-1], *events[:-1]]
    with pytest.raises(AssertionError):
        evidence.claude_background_completion(events, "helper complete", state)


def test_checkpoint_stop_requires_actual_same_session_save_and_successful_retry():
    import json

    def hook(status, text=""):
        return {
            "method": "hook/completed",
            "params": {
                "threadId": "thread",
                "turnId": "turn",
                "run": {
                    "eventName": "stop",
                    "status": status,
                    "entries": [{"kind": "feedback", "text": text}],
                },
            },
        }

    gate = hook("blocked", "Neurath needs a durable handoff before this turn ends.")
    saved = item(
        "commandExecution",
        command=".neurath/run memory checkpoint --summary done",
        exitCode=0,
        aggregatedOutput=json.dumps(
            {
                "status": "saved",
                "host": "codex",
                "session": "thread",
                "authority": "agent-report",
                "id": "a" * 64,
            }
        ),
    )
    with pytest.raises(AssertionError):
        evidence.codex_turn([gate, ending()], "thread", "turn", checkpoint=True)
    with pytest.raises(AssertionError):
        evidence.codex_turn([gate, saved, ending()], "thread", "turn", checkpoint=True)
    assert (
        evidence.codex_turn(
            [gate, saved, hook("completed"), ending()], "thread", "turn", checkpoint=True
        )["checkpoints"]
        == 1
    )
    saved["params"]["item"]["aggregatedOutput"] = json.dumps(
        {
            "status": "saved",
            "host": "codex",
            "session": "other",
            "authority": "agent-report",
            "id": "a" * 64,
        }
    )
    with pytest.raises(AssertionError):
        evidence.codex_turn(
            [gate, saved, hook("completed"), ending()], "thread", "turn", checkpoint=True
        )
    saved["params"]["item"]["aggregatedOutput"] = None
    with pytest.raises(AssertionError):
        evidence.codex_turn(
            [gate, saved, hook("completed"), ending()], "thread", "turn", checkpoint=True
        )


def mcp_checkpoint_events():
    def hook(status, text=""):
        return {"method": "hook/completed", "params": {"threadId": "thread", "turnId": "turn",
            "run": {"eventName": "stop", "status": status,
                    "entries": [{"kind": "feedback", "text": text}]}}}
    return [hook("blocked", "Neurath needs a durable handoff before this turn ends."),
        item("mcpToolCall", server="neurath_collaboration", tool="memory_checkpoint",
             status="completed", error=None, result={"structuredContent": {
                 "ok": True, "operation": "memory_checkpoint", "result": {
                     "status": "saved", "host": "codex", "session": "thread",
                     "authority": "agent-report", "id": "a" * 64}}}),
        hook("completed"), ending()]


def test_checkpoint_stop_accepts_actual_named_mcp_save():
    assert evidence.codex_turn(mcp_checkpoint_events(), "thread", "turn", checkpoint=True)["checkpoints"] == 1


@pytest.mark.parametrize("invalid", ["server", "tool", "status", "error", "isError", "ok", "operation",
    "session", "host", "authority", "id", "receipt-type", "missing-result", "other-turn", "before-gate", "no-retry"])
def test_checkpoint_stop_rejects_wrong_or_failed_mcp_receipts(invalid):
    events = mcp_checkpoint_events()
    call = events[1]["params"]["item"]
    value = call["result"]["structuredContent"]
    if invalid in {"server", "tool", "status", "error"}:
        call[invalid] = "wrong"
    elif invalid == "isError":
        call["result"]["isError"] = True
    elif invalid == "ok":
        value["ok"] = False
    elif invalid == "operation":
        value["operation"] = "other"
    elif invalid in {"session", "host", "authority", "id"}:
        value["result"][invalid] = "z" * 64 if invalid == "id" else "wrong"
    elif invalid == "receipt-type":
        value["result"] = []
    elif invalid == "missing-result":
        del call["result"]
    elif invalid == "other-turn":
        events[1]["params"]["turnId"] = "other"
    elif invalid == "before-gate":
        events[0], events[1] = events[1], events[0]
    else:
        del events[2]
    with pytest.raises(AssertionError):
        evidence.codex_turn(events, "thread", "turn", checkpoint=True)
