"""제품 CLI와 실제 SQLite를 연결하여 사용자가 내부 상태를 관리하지 않는 흐름을 검증한다."""

import asyncio
import json
import sqlite3
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from typer import Typer
from typer.testing import CliRunner

from neurath.infrastructure.database import sqlite_url
from tests.support.application import request_application
from tests.support.hook_cli import HookCliClient


async def invoke(database, arguments, content="", *, succeeds=True):
    async with request_application(sqlite_url(database, "rw")) as application:
        response = await asyncio.to_thread(
            CliRunner().invoke, application.container.get(Typer), arguments, input=content
        )
    if succeeds:
        assert response.exit_code == 0, (response.output, response.exception)
        return json.loads(response.stdout)
    assert response.exit_code != 0
    return response


@pytest.fixture
async def host(database, tmp_path, monkeypatch):
    directory = tmp_path / "workspace"
    directory.mkdir()
    monkeypatch.chdir(directory)
    monkeypatch.setenv("NEURATH_SESSION_ID", "native-test-session")
    monkeypatch.setenv("NEURATH_PROVIDER", "codex")
    client = HookCliClient("codex", database)
    payload = {
        "session_id": "native-test-session",
        "cwd": str(directory),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Create the requested artifact, verify its content, and preserve unfinished work.",
    }
    assert await client.handle(payload) == {}
    return directory, client, payload


async def create(database, *, start=True):
    return await invoke(
        database,
        [
            "task",
            "create",
            "--title",
            "Check requested artifact",
            "--result",
            "Verified file",
            *(["--start"] if start else []),
        ],
    )


async def test_original_prompt_to_agent_workflow_result_and_stop(database, host):
    directory, client, payload = host
    initial = await invoke(database, ["context", "show"])
    assert initial["host"]["turn"].startswith("observed:")
    sources = await invoke(database, ["context", "show", "--section", "sources"])
    assert sources[0]["body"] == payload["prompt"]
    task = await create(database)
    assert task["source_id"] == sources[0]["id"]
    flow = await invoke(database, ["workflow", "start", "--task-id", task["id"], "--skill", "qa"])
    assert flow["current"]["arguments"] == []
    assert (await client.handle(dict(payload, hook_event_name="Stop")))["decision"] == "block"
    artifact = directory / "result.txt"
    artifact.write_text("verified artifact\n")
    assert artifact.read_text() == "verified artifact\n"
    for number in range(3):
        flow = await invoke(
            database,
            [
                "workflow",
                "report",
                "--run-id",
                flow["id"],
                "--summary",
                f"Actual fixture check {number}",
                "--reference",
                str(artifact),
                "--check",
                "done",
            ],
        )
    assert flow["steps_complete"]
    reported = await invoke(
        database,
        [
            "task",
            "report",
            "--task-id",
            task["id"],
            "--summary",
            "File content verified",
            "--reference",
            str(artifact),
            "--exit-code",
            "0",
        ],
    )
    assert reported["status"] == "succeeded"
    assert await client.handle(dict(payload, hook_event_name="Stop")) == {}
    assert artifact.read_text() == "verified artifact\n"


async def test_context_memory_and_compaction_share_current_native_scope(database, host):
    _, client, payload = host
    task = await create(database)
    change = [
        {
            "op": "set",
            "key": "constraint",
            "value": "Preserve original data",
            "kind": "fact",
            "references": ["request:original"],
        }
    ]
    saved = await invoke(database, ["memory", "update", "--changes", json.dumps(change)])
    assert saved["revision"] == 1
    restored = await client.handle(dict(payload, hook_event_name="SessionStart", source="compact"))
    body = restored["hookSpecificOutput"]["additionalContext"]
    assert "Preserve original data" in body and task["id"] in body
    current = await invoke(database, ["context", "show"])
    assert current["facts"][0]["facts"][0]["value"] == "Preserve original data"
    assert (await invoke(database, ["context", "show", "--section", "collaboration"]))["peers"]
    assert (await invoke(database, ["context", "show", "--section", "memory"]))[
        "applied_lessons"
    ] == []
    checkpoint = await invoke(
        database,
        [
            "memory",
            "checkpoint",
            "--content",
            "Actual fixture report",
            "--reference",
            "fixture:verified",
        ],
    )
    found = await invoke(database, ["memory", "search", "--text", "fixture"])
    assert checkpoint["id"] in found["memory_ids"]
    content = await invoke(database, ["memory", "read", "--memory-id", checkpoint["id"]])
    assert content["content"] == "Actual fixture report"


