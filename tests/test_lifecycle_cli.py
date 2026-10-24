"""공개 CLI의 원 대화와 장애 수리 흐름을 실제 SQLite 상태에 연결한다."""

from pathlib import Path
from uuid import uuid7

import pytest

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.application.ports.services.recovery_log import IRecoveryLogService
from neurath.application.usecases.list_incidents import ListIncidentsQuery, ListIncidentsUseCase
from neurath.infrastructure.services.recovery_log import PosixRecoveryLogService
from tests.support.hook_cli import HookCliClient
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_host_flow import create, invoke
from tests.test_host_flow import host as host


async def test_public_question_reply_ack_close_keeps_conversation_and_unfinished_task(
    database, host, monkeypatch
):
    directory, client, payload = host
    task = await create(database)
    original = await invoke(database, ["session", "preview"])
    receiver = HookCliClient("claude", database)
    await receiver.handle(
        dict(payload, session_id="receiver", prompt="Answer the existing question")
    )
    question = await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "receiver",
            "--title",
            "Question",
            "--body",
            "Original question",
            "--key",
            "question",
        ],
    )
    monkeypatch.setenv("NEURATH_PROVIDER", "claude")
    monkeypatch.setenv("NEURATH_SESSION_ID", "receiver")
    await invoke(database, ["collaboration", "ack", "--message-id", question["id"]], succeeds=False)
    read = await invoke(database, ["collaboration", "read", "--message-id", question["id"]])
    assert (
        read["body"] == "Original question"
        and read["conversation_id"] == question["conversation_id"]
    )
    ack = await invoke(database, ["collaboration", "ack", "--message-id", question["id"]])
    assert ack["acknowledged"]
    args = [
        "collaboration",
        "send",
        "--recipient",
        "native-test-session",
        "--title",
        "Answer",
        "--body",
        "Original answer",
        "--reply-to",
        question["id"],
    ]
    answer = await invoke(database, args)
    assert (
        answer["conversation_id"] == question["conversation_id"]
        and answer["reply_to"] == question["id"]
    )
    assert (await invoke(database, args))["id"] == answer["id"]
    monkeypatch.setenv("NEURATH_PROVIDER", "codex")
    monkeypatch.setenv("NEURATH_SESSION_ID", "native-test-session")
    await invoke(database, ["collaboration", "ack", "--message-id", question["id"]], succeeds=False)
    await invoke(database, ["collaboration", "read", "--message-id", answer["id"]])
    assert (await invoke(database, ["collaboration", "ack", "--message-id", answer["id"]]))[
        "acknowledged"
    ]
    closed = await invoke(
        database, ["collaboration", "close", "--conversation-id", question["conversation_id"]]
    )
    assert closed["closed"]
    await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "receiver",
            "--title",
            "Late",
            "--body",
            "Must not reopen",
            "--reply-to",
            answer["id"],
        ],
        succeeds=False,
    )
    assert (await invoke(database, ["collaboration", "read", "--message-id", answer["id"]]))[
        "body"
    ] == "Original answer"
    current = await invoke(database, ["session", "preview"])
    assert current["tasks"] == original["tasks"] and current["tasks"][0]["id"] == task["id"]
    assert (await client.handle(dict(payload, hook_event_name="Stop")))["decision"] == "block"


