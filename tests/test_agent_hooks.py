"""Exercise real hook routing for independent peer sessions and resume delivery."""

import json
import subprocess

import pytest

from neurath.agents.store import AgentIdentity, MessageStore
from neurath.hosts.hooks import hook
from neurath.install.transaction import apply_plan, make_plan


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    from neurath.hosts import identity

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    storage = tmp_path / "host-storage"
    storage.mkdir()
    monkeypatch.setattr(identity, "host_storage", lambda host, env: storage)

    def invoke(host, session, event, **fields):
        transcript = storage / f"{session}.jsonl"
        transcript.touch()
        return hook(
            tmp_path,
            host,
            json.dumps(
                {
                    "session_id": session,
                    "cwd": str(tmp_path),
                    "transcript_path": str(transcript),
                    "hook_event_name": event,
                    **fields,
                }
            ),
            {},
        )

    for host, session in (("codex", "api"), ("claude-code", "ui")):
        assert invoke(host, session, "SessionStart", source="startup")[0] == 0
        assert (
            invoke(host, session, "UserPromptSubmit", prompt=session, turn_id=session + "-turn")[0]
            == 0
        )
    return tmp_path, invoke


def test_message_enters_recipient_hook_without_becoming_user_authority(sessions):
    root, invoke = sessions
    store = MessageStore(root)
    assert {p["address"] for p in store.discover()} == {"codex:api", "claude-code:ui"}
    message = store.send("codex:api", "claude-code:ui", "Check the API schema", key="schema")
    code, output, diagnostic = invoke(
        "claude-code", "ui", "PostToolUse", tool_name="Read", tool_use_id="read-1", tool_input={}
    )
    assert code == 0, diagnostic
    assert "peer-request" in json.dumps(output)
    assert message["id"] in json.dumps(output)
    assert store.message("codex:api", message["id"])["status"] == "queued"
    state = json.loads((root / ".neurath/local/runs/ui/.process-state.json").read_text())
    assert not state["delegations"]
    assert not state["workflows"]


def test_paused_session_receives_pending_message_on_resume(sessions):
    root, invoke = sessions
    assert invoke("claude-code", "ui", "SessionEnd")[0] == 0
    store = MessageStore(root)
    assert store.discover("claude-code:ui")[0]["status"] == "paused"
    sent = store.send("codex:api", "claude-code:ui", "Pending until resumed", key="resume")
    code, output, diagnostic = invoke("claude-code", "ui", "SessionStart", source="resume")
    assert code == 0, diagnostic
    assert sent["id"] in json.dumps(output)
    assert store.discover("claude-code:ui")[0]["status"] == "active"


def test_unregistered_protocol_session_is_not_a_peer(sessions):
    root, _ = sessions
    code, _, _ = hook(
        root,
        "codex",
        json.dumps(
            {
                "session_id": "protocol-only",
                "cwd": str(root),
                "hook_event_name": "SessionStart",
                "source": "startup",
            }
        ),
        {},
    )
    assert code == 0
    assert not MessageStore(root).discover("protocol-only")


def test_foreign_host_cannot_read_recipient_inbox(sessions):
    from neurath.agents.hooks import peer_event

    root, _ = sessions
    store = MessageStore(root)
    store.send("codex:api", "claude-code:ui", "Private peer message", key="private")
    output = peer_event(root, "codex", {"session_id": "ui", "hook_event_name": "PostToolUse"}, {})
    assert output == {}


def test_cli_does_not_accept_caller_selected_sender(sessions):
    from neurath.cli import main

    root, _ = sessions
    with pytest.raises(SystemExit):
        main(
            [
                "--root",
                str(root),
                "agent",
                "send",
                "--from",
                "codex:api",
                "--to",
                "claude-code:ui",
                "--message",
                "spoof",
                "--key",
                "spoof",
            ]
        )


def test_child_address_is_distinct_from_root():
    assert (
        AgentIdentity("codex", "same", "root").address
        != AgentIdentity("codex", "same", "child", is_root=False).address
    )


def test_peer_lifecycle_reports_error_and_disconnect_for_only_accepted_turn(sessions):
    from neurath.agents.hooks import native_turn
    from neurath.agents.lifecycle import TaskLifecycle

    root, invoke = sessions
    store = MessageStore(root)
    tasks = TaskLifecycle(store)
    worker = AgentIdentity("claude-code", "ui", "claude-code:session:ui")
    task = tasks.bind("codex:api", worker.address, key="work", transport="peer-assignment")
    tasks.accept(worker.address, task["id"], native_turn(root, worker))
    code, _, error = invoke("claude-code", "ui", "PostToolUseFailure",
                             tool_name="Read", tool_use_id="failed-read", tool_input={})
    assert code == 0, error
    assert tasks.read("codex:api", task["id"])["state"] == "error"
    assert invoke("claude-code", "ui", "SessionEnd")[0] == 0
    assert tasks.read("codex:api", task["id"])["state"] == "disconnected"
    assert invoke("claude-code", "ui", "SessionStart", source="resume")[0] == 0
    assert invoke("claude-code", "ui", "UserPromptSubmit", prompt="Unrelated work", turn_id="different")[0] == 0
    assert invoke("claude-code", "ui", "PermissionDenied", tool_name="Read",
                  tool_use_id="new-denial", tool_input={})[0] == 0
    assert tasks.read("codex:api", task["id"])["state"] == "disconnected"


