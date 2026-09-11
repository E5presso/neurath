"""Native task authority and canonical evidence share a SQLite transaction."""
import json
import hashlib
from pathlib import Path

from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import (
    ActorStatus, ForegroundTurnStatus, SessionLocator, SessionStateStore, SessionStatus,
)
from scripts.agent_harness.task_ledger import (
    TaskDefinition, TaskEvidence, TaskLedger, TaskLedgerError, TaskSource, TaskStatus, _digest, _json,
)


def read_ledger(tx, process):
    record = tx.get("task-ledger", str(process.session.id))
    ledger = (TaskLedger.empty(str(process.session.id), str(process.session.root_actor_id))
              if record is None else TaskLedger.decode(record.payload))
    if ledger.session != str(process.session.id) or ledger.owner != str(process.session.root_actor_id):
        raise TaskLedgerError("task list belongs to another session or owner")
    return record, ledger


def require_settled_tasks(tx, process):
    """Check the latest task revision inside the transaction that closes the root turn."""
    record, ledger = read_ledger(tx, process)
    if record is None:
        # Legacy workflows retain their existing Stop rules. Do not infer a
        # second task list from workflow status; registered tasks are authoritative.
        return
    if not ledger.all_terminal:
        pending = [task.id for task in ledger.tasks if not task.status.terminal]
        raise TaskLedgerError(f"unsettled task list revision {ledger.revision}: {', '.join(pending[:8])}")


