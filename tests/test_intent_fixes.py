"""실제 CLI로 원문 해석·현재 턴 양보·cwd 독립 조회와 평가 재사용을 검증한다."""

import json

import pytest

from tests.test_host_flow import create, delegate_review, finish_review, invoke, prepare_review
from tests.test_host_flow import host as host


async def test_status_only_turn_returns_control_on_first_stop_and_keeps_original_run(
    database, host
):
    task = await create(database)
    flow = await invoke(
        database, ["workflow", "start", "--task-id", task["id"], "--skill", "implement-spec"]
    )
    before = await invoke(database, ["session", "preview"])
    original = "What is the current status? Do not continue execution in this turn."
    payload = dict(host[2], prompt=original, turn_id="status-turn")
    await host[1].handle(payload)
    decision = await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "status",
            "--pause",
            "--reason",
            "The original asks for status only and explicitly excludes execution in this turn.",
        ],
    )
    for repeated in (False, True):
        stopped = await host[1].handle(
            dict(payload, hook_event_name="Stop", stop_hook_active=repeated)
        )
        assert stopped["continue"] is False and "decision" not in stopped
        assert "Continue unfinished work" not in stopped["stopReason"]
    after = await invoke(database, ["session", "preview"])
    assert before["tasks"] == after["tasks"] and before["workflows"] == after["workflows"]
    sources = (await invoke(database, ["context", "show", "--section", "sources"]))["sources"]
    assert (
        sources[-1]["id"] == decision["source_id"]
        and sources[-1]["kind"] == "status"
        and sources[-1]["body"] == original
    )
    memory = await invoke(database, ["memory", "read", "--memory-id", decision["memory_id"]])
    assert json.loads(memory["content"])["previous_kind"] == "prompt"
    await host[1].handle(
        dict(payload, prompt="Continue the original work now.", turn_id="work-turn")
    )
    stopped = await host[1].handle(dict(payload, hook_event_name="Stop", turn_id="work-turn"))
    assert stopped["decision"] == "block"
    resumed = await invoke(database, ["workflow", "show", "--run-id", flow["id"]])
    assert resumed["id"] == flow["id"] and resumed["current"]["key"] == flow["current"]["key"]


async def test_real_requirement_can_pause_this_turn_without_being_excluded(database, host):
    await create(database)
    await host[1].handle(
        dict(
            host[2],
            prompt="Also produce an accessibility report, but do not execute it in this turn.",
            turn_id="new-result",
        )
    )
    result = await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "prompt",
            "--pause",
            "--reason",
            "The original adds a required result and separately excludes execution in this turn.",
        ],
    )
    assert result["kind"] == "prompt" and result["paused"]
    assert (await host[1].handle(dict(host[2], hook_event_name="Stop", turn_id="new-result")))[
        "continue"
    ] is False
    await invoke(database, ["session", "resume"])
    assert (await host[1].handle(dict(host[2], hook_event_name="Stop", turn_id="new-result")))[
        "decision"
    ] == "block"


async def test_observed_native_session_survives_other_tool_cwd_without_merging_projects(
    database, host, tmp_path, monkeypatch
):
    task = await create(database)
    original = await invoke(database, ["context", "show"])
    other = tmp_path / "other-tool-directory"
    other.mkdir()
    monkeypatch.chdir(other)
    for suffix in ([], ["--session", "native-test-session"]):
        result = await invoke(database, ["context", "show", *suffix])
        assert [item["id"] for item in result["tasks"]] == [task["id"]]
        assert result["host"]["session_directory"] == str(host[0])
        assert result["host"]["invocation_directory"] == str(other)
    await host[1].handle(
        dict(host[2], cwd=str(other), prompt="Separate observed project requirement")
    )
    another = await create(database)
    here = await invoke(database, ["context", "show"])
    assert [item["id"] for item in here["tasks"]] == [another["id"]]
    outside = tmp_path / "outside-both"
    outside.mkdir()
    monkeypatch.chdir(outside)
    response = await invoke(database, ["context", "show"], succeeds=False)
    assert "ambiguous" in str(response.exception)
    selected = await invoke(
        database,
        [
            "context",
            "show",
            "--session",
            "native-test-session",
            "--project-id",
            original["host"]["project_id"],
        ],
    )
    assert [item["id"] for item in selected["tasks"]] == [task["id"]]
    assert selected["host"]["invocation_directory"] == str(outside)