async def test_monitor_wait_callback_change_receipt_and_resume_are_one_flow(database, host):
    directory, client, payload = host
    task = await create(database)
    target = directory / "job.jsonl"
    target.write_text('{"state":"running"}\n')
    waiting = await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "wait",
            "--task-id",
            task["id"],
            "--target",
            str(target),
            "--condition",
            "state done",
            "--resume-scope",
            "verify result",
            "--reason",
            "observed running",
            "--monitor",
            "output",
            "--poll-budget",
            "4",
        ],
    )
    assert waiting["status"] == "waiting"
    callback = dict(payload, prompt=waiting["monitors"][0]["callback"])
    assert (await client.handle(dict(payload, hook_event_name="Stop")))["continue"] is False
    assert (await client.handle(callback))["continue"] is False
    assert (await client.handle(callback))["continue"] is False
    assert len(await invoke(database, ["context", "show", "--section", "sources"])) == 1
    target.write_text('{"state":"running"}\n{"state":"done"}\n')
    changed = await client.handle(callback)
    assert "state done" in changed["hookSpecificOutput"]["additionalContext"]
    current = await invoke(database, ["context", "show"])
    monitor = current["tasks"][0]["monitors"][0]
    assert len(monitor["events"]) == 1
    assert monitor["events"][0]["notice_status"] == "submitted"
    assert not monitor["events"][0]["acknowledged"]
    assert (await client.handle(callback))["continue"] is False
    resumed = await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "resume",
            "--task-id",
            task["id"],
            "--reason",
            "observed complete result",
            "--monitor-event",
            "1",
        ],
    )
    assert resumed["status"] == "active"
    assert resumed["monitors"][0]["events"][0]["resolved"]
    assert (await client.handle(dict(payload, hook_event_name="Stop")))["decision"] == "block"


async def test_invalid_monitor_request_rolls_back_wait_and_never_observes(
    database, host, monkeypatch
):
    from neurath.infrastructure.services.monitor_observer import SubprocessMonitorObserverService

    task = await create(database)
    before = database.read_bytes()

    def forbidden(*args):
        raise AssertionError("invalid input must not observe external state")

    monkeypatch.setattr(SubprocessMonitorObserverService, "observe", forbidden)
    await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "wait",
            "--task-id",
            task["id"],
            "--target",
            "relative",
            "--condition",
            "done",
            "--resume-scope",
            "continue",
            "--reason",
            "waiting",
            "--monitor",
            "output",
        ],
        succeeds=False,
    )
    assert database.read_bytes() == before


async def test_real_cli_read_does_not_reserve_database_writer(database, host):
    acquired = []

    def inspect_lock(connection, cursor, statement, parameters, context, executemany):
        if "SELECT" not in statement or "core_memories" not in statement:
            return
        with sqlite3.connect(database, timeout=0.05) as contender:
            contender.execute("BEGIN IMMEDIATE")
            acquired.append(True)
            contender.rollback()

    before = database.read_bytes()
    event.listen(Engine, "after_cursor_execute", inspect_lock)
    try:
        assert (await invoke(database, ["memory", "search"]))["memory_ids"] == []
    finally:
        event.remove(Engine, "after_cursor_execute", inspect_lock)
    assert acquired and database.read_bytes() == before


