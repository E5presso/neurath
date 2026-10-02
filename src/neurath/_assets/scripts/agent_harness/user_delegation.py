"""Native-user opt-in grants; no grant exists or is enabled by default.

The receiver owns the proposal and approval. App ingress proves only the sender,
never human consent. Records share the task ledger's transaction and remain local.
"""
import hashlib
import json
import secrets
import subprocess
import time
from pathlib import Path
from uuid import UUID

from .task_ledger import TaskDefinition, TaskLedgerError, TaskSource, _digest, _json

NAMESPACE = "local-user-delegation"
SCHEMA = "neurath.user-delegation.v1"


def _unique_object(pairs):
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate delegation payload field")
    return dict(pairs)


def project_identity(worktree):
    from .session_kernel import SessionLocator
    try:
        root = SessionLocator.from_worktree(Path(worktree)).control_root.resolve()
    except (OSError, subprocess.SubprocessError) as error:
        raise TaskLedgerError("canonical delegation project is unavailable") from error
    return "project-sha256:" + hashlib.sha256(str(root).encode()).hexdigest()


def task_scope(definition):
    value = {key: getattr(definition, key) for key in
             ("key", "title", "goal", "acceptance", "dependencies")}
    return json.loads(_json(value))


def _record(tx, reference):
    stored = tx.get(NAMESPACE, reference)
    if stored is None:
        raise TaskLedgerError("local delegation grant is missing")
    return stored, json.loads(stored.payload)


def _bound(record, process, worktree):
    if (record["target_session"] != str(process.session.id)
            or record["target_actor"] != str(process.session.root_actor_id)
            or (worktree is not None and (record["worktree"] != str(Path(worktree).resolve())
                or record["project"] != project_identity(worktree)))):
        raise TaskLedgerError("local delegation target session or project differs")


def validate_source(tx, process, source, definition, worktree, *, now=None):
    """Revalidate consumed task authority, including later execution and children."""
    record = validate_consumed_source(tx, process, source, definition, worktree)
    if (record["state"] != "active"
            or (time.time() if now is None else now) >= record["expires_at"]):
        raise TaskLedgerError("local delegation is changed, expired or revoked")
    return record


def validate_consumed_source(tx, process, source, definition, worktree):
    """Verify historical intake for result return, without granting execution."""
    _, record = _record(tx, source.reference)
    _bound(record, process, worktree)
    if (source.revision != record["scope_digest"]
            or _digest(task_scope(definition)) != record["definition_digest"]
            or record.get("consumed_definition") != definition.digest):
        raise TaskLedgerError("local delegation task scope differs")
    return record


def consume(tx, process, source, definition, worktree, delivery, *, now):
    """Called only inside the transaction that creates the exact approved task."""
    stored, record = _record(tx, source.reference)
    _bound(record, process, worktree)
    if (record["state"] != "active" or now >= record["expires_at"]
            or source.revision != record["scope_digest"] or record["uses"] >= record["use_count"]):
        raise TaskLedgerError("local delegation is unavailable or already consumed")
    if (_digest(task_scope(definition)) != record["definition_digest"]
            or definition.producer != "canonical" or definition.evidence_contract != "agent-report"):
        raise TaskLedgerError("local delegation task definition differs from approved scope")
    turn = process.foreground_turns[process.session.root_actor_id]
    if delivery is None or turn.user_prompt_receipt is not None:
        raise TaskLedgerError("local delegation requires verified app ingress on a peer turn")
    try:
        payload = json.loads(delivery["input"], object_pairs_hook=_unique_object)
        expected = {"schema": SCHEMA, "grant_ref": source.reference,
                    "definition_digest": record["definition_digest"]}
        valid = (payload == expected and delivery["source_session"] == record["source_session"]
                 and delivery["target_session"] == str(process.session.id)
                 and delivery["turn"] == turn.vendor_turn_id
                 and delivery["delivery_id"].startswith("fco_")
                 and len(delivery["output_digest"]) == 64)
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise TaskLedgerError("app delegation source, recipient, turn or payload differs")
    witness_key = _digest([delivery["target_session"], delivery["delivery_id"]])
    if tx.get("local-delegation-delivery", witness_key) is not None:
        raise TaskLedgerError("app delegation delivery was already consumed")
    record.update(uses=record["uses"] + 1, consumed_definition=definition.digest,
                  delivery={key: delivery[key] for key in
                            ("source_session", "target_session", "turn", "delivery_id", "output_digest")})
    tx.put(NAMESPACE, source.reference, _json(record), expected_revision=stored.revision)
    tx.put("local-delegation-delivery", witness_key, _json({"grant": source.reference}), expected_revision=None)


