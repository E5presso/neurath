"""실제 SQLite 사본·선택 재개·원 경로 퇴역·전환 사건과 복구를 검증한다."""

import base64
import hashlib
import json
import sqlite3
import zlib
from pathlib import Path

import pytest

from neurath.infrastructure.services.historical_store import PosixHistoricalStoreService
from tests.test_host_flow import host as host
from tests.test_host_flow import invoke


def build_runtime(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
CREATE TABLE runtime_schema(component TEXT, version INTEGER);
INSERT INTO runtime_schema VALUES('runtime',3);
CREATE TABLE runtime_records(namespace TEXT,key TEXT,revision INTEGER,payload BLOB);
CREATE TABLE events(sequence INTEGER PRIMARY KEY,id TEXT,host TEXT,session TEXT,kind TEXT,content TEXT,metadata TEXT);
CREATE TABLE messages(sequence INTEGER PRIMARY KEY,id TEXT,sender TEXT,recipient TEXT,conversation TEXT,reply_to TEXT,body TEXT,status TEXT);
CREATE TABLE lessons(id TEXT,problem TEXT,solution TEXT,status TEXT);
CREATE TABLE lesson_history(sequence INTEGER,lesson TEXT,status TEXT,reason TEXT,evidence TEXT);
CREATE TABLE learning_observations(event TEXT);
CREATE TABLE learning_checks(lesson TEXT,observation TEXT,disposition TEXT,evidence TEXT);
CREATE TABLE opaque_table(id INTEGER, payload BLOB, measurement REAL, optional TEXT);
INSERT INTO opaque_table VALUES(1,x'00ff',1.5,NULL);
INSERT INTO events VALUES(1,'event-1','codex','old-session','prompt','Original user requirement','{}');
INSERT INTO messages VALUES(1,'message-1','old-peer','old-recipient','old-conversation',NULL,'Original message body','unread');
INSERT INTO lessons VALUES('lesson-1','Observed failure','Historical correction','proposed');
INSERT INTO lesson_history VALUES(1,'lesson-1','proposed','Original evidence','event-1');
INSERT INTO learning_observations VALUES('event-1');
INSERT INTO learning_checks VALUES('lesson-1','event-1','unknown','Original evidence');
""")
        ledger = {
            "owner": "old-owner",
            "session": "old-session",
            "tasks": [
                {
                    "id": "old-task",
                    "status": "in_progress",
                    "definition": {
                        "goal": "Preserve original artifact",
                        "acceptance": ["Verified original content"],
                        "dependencies": [],
                    },
                },
                {
                    "id": "done-task",
                    "status": "succeeded",
                    "definition": {
                        "goal": "Earlier completed work",
                        "acceptance": [],
                        "dependencies": [],
                    },
                },
            ],
        }
        workflow = {
            "workflows": {
                "old-flow": {
                    "id": "old-flow",
                    "kind": "implement-spec",
                    "status": "waiting",
                    "owner_actor_id": "old-owner",
                    "payload": {
                        "phase_run": {
                            "skill": "implement-spec",
                            "phases": [
                                {
                                    "id": 1,
                                    "name": "Original completed phase",
                                    "status": "succeeded",
                                    "evidence": ["old-proof"],
                                },
                                {
                                    "id": 2,
                                    "name": "Pending original verification",
                                    "status": "pending",
                                    "evidence": [],
                                },
                            ],
                        }
                    },
                }
            }
        }
        rows = [
            ("task-ledger", "old-session", 1, json.dumps(ledger).encode()),
            ("session", "old-session", 1, json.dumps(workflow).encode()),
            (
                "enclave",
                "old-session",
                1,
                json.dumps(
                    {
                        "facts": {
                            "original": {"value": "Preserved historical context", "kind": "fact"}
                        },
                        "session_id": "old-session",
                    }
                ).encode(),
            ),
            ("artifact:old-session", "artifact-1", 1, b"Original non-JSON artifact"),
            ("prompt:old-session", "prompt-1", 1, json.dumps({"reference": "event-1"}).encode()),
        ]
        db.executemany("INSERT INTO runtime_records VALUES(?,?,?,?)", rows)
    return ledger


def build_modern(path, runtime, *, storage="zlib-json-v1"):
    def cell(value):
        if value is None:
            return ["null", None]
        if isinstance(value, bytes):
            return ["blob", base64.b64encode(value).decode()]
        if isinstance(value, int):
            return ["integer", str(value)]
        if isinstance(value, float):
            return ["real", value.hex()]
        return ["text", value]

    tables = []
    with sqlite3.connect(runtime) as db:
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{name}")')]
            rows = [[cell(value) for value in row] for row in db.execute(f'SELECT * FROM "{name}"')]
            tables.append(
                dict(name=name, columns=columns, rows=rows, rowids=list(range(len(rows))))
            )
    raw = json.dumps(
        {
            "format": "neurath-legacy-snapshot-v1",
            "sources": [
                {"source_id": "original-runtime", "source_path": str(runtime), "tables": tables}
            ],
            "report": {},
        }
    ).encode()
    compressed = zlib.compress(raw)
    with sqlite3.connect(path) as db:
        db.executescript("""
CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES('0002');
CREATE TABLE records(kind TEXT,id TEXT,revision INTEGER,owner_id TEXT,task_id TEXT,status TEXT,data TEXT);
CREATE TABLE tasks(id TEXT,revision INTEGER,owner_id TEXT,source_id TEXT,goal TEXT,status TEXT,scope_version INTEGER,wait_reason TEXT,extra TEXT);
CREATE TABLE task_criteria(task_id TEXT,id TEXT,position INTEGER,description TEXT,satisfied INTEGER);
CREATE TABLE task_phases(task_id TEXT,id TEXT,position INTEGER,name TEXT,status TEXT,extra TEXT);
CREATE TABLE source_archives(id TEXT,digest TEXT,data TEXT);
CREATE TABLE source_archive_chunks(archive_id TEXT,position INTEGER,data BLOB);
CREATE TABLE unknown_current_table(payload TEXT); INSERT INTO unknown_current_table VALUES('preserved');
INSERT INTO tasks VALUES('imported-task',1,'legacy-owner','source-1','Preserve original artifact','waiting',1,'Original unfinished work','{}');
INSERT INTO task_criteria VALUES('imported-task','criterion-1',1,'Verified original content',0);
INSERT INTO task_phases VALUES('imported-task','phase-1',1,'Pending original verification','pending','{}');
""")
        lineage = {
            "state": {
                "original_owner": "old-owner",
                "original_session": "old-session",
                "original_task_id": "old-task",
                "original_status": "in_progress",
                "original_task": {"preserved": True},
            }
        }
        db.executemany(
            "INSERT INTO records VALUES(?,?,?,?,?,?,?)",
            [
                (
                    "source",
                    "source-1",
                    1,
                    "legacy-owner",
                    None,
                    None,
                    json.dumps(
                        {"text": "Original user requirement", "source_type": "legacy-import"}
                    ),
                ),
                (
                    "checkpoint",
                    "checkpoint-1",
                    1,
                    "legacy-owner",
                    "imported-task",
                    None,
                    json.dumps(lineage),
                ),
                (
                    "evidence",
                    "evidence-1",
                    1,
                    "legacy-owner",
                    "imported-task",
                    None,
                    json.dumps({"content": "Original evidence"}),
                ),
            ],
        )
        db.execute(
            "INSERT INTO source_archives VALUES(?,?,?)",
            (
                "archive-1",
                "logical-digest",
                json.dumps(
                    dict(storage=storage, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                ),
            ),
        )
        half = len(compressed) // 2
        db.executemany(
            "INSERT INTO source_archive_chunks VALUES(?,?,?)",
            [("archive-1", 0, compressed[:half]), ("archive-1", 1, compressed[half:])],
        )


@pytest.fixture
async def legacy(database, host, tmp_path):
    runtime = tmp_path / "runtime.sqlite3"
    build_runtime(runtime)
    modern = tmp_path / "neurath.sqlite3"
    build_modern(modern, runtime)
    archived = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(modern),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(tmp_path / "archives"),
        ],
    )
    return runtime, modern, archived


async def test_real_archived_lineage_resumes_once_and_recalls_each_function(database, host, legacy):
    runtime, modern, archive = legacy
    before = modern.read_bytes()
    tasks = await invoke(database, ["migration", "read", "--archive-id", archive["id"]])
    assert tasks["total"] == 2 and [row["status"] for row in tasks["records"]] == [
        "waiting",
        "succeeded",
    ]
    assert (await invoke(database, ["context", "show"]))["tasks"] == []
    current = await invoke(
        database,
        [
            "migration",
            "resume",
            "--archive-id",
            archive["id"],
            "--key",
            "imported-task",
            "--workflow-key",
            "old-flow",
        ],
    )
    again = await invoke(
        database, ["migration", "resume", "--archive-id", archive["id"], "--key", "imported-task"]
    )
    assert again["task_id"] == current["task_id"] and current["status"] == "active"
    context = await invoke(database, ["context", "show"])
    assert context["tasks"][0]["required_result"].startswith("Preserve original artifact")
    assert context["workflows"][0]["next_phase"]["key"] == "legacy-2"
    for category in ("sources", "enclave", "messages", "learning", "memory", "workflows"):
        page = await invoke(
            database,
            [
                "migration",
                "read",
                "--archive-id",
                archive["id"],
                "--section",
                category,
                "--limit",
                "1",
            ],
        )
        record = page["records"][0]
        recalled = await invoke(
            database,
            [
                "migration",
                "recall",
                "--archive-id",
                archive["id"],
                "--section",
                category,
                "--key",
                record["key"],
                "--task-id",
                current["task_id"],
            ],
        )
        repeat = await invoke(
            database,
            [
                "migration",
                "recall",
                "--archive-id",
                archive["id"],
                "--section",
                category,
                "--key",
                record["key"],
                "--task-id",
                current["task_id"],
            ],
        )
        assert recalled["memory_id"] == repeat["memory_id"]
        memory = await invoke(database, ["memory", "read", "--memory-id", recalled["memory_id"]])
        assert "current_validity" in memory["content"] and memory["kind"] == "artifact"
    context = await invoke(database, ["context", "show"])
    assert all(fact["kind"] == "assumption" for item in context["facts"] for fact in item["facts"])
    assert (await invoke(database, ["context", "show", "--section", "memory"]))[
        "applied_lessons"
    ] == []
    assert modern.read_bytes() == before
    raw = PosixHistoricalStoreService().read(str(runtime), "messages")
    assert raw.records[0].status == "unread"
    # A second physical source of the same work uses preserved original lineage.
    other = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(runtime),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(runtime.parent / "archives"),
        ],
    )
    second = await invoke(
        database, ["migration", "resume", "--archive-id", other["id"], "--key", "old-task"]
    )
    assert second["task_id"] == current["task_id"]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM core_tasks").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM core_messages").fetchone()[0] == 0


async def test_historical_read_pages_unknowns_and_duplicate_prepare(
    database, host, legacy, tmp_path
):
    runtime, modern, archive = legacy
    again = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(modern),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(tmp_path / "archives"),
        ],
    )
    assert archive["id"] == again["id"]
    before = database.read_bytes()
    page = await invoke(
        database, ["migration", "read", "--archive-id", archive["id"], "--limit", "1"]
    )
    assert page["total"] is None and page["next_offset"] == 1
    tail = await invoke(
        database,
        ["migration", "read", "--archive-id", archive["id"], "--offset", "1", "--limit", "1"],
    )
    assert tail["total"] == 2 and tail["next_offset"] is None
    unknown = await invoke(
        database,
        [
            "migration",
            "read",
            "--archive-id",
            archive["id"],
            "--section",
            "unknown",
            "--limit",
            "100",
        ],
    )
    assert any(
        row["key"] == "opaque_table" and row["data"]["rows"] == 1 for row in unknown["records"]
    )
    assert database.read_bytes() == before
    assert (await invoke(database, ["migration", "inspect", "--source", str(runtime)]))[
        "format"
    ] == "runtime-store"
    opaque = tmp_path / "opaque.sqlite3"
    with sqlite3.connect(opaque) as db:
        db.execute("CREATE TABLE unmapped(id INTEGER)")
        db.execute("INSERT INTO unmapped VALUES(1)")
    store = PosixHistoricalStoreService()
    assert store.inspect(str(opaque)).format == "unknown"
    with pytest.raises(ValueError, match="projection"):
        store.read(str(opaque), "tasks")
    assert store.read(str(opaque), "unknown").records[0].data["rows"] == 1
    with pytest.raises(ValueError, match="section"):
        store.read(str(runtime), "invalid")
    with pytest.raises(ValueError, match="section"):
        store.read(str(runtime), "tasks", limit=0)
    with pytest.raises(ValueError, match="configuration"):
        store.snapshot(str(runtime), str(tmp_path / "unused"), [str(tmp_path)])


async def test_new_records_survive_recovery_and_legacy_target_is_not_overwritten(
    database, host, legacy, tmp_path
):
    _, modern, archive = legacy
    await invoke(
        database, ["migration", "resume", "--archive-id", archive["id"], "--key", "imported-task"]
    )
    checkpoint = await invoke(
        database,
        [
            "memory",
            "checkpoint",
            "--content",
            "New post-migration record",
            "--reference",
            "fixture:150",
        ],
    )
    recovered = tmp_path / "recovered.sqlite3"
    result = await invoke(
        database,
        ["migration", "recover", "--source", str(database), "--destination", str(recovered)],
    )
    assert not result["legacy_rollback"] and not result["activated"]
    assert (
        checkpoint["id"]
        in (await invoke(recovered, ["memory", "search", "--text", "post-migration"]))["memory_ids"]
    )
    assert len((await invoke(recovered, ["context", "show"]))["tasks"]) == 1
    before = modern.read_bytes()
    await invoke(
        database,
        ["migration", "recover", "--source", str(database), "--destination", str(modern)],
        succeeds=False,
    )
    await invoke(
        database,
        [
            "migration",
            "recover",
            "--source",
            str(modern),
            "--destination",
            str(tmp_path / "wrong.sqlite3"),
        ],
        succeeds=False,
    )
    assert modern.read_bytes() == before and not (tmp_path / "wrong.sqlite3").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--key", "missing"],
        ["--key", "done-task"],
        ["--key", "imported-task", "--workflow-key", "missing"],
        ["--key", "imported-task", "--workflow-key", "phase-1-missing"],
    ],
)
async def test_invalid_historical_selection_never_mutates_current_work(
    database, host, legacy, arguments
):
    archive = legacy[2]
    before = database.read_bytes()
    await invoke(
        database, ["migration", "resume", "--archive-id", archive["id"], *arguments], succeeds=False
    )
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "section,key",
    [("tasks", "imported-task"), ("unknown", "opaque_table"), ("messages", "missing")],
)
async def test_invalid_recall_preserves_current_context(database, host, legacy, section, key):
    before = database.read_bytes()
    await invoke(
        database,
        [
            "migration",
            "recall",
            "--archive-id",
            legacy[2]["id"],
            "--section",
            section,
            "--key",
            key,
        ],
        succeeds=False,
    )
    assert database.read_bytes() == before


def test_archive_corruption_and_structured_unknowns_are_not_empty_success(legacy, tmp_path):
    runtime, modern, _ = legacy
    store = PosixHistoricalStoreService()
    unsupported = tmp_path / "unsupported.sqlite3"
    build_modern(unsupported, runtime, storage="unrecognized")
    with pytest.raises(ValueError, match="unrecognized"):
        store.read(str(unsupported), "messages")
    assert any(
        row.status == "unrecognized archive encoding"
        for row in store.read(str(unsupported), "unknown", limit=100).records
    )
    with sqlite3.connect(modern) as db:
        db.execute("UPDATE source_archives SET data=json_set(data,'$.size',0)")
    with pytest.raises(ValueError, match="recorded content"):
        store.read(str(modern), "messages")
    with sqlite3.connect(runtime) as db:
        db.execute("UPDATE runtime_records SET payload='not-json' WHERE namespace='task-ledger'")
    with pytest.raises(ValueError, match="unrecognized"):
        store.read(str(runtime), "tasks")
    with sqlite3.connect(runtime) as db:
        db.execute("UPDATE runtime_records SET payload='{}' WHERE namespace='task-ledger'")
    with pytest.raises(ValueError, match="shape"):
        store.read(str(runtime), "tasks")
    with pytest.raises(ValueError, match="cell"):
        store._cell(["unknown", "preserved"])


async def transition_service(database):
    from neurath.application.ports.services.store_transition import IStoreTransitionService
    from neurath.infrastructure.database import sqlite_url
    from tests.support.application import request_application

    async with request_application(sqlite_url(database, "rw")) as application:
        return application.container.get(IStoreTransitionService)


async def test_wal_snapshot_preserves_committed_rows_and_open_writer_blocks_fence(
    database, tmp_path
):
    import subprocess
    import sys

    runtime = tmp_path / "wal-runtime.sqlite3"
    build_runtime(runtime)
    code = """import sqlite3,sys
connection=sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA journal_mode=WAL')
connection.execute("INSERT INTO events VALUES(2,'event-2','codex','old-session','prompt','During snapshot','{}')")
connection.commit()
print('ready',flush=True)
sys.stdin.readline()
connection.close()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(runtime)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        store = PosixHistoricalStoreService()
        snapshot = store.snapshot(str(runtime), str(tmp_path / "backups"), ())
        assert snapshot.inspection.wal_present
        with sqlite3.connect(snapshot.path) as copied:
            assert copied.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        manifest = json.loads((Path(snapshot.path).parent / "files.json").read_text())
        assert any(item["source"].endswith("-wal") for item in manifest["files"])
        service = await transition_service(database)
        with pytest.raises(ValueError, match="connections"):
            service.fence(str(runtime), str(tmp_path / "backups"))
        assert runtime.is_file() and not runtime.is_symlink()
    finally:
        child.communicate("close\n", timeout=10)
    fence = service.fence(str(runtime), str(tmp_path / "backups"))
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(runtime)
    with sqlite3.connect(fence.snapshot) as preserved:
        assert preserved.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    assert service.fence(str(runtime), str(tmp_path / "backups")).directory == fence.directory


async def test_late_legacy_writer_connection_cannot_write_retired_inode(
    database, tmp_path, monkeypatch
):
    import subprocess
    import sys

    runtime = tmp_path / "late-runtime.sqlite3"
    build_runtime(runtime)
    service = await transition_service(database)
    original = service._seal
    children = []
    code = """import sqlite3,sys,json
connection=sqlite3.connect(sys.argv[1],timeout=1)
print('connected',flush=True)
sys.stdin.readline()
try:
 connection.execute("INSERT INTO events VALUES(9,'late','codex','old-session','prompt','must not commit','{}')")
 connection.commit()
 print(json.dumps({'wrote':True}),flush=True)
except sqlite3.Error as error:
 print(json.dumps({'wrote':False,'error':error.sqlite_errorname}),flush=True)
connection.close()
"""

    def late_connection(path, snapshot):
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        children.append(child)
        assert child.stdout.readline().strip() == "connected"
        return original(path, snapshot)

    monkeypatch.setattr(service, "_seal", late_connection)
    try:
        fence = service.fence(str(runtime), str(tmp_path / "backups"))
        output, _ = children[0].communicate("write\n", timeout=10)
        observation = json.loads(output)
        assert observation["wrote"] is False
        assert observation["error"] in {
            "SQLITE_READONLY_DBMOVED",
            "SQLITE_CANTOPEN",
            "SQLITE_CANTOPEN_ISDIR",
        }
        with sqlite3.connect(fence.retired) as db:
            assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


async def test_unobserved_writer_or_snapshot_race_never_switches_source(
    database, tmp_path, monkeypatch
):
    import subprocess

    runtime = tmp_path / "runtime.sqlite3"
    build_runtime(runtime)
    service = await transition_service(database)
    original = runtime.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(
            "neurath.infrastructure.services.store_transition.shutil.which", lambda name: None
        )
        with pytest.raises(ValueError, match="observe"):
            service.fence(str(runtime), str(tmp_path / "backups"))
    with monkeypatch.context() as patch:
        patch.setattr(
            "neurath.infrastructure.services.store_transition.subprocess.run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args, 2, "", "observation failed"),
        )
        with pytest.raises(ValueError, match="observation"):
            service.fence(str(runtime), str(tmp_path / "backups"))
    assert runtime.read_bytes() == original
    snapshot = service.historical.snapshot

    def change_after_snapshot(*args):
        result = snapshot(*args)
        with sqlite3.connect(runtime) as db:
            db.execute(
                "INSERT INTO events VALUES(3,'new','codex','old-session','prompt','Arrived during preparation','{}')"
            )
        return result

    with monkeypatch.context() as patch:
        patch.setattr(service.historical, "snapshot", change_after_snapshot)
        with pytest.raises(ValueError, match="changed after snapshot"):
            service.fence(str(runtime), str(tmp_path / "backups"))
    assert runtime.is_file() and not runtime.is_symlink()
    with sqlite3.connect(runtime) as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 2


async def test_actual_hook_queue_replay_is_ordered_idempotent_and_keeps_recovery_tools(
    database, host, tmp_path
):
    import json

    task = await invoke(
        database,
        ["task", "create", "--title", "Existing work", "--result", "Preserve pending result"],
    )
    service = await transition_service(database)
    fence = service.fence(str(database), str(tmp_path / "backups"))
    payload = host[2]
    for text in ("First transition input", "Second transition input"):
        queued = await invoke(
            database,
            ["hook", "handle", "--provider", "codex"],
            json.dumps(dict(payload, prompt=text)),
        )
        assert "ordinary host tools remain available" in queued["systemMessage"]
    stopped = await invoke(
        database,
        ["hook", "handle", "--provider", "codex"],
        json.dumps(dict(payload, hook_event_name="Stop")),
    )
    assert "return control to the user" in stopped["systemMessage"]
    assert "decision" not in stopped and "continue" not in stopped
    assert len(service.pending(fence.directory)) == 3
    restored = tmp_path / "recovered.sqlite3"
    await invoke(
        database,
        ["migration", "recover", "--source", fence.snapshot, "--destination", str(restored)],
    )
    result = await invoke(restored, ["migration", "replay", "--directory", fence.directory])
    assert result == {"applied": 3, "remaining": 0, "host_delivery": "unverified"}
    context = await invoke(restored, ["context", "show"])
    assert [item["id"] for item in context["tasks"]] == [task["id"]]
    sources = (await invoke(restored, ["context", "show", "--section", "sources"]))["sources"]
    assert [item["body"] for item in sources if item["body"].endswith("transition input")] == [
        "First transition input",
        "Second transition input",
    ]
    ack = Path(fence.directory) / "applied.jsonl"
    ack.write_text("\n".join(ack.read_text().splitlines()[:1]) + "\n")
    before = restored.read_bytes()
    assert (await invoke(restored, ["migration", "replay", "--directory", fence.directory]))[
        "applied"
    ] == 2
    assert restored.read_bytes() == before
    assert (await invoke(restored, ["migration", "replay", "--directory", fence.directory]))[
        "applied"
    ] == 0


async def test_queued_monitor_remains_pending_instead_of_becoming_user_goal(
    database, host, tmp_path
):
    import json

    service = await transition_service(database)
    fence = service.fence(str(database), str(tmp_path / "backups"))
    payload = dict(host[2], prompt="NEURATH_MONITOR_TICK 00000000-0000-4000-8000-000000000001 1")
    queued = await invoke(database, ["hook", "handle", "--provider", "codex"], json.dumps(payload))
    assert queued["continue"] is False
    restored = tmp_path / "recovered.sqlite3"
    await invoke(
        database,
        ["migration", "recover", "--source", fence.snapshot, "--destination", str(restored)],
    )
    before = restored.read_bytes()
    await invoke(restored, ["migration", "replay", "--directory", fence.directory], succeeds=False)
    assert restored.read_bytes() == before and len(service.pending(fence.directory)) == 1


async def test_transition_unknowns_and_settings_snapshot_identity(database, host, legacy, tmp_path):
    from sqlalchemy.engine import make_url

    from neurath.infrastructure.services.store_transition import PosixStoreTransitionService

    service = await transition_service(database)
    assert service.pending(service.fence(str(legacy[0]), str(tmp_path / "backups")).directory) == ()
    unknown = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(unknown) as db:
        db.execute("CREATE TABLE other_data(value TEXT)")
    with pytest.raises(ValueError, match="Unrecognized"):
        service.fence(str(unknown), str(tmp_path / "backups"))
    invalid = tmp_path / "invalid-transition"
    invalid.mkdir()
    (invalid / "transition.json").write_text('{"format":"other"}')
    with pytest.raises(ValueError, match="Unrecognized"):
        service.pending(str(invalid))
    for url in ("postgresql://localhost/store", "sqlite+aiosqlite://"):
        with pytest.raises(ValueError, match="SQLite"):
            PosixStoreTransitionService._path_for(make_url(url))
    config = tmp_path / "settings.json"
    config.write_text('{"user_setting":"preserve"}')
    first = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(legacy[1]),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(tmp_path / "archives"),
            "--config",
            str(config),
        ],
    )
    config.write_text('{"user_setting":"updated"}')
    second = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(legacy[1]),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(tmp_path / "archives"),
            "--config",
            str(config),
        ],
    )
    assert first["id"] != second["id"]
    originals = list(Path(first["snapshot"]).parent.glob("original-*-settings.json"))
    assert json.loads(originals[0].read_text())["user_setting"] == "preserve"