async def test_newsroom_uses_current_host_without_peer_id(database, host):
    article = await invoke(
        database,
        [
            "newsroom",
            "publish",
            "--title",
            "Finding",
            "--body",
            "Observed result",
            "--reference",
            "fixture:result",
        ],
    )
    listed = await invoke(database, ["newsroom", "list"])
    assert listed[0]["id"] == article["id"]
    read = await invoke(
        database, ["newsroom", "read", "--article-id", article["id"], "--revision-number", "1"]
    )
    assert read["content"]["body"] == "Observed result"
    comment = await invoke(
        database,
        [
            "newsroom",
            "comment",
            "--article-id",
            article["id"],
            "--revision-number",
            "1",
            "--body",
            "Checked actual result",
        ],
    )
    assert comment["body"] == "Checked actual result"


@pytest.mark.parametrize(
    "arguments",
    [
        ["task", "create", "--title", "", "--result", "x"],
        ["task", "update", "--action", "start"],
        ["task", "report", "--summary", "x", "--reference", "y"],
        [
            "collaboration",
            "delegate",
            "--task-id",
            "00000000-0000-0000-0000-000000000001",
            "--scope",
            "x",
        ],
        ["collaboration", "send", "--recipient", "absent", "--title", "x", "--body", ""],
    ],
)
async def test_invalid_public_requests_leave_original_state_unchanged(database, host, arguments):
    before = database.read_bytes()
    await invoke(database, arguments, succeeds=False)
    assert database.read_bytes() == before


async def test_repeated_original_prompt_is_not_merged_without_native_turn_identifier(
    database, host
):
    _, client, payload = host
    before = await invoke(database, ["context", "show"])
    await client.handle(payload)
    after = await invoke(database, ["context", "show"])
    assert after["host"]["turn"] != before["host"]["turn"]
    assert len(after["source_ids"]) == 2
    assert UUID(after["source_ids"][0])


async def prepare_review(database, host, *, reflection=False):
    directory, client, payload = host
    artifact = directory / "reviewed.txt"
    artifact.write_text("actual result under test")
    task = await create(database)
    flow = await invoke(
        database, ["workflow", "start", "--task-id", task["id"], "--skill", "implement-spec"]
    )
    for number in range(3):
        flow = await invoke(
            database,
            [
                "workflow",
                "report",
                "--run-id",
                flow["id"],
                "--summary",
                f"Verified step {number}",
                "--reference",
                str(artifact),
                "--check",
                "done",
            ],
        )
    if reflection:
        definition = [
            {
                "key": "reflection",
                "purpose": "Inspect actual failure and scoped improvement",
                "evaluation": {
                    "kind": "reflection",
                    "artifacts": [str(artifact)],
                    "verification": [str(artifact)],
                },
            }
        ]
        await invoke(
            database,
            [
                "workflow",
                "revise",
                "--run-id",
                flow["id"],
                "--reason",
                "User requested reflection",
                "--definition",
                json.dumps(definition),
            ],
        )
        await invoke(
            database,
            [
                "workflow",
                "revise",
                "--run-id",
                flow["id"],
                "--reason",
                "User requested reflection",
                "--reflection",
                "requested",
            ],
        )
    await client.handle(dict(payload, hook_event_name="SubagentStart", agent_id="native-reviewer"))
    return task, flow, artifact


async def delegate_review(database, task, artifact):
    return await invoke(
        database,
        [
            "collaboration",
            "delegate",
            "--task-id",
            task["id"],
            "--scope",
            "Compare original request and actual output",
            "--role",
            "reviewer",
            "--recipient",
            "native-reviewer",
            "--artifact",
            str(artifact),
            "--verification",
            str(artifact),
        ],
    )


async def finish_review(database, assignment, artifact, monkeypatch):
    monkeypatch.setenv("NEURATH_SESSION_ID", "native-reviewer")
    message = await invoke(
        database, ["collaboration", "read", "--message-id", assignment["message_id"]]
    )
    assert "Create the requested artifact" in message["body"]
    await invoke(
        database, ["task", "update", "--action", "accept", "--delegation-id", assignment["id"]]
    )
    report = await invoke(
        database,
        [
            "task",
            "report",
            "--delegation-id",
            assignment["id"],
            "--summary",
            "Independent fixture report after inspecting actual file",
            "--reference",
            str(artifact),
        ],
    )
    assert report["status"] == "completed"
    monkeypatch.setenv("NEURATH_SESSION_ID", "native-test-session")
    observed = await invoke(
        database, ["collaboration", "observe", "--delegation-id", assignment["id"]]
    )
    assert observed["report"]["summary"].startswith("Independent fixture report")


