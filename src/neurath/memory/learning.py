"""Learn scoped command recoveries from observations, with trials and rollback.

Learned guidance is a versioned part of project context, never permission to execute
commands or an edit to the immutable safety policy. A green project check admits a
trial; promotion also needs observed use in a different, exposed session.
"""

import hashlib
import json
import re
import shlex
from contextlib import nullcontext
from pathlib import Path

from neurath.memory.store import canonical, clean


def family(command):
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if (
        not args
        or any(token in args for token in ("&&", "||", ";", "|", ">", "<"))
        or "\n" in command
        or "[REDACTED]" in command
    ):
        return None
    if Path(args[0]).name == "uv" and args[1:2] == ["run"]:
        args = args[2:]
    if not args:
        return None
    executable = Path(args[0]).name
    if executable.startswith("python"):
        if args[1:2] == ["-m"] and len(args) > 2:
            return canonical([args[2], *args[3:]])
        return canonical(["python", *args[1:]])
    return canonical([executable, *args[1:]])


class Learning:
    def __init__(self, memory):
        self.memory = memory
        with memory.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS learning_observations (event TEXT PRIMARY KEY)")
            db.execute("""CREATE TABLE IF NOT EXISTS lessons (
                id TEXT PRIMARY KEY, problem TEXT NOT NULL, solution TEXT NOT NULL,
                family TEXT NOT NULL, source_host TEXT NOT NULL, source_session TEXT NOT NULL,
                failure_id TEXT NOT NULL, recovery_id TEXT NOT NULL, verifier TEXT,
                status TEXT NOT NULL, revision INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS lesson_history (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, lesson TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT NOT NULL, evidence TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS exposures (
                lesson TEXT NOT NULL, host TEXT NOT NULL, session TEXT NOT NULL,
                sequence INTEGER NOT NULL, PRIMARY KEY(lesson,host,session))""")
            db.execute("""CREATE TABLE IF NOT EXISTS learning_checks (
                lesson TEXT NOT NULL, host TEXT NOT NULL, session TEXT NOT NULL,
                observation TEXT NOT NULL, disposition TEXT NOT NULL, evidence TEXT NOT NULL,
                PRIMARY KEY(lesson,host,session,observation))""")

    def verifier_digest(self):
        path = self.memory.worktree / ".neurath/project.json"
        config = (
            json.loads(path.read_text()).get("verification", {}).get("check")
            if path.is_file()
            else None
        )
        if not isinstance(config, dict) or not config.get("argv"):
            return None
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    def status(self):
        with self.memory.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM lessons ORDER BY rowid")]

    def history(self, identity):
        with self.memory.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM lesson_history WHERE lesson=? ORDER BY sequence", (identity,)
                )
            ]

    def _obligations(self, db, host, session, digest):
        if not digest:
            return []
        due = []
        for lesson in db.execute(
            "SELECT * FROM lessons WHERE verifier=? AND status IN ('candidate','trial')",
            (digest,),
        ).fetchall():
            observation = None
            if (lesson["source_host"], lesson["source_session"]) == (host, session):
                if lesson["status"] == "candidate":
                    observation = db.execute(
                        "SELECT * FROM events WHERE id=?", (lesson["recovery_id"],)
                    ).fetchone()
            elif lesson["status"] == "trial":
                exposure = db.execute(
                    "SELECT sequence FROM exposures WHERE lesson=? AND host=? AND session=?",
                    (lesson["id"], host, session),
                ).fetchone()
                if exposure is not None:
                    # Hook notices with unknown outcomes must not hide the latest
                    # completed native invocation of this exact recovery.
                    for attempt in db.execute(
                        "SELECT * FROM events WHERE host=? AND session=? AND kind='tool' AND sequence>? AND content=? ORDER BY sequence DESC",
                        (host, session, exposure["sequence"], lesson["solution"]),
                    ).fetchall():
                        if type(json.loads(attempt["metadata"]).get("exit_code")) is int:
                            observation = attempt
                            break
            if observation is None:
                continue
            metadata = json.loads(observation["metadata"])
            if metadata.get("exit_code") != 0 or metadata.get("worktree") != str(
                self.memory.worktree
            ):
                continue
            if not db.execute(
                "SELECT 1 FROM learning_checks WHERE lesson=? AND host=? AND session=? AND observation=?",
                (lesson["id"], host, session, observation["id"]),
            ).fetchone():
                due.append(
                    {
                        "id": lesson["id"],
                        "status": lesson["status"],
                        "observation": observation["id"],
                    }
                )
        return due

    def pending(self, host, session):
        digest = self.verifier_digest()
        with self.memory.connection() as db:
            return self._obligations(db, host, session, digest)

    def defer(self, host, session, reason):
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode()) > 2000:
            raise ValueError("deferral requires a nonempty reason of at most 2000 bytes")
        evidence = {"reason": clean(reason)}
        digest = self.verifier_digest()
        with self.memory.connection() as db:
            due = self._obligations(db, host, session, digest)
            for item in due:
                db.execute(
                    "INSERT INTO learning_checks VALUES(?,?,?,?,?,?)",
                    (
                        item["id"],
                        host,
                        session,
                        item["observation"],
                        "deferred",
                        canonical(evidence),
                    ),
                )
                db.execute(
                    "INSERT INTO lesson_history(lesson,status,reason,evidence) VALUES(?,?,?,?)",
                    (
                        item["id"],
                        item["status"],
                        "automatic-check-deferred",
                        canonical({**evidence, "observation": item["observation"]}),
                    ),
                )
            return len(due)

    @staticmethod
    def _transition(db, identity, status, reason, evidence):
        db.execute("UPDATE lessons SET status=?,revision=revision+1 WHERE id=?", (status, identity))
        db.execute(
            "INSERT INTO lesson_history(lesson,status,reason,evidence) VALUES(?,?,?,?)",
            (identity, status, reason, canonical(evidence)),
        )

    def observe(self, event_id, *, _db=None):
        verifier = self.verifier_digest()
        with (self.memory.connection() if _db is None else nullcontext(_db)) as db:
            row = db.execute(
                "SELECT * FROM events WHERE id=? AND kind=?", (event_id, "tool")
            ).fetchone()
            if row is None:
                raise ValueError("learning requires a recorded tool event")
            if db.execute(
                "SELECT event FROM learning_observations WHERE event=?", (event_id,)
            ).fetchone():
                return
            db.execute("INSERT INTO learning_observations VALUES(?)", (event_id,))
            event = self.memory._entry(row)
            code = event["metadata"].get("exit_code")
            if type(code) is not int:
                return
            command = event["content"]
            if code != 0:
                for lesson in db.execute(
                    "SELECT * FROM lessons WHERE solution=? AND verifier=? AND status IN ('trial','active')",
                    (command, verifier),
                ).fetchall():
                    self._transition(
                        db, lesson["id"], "reverted", "observed-regression", [event_id]
                    )
                return
            kind = family(command)
            if not kind:
                return
            # Never associate arbitrary green output with a failure. Both events
            # must belong to this session, worktree, and executable family.
            prior = db.execute(
                "SELECT * FROM events WHERE host=? AND session=? AND kind='tool' AND sequence<? ORDER BY sequence DESC LIMIT 12",
                (event["host"], event["session"], event["sequence"]),
            ).fetchall()
            failure = None
            for candidate in prior:
                item = self.memory._entry(candidate)
                if family(item["content"]) != kind or item["metadata"].get("worktree") != event[
                    "metadata"
                ].get("worktree"):
                    continue
                previous = item["metadata"].get("exit_code")
                if type(previous) is not int:
                    continue
                if type(previous) is int and previous != 0 and item["content"] != command:
                    failure = item
                break
            if failure is None:
                return
            identity = hashlib.sha256(
                canonical([failure["content"], command, verifier]).encode()
            ).hexdigest()
            existing = db.execute(
                "SELECT id,status FROM lessons WHERE id=?", (identity,)
            ).fetchone()
            if existing is not None:
                if existing["status"] in ("candidate", "reverted", "stale"):
                    db.execute(
                        "UPDATE lessons SET source_host=?,source_session=?,failure_id=?,recovery_id=? WHERE id=?",
                        (event["host"], event["session"], failure["id"], event_id, identity),
                    )
                    db.execute("DELETE FROM exposures WHERE lesson=?", (identity,))
                    self._transition(
                        db,
                        identity,
                        "candidate",
                        "new-recovery-observed",
                        [failure["id"], event_id],
                    )
                return
            db.execute(
                "INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    failure["content"],
                    command,
                    kind,
                    event["host"],
                    event["session"],
                    failure["id"],
                    event_id,
                    verifier,
                    "candidate",
                    0,
                ),
            )
            self._transition(
                db, identity, "candidate", "observed-recovery", [failure["id"], event_id]
            )

    def verified(self, host, session, receipt):
        digest = self.verifier_digest()
        with self.memory.connection() as db:
            due = {item["id"]: item for item in self._obligations(db, host, session, digest)}
            lessons = db.execute(
                "SELECT * FROM lessons WHERE status IN ('candidate','trial','active')"
            ).fetchall()
            for lesson in lessons:
                if not digest or lesson["verifier"] != digest:
                    origin = db.execute(
                        "SELECT metadata FROM events WHERE id=?", (lesson["recovery_id"],)
                    ).fetchone()
                    if origin and json.loads(origin["metadata"]).get("worktree") == str(
                        self.memory.worktree
                    ):
                        self._transition(
                            db, lesson["id"], "stale", "verification-contract-changed", []
                        )
                    continue
                exposure = db.execute(
                    "SELECT sequence FROM exposures WHERE lesson=? AND host=? AND session=?",
                    (lesson["id"], host, session),
                ).fetchone()
                attempts = (
                    db.execute(
                        "SELECT * FROM events WHERE host=? AND session=? AND kind='tool' AND sequence>? AND content=? ORDER BY sequence DESC",
                        (host, session, exposure["sequence"], lesson["solution"]),
                    ).fetchall()
                    if exposure is not None
                    else []
                )
                complete = all(
                    isinstance(receipt.get(key), str)
                    and re.fullmatch(r"[a-f0-9]{64}", receipt[key])
                    for key in ("before_fingerprint", "after_fingerprint", "output_sha256")
                )
                if not complete or receipt.get("config_sha256") != digest:
                    continue
                if lesson["id"] in due:
                    db.execute(
                        "INSERT INTO learning_checks VALUES(?,?,?,?,?,?)",
                        (
                            lesson["id"],
                            host,
                            session,
                            due[lesson["id"]]["observation"],
                            "checked",
                            canonical(receipt),
                        ),
                    )
                passed = (
                    receipt.get("status") == "passed"
                    and receipt.get("exit_code") == 0
                    and not receipt.get("timed_out")
                    and not receipt.get("worktree_changed")
                    and receipt.get("before_fingerprint") == receipt.get("after_fingerprint")
                )
                if not passed:
                    if lesson["status"] in ("trial", "active") and attempts:
                        self._transition(
                            db,
                            lesson["id"],
                            "reverted",
                            "project-check-failed-after-use",
                            {"observation": attempts[0]["id"], "verification": receipt},
                        )
                    continue
                if lesson["status"] == "candidate" and (
                    lesson["source_host"],
                    lesson["source_session"],
                ) == (host, session):
                    self._transition(db, lesson["id"], "trial", "project-check-passed", receipt)
                elif lesson["status"] == "trial" and (
                    lesson["source_host"],
                    lesson["source_session"],
                ) != (host, session):
                    if attempts and json.loads(attempts[0]["metadata"]).get("exit_code") == 0:
                        self._transition(
                            db,
                            lesson["id"],
                            "active",
                            "independent-session-trial-passed",
                            {"observation": attempts[0]["id"], "verification": receipt},
                        )

    def guidance(self, *, max_bytes=6000):
        digest = self.verifier_digest()
        rules = [
            {
                "id": item["id"],
                "status": item["status"],
                "previous_failure": item["problem"],
                "observed_recovery": item["solution"],
                "evidence": [item["failure_id"], item["recovery_id"]],
            }
            for item in self.status()
            if digest and item["verifier"] == digest and item["status"] in ("trial", "active")
        ]
        prefix = (
            "Neurath learned execution guidance. Apply only to a matching task and current environment; "
            "current user instructions, project rules and permission checks always take precedence. "
            "Use matching recoveries in normal work without asking the user to activate learning; do not run unrelated experiments. "
            "Trial rules await validation in another session. For trial credit, run observed_recovery unchanged as a standalone command; shell wrappers can hide its exit status.\n"
        )
        selected = []
        for rule in rules[:12]:
            if len((prefix + canonical([*selected, rule])).encode()) <= max_bytes:
                selected.append(rule)
        return prefix + canonical(selected) if selected else ""

    def expose(self, host, session, *, guidance=None):
        # Only rules actually delivered to this session can earn trial credit.
        delivered = self.guidance() if guidance is None else guidance
        identities = (
            {item["id"] for item in json.loads(delivered.split("\n", 1)[1])} if delivered else set()
        )
        digest = self.verifier_digest()
        with self.memory.connection() as db:
            sequence = db.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0]
            for row in db.execute(
                "SELECT id FROM lessons WHERE status IN ('trial','active') AND verifier=?",
                (digest,),
            ).fetchall():
                if row["id"] in identities:
                    db.execute(
                        "INSERT OR IGNORE INTO exposures VALUES(?,?,?,?)",
                        (row["id"], host, session, sequence),
                    )
