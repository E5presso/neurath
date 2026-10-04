"""Explicit snapshot/adoption of unfinished v1 work; never load the retired engine.

The installer owns the offline host switch. This module preserves the observed
v1 records and imports obligations in one target transaction. It never changes
the original database, treats old reports as fresh native evidence, or activates
an actor from historical records.
"""

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

from neurath.core.codec import encode
from neurath.core.domain import Condition, Source, Task, require

NAMESPACES = {"task-ledger", "worktree", "session-migration", "session"}
UNFINISHED = {"pending", "in_progress", "failed"}


def owner_id(actor, session):
    for provider in ("codex", "claude-code"):
        if actor == f"{provider}:{session}":
            return f"{provider}:session:{session}"
        if actor.startswith((f"{provider}:session:", f"{provider}:agent:")):
            return actor
        if actor.startswith(provider + ":") and session:
            return f"{provider}:agent:" + actor.removeprefix(provider + ":")
    require(False, "legacy-owner-format")


def snapshot(root):
    path = Path(root).resolve() / ".neurath/local/runtime.sqlite3"
    require(not path.is_symlink(), "unsafe-legacy-work-source")
    if not path.exists():
        return None
    require(path.is_file(), "legacy-work-source-unavailable")
    rows = []
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "legacy-work-corrupt")
        if db.execute("SELECT 1 FROM sqlite_schema WHERE name='runtime_records'").fetchone():
            for namespace, key, revision, payload, digest, legacy_path, legacy_digest in db.execute(
                "SELECT namespace,key,revision,payload,digest,legacy_path,legacy_digest "
                "FROM runtime_records ORDER BY namespace,key"
            ):
                if namespace not in NAMESPACES and not namespace.startswith("prompt:"):
                    continue
                require(
                    isinstance(payload, bytes) and sha256(payload).hexdigest() == digest,
                    "legacy-work-corrupt",
                )
                if legacy_path is not None:
                    previous = Path(legacy_path)
                    require(
                        not previous.is_symlink()
                        and previous.is_file()
                        and sha256(previous.read_bytes()).hexdigest() == legacy_digest,
                        "legacy-work-source-changed",
                    )
                value = json.loads(payload)
                rows.append(
                    {
                        "namespace": namespace,
                        "key": key,
                        "revision": revision,
                        "digest": digest,
                        "payload": value,
                    }
                )
    result = {"source": str(path), "records": rows}
    return {**result, "digest": sha256(encode(result).encode()).hexdigest()}


def preview(document):
    if document is None:
        return {"required": False, "task_ids": [], "leases": []}
    moved = {row["key"] for row in document["records"] if row["namespace"] == "session-migration"}
    tasks, leases = [], []
    for row in document["records"]:
        value = row["payload"]
        if row["namespace"] == "task-ledger" and row["key"] not in moved:
            require(
                value.get("schema") == "neurath.task-ledger.v1"
                and value.get("session") == row["key"],
                "legacy-work-schema",
            )
            tasks.extend(item["id"] for item in value["tasks"] if item["status"] in UNFINISHED)
        elif row["namespace"] == "worktree":
            current = value.get("current")
            if current:
                leases.append(
                    {
                        "checkout": current["path"],
                        "writer": owner_id(current["actor_id"], current.get("session_id")),
                        "generation": current["lease_epoch"],
                    }
                )
    return {"required": True, "digest": document["digest"], "task_ids": tasks, "leases": leases}


def adopt(store, *, expected_digest):
    """Called only during the installer's explicit offline core transition.

    All old state stays as attributed history. Unfinished goals retain their IDs,
    owners, acceptance text and waiting state. Skill progress must be recovered
    against the new catalog; no old workflow is silently marked complete.
    """
    document = snapshot(store.root)
    require(
        document is not None and document["digest"] == expected_digest, "legacy-work-source-changed"
    )
    plan = preview(document)
    with store.transaction() as tx:
        previous = tx.record("migration", "v1-work")
        if previous:
            require(previous["value"]["digest"] == expected_digest, "legacy-work-source-changed")
            return previous["value"]
        require(
            not tx.tasks() and tx.db.execute("SELECT 1 FROM leases LIMIT 1").fetchone() is None,
            "legacy-work-target-not-empty",
        )
        moved = {
            row["key"] for row in document["records"] if row["namespace"] == "session-migration"
        }
        for row in document["records"]:
            source = Source.create(
                "legacy-" + sha256(encode(row).encode()).hexdigest(),
                "report",
                encode(row),
                "legacy-v1:" + row["namespace"] + ":" + row["key"],
            )
            tx.put_source(source)
            if row["namespace"].startswith("prompt:"):
                tx.put_record(
                    "legacy-prompt",
                    source.id,
                    {
                        "session": row["namespace"].removeprefix("prompt:"),
                        "proof": row["payload"],
                    },
                )
            if row["namespace"] != "task-ledger" or row["key"] in moved:
                continue
            ledger = row["payload"]
            for item in ledger["tasks"]:
                require(
                    item["status"] in UNFINISHED | {"succeeded", "invalidated"},
                    "legacy-work-schema",
                )
                definition = item["definition"]
                acceptance = tuple(Condition(criterion) for criterion in definition["acceptance"])
                state = (
                    "completed"
                    if item["status"] == "succeeded"
                    else "withdrawn"
                    if item["status"] == "invalidated"
                    else "waiting"
                )
                task = Task(
                    item["id"],
                    ledger["session"],
                    owner_id(ledger["owner"], ledger["session"]),
                    definition["goal"],
                    (source.id,),
                    acceptance,
                    state=state,
                    revision=item["revision"] + 1,
                    dependencies=tuple(definition.get("dependencies", ())),
                    withdrawal_source=source.id if state == "withdrawn" else None,
                    attempts=(
                        (
                            "Recover the retained skill context under the new core before continuing.",
                            source.id,
                        ),
                    ),
                )
                tx.db.execute(
                    "INSERT INTO tasks VALUES(?,?,?)", (task.id, task.revision, encode(task))
                )
        for task in tx.tasks():
            for dependency in task.dependencies:
                tx.task(dependency)
        for lease in plan["leases"]:
            require(
                Path(lease["checkout"]).is_absolute()
                and type(lease["generation"]) is int
                and lease["generation"] >= 0,
                "legacy-work-lease",
            )
            tx.db.execute(
                "INSERT INTO leases VALUES(?,?,?,1)",
                (lease["checkout"], lease["writer"], lease["generation"] + 1),
            )
        result = {
            "digest": expected_digest,
            "task_ids": plan["task_ids"],
            "leases": len(plan["leases"]),
            "source": document["source"],
            "authority": "retained-history",
        }
        tx.put_record("migration", "v1-work", result)
        return result