async def accepted_review(database, host, monkeypatch):
    task, flow, artifact = await prepare_review(database, host)
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
            "Observed independent fixture report",
            "--reference",
            str(artifact),
            "--accepted",
        ],
    )
    return task, flow, artifact


async def test_status_source_keeps_valid_review_without_discarding_original_or_reason(
    database, host, monkeypatch
):
    task, flow, artifact = await accepted_review(database, host, monkeypatch)
    original = "What is the current status?"
    await host[1].handle(dict(host[2], prompt=original, turn_id="status-after-review"))
    await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "status",
            "--reason",
            "This asks for status; no requested result, TODO, or artifact is changed.",
        ],
    )
    reported = await invoke(
        database,
        [
            "task",
            "report",
            "--task-id",
            task["id"],
            "--summary",
            "Unchanged verified artifact",
            "--reference",
            str(artifact),
        ],
    )
    assert reported["status"] == "succeeded"
    sources = (await invoke(database, ["context", "show", "--section", "sources"]))["sources"]
    assert sources[-1]["body"] == original and sources[-1]["kind"] == "status"
    assert (await invoke(database, ["workflow", "show", "--run-id", flow["id"]]))["steps_complete"]


@pytest.mark.parametrize("change", ["requirement", "artifact"])
async def test_new_unassigned_requirement_and_actual_artifact_change_still_invalidate_review(
    database, host, monkeypatch, change
):
    task, flow, artifact = await accepted_review(database, host, monkeypatch)
    if change == "requirement":
        await host[1].handle(
            dict(
                host[2],
                prompt="Also provide missing keyboard accessibility evidence.",
                turn_id="new-requirement",
            )
        )
        await invoke(
            database,
            [
                "session",
                "interpret",
                "--kind",
                "prompt",
                "--reason",
                "The original adds a required accessibility result that is not in TODO yet.",
            ],
        )
    else:
        artifact.write_text("Changed artifact after accepted review")
    response = await invoke(
        database,
        [
            "task",
            "report",
            "--task-id",
            task["id"],
            "--summary",
            "Candidate report",
            "--reference",
            str(artifact),
        ],
        succeeds=False,
    )
    assert "changed" in str(response.exception).lower()
    assert (await invoke(database, ["context", "show"]))["tasks"][0]["status"] == "active"
    assert (await invoke(database, ["workflow", "show", "--run-id", flow["id"]]))["id"] == flow[
        "id"
    ]


async def test_evaluator_receives_status_original_interpretation_and_omitted_real_requirement(
    database, host, monkeypatch
):
    task, flow, artifact = await prepare_review(database, host)
    await host[1].handle(
        dict(
            host[2],
            prompt="Explain the current state without changing the requested result.",
            turn_id="context-only",
        )
    )
    decision = await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "status",
            "--reason",
            "This requests an explanation and no new result.",
        ],
    )
    await host[1].handle(
        dict(
            host[2],
            prompt="Also include the unassigned accessibility evidence.",
            turn_id="omitted-result",
        )
    )
    assignment = await delegate_review(database, task, artifact)
    monkeypatch.setenv("NEURATH_SESSION_ID", "native-reviewer")
    message = await invoke(
        database, ["collaboration", "read", "--message-id", assignment["message_id"]]
    )
    assert "Explain the current state" in message["body"] and "[status]" in message["body"]
    assert "This requests an explanation and no new result." in message["body"]
    assert "unassigned accessibility evidence" in message["body"]
    assert decision["source_id"] in message["body"]


