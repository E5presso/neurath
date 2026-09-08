"""Creator-linked task events committed atomically with the existing message outbox.

This store never starts a session, changes native identity or accepts a work result.
Public adapters supply the authenticated actor; native adapters use observed lineage.
"""

import hashlib
import json
import time
from contextlib import nullcontext

from neurath.agents.store import bounded
from neurath.memory.store import canonical, clean

TERMINAL = frozenset({"completed", "failed", "cancelled"})
STATES = TERMINAL | {"assigned", "starting", "started", "waiting", "error", "disconnected"}


class TaskLifecycle:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS task_links (
                id TEXT PRIMARY KEY, issuer TEXT NOT NULL, executor TEXT NOT NULL,
                request TEXT NOT NULL, transport TEXT NOT NULL, state TEXT NOT NULL,
                updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                task TEXT NOT NULL, state TEXT NOT NULL, request TEXT NOT NULL,
                message TEXT NOT NULL)""")
            if "turn" not in {row[1] for row in db.execute("PRAGMA table_info(task_links)")}:
                db.execute("ALTER TABLE task_links ADD COLUMN turn TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _task(db, task_id):
        row = db.execute("SELECT * FROM task_links WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("unknown task")
        return row

    def bind(self, issuer, executor, *, key, transport, _db=None):
        bounded(key, "task key")
        bounded(transport, "task transport", 100)
        task_id = hashlib.sha256(canonical([issuer, key]).encode()).hexdigest()
        request = canonical([executor, transport])
        with self.store.connection() if _db is None else nullcontext(_db) as db:
            self.store._agent(db, issuer)
            self.store._agent(db, executor)
            previous = db.execute("SELECT * FROM task_links WHERE id=?", (task_id,)).fetchone()
            if previous and previous["request"] != request:
                raise ValueError("task key changed executor or transport")
            if not previous:
                db.execute("INSERT INTO task_links(id,issuer,executor,request,transport,state,updated) VALUES(?,?,?,?,?,?,?)",
                           (task_id, issuer, executor, request, transport, "assigned", time.time()))
            return self.read(issuer, task_id, _db=db)

    def accept(self, actor, task_id, turn):
        """Bind the native turn and publish its start in the same transaction."""
        bounded(turn, "native turn", 1024)
        with self.store.connection() as db:
            row = self._task(db, task_id)
            if row["executor"] != actor:
                raise ValueError("only the executor can accept")
            if row["state"] in TERMINAL:
                raise ValueError("task is terminal")
            if row["turn"] and row["turn"] != turn:
                if row["state"] != "disconnected":
                    raise ValueError("task already belongs to another native turn")
                previous = hashlib.sha256(canonical([task_id, "accept:" + turn]).encode()).hexdigest()
                if db.execute("SELECT 1 FROM task_events WHERE id=?", (previous,)).fetchone():
                    raise ValueError("cannot rebind a previous native turn")
            db.execute("UPDATE task_links SET turn=? WHERE id=?", (turn, task_id))
            return self.emit(actor, task_id, "started", key="accept:" + turn, _db=db)

    def read(self, actor, task_id, *, _db=None):
        with self.store.connection() if _db is None else nullcontext(_db) as db:
            row = self._task(db, task_id)
            if actor not in (row["issuer"], row["executor"]):
                raise ValueError("task requires a participant")
            result = {key: value for key, value in dict(row).items() if key != "request"}
            result["reports"] = [dict(event) for event in db.execute(
                """SELECT e.id,e.state,e.message,m.status AS delivery FROM task_events e
                   JOIN messages m ON e.message=m.id WHERE e.task=? ORDER BY e.sequence""",
                (task_id,))]
            return result

    def active(self, executor):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM task_links WHERE executor=? AND state NOT IN ('completed','failed','cancelled')",
                (executor,))]

    def emit(self, actor, task_id, state, *, key, detail="", reply_recipient=None, _db=None):
        if state not in STATES - {"assigned"}:
            raise ValueError("unknown lifecycle event")
        bounded(key, "event key")
        if not isinstance(detail, str) or len(detail.encode()) > 16000:
            raise ValueError("event detail exceeds 16000 bytes")
        event_id = hashlib.sha256(canonical([task_id, key]).encode()).hexdigest()
        request_fields = [state, clean(detail)]
        if reply_recipient is not None:
            request_fields.append({"reply_recipient": reply_recipient})
        request = canonical(request_fields)
        with self.store.connection() if _db is None else nullcontext(_db) as db:
            task = self._task(db, task_id)
            if task["executor"] != actor:
                raise ValueError("only the bound executor can report a task")
            old = db.execute("SELECT * FROM task_events WHERE id=?", (event_id,)).fetchone()
            if old:
                if old["request"] != request:
                    raise ValueError("event key changed state or detail")
                return {"id": event_id, "message": self.store._public(self.store._message(db, old["message"]))}
            if task["state"] in TERMINAL:
                raise ValueError("task is terminal; late events cannot revive it")
            body = ("Neurath task lifecycle report (not result acceptance). " + canonical({
                "task_id": task_id, "state": state, "transport": task["transport"],
                "detail": json.loads(request)[1], "issuer": task["issuer"], "executor": actor,
                **({"native_executor": reply_recipient} if reply_recipient is not None else {})}))
            message = self.store._send(db, actor, task["issuer"], body,
                key="lifecycle:" + event_id, kind="result" if state in TERMINAL else "update",
                ttl=604800, lifecycle=True, reply_recipient=reply_recipient)
            db.execute("INSERT INTO task_events(id,task,state,request,message) VALUES(?,?,?,?,?)",
                       (event_id, task_id, state, request, message["id"]))
            db.execute("UPDATE task_links SET state=?,updated=? WHERE id=?", (state, time.time(), task_id))
            return {"id": event_id, "message": message}
