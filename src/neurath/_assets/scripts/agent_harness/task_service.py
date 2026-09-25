"""Native task authority and canonical evidence share a SQLite transaction."""
import json
import hashlib
from pathlib import Path

from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import (
    ActorStatus, ForegroundTurnOutcome, ForegroundTurnStatus, SessionLocator, SessionStateStore, SessionStatus,
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


def validate_instruction_sources(tx, process, sources):
    """Validate retained native instructions without creating a new prompt."""
    prompts = [source for source in sources if source.kind == "prompt"]
    if not prompts:
        raise TaskLedgerError("an explicit native prompt source is required")
    for source in prompts:
        record = tx.get(f"prompt:{process.session.id}", source.reference)
        if record is None:
            raise TaskLedgerError("instruction prompt receipt is missing")
        proof = json.loads(record.payload)
        if (proof.get("actor_id") != str(process.session.root_actor_id)
                or proof.get("authority_reference") != source.reference
                or proof.get("prompt_digest") != source.revision):
            raise TaskLedgerError("instruction prompt receipt differs from source")


def validate_task_scope(tx, process, scope):
    if not isinstance(scope, dict) or set(scope) != {"task_id", "task_revision", "definition_digest"}:
        raise TaskLedgerError("invalid task delegation scope")
    if tx.get("session-migration", str(process.session.id)) is not None:
        raise TaskLedgerError("migrated source cannot delegate task work")
    _, ledger = read_ledger(tx, process)
    task = next((task for task in ledger.tasks if task.id == scope["task_id"]), None)
    if (task is None or type(scope["task_revision"]) is not int
            or task.revision != scope["task_revision"] or task.status is not TaskStatus.IN_PROGRESS
            or task.definition.digest != scope["definition_digest"]):
        raise TaskLedgerError("task delegation requires an exact in-progress task")
    validate_instruction_sources(tx, process, task.definition.sources)


def validate_scoped_foreground(tx, process, foreground):
    scope = foreground.get("task_scope")
    if scope is None:
        return
    actor = process.session.root_actor_id
    turn = process.foreground_turns.get(actor)
    if (process.session.status is not SessionStatus.ACTIVE
            or process.actors[actor].status is not ActorStatus.ACTIVE
            or turn is None or turn.status is not ForegroundTurnStatus.ACTIVE
            or foreground != {"generation": turn.generation, "turn": turn.vendor_turn_id,
                              "prompt": None, "task_scope": scope}
            or turn.user_prompt_receipt is not None):
        raise TaskLedgerError("task delegation belongs to an obsolete root turn")
    validate_task_scope(tx, process, scope)


def validate_native_task_grants(tx, previous, candidate):
    """Recheck scoped child grants in the same transaction as the process commit."""
    if previous is None:
        return
    root = candidate.session.root_actor_id
    turn = candidate.foreground_turns.get(root)
    if turn is None or turn.user_prompt_receipt is not None:
        return  # Ordinary user-authorized child lifecycle retains its contract.
    record = tx.get("host-journal", str(candidate.session.id))
    if record is None:
        return
    data = json.loads(record.payload)
    for witness in data.get("spawns", {}).values():
        foreground = witness.get("foreground", {})
        if "task_scope" not in foreground or not witness.get("child"):
            continue
        child_id = f"{witness['host']}:{witness['child']}"
        child = candidate.actors.get(child_id)
        before = previous.actors.get(child_id)
        child_turn = candidate.foreground_turns.get(child_id)
        granted = (child is not None and child.status is ActorStatus.ACTIVE
            and (before is None or before.status is not ActorStatus.ACTIVE
                 or (child_turn is not None and child_turn.status is ForegroundTurnStatus.ACTIVE
                     and previous.foreground_turns.get(child_id) != child_turn)))
        delegation_id = witness.get("delegation", {}).get("id")
        delegated = (delegation_id in candidate.delegations
                     and delegation_id not in previous.delegations)
        if granted or delegated:
            validate_scoped_foreground(tx, candidate, foreground)


def require_settled_tasks(tx, process):
    """Check the latest task revision inside the transaction that closes the root turn."""
    turn = process.foreground_turns.get(process.session.root_actor_id)
    if (turn is not None and turn.receipt is not None
            and turn.receipt.outcome is ForegroundTurnOutcome.AWAITING_INPUT):
        # Returning control is not task completion. Keep the ledger unchanged;
        # a later user prompt starts a new turn with the same unfinished work.
        return
    if tx.get("session-migration", str(process.session.id)) is not None:
        # A committed pull moved unfinished execution to another native root.
        # The original history remains unfinished, not falsely marked successful.
        return
    record, ledger = read_ledger(tx, process)
    if record is None:
        # Legacy workflows retain their existing Stop rules. Do not infer a
        # second task list from workflow status; registered tasks are authoritative.
        return
    if not ledger.all_terminal:
        pending = [task.id for task in ledger.tasks if not task.status.terminal]
        raise TaskLedgerError(
            f"unsettled task list revision {ledger.revision}: {', '.join(pending[:8])}. "
            "Continue the authorized work. A Stop rejection or status question is not "
            "evidence for failing, invalidating, or abandoning these tasks.")


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
        if mutation and tx.get("session-migration", str(process.session.id)) is not None:
            raise TaskLedgerError("session work was migrated; read the receiver reference instead of resuming writes")
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
        # Terminal execution history is not successful delivery. These are
        # projections of the existing ledger, not another completion authority.
        result["all_succeeded"] = bool(ledger.tasks) and all(
            task.status is TaskStatus.SUCCEEDED for task in ledger.tasks)
        result["unsuccessful_task_ids"] = [task.id for task in ledger.tasks
            if task.status in {TaskStatus.FAILED, TaskStatus.INVALIDATED}]
        migration = tx.get("session-migration", str(process.session.id))
        if migration is not None:
            result["superseded_by"] = json.loads(migration.payload)
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
            definitions = []
            for item in tasks:
                sources = tuple(TaskSource(**source) for source in item["sources"])
                has_prompt = any(source.kind == "prompt" for source in sources)
                if prompt is None and not has_prompt:
                    raise TaskLedgerError(
                        "task intake requires a native user instruction receipt or an explicit retained prompt source")
                if (prompt is not None and ledger.tasks and not has_prompt
                        and not any(source.kind == "prompt"
                            and source.reference == prompt.authority_reference
                            and source.revision == prompt.prompt_digest
                            for task in ledger.tasks for source in task.definition.sources)):
                    raise TaskLedgerError(
                        "appending tasks after a new prompt requires an explicit prompt source; "
                        "select the original requirement or an explicit new request from task_list, "
                        "not an implicit status question")
                if not has_prompt:
                    sources += (TaskSource("prompt", prompt.authority_reference, prompt.prompt_digest),)
                validate_instruction_sources(tx, process, sources)
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
            if requested is TaskStatus.SUCCEEDED:
                from .delegation_wave import require_complete
                record = tx.get("host-journal", str(process.session.id))
                if record is not None:
                    try:
                        require_complete(json.loads(record.payload), process, task_id)
                    except ValueError as error:
                        raise TaskLedgerError(str(error)) from error
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