async def test_reused_address_across_providers_requires_observed_provider(
    database, host, monkeypatch
):
    from tests.support.hook_cli import HookCliClient

    original = await create(database)
    claude = HookCliClient("claude", database)
    await claude.handle(dict(host[2], prompt="Separate Claude fixture work"))
    monkeypatch.setenv("NEURATH_PROVIDER", "claude")
    other = await create(database)
    monkeypatch.setenv("NEURATH_PROVIDER", "codex")
    assert (await invoke(database, ["context", "show"]))["tasks"][0]["id"] == original["id"]
    response = await invoke(
        database, ["context", "show", "--session", "native-test-session"], succeeds=False
    )
    assert "ambiguous" in str(response.exception)
    selected = await invoke(
        database, ["context", "show", "--session", "native-test-session", "--provider", "claude"]
    )
    assert selected["tasks"][0]["id"] == other["id"] and selected["host"]["provider"] == "claude"


@pytest.mark.parametrize(
    "case",
    [
        "missing-reason",
        "past-source",
        "unsupported-kind",
        "assigned-requirement",
        "missing-execution",
    ],
)
async def test_invalid_interpretations_do_not_change_original_requirements(database, host, case):
    import sqlite3

    original = (await invoke(database, ["context", "show", "--section", "sources"]))["sources"][0]
    if case == "assigned-requirement":
        await create(database)
    elif case == "past-source":
        await host[1].handle(dict(host[2], prompt="Another observed turn", turn_id="new-turn"))
    elif case == "missing-execution":
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM core_executions")
    args = [
        "session",
        "interpret",
        "--kind",
        "summary" if case == "unsupported-kind" else "status",
        "--reason",
        "" if case == "missing-reason" else "Read the actual source",
    ]
    if case == "past-source":
        args.extend(["--source-id", original["id"]])
    before = database.read_bytes()
    await invoke(database, args, succeeds=False)
    assert database.read_bytes() == before


async def test_turn_control_compatibility_downgrade_does_not_erase_pause(database, host):
    from alembic import command

    from neurath.infrastructure.database import create_database_engine
    from tests.test_task_migrations import migration_config

    await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "prompt",
            "--pause",
            "--reason",
            "Current source is retained; this turn yields control.",
        ],
    )
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="turn-control"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda db: command.downgrade(migration_config(db), "core_0015")
                )
    finally:
        await engine.dispose()
    stopped = await host[1].handle(dict(host[2], hook_event_name="Stop"))
    assert stopped["continue"] is False


async def test_current_source_selection_uses_exact_opaque_turn_and_preserves_other_originals(
    database, host
):
    await host[1].handle(
        dict(host[2], prompt="Earlier additional requested result", turn_id="turn:related")
    )
    old = (await invoke(database, ["context", "show", "--section", "sources"]))["sources"][-1]
    await host[1].handle(dict(host[2], prompt="Explain current progress only", turn_id="turn"))
    current = (await invoke(database, ["context", "show", "--section", "sources"]))["sources"][-1]
    await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "status",
            "--source-id",
            old["id"],
            "--reason",
            "This older opaque turn must not match",
        ],
        succeeds=False,
    )
    await invoke(
        database,
        [
            "session",
            "interpret",
            "--kind",
            "status",
            "--source-id",
            current["id"],
            "--reason",
            "The current original asks for explanation only.",
        ],
    )
    sources = (await invoke(database, ["context", "show", "--section", "sources"]))["sources"]
    assert next(item for item in sources if item["id"] == old["id"])["kind"] == "prompt"
    assert sources[-1]["body"] == current["body"] and sources[-1]["kind"] == "status"


def test_nonprompt_sources_cannot_be_rewritten_as_turn_interpretations():
    from uuid import uuid7

    from neurath.domain.aggregates.request_source import RequestSource, SourceKind
    from neurath.domain.errors import InvalidTaskState

    source = RequestSource.create(uuid7(), uuid7(), SourceKind.TICKET, "Actual ticket requirement")
    with pytest.raises(InvalidTaskState, match="observed prompts"):
        source.interpret(SourceKind.STATUS)
    assert source.kind is SourceKind.TICKET and source.body == "Actual ticket requirement"