async def test_native_child_review_connects_original_report_to_parent_completion(
    database, host, monkeypatch
):
    task, flow, artifact = await prepare_review(database, host)
    await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "not a review",
            "--reference",
            str(artifact),
        ],
        succeeds=False,
    )
    assignment = await delegate_review(database, task, artifact)
    repeated = await delegate_review(database, task, artifact)
    assert assignment["id"] == repeated["id"]
    await finish_review(database, assignment, artifact, monkeypatch)
    accepted = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Original requirement and output matched",
            "--reference",
            str(artifact),
            "--accepted",
        ],
    )
    assert accepted["steps_complete"]
    await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "duplicate",
            "--reference",
            str(artifact),
        ],
        succeeds=False,
    )
    final = await invoke(
        database,
        [
            "task",
            "report",
            "--task-id",
            task["id"],
            "--summary",
            "Verified result",
            "--reference",
            str(artifact),
        ],
    )
    assert final["status"] == "succeeded"


async def test_requested_reflection_cli_applies_and_recalls_only_validated_lesson(
    database, host, monkeypatch
):
    task, flow, artifact = await prepare_review(database, host, reflection=True)
    assignment = await delegate_review(database, task, artifact)
    await finish_review(database, assignment, artifact, monkeypatch)
    await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Scoped improvement supported",
            "--reference",
            str(artifact),
            "--accepted",
        ],
    )
    lesson = await invoke(
        database,
        [
            "memory",
            "propose-lesson",
            "--run-id",
            flow["id"],
            "--phase",
            "reflection",
            "--content",
            "-",
            "--reference",
            str(artifact),
        ],
        "Use the verified narrow correction",
    )
    await invoke(
        database,
        [
            "memory",
            "observe-lesson",
            "--memory-id",
            lesson["id"],
            "--state",
            "validated",
            "--reason",
            "Original failure and healthy control checked",
            "--reference",
            str(artifact),
            "--failure-case",
            "failure reproduced and fixed",
            "--normal-case",
            "normal control unchanged",
        ],
    )
    await invoke(
        database,
        [
            "memory",
            "observe-lesson",
            "--memory-id",
            lesson["id"],
            "--state",
            "applied",
            "--reason",
            "Applied to fixture rule and verified",
            "--reference",
            str(artifact),
            "--effective",
        ],
    )
    restored = await host[1].handle(dict(host[2], hook_event_name="SessionStart", source="compact"))
    assert (
        "Use the verified narrow correction" in restored["hookSpecificOutput"]["additionalContext"]
    )
    memories = await invoke(database, ["context", "show", "--section", "memory"])
    assert lesson["id"] in memories["applied_lessons"]
    await invoke(
        database,
        [
            "memory",
            "observe-lesson",
            "--memory-id",
            lesson["id"],
            "--state",
            "withdrawn",
            "--reason",
            "Later evidence refuted it",
            "--reference",
            str(artifact),
            "--ineffective",
        ],
    )
    restored = await host[1].handle(dict(host[2], hook_event_name="SessionStart", source="compact"))
    assert "Use the verified narrow correction" not in restored.get("hookSpecificOutput", {}).get(
        "additionalContext", ""
    )