async def test_historical_ports_and_adoption_invariants():
    from uuid import uuid7

    from neurath.application.ports.repositories.historical_archive import (
        IHistoricalArchiveRepository,
    )
    from neurath.application.ports.services.historical_store import IHistoricalStoreService
    from neurath.application.ports.services.store_transition import IStoreTransitionService
    from neurath.domain.aggregates.historical_archive import HistoricalArchive

    for method, arguments in [
        (IHistoricalStoreService.inspect, (None, "source")),
        (IHistoricalStoreService.snapshot, (None, "source", "directory", ())),
        (IHistoricalStoreService.read, (None, "source", "tasks")),
        (IStoreTransitionService.fence, (None, "source", "directory")),
        (IStoreTransitionService.enqueue, (None, {}, {})),
        (IStoreTransitionService.pending, (None, "directory")),
        (IStoreTransitionService.acknowledge, (None, "directory", uuid7())),
    ]:
        with pytest.raises(NotImplementedError):
            method(*arguments)
    for method, arguments in [
        (IHistoricalStoreService.recover, (None, "source", "destination")),
        (IHistoricalArchiveRepository.find_by_source_path_and_digest, (None, "source", "digest")),
        (IHistoricalArchiveRepository.find_by_directory_and_origin, (None, "directory", "origin")),
    ]:
        with pytest.raises(NotImplementedError):
            await method(*arguments)
    archive = HistoricalArchive(
        uid=uuid7(),
        directory="project",
        source_path="original",
        snapshot_path="copy",
        digest="digest",
        format="unknown",
        tables=(),
    )
    task_id = uuid7()
    archive.adopt("first", task_id)
    archive.adopt("first", task_id)
    assert len(archive.adoptions) == 1
    with pytest.raises(ValueError, match="already"):
        archive.adopt("first", uuid7())
    archive.adopt("second", uuid7())
    assert len(archive.adoptions) == 2