def test_named_report_cannot_finish_an_unaccepted_or_unrelated_turn(sessions):
    from neurath.agents.lifecycle import TaskLifecycle
    from neurath.runtime.tasks import execute

    root, invoke = sessions
    tasks = TaskLifecycle(MessageStore(root))
    worker = AgentIdentity("claude-code", "ui", "claude-code:session:ui")
    task = tasks.bind("codex:api", worker.address, key="bound-turn", transport="peer-assignment")
    report = {"task_id": task["id"], "state": "completed", "key": "done"}
    with pytest.raises(ValueError, match="accepted native turn"):
        execute(root, "collaboration_report", report, identity=worker)
    execute(root, "collaboration_accept", {"task_id": task["id"]}, identity=worker)
    assert invoke("claude-code", "ui", "SessionEnd")[0] == 0
    assert invoke("claude-code", "ui", "SessionStart", source="resume")[0] == 0
    assert invoke("claude-code", "ui", "UserPromptSubmit", prompt="A different request", turn_id="other-turn")[0] == 0
    with pytest.raises(ValueError, match="accepted native turn"):
        execute(root, "collaboration_report", report, identity=worker)
    assert tasks.read("codex:api", task["id"])["state"] == "disconnected"


def test_newsroom_hooks_join_active_turns_and_push_only_titles(sessions):
    from neurath.agents.newsroom import Newsroom

    root, invoke = sessions
    room = Newsroom(MessageStore(root))
    article = room.publish("codex:api", title="재시도 중복 발견", body="EXPLICIT_BODY_ONLY", key="news")
    code, output, diagnostic = invoke("claude-code", "ui", "PostToolUse", tool_name="Read",
                                      tool_use_id="news-read", tool_input={})
    assert code == 0, diagnostic
    assert article["title"] in json.dumps(output, ensure_ascii=False)
    assert article["id"] in json.dumps(output)
    assert "EXPLICIT_BODY_ONLY" not in json.dumps(output)
    code, next_output, _ = invoke("claude-code", "ui", "PostToolUse", tool_name="Read",
                                  tool_use_id="next-read", tool_input={})
    assert article["title"] not in json.dumps(next_output, ensure_ascii=False)
    invoke("claude-code", "ui", "SessionEnd")
    with pytest.raises(ValueError, match="active"):
        room.read("claude-code:ui", article["id"])
    room.publish("codex:api", title="停止中の記事", body="NO_BACKLOG", key="offline")
    invoke("claude-code", "ui", "SessionStart", source="resume")
    assert "NO_BACKLOG" not in json.dumps(invoke("claude-code", "ui", "UserPromptSubmit",
                                                 prompt="Continue", turn_id="next-turn"))
    assert room.headlines("claude-code:ui") == []


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
def test_mcp_call_is_native_bound_and_cannot_change_request_or_sender(sessions, host, session):
    from neurath.agents.mcp import call_tool
    from neurath.agents.newsroom import Newsroom

    root, invoke = sessions
    inputs = {"argv": ["newsroom", "publish", "--title", "Native newsroom", "--body",
                        "MCP_BODY_ONLY", "--key", "mcp-publish"]}
    code, output, diagnostic = invoke(host, session, "PreToolUse",
                                      tool_name="mcp__neurath_collaboration__agent",
                                      tool_use_id="mcp-1", tool_input=inputs)
    assert code == 0, diagnostic
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    bound = output["hookSpecificOutput"]["updatedInput"]
    result = call_tool(root, bound)
    assert result["author"] == f"{host}:{session}"
    assert call_tool(root, bound) == result
    peer = "codex:api" if host == "claude-code" else "claude-code:ui"
    assert len(Newsroom(MessageStore(root)).headlines(peer)) == 1
    with pytest.raises(ValueError, match="request"):
        call_tool(root, {**bound, "argv": ["agent", "discover"]})
    with pytest.raises(ValueError, match="bound"):
        call_tool(root, inputs)
    invoke(host, session, "PostToolUse", tool_name="mcp__neurath_collaboration__agent",
           tool_use_id="mcp-1", tool_input=bound, tool_response={})
    with pytest.raises(ValueError, match="closed|expired"):
        call_tool(root, bound)


def test_newsroom_body_does_not_leak_into_automatic_project_memory(sessions):
    from neurath.memory.store import ProjectMemory

    root, invoke = sessions
    invoke("codex", "api", "PostToolUse", tool_name="exec_command", tool_use_id="publish-shell",
           tool_input={"command": ".neurath/run newsroom publish --title Title --body BODY_MUST_STAY_IN_NEWSROOM --key once"},
           exit_code=0)
    memory = ProjectMemory(root)
    assert "BODY_MUST_STAY_IN_NEWSROOM" not in json.dumps(memory.history("codex", "api"))