async def test_peer_message_delivery_body_read_and_duplicate_retry(database, host, monkeypatch):
    _, client, payload = host
    receiver = HookCliClient("claude", database)
    await receiver.handle(
        dict(payload, session_id="other-native", hook_event_name="SessionStart", source="startup")
    )
    sent = await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "other-native",
            "--title",
            "Selected finding",
            "--body",
            "-",
            "--key",
            "original-message",
        ],
        "original\nbody",
    )
    again = await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "other-native",
            "--title",
            "Selected finding",
            "--body",
            "original\nbody",
            "--key",
            "original-message",
        ],
    )
    assert again["id"] == sent["id"]
    await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "other-native",
            "--title",
            "Selected finding",
            "--body",
            "changed",
            "--key",
            "original-message",
        ],
        succeeds=False,
    )
    automatic = await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "other-native",
            "--title",
            "Another finding",
            "--body",
            "selected body",
        ],
    )
    assert automatic["id"] != sent["id"]
    headline = await receiver.handle(
        dict(
            payload,
            session_id="other-native",
            hook_event_name="PreToolUse",
            tool_name="Read",
            tool_use_id="read-1",
        )
    )
    assert sent["id"] in headline["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setenv("NEURATH_SESSION_ID", "other-native")
    monkeypatch.setenv("NEURATH_PROVIDER", "claude")
    read = await invoke(database, ["collaboration", "read", "--message-id", sent["id"]])
    assert read["body"] == "original\nbody"
    inbox = await invoke(database, ["context", "show", "--section", "collaboration"])
    assert next(item for item in inbox["inbox"] if item["id"] == sent["id"])["read"]


async def test_task_correction_cancellation_and_method_revision_use_observed_source(database, host):
    _, client, payload = host
    sources = await invoke(database, ["context", "show", "--section", "sources"])
    task = await invoke(
        database,
        [
            "task",
            "create",
            "--title",
            "Original",
            "--result",
            "Output",
            "--source-id",
            sources[0]["id"],
        ],
    )
    assert task["status"] == "pending"
    await invoke(
        database,
        [
            "task",
            "report",
            "--task-id",
            task["id"],
            "--summary",
            "unstarted",
            "--reference",
            "fixture",
        ],
        succeeds=False,
    )
    await invoke(database, ["task", "update", "--task-id", task["id"], "--action", "start"])
    flow = await invoke(database, ["workflow", "start", "--task-id", task["id"], "--skill", "qa"])
    await invoke(
        database,
        ["workflow", "revise", "--run-id", flow["id"], "--reason", "invalid combination"],
        succeeds=False,
    )
    await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reason",
            "invalid shape",
            "--definition",
            "{}",
        ],
        succeeds=False,
    )
    revised = [{"key": "check", "purpose": "Different valid method"}]
    result = await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reason",
            "Original goal unchanged",
            "--definition",
            "-",
        ],
        json.dumps(revised),
    )
    assert result["current"]["purpose"] == "Different valid method"
    await client.handle(dict(payload, prompt="Correct the result format only"))
    corrected = await invoke(
        database,
        [
            "task",
            "update",
            "--task-id",
            task["id"],
            "--action",
            "correct",
            "--result",
            "Corrected output format",
        ],
    )
    assert corrected["source_id"] != task["source_id"]
    cancelled = await invoke(
        database,
        [
            "task",
            "update",
            "--task-id",
            task["id"],
            "--action",
            "cancel",
            "--reason",
            "The user cancelled this work",
            "--source-id",
            corrected["source_id"],
        ],
    )
    assert cancelled["status"] == "invalidated"


async def test_newsroom_default_connection_and_opt_out_preserve_other_topics(database, host):
    initial = await invoke(database, ["context", "show", "--section", "collaboration"])
    assert "newsroom" in initial["peers"][0]["subscriptions"]
    assert (await invoke(database, ["newsroom", "subscribe", "--disabled"]))["topics"] == []
    assert (await invoke(database, ["newsroom", "subscribe", "--enabled"]))["topics"] == [
        "newsroom"
    ]


async def test_withdrawing_running_reflection_releases_wait_and_does_not_gate_original_work(
    database, host
):
    task, flow, artifact = await prepare_review(database, host, reflection=True)
    assignment = await delegate_review(database, task, artifact)
    await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reason",
            "User withdrew the optional reflection",
            "--reflection",
            "declined",
        ],
    )
    original = await invoke(
        database, ["collaboration", "observe", "--delegation-id", assignment["id"]]
    )
    assert original["status"] == "stop_requested"
    artifact.write_text("original work remains valid; reflection was withdrawn")
    result = await invoke(
        database,
        [
            "task",
            "report",
            "--task-id",
            task["id"],
            "--summary",
            "Original requested work verified independently of cancelled reflection",
            "--reference",
            str(artifact),
        ],
    )
    assert result["status"] == "succeeded"


