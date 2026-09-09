"""Native task authority and canonical evidence share a SQLite transaction."""
import json
import hashlib
from pathlib import Path

from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_kernel import (
    ActorStatus, ForegroundTurnStatus, SessionLocator, SessionStateStore, SessionStatus, WorkflowStatus,
)
from scripts.agent_harness.task_ledger import (
    TaskDefinition, TaskEvidence, TaskLedger, TaskLedgerError, TaskSource, TaskStatus, _digest, _json,
)


def _resolution_assignment(task, workflow):
    return {"kind": "task-resolution", "task_id": task.id,
            "definition_digest": task.definition.digest, "workflow_id": str(workflow.id),
            "workflow_revision": workflow.revision,
            "workflow_payload_digest": _digest(workflow.to_payload())}


def read_ledger(tx, process):
    record = tx.get("task-ledger", str(process.session.id))
    ledger = (TaskLedger.empty(str(process.session.id), str(process.session.root_actor_id))
              if record is None else TaskLedger.decode(record.payload))
    if ledger.session != str(process.session.id) or ledger.owner != str(process.session.root_actor_id):
        raise TaskLedgerError("task list belongs to another session or owner")
    return record, ledger


def bind_active_workflows(tx, process, ledger=None):
    """Bind task scope while its execution workflow is active, never after completion."""
    if ledger is None:
        record = tx.get("task-ledger", str(process.session.id))
        if record is None:
            return
        _, ledger = read_ledger(tx, process)
    namespace = f"task-workflow:{process.session.id}"
    for task in ledger.tasks:
        workflow = process.workflows.get(task.definition.evidence_contract)
        if (task.status.terminal or workflow is None or workflow.status is not WorkflowStatus.ACTIVE
                or str(workflow.owner_actor_id) != ledger.owner
                or workflow.goal != task.definition.goal):
            continue
        binding = {"task_id": task.id, "definition_digest": task.definition.digest,
                   "workflow_id": str(workflow.id), "workflow_kind": workflow.kind,
                   "owner": ledger.owner, "goal": workflow.goal}
        old = tx.get(namespace, task.id)
        if old is None:
            tx.put(namespace, task.id, _json(binding), expected_revision=None)
        elif old.payload != _json(binding):
            raise TaskLedgerError("task workflow binding changed")


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
    from .task_todo import require_current
    require_current(tx, process, ledger)


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
        result["all_terminal"] = ledger.all_terminal
        turn = process.foreground_turns.get(process.session.root_actor_id)
        prompt = None if turn is None else turn.user_prompt_receipt
        result["current_prompt_source"] = None if prompt is None else {
            "kind": "prompt", "reference": prompt.authority_reference, "revision": prompt.prompt_digest}
        for task, projection in zip(ledger.tasks, result["tasks"], strict=True):
            projection["definition_digest"] = task.definition.digest
            workflow = process.workflows.get(task.definition.evidence_contract)
            if (not task.status.terminal and workflow is not None
                    and workflow.status in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}
                    and workflow.owner_actor_id == process.session.root_actor_id):
                projection["optional_resolution_review"] = {
                    "assignment": _resolution_assignment(task, workflow),
                    "workflow_reference": f"workflow:{workflow.id}:{workflow.revision}",
                    "acceptance_conditions": list(task.definition.acceptance)}
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
            if prompt is not None:
                projection["invalidation_assignment"] = {
                    "kind": "task-invalidation", "task_id": task.id,
                    "definition_digest": task.definition.digest,
                    "source_reference": prompt.authority_reference, "source_digest": prompt.prompt_digest}
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
            bind_active_workflows(tx, process, candidate)
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
                    evidence_contract=item["evidence_contract"], dependencies=tuple(item["dependencies"])))
            return ledger.define(tuple(definitions), expected_revision=expected_revision, key=key)
        request = ["define", expected_revision, sorted(tasks, key=lambda item: item["key"])]
        return self._mutate(key, request, transform)

    def start(self, task_id, *, expected_revision, expected_task_revision, key):
        return self._mutate(key, ["start", task_id, expected_revision, expected_task_revision],
            lambda tx, process, ledger: ledger.start(task_id, expected_revision=expected_revision,
                expected_task_revision=expected_task_revision, key=key))

    def resolve(self, task_id, *, expected_revision, expected_task_revision, key, references,
                status, assessment=None, decision=None):
        requested = TaskStatus(status)
        if requested in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
            if assessment is None or decision is not None:
                raise TaskLedgerError("success or failure requires only a root acceptance assessment")
        elif assessment is not None:
            raise TaskLedgerError("invalidation does not accept a workflow assessment")
        def transform(tx, process, ledger):
            def resolver(task, refs):
                if requested is TaskStatus.INVALIDATED:
                    proof = (self._invalidation_evidence(tx, process, task, refs)
                             if decision is None else
                             self._root_invalidation_evidence(tx, process, task, refs, decision))
                else:
                    proof = self._workflow_evidence(tx, process, task, refs, assessment)
                if proof.status is not requested:
                    raise TaskLedgerError("requested status disagrees with canonical evidence")
                return proof
            return ledger.resolve(task_id, expected_revision=expected_revision,
                expected_task_revision=expected_task_revision, key=key,
                references=tuple(references), resolver=resolver)
        return self._mutate(key, ["resolve", task_id, expected_revision, expected_task_revision,
            sorted(references), status, assessment, decision], transform)

    def _store_result_report(self, payload):
        from scripts.agent_harness.artifact_store import SessionArtifactStore
        receipt = SessionArtifactStore(self.handle).put_json(payload)
        return receipt.reference, receipt.reference.removeprefix("sha256:")

    def _root_assessment(self, process, task, derived, workflow_ref, assessment):
        if (not isinstance(assessment, dict) or set(assessment) != {"summary", "acceptance"}
                or not isinstance(assessment["summary"], str) or not assessment["summary"].strip()):
            raise TaskLedgerError("task resolution requires a concise root acceptance assessment")
        coverage = assessment["acceptance"]
        if (not isinstance(coverage, list)
                or len(coverage) != len(task.definition.acceptance)):
            raise TaskLedgerError("root assessment must cover every declared acceptance condition")
        normalized, outcomes = [], []
        for condition, entry in zip(task.definition.acceptance, coverage, strict=True):
            if (not isinstance(entry, dict)
                    or set(entry) != {"condition", "outcome", "explanation", "reference"}
                    or entry["condition"] != condition or entry["outcome"] not in {"met", "unmet"}
                    or not isinstance(entry["explanation"], str)
                    or not entry["explanation"].strip() or entry["reference"] != workflow_ref):
                raise TaskLedgerError(
                    "acceptance coverage is missing, changed or references another result")
            outcomes.append(entry["outcome"])
            normalized.append({"condition": condition, "outcome": entry["outcome"],
                "explanation": entry["explanation"].strip(), "reference": workflow_ref})
        if (derived is TaskStatus.SUCCEEDED and
                any(outcome != "met" for outcome in outcomes)):
            raise TaskLedgerError("successful workflow requires every condition to be met")
        if derived is TaskStatus.FAILED and "unmet" not in outcomes:
            raise TaskLedgerError("failed workflow requires an observed unmet condition")
        return {"actor_id": str(process.session.root_actor_id),
                "summary": assessment["summary"].strip(), "acceptance": normalized}

    def _invalidation_evidence(self, tx, process, task, references):
        from scripts.agent_harness.artifact_store import SessionArtifactStore
        from scripts.agent_harness.session_kernel import (
            ActorKind, ActorLineageAssurance, DelegationStatus, DelegationTopologyPolicy,
        )
        identity = references[0][len("delegation:"):]
        delegation = process.delegations.get(identity)
        if (delegation is None or delegation.status is not DelegationStatus.CONSUMED
                or delegation.owner_actor_id != process.session.root_actor_id
                or delegation.topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD):
            raise TaskLedgerError("task invalidation requires consumed independent review")
        reviewer = process.actors.get(delegation.target_actor_id)
        if (reviewer is None or reviewer.kind is not ActorKind.SUBAGENT
                or reviewer.parent_actor_id != process.session.root_actor_id
                or reviewer.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED):
            raise TaskLedgerError("task decision reviewer lacks native independent lineage")
        assignment = json.loads(delegation.assignment)
        expected_fields = {"kind", "task_id", "definition_digest", "source_reference", "source_digest"}
        if (not isinstance(assignment, dict) or set(assignment) != expected_fields
                or assignment["kind"] != "task-invalidation" or assignment["task_id"] != task.id
                or assignment["definition_digest"] != task.definition.digest):
            raise TaskLedgerError("invalidation review identifies another task definition")
        source = tx.get(f"prompt:{process.session.id}", assignment["source_reference"])
        if source is not None:
            native = json.loads(source.payload)
            if (
                native["actor_id"] != str(process.session.root_actor_id)
                or native["prompt_digest"] != assignment["source_digest"]
            ):
                raise TaskLedgerError("invalidation substituted user source content")
        else:
            try:
                from neurath.runtime.user_choices import verify_registered_prompt
                native = verify_registered_prompt(
                    self.worktree,
                    process.session.id,
                    assignment["source_reference"],
                    assignment["source_digest"],
                )
            except (ValueError, OSError) as error:
                raise TaskLedgerError(
                    "invalidation has no authenticated user source") from error
        result = delegation.result
        if result.verdict != "pass" or result.blocking_findings:
            raise TaskLedgerError("independent reviewer did not accept task invalidation")
        report = SessionArtifactStore(self.handle).read_json(result.outcome_ref)
        if (set(report) != {"kind", "assignment", "verdict", "disposition", "reason",
                            "covering_sources", "covering_workflows"}
                or report["kind"] != "task-invalidation-result"
                or report["assignment"] != assignment or report["verdict"] != result.verdict
                or report["reason"] != result.summary
                or report["disposition"] not in {"cancelled", "duplicate", "superseded", "no-longer-required"}):
            raise TaskLedgerError("invalidation artifact differs from its native reviewer report")
        sources, workflows = report["covering_sources"], report["covering_workflows"]
        if (not isinstance(sources, list) or not isinstance(workflows, list)
                or len(sources) + len(workflows) > 32):
            raise TaskLedgerError("invalidation coverage must be a bounded list")
        if report["disposition"] in {"duplicate", "superseded"} and not (sources or workflows):
            raise TaskLedgerError("duplicate or superseded task requires covering evidence")
        for covered in sources:
            if not isinstance(covered, dict) or set(covered) != {"path", "sha256"}:
                raise TaskLedgerError("invalid covering source reference")
            path = Path(covered["path"])
            resolved = (self.worktree / path).resolve()
            if (path.is_absolute() or ".." in path.parts or not resolved.is_relative_to(self.worktree)
                    or not resolved.is_file()
                    or any(resolved.is_relative_to(self.worktree / private) for private in
                           (".git", ".neurath/local", ".agents/runs", ".agents/resources"))
                    or hashlib.sha256(resolved.read_bytes()).hexdigest() != covered["sha256"]):
                raise TaskLedgerError("covering source is missing, stale or outside product scope")
        for covered in workflows:
            if not isinstance(covered, dict) or set(covered) != {"id", "revision"}:
                raise TaskLedgerError("invalid covering workflow reference")
            workflow = process.workflows.get(covered["id"])
            if (workflow is None or workflow.status is not WorkflowStatus.COMPLETED
                    or workflow.revision != covered["revision"]):
                raise TaskLedgerError("covering workflow is not currently completed")
        return TaskEvidence(status=TaskStatus.INVALIDATED, subject=task.id,
            owner=str(process.session.root_actor_id), definition_digest=task.definition.digest,
            producer="canonical", references=references, source_basis=_digest(native),
            payload_digest=_digest({"delegation": delegation.to_payload(), "report": report}),
            reason=report["reason"])

    def _workflow_evidence(self, tx, process, task, references, assessment):
        from scripts.skill_harness.phase_runner import PhaseRunState
        workflow_refs = [ref for ref in references if ref.startswith("workflow:")]
        review_refs = [ref for ref in references if ref.startswith("delegation:")]
        if (len(workflow_refs) != 1 or len(review_refs) > 1
                or len(references) != 1 + len(review_refs)):
            raise TaskLedgerError(
                "resolution requires one exact workflow and at most one optional review")
        identity, separator, revision = workflow_refs[0][len("workflow:"):].rpartition(":")
        if not separator or not revision.isdecimal():
            raise TaskLedgerError("workflow evidence requires an exact revision")
        workflow = process.workflows.get(identity)
        binding_record = tx.get(f"task-workflow:{process.session.id}", task.id)
        if workflow is None or binding_record is None:
            raise TaskLedgerError("task lacks its original active workflow binding")
        binding = json.loads(binding_record.payload)
        if (binding != {"task_id": task.id, "definition_digest": task.definition.digest,
                        "workflow_id": str(workflow.id), "workflow_kind": workflow.kind,
                        "owner": str(workflow.owner_actor_id), "goal": workflow.goal}
                or identity != task.definition.evidence_contract
                or workflow.owner_actor_id != process.session.root_actor_id
                or workflow.revision != int(revision)):
            raise TaskLedgerError("workflow evidence is foreign, stale or changed")
        derived = {WorkflowStatus.COMPLETED: TaskStatus.SUCCEEDED,
                   WorkflowStatus.FAILED: TaskStatus.FAILED}.get(workflow.status)
        if derived is None:
            raise TaskLedgerError("workflow has not reached its canonical terminal state")
        phase = PhaseRunState.from_payload(dict(workflow.payload.get("phase_run", {})))
        if (phase.current_phase_id is not None or phase.terminal_state is None
                or phase.north_star != task.definition.goal or phase.skill != workflow.kind):
            raise TaskLedgerError("workflow phase evidence does not complete this task")
        root_assessment = self._root_assessment(
            process, task, derived, workflow_refs[0], assessment)
        optional_review = (None if not review_refs else self._acceptance_review(
            process, task, workflow, derived, workflow_refs[0], review_refs[0],
            root_assessment))
        report = {"schema": "neurath.task-result.v1", "task_id": task.id,
            "definition_digest": task.definition.digest, "status": derived.value,
            "result_references": [workflow_refs[0]], "assurance": "agent-assessment",
            "assessment": root_assessment, "decision": None,
            "optional_review_reference": None if not review_refs else review_refs[0]}
        report_ref, report_digest = self._store_result_report(report)
        return TaskEvidence(status=derived, subject=task.id, owner=str(workflow.owner_actor_id),
            definition_digest=task.definition.digest, producer="canonical", references=references,
            source_basis=report_ref, payload_digest=report_digest,
            reason=root_assessment["summary"])

    def _acceptance_review(self, process, task, workflow, derived, workflow_ref, review_ref,
                           root_assessment):
        """Validate a supplied independent review; ordinary resolution may omit it."""
        from scripts.agent_harness.artifact_store import SessionArtifactStore
        from scripts.agent_harness.session_kernel import (
            ActorKind, ActorLineageAssurance, DelegationStatus, DelegationTopologyPolicy,
        )
        delegation = process.delegations.get(review_ref[len("delegation:"):])
        if (delegation is None or delegation.status is not DelegationStatus.CONSUMED
                or delegation.owner_actor_id != process.session.root_actor_id
                or delegation.topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD):
            raise TaskLedgerError("task resolution requires consumed independent acceptance review")
        reviewer = process.actors.get(delegation.target_actor_id)
        if (reviewer is None or reviewer.kind is not ActorKind.SUBAGENT
                or reviewer.parent_actor_id != process.session.root_actor_id
                or reviewer.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED):
            raise TaskLedgerError("task acceptance reviewer lacks native independent lineage")
        expected = _resolution_assignment(task, workflow)
        assignment = json.loads(delegation.assignment)
        if assignment != expected:
            raise TaskLedgerError("acceptance review identifies another task or workflow revision")
        result = delegation.result
        if result is None or result.verdict != "pass" or result.blocking_findings:
            raise TaskLedgerError("independent reviewer did not accept the task outcome")
        report = SessionArtifactStore(self.handle).read_json(result.outcome_ref)
        if (not isinstance(report, dict)
                or set(report) != {"kind", "assignment", "verdict", "status", "reason", "acceptance"}
                or report["kind"] != "task-resolution-result" or report["assignment"] != expected
                or report["verdict"] != result.verdict or report["status"] != derived.value
                or not isinstance(report["reason"], str) or not report["reason"].strip()
                or report["reason"] != result.summary):
            raise TaskLedgerError("acceptance artifact differs from its native reviewer report")
        coverage = report["acceptance"]
        if not isinstance(coverage, list) or len(coverage) != len(task.definition.acceptance):
            raise TaskLedgerError("acceptance review must cover every declared condition")
        outcomes = []
        for condition, entry in zip(task.definition.acceptance, coverage, strict=True):
            if (not isinstance(entry, dict) or set(entry) != {"condition", "outcome", "references"}
                    or entry["condition"] != condition or entry["outcome"] not in {"met", "unmet"}
                    or entry["references"] != [workflow_ref]):
                raise TaskLedgerError("acceptance coverage has missing, changed or noncanonical evidence")
            outcomes.append(entry["outcome"])
        if ((derived is TaskStatus.SUCCEEDED and any(outcome != "met" for outcome in outcomes))
                or (derived is TaskStatus.FAILED and "unmet" not in outcomes)):
            raise TaskLedgerError("task outcome disagrees with its acceptance conditions")
        for reviewed, assessed in zip(coverage, root_assessment["acceptance"], strict=True):
            if (reviewed["condition"] != assessed["condition"]
                    or reviewed["outcome"] != assessed["outcome"]
                    or reviewed["references"] != [assessed["reference"]]):
                raise TaskLedgerError(
                    "optional acceptance review disagrees with root assessment")
        return {"delegation": delegation.to_payload(), "report": report}

    def _root_invalidation_evidence(self, tx, process, task, references, decision):
        prompt_refs = [ref for ref in references if ref.startswith("prompt:")]
        if len(prompt_refs) != 1 or len(references) != 1:
            raise TaskLedgerError(
                "root invalidation requires one exact authenticated prompt reference")
        expected = {"source_reference", "source_digest", "disposition", "reason",
                    "covering_sources", "covering_workflows"}
        if not isinstance(decision, dict) or set(decision) != expected:
            raise TaskLedgerError("invalidation source decision fields are invalid")
        if decision["disposition"] not in {
                "cancelled", "duplicate", "superseded", "no-longer-required"}:
            raise TaskLedgerError("invalid task disposition")
        if not isinstance(decision["reason"], str) or not decision["reason"].strip():
            raise TaskLedgerError("invalidation requires a task-specific reason")
        expected_ref = f"prompt:{decision['source_reference']}:{decision['source_digest']}"
        if prompt_refs[0] != expected_ref:
            raise TaskLedgerError(
                "invalidation reference differs from its authenticated source")
        source = tx.get(f"prompt:{process.session.id}", decision["source_reference"])
        if source is not None:
            native = json.loads(source.payload)
            if (native["actor_id"] != str(process.session.root_actor_id)
                    or native["prompt_digest"] != decision["source_digest"]):
                raise TaskLedgerError("invalidation substituted user source content")
        else:
            try:
                from neurath.runtime.user_choices import verify_registered_prompt
                native = verify_registered_prompt(self.worktree, process.session.id,
                    decision["source_reference"], decision["source_digest"])
            except (ValueError, OSError) as error:
                raise TaskLedgerError(
                    "invalidation has no authenticated user source") from error
        sources, workflows = decision["covering_sources"], decision["covering_workflows"]
        if (not isinstance(sources, list) or not isinstance(workflows, list)
                or len(sources) + len(workflows) > 32):
            raise TaskLedgerError("invalidation coverage must be a bounded list")
        if decision["disposition"] in {"duplicate", "superseded"} and not (sources or workflows):
            raise TaskLedgerError("duplicate or superseded task requires covering evidence")
        for covered in sources:
            if not isinstance(covered, dict) or set(covered) != {"path", "sha256"}:
                raise TaskLedgerError("invalid covering source reference")
            path = Path(covered["path"])
            resolved = (self.worktree / path).resolve()
            if (path.is_absolute() or ".." in path.parts
                    or not resolved.is_relative_to(self.worktree) or not resolved.is_file()
                    or any(resolved.is_relative_to(self.worktree / private) for private in
                           (".git", ".neurath/local", ".agents/runs", ".agents/resources"))
                    or hashlib.sha256(resolved.read_bytes()).hexdigest() != covered["sha256"]):
                raise TaskLedgerError(
                    "covering source is missing, stale or outside product scope")
        for covered in workflows:
            if not isinstance(covered, dict) or set(covered) != {"id", "revision"}:
                raise TaskLedgerError("invalid covering workflow reference")
            workflow = process.workflows.get(covered["id"])
            if (workflow is None or workflow.status is not WorkflowStatus.COMPLETED
                    or workflow.revision != covered["revision"]):
                raise TaskLedgerError("covering workflow is not currently completed")
        normalized_decision = {**decision, "reason": decision["reason"].strip()}
        report = {"schema": "neurath.task-result.v1", "task_id": task.id,
            "definition_digest": task.definition.digest,
            "status": TaskStatus.INVALIDATED.value,
            "result_references": [prompt_refs[0]], "assurance": "agent-assessment",
            "assessment": None, "decision": normalized_decision,
            "optional_review_reference": None}
        report_ref, report_digest = self._store_result_report(report)
        return TaskEvidence(status=TaskStatus.INVALIDATED, subject=task.id,
            owner=str(process.session.root_actor_id),
            definition_digest=task.definition.digest, producer="canonical",
            references=tuple(references), source_basis=report_ref,
            payload_digest=report_digest, reason=normalized_decision["reason"])