async def test_public_failure_recovery_history_and_queries_do_not_change_work(
    database, host, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    task = await create(database)
    before = await invoke(database, ["session", "preview"])
    receipt = await invoke(
        database,
        [
            "maintenance",
            "record-failure",
            "--detail",
            "Original storage failure",
            "--reference",
            "call:original",
        ],
    )
    journal = Path(receipt["record_path"])
    raw = journal.read_bytes()
    assert (await invoke(database, ["maintenance", "failures"]))["incidents"] == []
    synced = await invoke(database, ["maintenance", "repair"])
    incident = synced["incidents"][0]
    assert incident["symptom"] == "Original storage failure" and incident["status"] == "open"
    assert "call:original" in incident["references"]
    assert (await invoke(database, ["maintenance", "repair", "--journal", str(journal)]))[
        "incidents"
    ] == synced["incidents"]
    saved = database.read_bytes()
    page = await invoke(database, ["maintenance", "failures", "--limit", "1"])
    assert page["next_after_id"] == incident["id"]
    assert (await invoke(database, ["maintenance", "failures", "--after", incident["id"]]))[
        "incidents"
    ] == []
    assert (
        await invoke(database, ["maintenance", "failure", "--incident-id", incident["id"]])
    ) == incident
    assert database.read_bytes() == saved
    for kind in ["reproduction", "fix", "regression"]:
        arguments = [
            "maintenance",
            "repair",
            "--incident-id",
            incident["id"],
            "--kind",
            kind,
            "--detail",
            "Actual " + kind,
            "--reference",
            "evidence:" + kind,
        ]
        if kind == "regression":
            await invoke(
                database,
                [*arguments, "--failed", "--resolve", "Cannot resolve a failed check"],
                succeeds=False,
            )
            arguments += ["--passed", "--resolve", "Actual regression passed"]
        incident = await invoke(database, arguments)
    assert incident["status"] == "resolved" and len(incident["evidence"]) == 4
    assert [item["kind"] for item in incident["evidence"]] == [
        "reproduction",
        "fix",
        "regression",
        "regression",
    ]
    assert (await invoke(database, ["maintenance", "repair"]))["incidents"][0][
        "status"
    ] == "resolved"
    assert journal.read_bytes() == raw
    current = await invoke(database, ["session", "preview"])
    assert current["tasks"] == before["tasks"] and current["tasks"][0]["id"] == task["id"]


async def test_unresolved_failure_observation_handoff_and_replacement(
    database, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for detail in ["first symptom", "replacement symptom"]:
        await invoke(
            database, ["maintenance", "record-failure", "--detail", detail, "--reference", detail]
        )
    incidents = (await invoke(database, ["maintenance", "repair"]))["incidents"]
    first, replacement = incidents
    refreshed = await invoke(
        database,
        ["maintenance", "diagnose", "--incident-id", first["id"], "--database", str(database)],
    )
    assert refreshed["status"] == "open" and refreshed["evidence"][0]["kind"] == "observation"
    transferred = await invoke(
        database,
        [
            "maintenance",
            "handoff-failure",
            "--incident-id",
            first["id"],
            "--destination",
            "Next repair: reproduction remains",
        ],
    )
    assert transferred["status"] == "escalated" and transferred["resolution"] == ""
    superseded = await invoke(
        database,
        [
            "maintenance",
            "handoff-failure",
            "--incident-id",
            first["id"],
            "--replacement-id",
            replacement["id"],
        ],
    )
    assert (
        superseded["status"] == "superseded" and superseded["replacement_id"] == replacement["id"]
    )
    assert (
        superseded["symptom"] == first["symptom"]
        and superseded["transfers"] == transferred["transfers"]
    )
    assert (await invoke(database, ["maintenance", "failure", "--incident-id", replacement["id"]]))[
        "status"
    ] == "open"
    for arguments in [
        ["repair", "--kind", "fix"],
        ["repair", "--incident-id", first["id"]],
        ["repair", "--incident-id", first["id"], "--journal", "unread", "--kind", "fix"],
        ["repair", "--incident-id", first["id"], "--kind", "fix"],
        ["handoff-failure", "--incident-id", first["id"]],
        [
            "handoff-failure",
            "--incident-id",
            first["id"],
            "--destination",
            "x",
            "--replacement-id",
            replacement["id"],
        ],
    ]:
        snapshot = database.read_bytes()
        await invoke(database, ["maintenance", *arguments], succeeds=False)
        assert database.read_bytes() == snapshot


@pytest.mark.parametrize(
    "content", ["broken json", "[]\n", '{"time":"now","detail":"","reference":"source"}\n']
)
async def test_invalid_journal_never_imports_a_partial_history(database, tmp_path, content):
    journal = tmp_path / "invalid.jsonl"
    journal.write_text('{"time":"before","detail":"valid","reference":"source"}\n' + content)
    snapshot = database.read_bytes()
    await invoke(database, ["maintenance", "repair", "--journal", str(journal)], succeeds=False)
    assert database.read_bytes() == snapshot and journal.read_text().endswith(content)


async def test_recovery_read_contracts_and_empty_journal_are_explicit(
    database, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "empty"))
    assert (await invoke(database, ["maintenance", "repair"]))["incidents"] == []
    with pytest.raises(FileNotFoundError):
        PosixRecoveryLogService().read(str(tmp_path / "missing"))
    with pytest.raises(NotImplementedError):
        IRecoveryLogService.read(None)
    with pytest.raises(NotImplementedError):
        await IIncidentRepository.find_by_origin(None, "source")
    with pytest.raises(ValueError):
        await run(ListIncidentsUseCase, ListIncidentsQuery(limit=0), database_path=database)


@pytest.mark.parametrize("arguments", [["ack", "--message-id"], ["close", "--conversation-id"]])
async def test_public_conversation_controls_require_an_observed_peer(
    database, tmp_path, monkeypatch, arguments
):
    await register_session(str(tmp_path), "codex", "unobserved-peer", database_path=database)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEURATH_SESSION_ID", "unobserved-peer")
    monkeypatch.setenv("NEURATH_PROVIDER", "codex")
    before = database.read_bytes()
    result = await invoke(database, ["collaboration", *arguments, str(uuid7())], succeeds=False)
    assert "peer has not been observed" in str(result.exception)
    assert database.read_bytes() == before


async def test_reply_from_observed_session_without_execution_keeps_original_conversation(
    database, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEURATH_PROVIDER", "codex")
    for session in ["first", "second"]:
        await HookCliClient("codex", database).handle(
            {
                "session_id": session,
                "cwd": str(tmp_path),
                "hook_event_name": "SessionStart",
                "source": "startup",
            }
        )
    monkeypatch.setenv("NEURATH_SESSION_ID", "first")
    original = await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "second",
            "--title",
            "Question",
            "--body",
            "Question before work",
        ],
    )
    monkeypatch.setenv("NEURATH_SESSION_ID", "second")
    reply = await invoke(
        database,
        [
            "collaboration",
            "send",
            "--recipient",
            "first",
            "--title",
            "Answer",
            "--body",
            "Answer before work",
            "--reply-to",
            original["id"],
        ],
    )
    assert reply["conversation_id"] == original["conversation_id"]