async def test_cli_fence_and_populated_downgrade_preserve_originals(
    database, host, legacy, tmp_path
):
    from alembic import command

    from neurath.infrastructure.database import create_database_engine
    from tests.test_task_migrations import migration_config

    result = await invoke(
        database,
        [
            "migration",
            "fence",
            "--source",
            str(legacy[0]),
            "--archive-directory",
            str(tmp_path / "fence"),
        ],
    )
    assert Path(result["retired"]).is_file()
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="must be preserved"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda db: command.downgrade(migration_config(db), "core_0014")
                )
    finally:
        await engine.dispose()
    assert (await invoke(database, ["migration", "read", "--archive-id", legacy[2]["id"]]))[
        "total"
    ] == 2


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("UPDATE tasks SET goal=''", "no interpretable goal"),
        (
            "UPDATE records SET data=json_set(data,'$.state.original_task.definition.dependencies',json('[\"prior-task\"]')) WHERE kind='checkpoint'",
            "dependencies",
        ),
    ],
)
async def test_incomplete_historical_definition_is_not_invented(
    database, host, legacy, mutation, error
):
    with sqlite3.connect(legacy[2]["snapshot"]) as db:
        db.execute(mutation)
    before = database.read_bytes()
    response = await invoke(
        database,
        ["migration", "resume", "--archive-id", legacy[2]["id"], "--key", "imported-task"],
        succeeds=False,
    )
    assert error in str(response.exception)
    assert database.read_bytes() == before