async def test_provider_review_validates_before_dispatch_and_observes_same_run(
    database, host, monkeypatch
):
    from neurath.application.ports.services.provider import (
        ProviderCapabilities,
        ProviderObservation,
    )
    from neurath.domain.enums.provider_kind import ProviderKind
    from neurath.domain.enums.provider_status import ProviderStatus
    from neurath.infrastructure.services.provider import SubprocessProviderService

    task, flow, artifact = await prepare_review(database, host)
    starts, observations = [], []

    def capabilities(self, provider):
        return ProviderCapabilities(
            provider=provider, models=("fixture-model",), policies=("read-only",)
        )

    def start(self, uid, plan, prompt):
        starts.append((uid, prompt))
        return ProviderObservation(reference="fixture:" + str(uid), status=ProviderStatus.RUNNING)

    def observe(self, uid):
        observations.append(uid)
        return ProviderObservation(
            reference="fixture:" + str(uid),
            status=ProviderStatus.RUNNING if len(observations) == 1 else ProviderStatus.COMPLETED,
            native_session_id="fixture-provider",
            output="actual fixture output",
        )

    monkeypatch.setattr(SubprocessProviderService, "discover", capabilities)
    monkeypatch.setattr(SubprocessProviderService, "start", start)
    monkeypatch.setattr(SubprocessProviderService, "observe", observe)
    base = [
        "collaboration",
        "delegate",
        "--task-id",
        task["id"],
        "--scope",
        "Read actual candidate",
        "--role",
        "reviewer",
        "--provider",
        ProviderKind.CODEX.value,
        "--policy",
        "read-only",
        "--artifact",
        str(artifact),
        "--verification",
        str(artifact),
    ]
    before = database.read_bytes()
    await invoke(database, [*base, "--model", "unsupported"], succeeds=False)
    assert before == database.read_bytes() and starts == []
    assignment = await invoke(database, [*base, "--model", "fixture-model"])
    assert len(starts) == 1 and "Create the requested artifact" in starts[0][1]
    result = await invoke(
        database, ["collaboration", "observe", "--delegation-id", assignment["id"], "--wait", "1"]
    )
    assert (
        result["provider_status"] == "completed"
        and result["provider_output"] == "actual fixture output"
    )
    assert len(starts) == 1 and len(observations) >= 2


async def test_regular_peer_assignment_and_missing_recipient_are_not_new_sessions(database, host):
    _, _, payload = host
    receiver = HookCliClient("claude", database)
    await receiver.handle(
        dict(payload, session_id="peer-session", hook_event_name="SessionStart", source="startup")
    )
    task = await create(database)
    before = database.read_bytes()
    await invoke(
        database,
        [
            "collaboration",
            "delegate",
            "--task-id",
            task["id"],
            "--recipient",
            "not-observed",
            "--scope",
            "existing work",
        ],
        succeeds=False,
    )
    assert before == database.read_bytes()
    assigned = await invoke(
        database,
        [
            "collaboration",
            "delegate",
            "--task-id",
            task["id"],
            "--recipient",
            "peer-session",
            "--scope",
            "existing work",
        ],
    )
    observed = await invoke(
        database, ["collaboration", "observe", "--delegation-id", assigned["id"], "--wait", "0.01"]
    )
    assert observed["status"] == "assigned" and observed["report"] is None
    assert (
        len((await invoke(database, ["context", "show", "--section", "collaboration"]))["peers"])
        == 2
    )