class TaskService:
    def __init__(self, handle, *, worktree=None, admission=None):
        self.handle = handle
        self.admission = admission
        root = handle._repository_control_root()
        self.worktree = Path(root if worktree is None else worktree).resolve()
        self.database = RuntimeDatabase(root)
        self.session_store = SessionStateStore(SessionLocator(root).locate(handle.session_id).process_state)

    def _process(self, tx, *, mutation):
        process = self.session_store.read_transaction(tx, self.handle.session_id)
        if self.admission is not None:
            self.admission(process)
        actor = process.actors.get(self.handle.actor_id)
        if (process.session.status is not SessionStatus.ACTIVE or actor is None
                or actor.status not in {ActorStatus.ACTIVE, ActorStatus.IDLE}):
            raise TaskLedgerError("task access requires an active native participant")
        if mutation and process.session.root_actor_id != self.handle.actor_id:
            raise TaskLedgerError("task mutation requires the native root owner")
        turn = process.foreground_turns.get(self.handle.actor_id)
        if mutation and (turn is None or turn.status is not ForegroundTurnStatus.ACTIVE):
            raise TaskLedgerError("task mutation requires an active foreground turn")
        return process

    def _result(self, tx, ledger, process):
        from .task_todo import instruction
        result = json.loads(ledger.encode())
        # Retry bookkeeping stays in SQLite; it is not task-list content.
        result.pop("operations", None)
        result["all_terminal"] = ledger.all_terminal
        turn = process.foreground_turns.get(process.session.root_actor_id)
        prompt = None if turn is None else turn.user_prompt_receipt
        result["current_prompt_source"] = None if prompt is None else {
            "kind": "prompt", "reference": prompt.authority_reference, "revision": prompt.prompt_digest}
        for task, projection in zip(ledger.tasks, result["tasks"], strict=True):
            projection["definition_digest"] = task.definition.digest
            if task.evidence is not None and task.evidence.source_basis.startswith("sha256:"):
                reference = task.evidence.source_basis
                digest = reference.removeprefix("sha256:")
                stored = tx.get(f"artifact:{process.session.id}", digest)
                if (stored is None or hashlib.sha256(stored.payload).hexdigest() != digest
                        or task.evidence.payload_digest != digest):
                    raise TaskLedgerError("task result report is missing or corrupt")
                report = json.loads(stored.payload)
                if (report.get("schema") != "neurath.task-result.v1"
                        or report.get("task_id") != task.id
                        or report.get("definition_digest") != task.definition.digest):
                    raise TaskLedgerError("task result report identifies another task")
                projection["result_report_reference"] = reference
                projection["assurance"] = report["assurance"]
        # The host adapter must publish this projection through its native TODO tool.
        result["todo_projection"] = [{"id": task.id, "title": task.definition.title,
                                      "status": task.status.value} for task in ledger.tasks]
        result["native_todo"] = instruction(tx, process, ledger)
        return result

    def list(self):
        with self.database.transaction() as tx:
            process = self._process(tx, mutation=False)
            _, ledger = read_ledger(tx, process)
            return self._result(tx, ledger, process)

    def _mutate(self, key, request, transform):
        with self.database.transaction() as tx:
            process = self._process(tx, mutation=True)
            record, ledger = read_ledger(tx, process)
            namespace = f"task-request:{process.session.id}"
            prior = tx.get(namespace, key)
            request_digest = _digest(request).encode()
            if prior is not None:
                if prior.payload != request_digest:
                    raise TaskLedgerError("task request key reused for different input")
                return self._result(tx, ledger, process)
            candidate = transform(tx, process, ledger)
            if candidate is not ledger:
                tx.put("task-ledger", str(process.session.id), candidate.encode(),
                       expected_revision=None if record is None else record.revision)
            tx.put(namespace, key, request_digest, expected_revision=None)
            return self._result(tx, candidate, process)

    def define(self, tasks, *, expected_revision, key):
        def transform(tx, process, ledger):
            turn = process.foreground_turns.get(process.session.root_actor_id)
            prompt = None if turn is None else turn.user_prompt_receipt
            if prompt is None:
                raise TaskLedgerError("task intake requires a native user instruction receipt")
            definitions = []
            for item in tasks:
                sources = tuple(TaskSource(**source) for source in item["sources"])
                for source in sources:
                    if source.kind == "prompt":
                        record = tx.get(f"prompt:{process.session.id}", source.reference)
                        if record is None:
                            raise TaskLedgerError("instruction prompt receipt is missing")
                        proof = json.loads(record.payload)
                        if (proof["actor_id"] != ledger.owner or proof["prompt_digest"] != source.revision):
                            raise TaskLedgerError("instruction prompt receipt differs from source")
                if not any(source.kind == "prompt" for source in sources):
                    sources += (TaskSource("prompt", prompt.authority_reference, prompt.prompt_digest),)
                definitions.append(TaskDefinition(key=item["key"], title=item["title"], goal=item["goal"],
                    sources=sources, acceptance=tuple(item["acceptance"]), producer="canonical",
                    evidence_contract=item.get("evidence_contract", "agent-report"), dependencies=tuple(item["dependencies"])))
            return ledger.define(tuple(definitions), expected_revision=expected_revision, key=key)
        request = ["define", expected_revision, sorted(tasks, key=lambda item: item["key"])]
        return self._mutate(key, request, transform)

    def start(self, task_id, *, expected_revision, expected_task_revision, key):
        return self._mutate(key, ["start", task_id, expected_revision, expected_task_revision],
            lambda tx, process, ledger: ledger.start(task_id, expected_revision=expected_revision,
                expected_task_revision=expected_task_revision, key=key))

    def resolve(self, task_id, *, expected_revision, expected_task_revision, key, references,
                status, summary):
        """Record the owner result once without a separate workflow completion gate."""
        from .task_ledger import _text
        requested = TaskStatus(status)
        if not requested.terminal:
            raise TaskLedgerError("resolution requires a terminal status")
        _text(summary, 4096)

        def transform(tx, process, ledger):
            def resolver(task, refs):
                report = {"schema": "neurath.task-result.v1", "task_id": task.id,
                    "definition_digest": task.definition.digest, "status": requested.value,
                    "summary": summary, "result_references": list(refs),
                    "assurance": "agent-report", "actor_id": ledger.owner}
                from scripts.agent_harness.artifact_store import SessionArtifactStore
                receipt = SessionArtifactStore(self.handle).put_json(report)
                return TaskEvidence(status=requested, subject=task.id, owner=ledger.owner,
                    definition_digest=task.definition.digest, producer=task.definition.producer,
                    references=refs, source_basis=receipt.reference,
                    payload_digest=receipt.reference.removeprefix("sha256:"), reason=summary)
            return ledger.resolve(task_id, expected_revision=expected_revision,
                expected_task_revision=expected_task_revision, key=key,
                references=tuple(references), resolver=resolver)
        return self._mutate(key, ["resolve", task_id, expected_revision, expected_task_revision,
            sorted(references), status, summary], transform)