async def test_original_definition_without_source_or_phases_is_preserved(database, host, legacy):
    with sqlite3.connect(legacy[2]["snapshot"]) as db:
        db.execute("DELETE FROM records WHERE kind='source'")
        db.execute("DELETE FROM task_phases")
    result = await invoke(
        database, ["migration", "resume", "--archive-id", legacy[2]["id"], "--key", "imported-task"]
    )
    context = await invoke(database, ["context", "show"])
    assert result["status"] == "active" and not context["workflows"]
    sources = await invoke(database, ["context", "show", "--section", "sources"])
    assert any('"original_user_source": "unknown"' in item["body"] for item in sources["sources"])
    recalled = await invoke(
        database,
        [
            "migration",
            "recall",
            "--archive-id",
            legacy[2]["id"],
            "--section",
            "memory",
            "--key",
            "artifact-1",
        ],
    )
    memory = await invoke(database, ["memory", "read", "--memory-id", recalled["memory_id"]])
    assert "sqlite_blob_base64" in memory["content"]


async def test_historical_archive_scope_and_missing_records_fail_without_work(
    database, host, legacy, tmp_path
):
    from uuid import UUID, uuid7

    from neurath.application.usecases.read_historical_records import (
        ReadHistoricalRecordsQuery,
        ReadHistoricalRecordsUseCase,
    )
    from neurath.infrastructure.database import sqlite_url
    from tests.support.application import request_application

    await invoke(database, ["migration", "read", "--archive-id", str(uuid7())], succeeds=False)
    async with request_application(sqlite_url(database, "rw")) as app:
        with pytest.raises(ValueError, match="page"):
            await app.container.get(ReadHistoricalRecordsUseCase).run(
                ReadHistoricalRecordsQuery(
                    archive_id=UUID(legacy[2]["id"]), category="tasks", offset=-1
                )
            )
    other = tmp_path / "other-project"
    other.mkdir()
    await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(legacy[1]),
            "--directory",
            str(other),
            "--archive-directory",
            str(tmp_path / "copies"),
        ],
        succeeds=False,
    )
    with sqlite3.connect(database) as db:
        db.execute("UPDATE core_historical_archives SET directory=?", (str(other),))
    before = database.read_bytes()
    await invoke(
        database,
        ["migration", "resume", "--archive-id", legacy[2]["id"], "--key", "imported-task"],
        succeeds=False,
    )
    await invoke(
        database,
        [
            "migration",
            "recall",
            "--archive-id",
            legacy[2]["id"],
            "--section",
            "messages",
            "--key",
            "message-1",
        ],
        succeeds=False,
    )
    assert database.read_bytes() == before


