"""Durable repair holds. Releasing a hold retries delivery, not task effects."""

import json

from neurath.agents.store import bounded
from neurath.memory.store import canonical


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS delivery_holds (
        message TEXT PRIMARY KEY, revision INTEGER NOT NULL, reason TEXT NOT NULL,
        active INTEGER NOT NULL, repair_reference TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS delivery_redrives (
        actor TEXT NOT NULL, key TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL,
        PRIMARY KEY(actor,key))""")


def quarantine(store, message_id, *, reason, expected_generation=None):
    if reason not in {"envelope-version", "recipient-binding"}:
        raise ValueError("repair requires a known failure classification")
    with store.connection() as db:
        schema(db)
        message = store._message(db, message_id)
        if expected_generation is not None:
            endpoint = db.execute("SELECT generation FROM delivery_endpoints WHERE address=?",
                                  (message["recipient"],)).fetchone()
            if endpoint is None or endpoint["generation"] != expected_generation:
                return None  # Late transport results cannot hold a successor connection.
        if message["status"] not in {"queued", "submitted"}:
            raise ValueError("only pending messages can require repair")
        row = db.execute("SELECT * FROM delivery_holds WHERE message=?", (message_id,)).fetchone()
        if row and row["active"] and row["reason"] == reason:
            return dict(row)
        revision = row["revision"] + 1 if row else 1
        db.execute("INSERT INTO delivery_holds VALUES(?,?,?,1,NULL) ON CONFLICT(message) "
                   "DO UPDATE SET revision=excluded.revision,reason=excluded.reason,active=1,repair_reference=NULL",
                   (message_id, revision, reason))
        return dict(db.execute("SELECT * FROM delivery_holds WHERE message=?", (message_id,)).fetchone())


def delivery_status(store, actor, message_id):
    from neurath.agents.delivery import _schema
    _schema(store)
    with store.connection() as db:
        message = store._message(db, message_id)
        if actor not in (message["sender"], message["recipient"]):
            raise ValueError("delivery status requires a participant")
        hold = db.execute("SELECT * FROM delivery_holds WHERE message=?", (message_id,)).fetchone()
        attempts = [dict(row) for row in db.execute(
            "SELECT * FROM delivery_history WHERE message=? ORDER BY id DESC LIMIT 100", (message_id,))]
        return {"message_id": message_id, "status": message["status"],
                "hold": dict(hold) if hold else None, "recent_attempts": attempts}


def redrive(store, actor, message_id, *, expected_revision, repair_reference, key):
    bounded(repair_reference, "repair reference", 1024)
    bounded(key, "redrive key")
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("invalid hold revision")
    request = canonical([message_id, expected_revision, repair_reference])
    with store.connection() as db:
        schema(db)
        message = store._message(db, message_id)
        if actor not in (message["sender"], message["recipient"]):
            raise ValueError("redrive requires a participant")
        old = db.execute("SELECT * FROM delivery_redrives WHERE actor=? AND key=?", (actor, key)).fetchone()
        if old:
            if old["request"] != request:
                raise ValueError("redrive key changed request")
            return json.loads(old["result"])
        hold = db.execute("SELECT * FROM delivery_holds WHERE message=?", (message_id,)).fetchone()
        if not hold or not hold["active"] or hold["revision"] != expected_revision:
            raise ValueError("hold revision changed")
        if message["status"] not in {"queued", "submitted"}:
            raise ValueError("redrive cannot revive a terminal message")
        # No destination, content, execution policy or identity can be changed.
        # The owned transport still performs its normal checks on the next try.
        db.execute("UPDATE delivery_holds SET active=0,revision=revision+1,repair_reference=? WHERE message=?",
                   (repair_reference, message_id))
        result = {"message_id": message_id, "status": "retry-eligible", "revision": expected_revision + 1}
        db.execute("INSERT INTO delivery_redrives VALUES(?,?,?,?)", (actor, key, request, canonical(result)))
        db.notices.append(message_id)
        return result
