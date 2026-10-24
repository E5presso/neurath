"""실제 저장·CLI·손상 파일로 진단과 장애 복구의 보존 경계를 검증한다."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from typer import Typer
from typer.testing import CliRunner

from neurath.application.ports.services.diagnostics import IDiagnosticsService
from neurath.application.ports.services.recovery_log import IRecoveryLogService
from neurath.application.usecases.diagnose import DiagnoseQuery
from neurath.application.usecases.get_incident import GetIncidentQuery, GetIncidentUseCase
from neurath.application.usecases.open_incident import OpenIncidentCommand, OpenIncidentUseCase
from neurath.application.usecases.record_recovery_failure import (
    RecordRecoveryFailureCommand,
    RecordRecoveryFailureUseCase,
)
from neurath.application.usecases.refresh_incident import (
    RefreshIncidentCommand,
    RefreshIncidentUseCase,
)
from neurath.domain.aggregates.incident import Incident
from neurath.domain.enums.incident_evidence_kind import IncidentEvidenceKind as Kind
from neurath.domain.enums.incident_status import IncidentStatus as Status
from neurath.domain.errors import RevisionConflict
from neurath.domain.values.incident_evidence import IncidentEvidence
from neurath.infrastructure.database import create_database_engine, initialize_database, sqlite_url
from neurath.infrastructure.services.diagnostics import SQLAlchemyDiagnosticsService
from neurath.infrastructure.services.directory_observer import GitDirectoryObserverService
from neurath.infrastructure.services.recovery_log import PosixRecoveryLogService
from tests.support.application import request_application
from tests.support.hook_cli import HookCliClient
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_runtime import execution
from tests.test_task_migrations import migration_config
from tests.test_task_requests import create


def evidence(kind, passed=None):
    return IncidentEvidence(
        kind=kind, detail="실제 실행과 관찰", references=("run:actual",), passed=passed
    )


def new_incident(project=None):
    return Incident.create(project, "원래 오류", ("source:1",))


def test_incident_resolution_requires_current_ordered_evidence():
    incident = new_incident()
    assert incident.uid.version == 7
    with pytest.raises(RevisionConflict):
        incident.require_revision(2)
    incident.require_revision(1)
    with pytest.raises(ValueError):
        incident.resolve("근거 없음")
    incident.record(evidence(Kind.FIX))
    incident.record(evidence(Kind.REGRESSION, True))
    with pytest.raises(ValueError):
        incident.resolve("재현 없음")
    incident.record(evidence(Kind.REPRODUCTION))
    incident.record(evidence(Kind.FIX))
    incident.record(evidence(Kind.REGRESSION, False))
    with pytest.raises(ValueError):
        incident.resolve("실패")
    incident.record(evidence(Kind.REPRODUCTION))
    incident.record(evidence(Kind.FIX))
    incident.record(evidence(Kind.REGRESSION, True))
    with pytest.raises(ValueError):
        incident.resolve(" ")
    incident.record(evidence(Kind.OBSERVATION))
    with pytest.raises(ValueError):
        incident.resolve("새 관찰은 새 근거가 필요")
    incident.record(evidence(Kind.REPRODUCTION))
    incident.record(evidence(Kind.FIX))
    incident.record(evidence(Kind.REGRESSION, True))
    with pytest.raises(ValueError):
        incident.escalate(" ")
    incident.escalate("ticket:upstream 원인 이관")
    assert incident.status is Status.ESCALATED
    incident.resolve("재현된 오류 수정과 회귀 성공")
    assert incident.status is Status.RESOLVED
    assert incident.symptom == "원래 오류" and incident.transfers
    with pytest.raises(ValueError):
        incident.record(evidence(Kind.FIX))


@pytest.mark.parametrize(
    "detail,refs,kind,passed",
    [
        ("", ("r",), Kind.FIX, None),
        ("x", (), Kind.FIX, None),
        ("x", ("",), Kind.FIX, None),
        ("x", ("r",), Kind.REGRESSION, None),
        ("x", ("r",), Kind.FIX, True),
    ],
)
def test_empty_or_fabricated_evidence_is_rejected(detail, refs, kind, passed):
    with pytest.raises(ValueError):
        IncidentEvidence(kind=kind, detail=detail, references=refs, passed=passed)


def test_supersede_preserves_old_history_and_prevents_cycles():
    old, new = new_incident(), new_incident()
    with pytest.raises(ValueError):
        old.supersede(old)
    with pytest.raises(ValueError):
        old.supersede(new_incident(uuid4()))
    old.escalate("ticket:2")
    old.supersede(new)
    assert old.replacement_id == new.uid and old.status is Status.SUPERSEDED
    assert old.transfers == ("ticket:2",)
    with pytest.raises(ValueError):
        new.supersede(old)


async def cli(database, args, payload=""):
    async with request_application(sqlite_url(database, "rw")) as app:
        return await asyncio.to_thread(
            CliRunner().invoke, app.container.get(Typer), args, input=payload
        )


async def test_incident_cli_roundtrip_resolution_and_readonly_query(database):
    first = await cli(
        database, ["incident", "open", "--symptom", "원 증상", "--reference", "run:1"]
    )
    assert first.exit_code == 0, first.output
    incident = json.loads(first.stdout)
    before = database.read_bytes()
    query = await cli(database, ["incident", "show", "--incident-id", incident["id"]])
    assert query.exit_code == 0 and json.loads(query.stdout) == incident
    assert database.read_bytes() == before

    async def edit(action, *args):
        result = await cli(
            database,
            [
                "incident",
                action,
                "--incident-id",
                incident["id"],
                "--revision",
                str(incident["revision"]),
                *args,
            ],
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    incident = await edit("escalate", "--destination", "upstream:2")
    assert incident["status"] == "escalated"
    for kind in ("reproduction", "fix", "regression"):
        incident = await edit(
            "record",
            "--kind",
            kind,
            "--detail",
            "실제 결과",
            "--reference",
            "run:1",
            *(["--passed"] if kind == "regression" else []),
        )
    incident = await edit("resolve", "--explanation", "실제 회귀 확인")
    assert incident["status"] == "resolved" and len(incident["evidence"]) == 3
    stale = await cli(
        database,
        [
            "incident",
            "escalate",
            "--incident-id",
            incident["id"],
            "--revision",
            "1",
            "--destination",
            "old",
        ],
    )
    assert stale.exit_code == 1 and "revision" in stale.output
    assert incident["symptom"] == "원 증상"


async def test_supersede_cli_and_project_reference(database, tmp_path):
    actor = await register_session(str(tmp_path), "codex", "s", database_path=database)
    args = [
        "incident",
        "open",
        "--symptom",
        "x",
        "--reference",
        "actual",
        "--project-id",
        str(actor.project.uid),
    ]
    old = json.loads((await cli(database, args)).stdout)
    new = json.loads((await cli(database, args)).stdout)
    linked = await cli(
        database,
        [
            "incident",
            "supersede",
            "--incident-id",
            old["id"],
            "--revision",
            "1",
            "--replacement-id",
            new["id"],
        ],
    )
    assert linked.exit_code == 0, linked.output
    assert json.loads(linked.stdout)["replacement_id"] == new["id"]
    assert (
        json.loads((await cli(database, ["incident", "show", "--incident-id", new["id"]])).stdout)[
            "status"
        ]
        == "open"
    )


async def test_real_refresh_retains_failed_observation_and_does_not_resolve(database, tmp_path):
    opened = json.loads(
        (
            await cli(database, ["incident", "open", "--symptom", "broken", "--reference", "run"])
        ).stdout
    )
    result = await cli(
        database,
        [
            "incident",
            "refresh",
            "--incident-id",
            opened["id"],
            "--revision",
            "1",
            "--database",
            str(tmp_path / "gone"),
        ],
    )
    assert result.exit_code == 0, result.output
    updated = json.loads(result.stdout)
    assert updated["status"] == "open"
    findings = json.loads(updated["evidence"][0]["detail"])
    assert {item["status"] for item in findings} >= {"missing"}
    with pytest.raises(RevisionConflict):
        await run(
            RefreshIncidentUseCase,
            RefreshIncidentCommand(
                incident_id=UUID(opened["id"]),
                revision=1,
                query=DiagnoseQuery(),
            ),
            database_path=database,
        )


async def inspect(database, directory=None, provider="", host_session_id=""):
    result = await SQLAlchemyDiagnosticsService(GitDirectoryObserverService()).inspect(
        str(database) if database is not None else None,
        str(directory) if directory is not None else None,
        provider,
        host_session_id,
    )
    return {item.area: item for item in result}


async def test_diagnostics_readonly_native_resume_and_bypass_restore(database, tmp_path):
    actor = await register_session(str(tmp_path), "codex", "native", database_path=database)
    client = HookCliClient("codex", database)
    payload = dict(
        session_id="native", cwd=str(tmp_path), turn_id="new", hook_event_name="UserPromptSubmit"
    )
    bypassed = await client.handle(payload, bypass=True)
    assert "bypass" in bypassed["systemMessage"]
    task = await create(database, actor)
    assert (await execution(database, actor)).turn_id == "new"
    before = database.read_bytes()
    result = await cli(
        database,
        [
            "maintenance",
            "diagnose",
            "--database",
            str(database),
            "--directory",
            str(tmp_path),
            "--provider",
            "codex",
            "--host-session-id",
            "native",
        ],
    )
    assert result.exit_code == 0, result.output
    findings = {x["area"]: x for x in json.loads(result.stdout)}
    assert (
        str(task.uid) in findings["resume"]["detail"]
        and "unverified" in findings["resume"]["detail"]
    )
    assert database.read_bytes() == before
    # 우회 중의 실제 새 턴을 유지하므로 다음 인간 프롬프트 없이 원래 차단 경로가 동작한다.
    stop = dict(payload, hook_event_name="Stop")
    assert "bypass" in (await client.handle(stop, bypass=True))["systemMessage"]
    restored = await cli(database, ["hook", "verify", "--provider", "codex"], json.dumps(stop))
    assert restored.exit_code == 0, restored.output
    assert json.loads(restored.stdout)["verified"] is True
    assert (await execution(database, actor)).turn_id == "new"
    write = dict(payload, hook_event_name="PreToolUse", tool_name="Write", tool_use_id="bypass")
    assert "bypass" in (await client.handle(write, bypass=True))["systemMessage"]
    assert (await client.handle(dict(payload, hook_event_name="Interrupt"), bypass=True))[
        "systemMessage"
    ]
    assert (await execution(database, actor)).status.value == "cancelled"
    assert (await client.handle(write))["continue"] is False


async def test_verify_rejects_non_guard_missing_and_allowed_events(database, tmp_path):
    payload = dict(
        session_id="verify", cwd=str(tmp_path), turn_id="t", hook_event_name="UserPromptSubmit"
    )
    assert (
        await cli(database, ["hook", "verify", "--provider", "codex"], json.dumps(payload))
    ).exit_code == 1
    await HookCliClient("codex", database).handle(payload)
    result = await cli(
        database,
        ["hook", "verify", "--provider", "codex"],
        json.dumps(dict(payload, hook_event_name="Stop")),
    )
    assert result.exit_code == 1 and json.loads(result.stdout)["verified"] is False
    assert (await cli(database, ["hook", "verify", "--provider", "codex"], "bad")).exit_code == 1


async def test_diagnostics_missing_corrupt_wrong_schema_and_inaccessible_project(
    database, tmp_path
):
    missing = tmp_path / "missing"
    result = await inspect(missing)
    assert result["integrity"].status == "missing" and not missing.exists()
    corrupt = tmp_path / "corrupt"
    corrupt.write_text("not a database")
    before = corrupt.read_bytes()
    result = await inspect(corrupt)
    assert result["integrity"].status == "failed" and corrupt.read_bytes() == before
    empty = tmp_path / "empty"
    sqlite3.connect(empty).close()
    result = await inspect(empty)
    assert result["schema"].status == "failed" and result["resume"].status == "unknown"
    assert (await inspect(database))["project"].status == "missing"
    assert (await inspect(database, missing))["project"].status == "failed"
    assert (await inspect(database, tmp_path))["project"].status == "missing"
    await register_session(str(tmp_path), "codex", "saved", database_path=database)
    assert (await inspect(database, tmp_path, "codex", "absent"))["resume"].status == "missing"
    assert (await inspect(database, tmp_path, "codex", "saved"))["resume"].status == "missing"


async def test_config_diagnostics_does_not_rewrite_settings(database, monkeypatch, tmp_path):
    monkeypatch.delenv("SPAKKY_SQLALCHEMY__CONNECTION_STRING", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert (await inspect(None))["configuration"].status == "ok"
    for url in (
        "bad",
        "sqlite+aiosqlite:///:memory:",
        "sqlite+aiosqlite://",
        "postgresql://localhost/db",
    ):
        monkeypatch.setenv("SPAKKY_SQLALCHEMY__CONNECTION_STRING", url)
        assert (await inspect(None))["integrity"].status == "unknown"
        assert (await inspect(database))["configuration"].status == "failed"
        assert os.environ["SPAKKY_SQLALCHEMY__CONNECTION_STRING"] == url
    monkeypatch.setenv(
        "SPAKKY_SQLALCHEMY__CONNECTION_STRING",
        sqlite_url(database, "rw").render_as_string(hide_password=False),
    )
    assert (await inspect(None))["integrity"].status == "ok"


class BrokenOutput:
    def write(self, value):
        raise OSError("closed host output")


def test_independent_recovery_records_host_failure_and_both_failures(tmp_path, monkeypatch):
    service = PosixRecoveryLogService()
    monkeypatch.setattr("neurath.infrastructure.services.recovery_log.sys.stderr", BrokenOutput())
    first = service.record("DB unavailable", "hook:actual")
    assert first.record_path and not first.host_submitted and first.delivery == "unverified"
    assert "unfinished" in Path(first.record_path).read_text()
    second = service.record("again", "same original")
    assert len(Path(second.record_path).read_text().splitlines()) == 2
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    failed = service.record("DB unavailable", "hook:actual")
    assert failed.record_path is None and not failed.host_submitted
    assert "record failed" in failed.error and "output failed" in failed.error
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert service.record("x", "r").record_path == str(
        tmp_path / ".local/state/neurath/recovery.jsonl"
    )


async def test_recovery_validation_and_abstract_contracts():
    with pytest.raises(ValueError):
        await RecordRecoveryFailureUseCase(PosixRecoveryLogService()).run(
            RecordRecoveryFailureCommand(detail="", reference="r")
        )
    with pytest.raises(ValueError):
        await RecordRecoveryFailureUseCase(PosixRecoveryLogService()).run(
            RecordRecoveryFailureCommand(detail="x", reference="")
        )
    with pytest.raises(NotImplementedError):
        IRecoveryLogService.record(None, "x", "r")
    with pytest.raises(NotImplementedError):
        await IDiagnosticsService.inspect(None, None, None, "", "")


async def test_management_and_hook_work_when_business_database_is_corrupt(tmp_path):
    database = tmp_path / "corrupt"
    database.write_text("corrupt")
    result = await cli(
        database, ["incident", "open", "--symptom", "actual", "--reference", "source"]
    )
    assert result.exit_code == 1 and "recovery" in result.output
    result = await cli(database, ["maintenance", "diagnose", "--database", str(database)])
    assert result.exit_code == 1 and "failed" in result.stdout
    result = await cli(
        database, ["maintenance", "record-failure", "--detail", "actual", "--reference", "source"]
    )
    assert result.exit_code == 0 and json.loads(result.stdout)["delivery"] == "unverified"
    payload = dict(
        session_id="s", cwd=str(tmp_path), turn_id="t", hook_event_name="UserPromptSubmit"
    )
    failed = await HookCliClient("codex", database).handle(payload)
    assert failed["continue"] is False and "unfinished" in failed["stopReason"]
    bypass = await HookCliClient("codex", database).handle(payload, bypass=True)
    assert "bookkeeping failed" in bypass["systemMessage"] and database.read_text() == "corrupt"


async def test_management_record_failure_reports_unavailable_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    response = await cli(
        tmp_path / "missing",
        ["maintenance", "record-failure", "--detail", "actual", "--reference", "source"],
    )
    assert response.exit_code == 1 and json.loads(response.stdout)["record_path"] is None


async def test_hook_output_failure_is_recorded_without_loop(database, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("stdout closed")

    monkeypatch.setattr("neurath.transport.cli.hooks.echo", fail)
    result = await cli(database, ["hook", "handle", "--provider", "codex"], "broken")
    assert result.exit_code == 1
    records = [
        json.loads(x) for x in (tmp_path / "state/neurath/recovery.jsonl").read_text().splitlines()
    ]
    assert len(records) == 2 and records[-1]["reference"] == "hook:codex:stdout"


async def test_incident_migration_preserves_data_and_refuses_loss(database):
    old = await run(
        OpenIncidentUseCase,
        OpenIncidentCommand(symptom="must preserve", references=("run:1",)),
        database_path=database,
    )
    engine = create_database_engine(database, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            with pytest.raises(RuntimeError, match="preserved"):
                await connection.run_sync(
                    lambda conn: alembic_command.downgrade(migration_config(conn), "core_0011")
                )
    finally:
        await engine.dispose()
    restored = await run(
        GetIncidentUseCase, GetIncidentQuery(incident_id=old.uid), database_path=database
    )
    assert restored.symptom == old.symptom


async def test_empty_migration_can_downgrade_and_upgrade(database):
    engine = create_database_engine(database, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: alembic_command.downgrade(migration_config(conn), "core_0011")
            )
    finally:
        await engine.dispose()
    await initialize_database(database)
    assert (await inspect(database))["schema"].status == "ok"


async def test_management_bootstrap_observes_bad_config_without_changing_it(tmp_path, monkeypatch):
    import subprocess
    import sys

    from neurath.bootstrap import start_cli_application

    key = "SPAKKY_SQLALCHEMY__CONNECTION_STRING"
    monkeypatch.setenv(key, "not-a-valid-connection")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from neurath.cli import cli; cli()",
            "maintenance",
            "diagnose",
            "--database",
            str(tmp_path / "missing"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    findings = {item["area"]: item for item in json.loads(result.stdout)}
    assert findings["configuration"]["status"] == "failed"
    assert os.environ[key] == "not-a-valid-connection"
    app = start_cli_application(management=True)
    app.stop()
    assert os.environ[key] == "not-a-valid-connection"
    monkeypatch.delenv(key)
    app = start_cli_application(management=True)
    app.stop()
    assert key not in os.environ


async def test_diagnostics_finds_foreign_key_damage_and_conflicting_project_aliases(
    database, tmp_path
):
    from tests.conftest import initialize_git

    # 파손은 진단이 아닌 고의 fixture에서만 만든다. 진단 자체는 파일을 변경하지 않는다.
    first = await register_session(str(tmp_path), "codex", "first", database_path=database)
    second_folder = tmp_path / "other"
    second_folder.mkdir()
    second = await register_session(str(second_folder), "codex", "second", database_path=database)
    initialize_git(tmp_path)
    observation = GitDirectoryObserverService().observe(str(tmp_path))
    assert observation.git_common_directory
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO core_project_locations (kind,path,project_id) VALUES (?,?,?)",
            ("git", observation.git_common_directory, second.project.uid.hex),
        )
    result = await inspect(database, tmp_path)
    assert result["project"].status == "failed"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE core_sessions SET project_id=? WHERE id=?", (uuid4().hex, first.session.uid.hex)
        )
    before = database.read_bytes()
    assert (await inspect(database))["integrity"].status == "failed"
    assert database.read_bytes() == before


async def test_database_and_both_error_outputs_fail_without_retry(tmp_path, monkeypatch):
    import io

    from typer import Exit

    from neurath.domain.enums.provider_kind import ProviderKind
    from neurath.transport.cli.hooks import HookCliController

    database = tmp_path / "corrupt.sqlite3"
    database.write_text("broken database")
    monkeypatch.setenv("XDG_STATE_HOME", "invalid-relative")
    payload = dict(
        session_id="actual", cwd=str(tmp_path), turn_id="turn", hook_event_name="UserPromptSubmit"
    )
    attempts = []
    original = PosixRecoveryLogService.record

    def record(service, detail, reference):
        result = original(service, detail, reference)
        attempts.append(result)
        return result

    def output(*args, **kwargs):
        raise OSError("host response unavailable")

    monkeypatch.setattr(PosixRecoveryLogService, "record", record)
    monkeypatch.setattr("neurath.transport.cli.hooks.sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("neurath.infrastructure.services.recovery_log.sys.stderr", BrokenOutput())
    monkeypatch.setattr("neurath.transport.cli.hooks.echo", output)
    async with request_application(sqlite_url(database, "rw")) as app:
        with pytest.raises(Exit) as stopped:
            await app.container.get(HookCliController).handle(ProviderKind.CODEX)
    assert stopped.value.exit_code == 1
    assert len(attempts) == 2  # DB 오류와 최종 응답 출력 오류, 재시도 루프 없음.
    assert all(
        x.record_path is None and not x.host_submitted and x.delivery == "unverified"
        for x in attempts
    )
    assert database.read_text() == "broken database"


async def test_bypass_compact_keeps_context_and_restart_checks_same_turn(database, tmp_path):
    import subprocess
    import sys

    actor = await register_session(str(tmp_path), "codex", "restart", database_path=database)
    task = await create(database, actor)
    payload = dict(
        session_id="restart",
        cwd=str(tmp_path),
        turn_id="same-turn",
        hook_event_name="UserPromptSubmit",
    )
    client = HookCliClient("codex", database)
    await client.handle(payload, bypass=True)
    compact = await client.handle(
        dict(payload, hook_event_name="SessionStart", source="compact"), bypass=True
    )
    assert str(task.uid) in compact["hookSpecificOutput"]["additionalContext"]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from neurath.cli import cli; cli()",
            "hook",
            "verify",
            "--provider",
            "codex",
        ],
        env={
            **os.environ,
            "SPAKKY_SQLALCHEMY__CONNECTION_STRING": sqlite_url(database, "rw").render_as_string(
                hide_password=False
            ),
        },
        input=json.dumps(dict(payload, hook_event_name="Stop")),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verified"] is True
    assert str(task.uid) in json.loads(result.stdout)["response"]["reason"]


def test_failed_regression_is_retained_when_real_retest_passes():
    incident = new_incident()
    incident.record(evidence(Kind.REPRODUCTION))
    incident.record(evidence(Kind.FIX))
    incident.record(evidence(Kind.REGRESSION, False))
    with pytest.raises(ValueError):
        incident.resolve("실패를 성공으로 처리할 수 없음")
    incident.record(evidence(Kind.REGRESSION, True))
    incident.resolve("실제 재시험 성공 확인")
    assert incident.evidence[2].passed is False
    assert incident.status is Status.RESOLVED


async def test_hook_failure_with_empty_message_still_records_cause(database, tmp_path, monkeypatch):
    from neurath.application.usecases.receive_hook import ReceiveHookUseCase

    async def fail(*args, **kwargs):
        raise RuntimeError()

    monkeypatch.setattr(ReceiveHookUseCase, "run", fail)
    payload = dict(
        session_id="s", cwd=str(tmp_path), turn_id="t", hook_event_name="UserPromptSubmit"
    )
    response = await HookCliClient("codex", database).handle(payload)
    assert response["continue"] is False
    record = json.loads((tmp_path / "state/neurath/recovery.jsonl").read_text())
    assert record["detail"] == "RuntimeError: "