def test_unknown_schema_and_typed_historical_values_are_explicit(tmp_path):
    from uuid import uuid7

    from neurath.serialization import encode_historical

    runtime, modern = tmp_path / "runtime.sqlite3", tmp_path / "modern.sqlite3"
    build_runtime(runtime)
    build_modern(modern, runtime)
    with sqlite3.connect(modern) as db:
        db.execute("UPDATE alembic_version SET version_num='future'")
    store = PosixHistoricalStoreService()
    assert store.inspect(str(modern)).format == "unknown"
    with pytest.raises(ValueError, match="cell type"):
        store._cell(["unknown", "original"])
    assert store._cell(["real", (1.5).hex()]) == 1.5
    assert encode_historical(uuid7())
    with pytest.raises(TypeError):
        encode_historical(object())
    assert (
        store._runtime({"runtime_records": [{"namespace": "unrelated"}]}, "tasks", "original") == []
    )
    assert (
        store._modern({"records": [{"kind": "unrelated", "data": "{}"}]}, "sources", "original")
        == []
    )


async def test_historical_workflow_without_phases_and_unobserved_execution(
    database, host, legacy, tmp_path
):
    runtime = legacy[0]
    with sqlite3.connect(runtime) as db:
        db.execute(
            "UPDATE runtime_records SET payload=json_set(payload,'$.workflows.old-flow.payload.phase_run.phases',json('[]')) WHERE namespace='session'"
        )
    archive = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(runtime),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(tmp_path / "copies"),
        ],
    )
    before = database.read_bytes()
    response = await invoke(
        database,
        [
            "migration",
            "resume",
            "--archive-id",
            archive["id"],
            "--key",
            "old-task",
            "--workflow-key",
            "old-flow",
        ],
        succeeds=False,
    )
    assert "no interpretable phases" in str(response.exception)
    assert database.read_bytes() == before
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM core_executions")
    before = database.read_bytes()
    response = await invoke(
        database,
        ["migration", "resume", "--archive-id", archive["id"], "--key", "old-task"],
        succeeds=False,
    )
    assert "execution has not been observed" in str(response.exception)
    assert database.read_bytes() == before