@pytest.mark.parametrize(
    "arguments,core",
    [
        (["diagnose"], False),
        (["record-failure"], False),
        (["failures"], True),
        (["repair"], True),
        (["failure"], True),
        (["handoff-failure"], True),
        (["diagnose", "--database", "selected", "--incident-id", "actual-id"], True),
        (["diagnose", "--incident-id=actual-id"], True),
    ],
)
async def test_maintenance_entrypoint_separates_fallback_from_core(
    database, monkeypatch, arguments, core
):
    import atexit
    import runpy
    import sys

    from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager

    from neurath.infrastructure.database import sqlite_url

    callbacks = []
    monkeypatch.setattr(atexit, "register", callbacks.append)
    monkeypatch.setenv(
        "SPAKKY_SQLALCHEMY__CONNECTION_STRING",
        sqlite_url(database, "rw").render_as_string(hide_password=False),
    )
    monkeypatch.setattr(sys, "argv", ["neurath", "maintenance", *arguments])
    namespace = runpy.run_module("neurath.cli")
    connection = namespace["application"].container.get(AsyncConnectionManager)
    try:
        selected = connection.connection.url.database
        assert (str(database) in selected) is core
        assert ("neurath-management-unopened.sqlite3" in selected) is (not core)
    finally:
        await connection.dispose()
        for callback in callbacks:
            callback()