async def test_missing_original_and_ambiguous_scope_require_observation_not_fabrication(
    database, host, monkeypatch
):
    _, _, payload = host
    sources = await invoke(database, ["context", "show", "--section", "sources"])
    client = HookCliClient("codex", database)
    await client.handle(
        dict(payload, session_id="second-session", hook_event_name="SessionStart", source="startup")
    )
    monkeypatch.delenv("NEURATH_SESSION_ID")
    await invoke(database, ["context", "show"], succeeds=False)
    monkeypatch.setenv("NEURATH_SESSION_ID", "second-session")
    await invoke(
        database,
        ["task", "create", "--title", "missing instruction", "--result", "result"],
        succeeds=False,
    )
    task = await invoke(
        database,
        [
            "task",
            "create",
            "--title",
            "shared instruction",
            "--result",
            "result",
            "--source-id",
            sources[0]["id"],
        ],
    )
    await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "correct",
            "--task-id",
            task["id"],
            "--result",
            "unattributed change",
        ],
        succeeds=False,
    )
    assert (await invoke(database, ["context", "show"]))["tasks"][0]["required_result"] == "result"
    assert (await invoke(database, ["session", "preview"]))["session_id"]
    await client.handle(
        dict(payload, session_id="second-session", prompt="Resume the current unfinished work")
    )
    assert await invoke(database, ["session", "resume"])


async def test_unknown_skill_and_registered_agent_attempt_are_not_programs(database, host):
    from neurath.application.usecases.get_workflow import GetWorkflowQuery, GetWorkflowUseCase
    from neurath.application.usecases.prepare_phase import PreparePhaseCommand, PreparePhaseUseCase
    from neurath.application.usecases.resolve_session_context import (
        ResolveSessionContextQuery,
        ResolveSessionContextUseCase,
    )
    from tests.support.requests import run

    task = await create(database)
    await invoke(
        database,
        ["workflow", "start", "--task-id", task["id"], "--skill", "not-installed"],
        succeeds=False,
    )
    flow = await invoke(database, ["workflow", "start", "--task-id", task["id"], "--skill", "qa"])
    scope = await run(
        ResolveSessionContextUseCase, ResolveSessionContextQuery(), database_path=database
    )
    current = (
        await run(
            GetWorkflowUseCase,
            GetWorkflowQuery(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                run_id=UUID(flow["id"]),
            ),
            database_path=database,
        )
    ).run
    prepared = await run(
        PreparePhaseUseCase,
        PreparePhaseCommand(
            project_id=current.project_id,
            session_id=current.session_id,
            run_id=current.uid,
            expected_revision=current.revision,
        ),
        database_path=database,
    )
    assert prepared.run.attempts[-1].result is None
    current.request_execution(current.begin(), fresh=True)
    assert current.events == []
    result = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Actual agent reasoning verified",
            "--reference",
            "fixture:source",
            "--check",
            "done",
        ],
    )
    assert result["current"]["key"] == "step-2"


async def test_monitor_current_context_and_error_callback_are_bounded(database, host):
    directory, client, payload = host
    task = await create(database)
    target = directory / "missing-job.jsonl"
    waiting = await invoke(
        database,
        [
            "task",
            "update",
            "--action",
            "wait",
            "--task-id",
            task["id"],
            "--target",
            str(target),
            "--condition",
            "done",
            "--resume-scope",
            "read result",
            "--reason",
            "job pending",
            "--monitor",
            "output",
            "--poll-budget",
            "2",
        ],
    )
    callback = dict(payload, prompt=waiting["monitors"][0]["callback"])
    first = await client.handle(callback)
    assert first["hookSpecificOutput"]["additionalContext"]
    second = await client.handle(callback)
    assert second["continue"] is False
    status = await invoke(
        database, ["monitor", "status", "--task-id", task["id"], "--monitor-number", "1"]
    )
    assert status["error"] and status["remaining_polls"] == 0
    await invoke(database, ["monitor", "tick", "--task-id", task["id"], "--monitor-number", "1"])
    invalid = await client.handle(
        dict(payload, prompt="NEURATH_MONITOR_TICK 00000000-0000-0000-0000-000000000001 1")
    )
    assert invalid["continue"] is False and "could not be processed" in invalid["stopReason"]