async def test_historical_success_requires_current_prerequisite_verification(
    database, host, legacy
):
    with sqlite3.connect(legacy[2]["snapshot"]) as db:
        db.execute(
            "UPDATE records SET data=json_set(data,'$.state.original_task.definition.dependencies',json('[\"done-task\"]')) WHERE kind='checkpoint'"
        )
    current = await invoke(
        database, ["migration", "resume", "--archive-id", legacy[2]["id"], "--key", "imported-task"]
    )
    context = await invoke(database, ["context", "show"])
    assert current["status"] == "active"
    assert context["workflows"][0]["next_phase"]["key"] == "historical-prerequisite-1"
    assert context["workflows"][0]["next_phase"]["checks"] == ["prerequisite-valid"]
    assert len(context["tasks"]) == 1
    assert (
        "historical success is not current verification" in context["tasks"][0]["required_result"]
    )


async def test_unfinished_prerequisite_maps_to_existing_task_without_success(
    database, host, legacy, tmp_path
):
    runtime = legacy[0]
    with sqlite3.connect(runtime) as db:
        ledger = json.loads(
            db.execute(
                "SELECT payload FROM runtime_records WHERE namespace='task-ledger'"
            ).fetchone()[0]
        )
        ledger["tasks"][0]["definition"]["dependencies"] = ["done-task"]
        ledger["tasks"][1]["status"] = "pending"
        db.execute(
            "UPDATE runtime_records SET payload=? WHERE namespace='task-ledger'",
            (json.dumps(ledger),),
        )
    archive = await invoke(
        database,
        [
            "migration",
            "prepare",
            "--source",
            str(runtime),
            "--directory",
            str(host[0]),
            "--archive-directory",
            str(tmp_path / "copies"),
        ],
    )
    response = await invoke(
        database,
        ["migration", "resume", "--archive-id", archive["id"], "--key", "old-task"],
        succeeds=False,
    )
    assert "prerequisite first" in str(response.exception)
    prerequisite = await invoke(
        database, ["migration", "resume", "--archive-id", archive["id"], "--key", "done-task"]
    )
    dependent = await invoke(
        database, ["migration", "resume", "--archive-id", archive["id"], "--key", "old-task"]
    )
    assert prerequisite["status"] == "active" and dependent["status"] == "pending"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM core_tasks").fetchone()[0] == 2
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT prerequisite_id FROM core_task_dependencies WHERE task_id=?",
            (dependent["task_id"].replace("-", ""),),
        ).fetchone()[0] == prerequisite["task_id"].replace("-", "")