def require_delegated_execution(tx, process, worktree, *, now=None):
    from .task_service import read_ledger
    _, ledger = read_ledger(tx, process)
    for task in ledger.tasks:
        if task.status.value != "in_progress":
            continue
        for source in task.definition.sources:
            if source.kind == "delegation":
                validate_source(tx, process, source, task.definition, worktree, now=now)


class GrantService:
    def __init__(self, task_service, *, messages, clock=time.time):
        self.tasks = task_service
        self.messages = messages
        self.clock = clock

    def _view(self, stored, record):
        result = {key: record[key] for key in ("reference", "state", "source_session", "target_session",
            "project", "task", "definition_digest", "scope_digest", "expires_at", "use_count", "uses", "question")}
        result["revision"] = stored.revision
        result["expired"] = self.clock() >= record["expires_at"]
        if record["state"] == "active" and not result["expired"] and record["uses"] < record["use_count"]:
            result["task_source"] = {"kind": "delegation", "reference": record["reference"],
                                     "revision": record["scope_digest"]}
            result["delivery_input"] = _json({"schema": SCHEMA, "grant_ref": record["reference"],
                "definition_digest": record["definition_digest"]}).decode()
        return result

    def prepare(self, source_session, task, *, expires_at, use_count, key):
        if str(UUID(source_session)) != source_session:
            raise TaskLedgerError("source session must be a canonical app thread UUID")
        if (type(expires_at) is not int or not self.clock() < expires_at <= self.clock() + 86400
                or type(use_count) is not int or use_count != 1):
            raise TaskLedgerError("grant requires an expiry within one day and exactly one intake")
        if set(task) != {"key", "title", "goal", "acceptance", "dependencies"}:
            raise TaskLedgerError("grant task must contain the exact bounded definition")
        with self.tasks.database.transaction() as tx:
            process = self.tasks._process(tx, mutation=True)
            receipt = process.foreground_turns[process.session.root_actor_id].user_prompt_receipt
            if receipt is None:
                raise TaskLedgerError("grant preparation requires an actual native user instruction")
            definition = TaskDefinition(**{**task, "sources": (TaskSource("prompt", receipt.authority_reference, receipt.prompt_digest),),
                "acceptance": tuple(task["acceptance"]), "dependencies": tuple(task["dependencies"]),
                "producer": "canonical", "evidence_contract": "agent-report"})
            scope = {"source_session": source_session, "target_session": str(process.session.id),
                "target_actor": str(process.session.root_actor_id), "project": project_identity(self.tasks.worktree),
                "worktree": str(self.tasks.worktree.resolve()), "task": task_scope(definition),
                "expires_at": expires_at, "use_count": use_count}
            request = _digest(scope)
            request_key = _digest([str(process.session.id), key])
            old = tx.get("local-delegation-prepare", request_key)
            if old is not None:
                prior = json.loads(old.payload)
                if prior["request"] != request:
                    raise TaskLedgerError("grant preparation key changed scope")
                stored, record = _record(tx, prior["reference"])
                return self._view(stored, record)
            reference = "delegation-grant:" + secrets.token_hex(24)
            record = {**scope, "reference": reference, "state": "prepared", "uses": 0,
                "definition_digest": _digest(scope["task"]), "scope_digest": _digest([reference, scope]),
                "prepared_prompt": receipt.to_payload()}
            preview = json.dumps(scope, ensure_ascii=False, sort_keys=True, indent=2)
            record["question"] = ("Approve this exact one-use local delegation? / 이 일회성 로컬 위임을 승인할까요?\n"
                + preview + "\nSource host/account identity is not supplied by the app envelope.\n"
                + "Reference / 확인 번호: " + reference + "\nyes / no")
            tx.put(NAMESPACE, reference, _json(record), expected_revision=None)
            tx.put("local-delegation-prepare", request_key, _json({"reference": reference, "request": request}), expected_revision=None)
            stored, _ = _record(tx, reference)
            return self._view(stored, record)

    def choose(self, reference, *, decision, key):
        with self.tasks.database.transaction() as tx:
            process = self.tasks._process(tx, mutation=True)
            stored, record = _record(tx, reference)
            _bound(record, process, self.tasks.worktree)
            receipt = process.foreground_turns[process.session.root_actor_id].user_prompt_receipt
            messages = self.messages()
            if (receipt is None or (receipt.generation, receipt.turn_revision) <=
                    (record["prepared_prompt"]["generation"], record["prepared_prompt"]["turn_revision"])):
                raise TaskLedgerError("grant approval requires fresh actual native user input")
            if (len(messages) < 2 or messages[-2] != ("assistant", record["question"])
                    or messages[-1][0] != "user"):
                raise TaskLedgerError("exact grant question and native answer are unobserved")
            text = messages[-1][1]
            if receipt.prompt_digest not in {hashlib.sha256(text.encode()).hexdigest(),
                                            hashlib.sha256(text.rstrip("\r\n").encode()).hexdigest()}:
                raise TaskLedgerError("grant answer differs from native user receipt")
            answer = {"yes": "yes", "네": "yes", "예": "yes", "승인합니다": "yes", "no": "no", "아니요": "no"}.get(text.strip().casefold())
            if answer != decision or answer is None:
                raise TaskLedgerError("grant decision differs from explicit native answer")
            if record["state"] != "prepared":
                if record.get("choice_key") == key and record.get("approval_digest") == receipt.prompt_digest:
                    return self._view(stored, record)
                raise TaskLedgerError("grant proposal was already decided")
            if self.clock() >= record["expires_at"]:
                raise TaskLedgerError("grant proposal expired before approval")
            record.update(state="active" if answer == "yes" else "declined", choice_key=key,
                          approval_digest=receipt.prompt_digest, approval_source=receipt.to_payload())
            tx.put(NAMESPACE, reference, _json(record), expected_revision=stored.revision)
            stored, _ = _record(tx, reference)
            return self._view(stored, record)

    def revoke(self, reference, *, expected_revision, key):
        with self.tasks.database.transaction() as tx:
            process = self.tasks._process(tx, mutation=True)
            stored, record = _record(tx, reference)
            _bound(record, process, self.tasks.worktree)
            receipt = process.foreground_turns[process.session.root_actor_id].user_prompt_receipt
            messages = self.messages()
            text = messages[-1][1] if messages and messages[-1][0] == "user" else ""
            if (receipt is None or receipt.prompt_digest not in {hashlib.sha256(text.encode()).hexdigest(),
                    hashlib.sha256(text.rstrip("\r\n").encode()).hexdigest()}
                    or text.strip() not in {"revoke delegation " + reference, "위임 취소 " + reference}):
                raise TaskLedgerError("revocation requires an exact actual native user instruction")
            if record.get("revoke_key") == key and record["state"] == "revoked":
                return self._view(stored, record)
            if stored.revision != expected_revision:
                raise TaskLedgerError("grant revision changed before revocation")
            record.update(state="revoked", revoke_key=key, revoke_source=receipt.to_payload())
            tx.put(NAMESPACE, reference, _json(record), expected_revision=stored.revision)
            stored, _ = _record(tx, reference)
            return self._view(stored, record)

    def status(self, reference):
        with self.tasks.database.transaction() as tx:
            process = self.tasks._process(tx, mutation=False)
            stored, record = _record(tx, reference)
            _bound(record, process, self.tasks.worktree)
            result = self._view(stored, record)
            result["expired"] = self.clock() >= record["expires_at"]
            return result
