"""Retain project-check obligations independently of the latest material batch.

This host completion gate records only canonical material baselines and actual
runner receipts. It does not classify natural-language goals or grant semantic
acceptance, execution permission, or independent-review authority.
"""

import hashlib
import json
import subprocess
from pathlib import Path

from neurath.memory.store import ProjectMemory, canonical


class VerificationObligations:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.memory = ProjectMemory(self.root)
        with self.memory.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS material_verification_obligations (
                worktree TEXT NOT NULL, host TEXT NOT NULL, session TEXT NOT NULL,
                actor TEXT NOT NULL, batch TEXT NOT NULL, targets TEXT NOT NULL,
                PRIMARY KEY(worktree,host,session,actor,batch))""")
            db.execute("""CREATE TABLE IF NOT EXISTS material_verification_proofs (
                worktree TEXT NOT NULL, host TEXT NOT NULL, session TEXT NOT NULL,
                actor TEXT NOT NULL, receipt TEXT NOT NULL,
                PRIMARY KEY(worktree,host,session,actor))""")

    def _key(self, host, session, actor):
        return str(self.root), host, session, str(actor)

    def register(self, host, session, actor, batch, expectations):
        # Git ignores private runtime artifacts, but tracked files remain in scope
        # even when a later ignore rule matches them. A failed Git read fails closed.
        paths = [str(Path(item["observable_id"]).relative_to(self.root)) for item in expectations]
        result = subprocess.run(["git", "-C", str(self.root), "check-ignore", "--stdin", "-z"],
            input=b"\0".join(p.encode() for p in paths) + b"\0", capture_output=True, check=False)
        if result.returncode not in (0, 1):
            raise ValueError("cannot determine verification target scope")
        ignored = set(result.stdout.decode().split("\0"))
        targets = [{"path": path, "baseline": item["baseline_digest"]}
                   for path, item in zip(paths, expectations, strict=True) if path not in ignored]
        if not targets:
            return
        with self.memory.connection() as db:
            # Retry cannot replace the original baseline with already-edited bytes.
            db.execute("INSERT OR IGNORE INTO material_verification_obligations VALUES(?,?,?,?,?,?)",
                       (*self._key(host, session, actor), batch, canonical(targets)))

    def verified(self, host, session, actor, check, receipt):
        if (check != "check" or receipt.get("status") != "passed"
                or receipt.get("timed_out") is not False
                or receipt.get("worktree_changed") is not False
                or not receipt.get("before_fingerprint")
                or receipt["before_fingerprint"] != receipt.get("after_fingerprint")):
            return
        from neurath.runtime.verification import fingerprint
        from scripts.agent_harness.material_action import material_observable_digest
        with self.memory.connection() as db:
            rows = db.execute("""SELECT batch,targets FROM material_verification_obligations
                WHERE worktree=? AND host=? AND session=? AND actor=?""",
                self._key(host, session, actor)).fetchall()
        targets = {row["batch"]: {item["path"]: material_observable_digest(self.root / item["path"])
                   for item in json.loads(row["targets"])} for row in rows}
        # Never certify bytes that arrived after the actual check. New rows not
        # captured here remain pending even if they are registered concurrently.
        if fingerprint(self.root) != receipt["after_fingerprint"]:
            return
        # Called only after the verifier has revalidated native caller and claim.
        proof = {name: receipt[name] for name in (
            "before_fingerprint", "after_fingerprint", "config_sha256")}
        proof["targets"] = targets
        with self.memory.connection() as db:
            db.execute("INSERT OR REPLACE INTO material_verification_proofs VALUES(?,?,?,?,?)",
                       (*self._key(host, session, actor), canonical(proof)))

    def pending(self, host, session, actor):
        from neurath.runtime.engine import activate
        activate()
        from scripts.agent_harness.material_action import material_observable_digest

        with self.memory.connection() as db:
            rows = db.execute("""SELECT batch,targets FROM material_verification_obligations
                WHERE worktree=? AND host=? AND session=? AND actor=?""",
                self._key(host, session, actor)).fetchall()
            saved = db.execute("""SELECT receipt FROM material_verification_proofs
                WHERE worktree=? AND host=? AND session=? AND actor=?""",
                self._key(host, session, actor)).fetchone()
        if not rows:
            return []
        config = json.loads((self.root / ".neurath/project.json").read_text()).get("verification", {}).get("check")
        digest = None if not config else hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        proof = {} if saved is None else json.loads(saved["receipt"])
        verified = proof.get("targets", {}) if proof.get("config_sha256") == digest else {}
        changed = [row["batch"] for row in rows if any(
            material_observable_digest(self.root / item["path"]) !=
            verified.get(row["batch"], {}).get(item["path"], item["baseline"])
            for item in json.loads(row["targets"]))]
        return [{"batch": batch, "check": "check",
                 "reason": "verification-required" if digest else "verification-unbound"}
                for batch in changed]


def stop_request(root, host, payload):
    if payload.get("hook_event_name") != "Stop" or payload.get("agent_id"):
        return None
    from neurath.hosts.identity import _state
    state = _state(root, payload["session_id"])
    ledger = VerificationObligations(root)
    reconcile_material(ledger, state, state.session.root_actor_id)
    pending = ledger.pending(host, payload["session_id"], state.session.root_actor_id)
    if not pending:
        return None
    reason = "verification-unbound" if any(p["reason"] == "verification-unbound" for p in pending) else "verification-required"
    return (
        f"Neurath implementation verification remains incomplete ({reason}). "
        "Run the project-registered verification_run(check='check') on the final source when authorized. "
        "A checkpoint or resolved material batch does not satisfy this obligation. "
        "Inspect an existing failed or uncertain result before any retry. If the current route is unavailable, "
        "check allowed alternatives; report concrete policy or missing-binding constraints without bypassing them. "
        "Preserve unresolved work when returning control; do not claim completion."
    )


def reconcile_material(ledger, state, actor):
    """Recover a committed prepare whose post-commit ledger write was interrupted."""
    batch = state.material_actions.get(actor)
    if batch is not None and batch.kind.value == "local-mutation":
        ledger.register(state.session.runtime.value, str(state.session.id), str(actor),
                        f"{batch.sequence}:{batch.batch_id}",
                        [item.to_payload() for item in batch.expectations])