async def test_nonidentifier_historical_dependency_is_preserved(database, host, legacy):
    with sqlite3.connect(legacy[2]["snapshot"]) as db:
        db.execute(
            "UPDATE records SET data=json_set(data,'$.state.original_task.definition.dependencies',json('[{}]')) WHERE kind='checkpoint'"
        )
    before = database.read_bytes()
    response = await invoke(
        database,
        ["migration", "resume", "--archive-id", legacy[2]["id"], "--key", "imported-task"],
        succeeds=False,
    )
    assert "identifier is unrecognized" in str(response.exception)
    assert database.read_bytes() == before


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
async def test_repeated_transition_stop_returns_control_without_completion(
    database, host, tmp_path, provider, event
):
    task = await invoke(
        database,
        ["task", "create", "--title", "Unfinished transition work", "--result", "Still required"],
    )
    service = await transition_service(database)
    fence = service.fence(str(database), str(tmp_path / "backups"))
    original = Path(fence.snapshot).read_bytes()
    for number in range(3):
        payload = dict(host[2], hook_event_name=event, marker=f"original-{number}")
        response = await invoke(
            database, ["hook", "handle", "--provider", provider], json.dumps(payload)
        )
        assert set(response) == {"systemMessage"}
        assert "without another recovery turn" in response["systemMessage"]
        assert "not task completion" in response["systemMessage"]
    pending = service.pending(fence.directory)
    assert [item.payload["marker"] for item in pending] == [
        f"original-{number}" for number in range(3)
    ]
    assert all(item.command["event"] in {"Stop", "SubagentStop"} for item in pending)
    assert Path(fence.snapshot).read_bytes() == original
    with sqlite3.connect(fence.snapshot) as db:
        assert (
            db.execute(
                "SELECT status FROM core_tasks WHERE id=?", (task["id"].replace("-", ""),)
            ).fetchone()[0]
            == "pending"
        )
    assert not (Path(fence.directory) / "applied.jsonl").exists()
