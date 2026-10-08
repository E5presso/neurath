"""Preserve SQLite data without executing source SQL or adopting source authority.

This adapter understands data envelopes, not legacy implementation behavior. Every
cell, including unknown tables and arbitrary BLOBs, is retained in a typed archive.
Only unfinished task descriptions become new waiting work; prior claims, approval
records, and tool results remain historical data.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from neurath.domain.models import Checkpoint, Criterion, Session, Source, Task


class LegacyImportError(ValueError):
    """A snapshot is inconsistent, corrupt, or cannot be safely normalized."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identifier(*parts: str) -> str:
    return "legacy-" + digest(list(parts))


def encode_cell(value: Any) -> list[Any]:
    if value is None:
        return ["null", None]
    if isinstance(value, bytes):
        return ["blob", base64.b64encode(value).decode("ascii")]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    raise LegacyImportError("Unsupported SQLite cell type")


def decode_cell(cell: list[Any]) -> Any:
    kind, value = cell
    if kind == "null":
        return None
    if kind == "blob":
        return base64.b64decode(value, validate=True)
    if kind == "integer":
        return int(value)
    if kind == "real":
        return float.fromhex(value)
    if kind == "text":
        return value
    raise LegacyImportError("Unknown archived SQLite cell type")


def _file_state(path: Path) -> dict[str, Any]:
    result = {}
    for label, candidate in (("main", path), ("wal", Path(str(path) + "-wal"))):
        if candidate.is_file():
            with candidate.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            result[label] = {"sha256": checksum, "size": candidate.stat().st_size}
    return result