def test_mcp_closed_session_cannot_use_pending_native_call(sessions):
    from neurath.agents.mcp import call_tool

    root, invoke = sessions
    code, output, diagnostic = invoke("claude-code", "ui", "PreToolUse",
        tool_name="mcp__neurath_collaboration__agent", tool_use_id="pending",
        tool_input={"argv": ["newsroom", "headlines"]})
    assert code == 0, diagnostic
    bound = output["hookSpecificOutput"]["updatedInput"]
    invoke("claude-code", "ui", "SessionEnd")
    with pytest.raises(ValueError, match="active|closed"):
        call_tool(root, bound)


def test_newsroom_checks_native_disconnect_in_addition_to_registry(sessions):
    from neurath.agents.newsroom import Newsroom

    root, invoke = sessions
    store = MessageStore(root)
    # Simulate a missed newsroom retirement hook; native disconnect is still recorded.
    from unittest.mock import patch
    with patch("neurath.agents.hooks.peer_event", side_effect=RuntimeError("unavailable")):
        invoke("claude-code", "ui", "SessionEnd")
    room = Newsroom(store)
    assert store.discover("claude-code:ui")[0]["status"] == "active"
    with pytest.raises(ValueError, match="active"):
        room.publish("claude-code:ui", title="Stopped", body="no", key="stopped")
    room.publish("codex:api", title="Still active", body="yes", key="active")
    with store.connection() as db:
        assert not db.execute("SELECT * FROM newsroom_deliveries WHERE recipient='claude-code:ui'").fetchall()


@pytest.mark.parametrize("cached", [False, True])
def test_reconnect_never_revives_previous_process_tool_grants(sessions, cached):
    from neurath.agents.mcp import call_tool
    from neurath.agents.newsroom import Newsroom

    root, invoke = sessions
    article = Newsroom(MessageStore(root)).publish("codex:api", title="Private lookup",
        body="NO_RECONNECT_CACHE_BODY", key="cache")
    _, output, _ = invoke("claude-code", "ui", "PreToolUse",
        tool_name="mcp__neurath_collaboration__agent", tool_use_id="old-call",
        tool_input={"argv": ["newsroom", "read", article["id"]]})
    bound = output["hookSpecificOutput"]["updatedInput"]
    if cached:
        call_tool(root, bound)
    invoke("claude-code", "ui", "SessionEnd")
    invoke("claude-code", "ui", "SessionStart", source="resume")
    with pytest.raises(ValueError, match="closed|active"):
        call_tool(root, bound)
    invoke("claude-code", "ui", "UserPromptSubmit", prompt="ui", turn_id="ui-turn")
    with pytest.raises(ValueError, match="closed|active"):
        call_tool(root, bound)


def test_active_compaction_keeps_newsroom_and_native_communication_available(sessions):
    from neurath.agents.mcp import call_tool
    from neurath.agents.newsroom import Newsroom

    root, invoke = sessions
    room = Newsroom(MessageStore(root))
    article = room.publish("codex:api", title="Before compact", body="ACTIVE_COMPACT", key="compact")
    assert invoke("claude-code", "ui", "SessionStart", source="compact")[0] == 0
    code, output, diagnostic = invoke("claude-code", "ui", "PreToolUse",
        tool_name="mcp__neurath_collaboration__agent", tool_use_id="after-compact",
        tool_input={"argv": ["newsroom", "read", article["id"]]})
    assert code == 0, diagnostic
    assert call_tool(root, output["hookSpecificOutput"]["updatedInput"])["body"] == "ACTIVE_COMPACT"


@pytest.mark.parametrize("source,expected", [("compact", True), ("resume", False)])
def test_upgrade_distinguishes_legacy_compact_from_unaccepted_resume(sessions, source, expected):
    from neurath.hosts.identity import active_connection, journal

    root, invoke = sessions
    assert invoke("claude-code", "ui", "SessionStart", source=source)[0] == 0
    with journal(root, "ui") as data:
        data.pop("start_source")
        data.pop("connected")
    assert active_connection(root, "ui") is expected


def test_upgrade_redacts_legacy_newsroom_events_before_transcript_replay(sessions):
    from neurath.memory.store import MemoryConflict, ProjectMemory, canonical

    root, _ = sessions
    memory = ProjectMemory(root)
    command = ".neurath/run newsroom publish --title Title --body LEGACY_BODY --key once"
    metadata = {"command": command, "exit_code": 0}
    event = memory.record("codex", "api", "legacy-publish", "tool", command, metadata)
    with memory.connection() as db:
        db.execute("UPDATE events SET content=?,metadata=? WHERE id=?",
                   (command, canonical(metadata), event))
    upgraded = ProjectMemory(root)
    assert "LEGACY_BODY" not in json.dumps(upgraded.history("codex", "api"))
    assert upgraded.record("codex", "api", "legacy-publish", "tool", command, metadata) == event
    with pytest.raises(MemoryConflict):
        upgraded.record("codex", "api", "legacy-publish", "tool", "different command")