def capture_sqlite(path: str | Path, *, source_id: str | None = None) -> dict[str, Any]:
    """Capture one stable read-only transaction. Never open a retired directory.

    Use source_id for the original database identity when reading a backup copy.
    The main/WAL checksums reject concurrent mutation; retry only after quiescing
    the source. Source schema is inert archive text and is never executed.
    """
    path = Path(path).resolve()
    if not path.is_file():
        raise LegacyImportError("Legacy SQLite source must be an existing regular file")
    before = _file_state(path)
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise LegacyImportError("Legacy SQLite integrity check failed")
            schema = [dict(zip(("type", "name", "table", "sql"), row)) for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
            tables = []
            for item in schema:
                if item["type"] != "table":
                    continue
                name = '"' + item["name"].replace('"', '""') + '"'
                cursor = connection.execute("SELECT * FROM " + name)
                columns = [column[0] for column in cursor.description]
                rows = [[encode_cell(cell) for cell in row] for row in cursor]
                # Implicit row identity is data too (including tables without a
                # declared primary key). Preserve it when SQLite exposes it.
                rowid_alias = next((alias for alias in ("rowid", "_rowid_", "oid")
                                    if alias not in {column.lower() for column in columns}), None)
                rowids = None
                if rowid_alias is not None:
                    try:
                        paired = list(connection.execute("SELECT " + rowid_alias + ", * FROM " + name))
                        rowids = [encode_cell(row[0]) for row in paired]
                        rows = [[encode_cell(cell) for cell in row[1:]] for row in paired]
                    except sqlite3.OperationalError:
                        pass  # WITHOUT ROWID tables have their declared key.
                indexed = sorted(zip(rows, rowids or [None] * len(rows)), key=canonical)
                table = {"name": item["name"], "columns": columns,
                         "rows": [pair[0] for pair in indexed],
                         "rowids": [pair[1] for pair in indexed] if rowids is not None else None}
                table["sha256"] = digest(table)
                tables.append(table)
            pragmas = {key: connection.execute("PRAGMA " + key).fetchone()[0]
                       for key in ("user_version", "application_id", "encoding")}
            connection.rollback()
    except (sqlite3.Error, OSError) as exc:
        raise LegacyImportError("Cannot capture a valid SQLite source") from exc
    if before != _file_state(path):
        raise LegacyImportError("Legacy database changed while capturing snapshot")
    result = {"source_id": source_id or str(path), "source_path": str(path),
              "files": before, "schema": schema, "pragmas": pragmas, "tables": tables}
    result["sha256"] = digest(result)
    return result


def _rows(snapshot: dict[str, Any], table_name: str) -> Iterable[dict[str, Any]]:
    for table in snapshot["tables"]:
        if table["name"] == table_name:
            for row in table["rows"]:
                yield dict(zip(table["columns"], (decode_cell(cell) for cell in row)))


def _json(value: Any) -> Any:
    try:
        return json.loads(value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise LegacyImportError("Malformed legacy task JSON") from exc


def _task_envelopes(snapshot: dict[str, Any]) -> Iterable[tuple[str, str, str, dict[str, Any]]]:
    for row in _rows(snapshot, "runtime_records"):
        payload = row.get("payload")
        if isinstance(payload, str):
            payload = payload.encode()
        if not isinstance(payload, bytes) or hashlib.sha256(payload).hexdigest() != row.get("digest"):
            raise LegacyImportError("Legacy runtime record digest mismatch")
        if row.get("namespace") != "task-ledger":
            continue
        ledger = _json(payload)
        if not isinstance(ledger, dict) or not isinstance(ledger.get("tasks"), list):
            raise LegacyImportError("Unrecognized task-ledger data envelope")
        for task in ledger["tasks"]:
            yield str(row["key"]), ledger.get("owner", ""), ledger.get("session", ""), task
    # Alternate fixture format: tasks(payload JSON), with optional owner/session
    # columns. A generic tasks table without a JSON payload is archived only.
    for row in _rows(snapshot, "tasks"):
        payload_column = next((name for name in ("payload", "data") if name in row), None)
        if payload_column is None:
            continue
        task = _json(row[payload_column])
        if not isinstance(task, dict):
            raise LegacyImportError("Legacy task payload must be an object")
        yield "tasks", task.get("owner_id", row.get("owner_id", row.get("owner", ""))), task.get("session_id", row.get("session_id", row.get("session", ""))), task


def _normalize(snapshot: dict[str, Any]) -> tuple[dict[str, list[dict]], Counter]:
    records: dict[str, list[dict]] = {"task": [], "source": [], "checkpoint": [], "session": []}
    states: Counter = Counter()
    for ledger_key, owner, session, legacy in _task_envelopes(snapshot):
        if not isinstance(legacy, dict):
            raise LegacyImportError("Legacy task must be an object")
        status = legacy.get("status", legacy.get("state"))
        if not isinstance(status, str) or not status:
            raise LegacyImportError("Legacy task status is missing")
        states[status] += 1
        # Failed and invalidated are unfinished obligations. Only explicit
        # completion/withdrawal statuses are history-only.
        if status in {"succeeded", "completed", "withdrawn", "cancelled", "canceled"}:
            continue
        if not isinstance(owner, str) or not owner.strip():
            raise LegacyImportError("Unfinished legacy task has no original owner")
        old_id = legacy.get("id")
        if not isinstance(old_id, str) or not old_id:
            raise LegacyImportError("Unfinished legacy task has no stable identity")
        task_id = identifier(snapshot["source_id"], ledger_key, old_id)
        definition = legacy.get("definition", legacy)
        if not isinstance(definition, dict):
            raise LegacyImportError("Legacy task definition must be an object")
        goal = definition.get("goal", definition.get("title", ""))
        if not isinstance(goal, str) or not goal.strip():
            raise LegacyImportError("Unfinished legacy task has no goal")
        acceptance = definition.get("acceptance", [])
        if not isinstance(acceptance, list):
            raise LegacyImportError("Legacy acceptance must be a list")
        criteria = [Criterion(id=identifier(task_id, "criterion", str(index)),
                              description=item if isinstance(item, str) else canonical(item))
                    for index, item in enumerate(acceptance)]
        if not criteria:
            criteria = [Criterion(id=identifier(task_id, "criterion", "review"),
                                  description="Original owner must establish acceptance criteria from retained source")]
        text = canonical({"legacy_sources": definition.get("sources", []), "task": legacy})
        source = Source(id=identifier(task_id, "source"), session_id=owner,
                        event_id=identifier(task_id, "legacy-record"), text=text,
                        digest=hashlib.sha256(text.encode()).hexdigest(), source_type="legacy-import")
        task = Task(id=task_id, owner_id=owner, source_id=source.id, goal=goal,
                    criteria=criteria, status="waiting",
                    wait_reason=f"Recovered unfinished legacy obligation; original status={status}; original owner review required")
        checkpoint = Checkpoint(id=identifier(task_id, "provenance"), task_id=task_id,
                                actor_id=owner, task_revision=0,
                                note="Imported historical data; no new verification, approval, or writer authority",
                                state={"source_id": snapshot["source_id"], "ledger_key": ledger_key,
                                       "original_task_id": old_id, "original_status": status,
                                       "original_owner": owner, "original_session": session,
                                       "original_task": legacy})
        owner_session = Session(id=owner, host="legacy-import", native_id=str(session), status="legacy-unknown")
        records["session"].append(owner_session.to_dict())
        records["task"].append(task.to_dict())
        records["source"].append(source.to_dict())
        records["checkpoint"].append(checkpoint.to_dict())
    return records, states


def prepare_import(sources: Iterable[str | Path | tuple[str | Path, str]]) -> dict[str, Any]:
    """Prepare a reviewable immutable archive and deterministic import records."""
    snapshots = []
    records: dict[str, list[dict]] = {"task": [], "source": [], "checkpoint": [], "session": []}
    states: Counter = Counter()
    seen_sources = set()
    for source in sources:
        path, source_id = source if isinstance(source, tuple) else (source, None)
        snapshot = capture_sqlite(path, source_id=source_id)
        if snapshot["source_id"] in seen_sources:
            raise LegacyImportError("Duplicate source database identity")
        seen_sources.add(snapshot["source_id"])
        snapshots.append(snapshot)
        normalized, counts = _normalize(snapshot)
        states.update(counts)
        for kind, values in normalized.items():
            records[kind].extend(values)
    if not snapshots:
        raise LegacyImportError("At least one source database is required")
    snapshots.sort(key=lambda item: item["source_id"])
    for kind, values in records.items():
        values.sort(key=lambda item: item["id"])
        if kind == "session":
            owners = {}
            for value in values:
                if value["id"] in owners and owners[value["id"]] != value:
                    raise LegacyImportError("Original owner has conflicting legacy session identities")
                owners[value["id"]] = value
            records[kind] = list(owners.values())
        elif len({item["id"] for item in values}) != len(values):
            raise LegacyImportError("Conflicting duplicate legacy task identity")
    report = {"source_count": len(snapshots),
              "table_count": sum(len(item["tables"]) for item in snapshots),
              "row_count": sum(len(table["rows"]) for item in snapshots for table in item["tables"]),
              "task_states": dict(sorted(states.items())), "unfinished_imported": len(records["task"]),
              "record_counts": {kind: len(values) for kind, values in records.items()},
              "records_sha256": digest(records),
              "source_checksums": {item["source_id"]: item["sha256"] for item in snapshots}}
    archive = {"format": "neurath-legacy-snapshot-v1", "sources": snapshots, "report": report}
    return {"snapshot_id": identifier("snapshot", digest(archive)), "archive": archive, "records": records, "report": report}



def verify_archive(archive: dict[str, Any]) -> dict[str, Any]:
    """Recompute stored row/schema checksums after archive read-back."""
    if archive.get("format") != "neurath-legacy-snapshot-v1":
        raise LegacyImportError("Unknown legacy archive format")
    tables = rows = 0
    checksums = {}
    for source in archive["sources"]:
        for table in source["tables"]:
            body = {key: value for key, value in table.items() if key != "sha256"}
            if digest(body) != table["sha256"]:
                raise LegacyImportError("Archived table checksum mismatch")
            tables += 1
            rows += len(table["rows"])
        body = {key: value for key, value in source.items() if key != "sha256"}
        if digest(body) != source["sha256"]:
            raise LegacyImportError("Archived source checksum mismatch")
        checksums[source["source_id"]] = source["sha256"]
    report = archive["report"]
    if (tables != report["table_count"] or rows != report["row_count"]
            or len(archive["sources"]) != report["source_count"]
            or checksums != report["source_checksums"]):
        raise LegacyImportError("Archive report counts or checksums mismatch")
    return report


def import_legacy(database: Any, sources: Iterable[str | Path | tuple[str | Path, str]]) -> dict[str, Any]:
    """Archive and import together using the new storage transaction boundary."""
    prepared = prepare_import(sources)
    database.import_records(prepared["records"], snapshot_id=prepared["snapshot_id"], archive=prepared["archive"])
    return {"snapshot_id": prepared["snapshot_id"], **prepared["report"]}
