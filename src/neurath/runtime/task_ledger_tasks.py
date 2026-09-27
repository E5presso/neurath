"""Named measurable task operations bound to the current native session."""

import hashlib
import re
from collections import Counter, defaultdict


def _explicit_autopilot_invocation(text):
    command = re.compile(r"^(?:\[\$autopilot\]\(|[$/]autopilot\b|autopilot\s+#\d+|"
                         r"(?:please\s+)?(?:use|run|invoke|execute)\s+(?:the\s+)?[$/]?autopilot\b|"
                         r"(?:can|could|would|will)\s+you\s+(?:please\s+)?"
                         r"(?:use|run|invoke|execute)\s+(?:the\s+)?[$/]?autopilot\b|"
                         r"이제\s+[$/]?autopilot\b)", re.IGNORECASE)
    return any(command.search(line.strip()) for line in text.splitlines())


def _require_autopilot_phase(root, identity, process, actor_id, task, ledger=None):
    """Fence work while a matching explicit autopilot request is unsettled."""
    from neurath.runtime.task_schema import TaskError
    from neurath.runtime.user_choices import native_messages
    try:
        # Terminal workflows span the whole native session; count invocations over
        # that same history, not the choice reader's bounded recent window.
        messages = native_messages(root, identity, record_limit=None)
    except ValueError as error:
        raise TaskError("autopilot-transcript-unavailable",
                        "registered native transcript is required for phase admission") from error
    tasks = (task,) if ledger is None else ledger.tasks
    known_digests = {source.revision for candidate in tasks
                     for source in candidate.definition.sources if source.kind == "prompt"}
    turn = getattr(process, "foreground_turns", {}).get(actor_id)
    receipt = None if turn is None else turn.user_prompt_receipt
    current_prompt_digest = None if receipt is None else receipt.prompt_digest
    if receipt is not None:
        known_digests.add(receipt.prompt_digest)
    known_digests.update(workflow.payload.get("invocation_prompt_digest")
        for workflow in process.workflows.values() if workflow.kind == "autopilot"
        and isinstance(workflow.payload.get("invocation_prompt_digest"), str))

    def prompt_digest(text):
        # Codex's visible transcript can append a line ending to the exact
        # foreground prompt used by the native receipt.
        exact = hashlib.sha256(text.encode()).hexdigest()
        visible = hashlib.sha256(text.rstrip("\r\n").encode()).hexdigest()
        return exact if exact in known_digests else visible
    invocations = Counter(prompt_digest(text) for role, text in messages
                          if role == "user" and _explicit_autopilot_invocation(text))
    if not invocations:
        return
    groups = defaultdict(list)
    source_goals = defaultdict(set)
    for candidate in tasks:
        for source in candidate.definition.sources:
            if source.kind == "prompt" and source.revision in invocations:
                groups[(source.reference, source.revision)].append(candidate.status.value)
                if candidate.status.value in {"pending", "in_progress"}:
                    source_goals[(source.reference, source.revision)].add(candidate.definition.goal)
    covered = defaultdict(set)
    for (reference, digest), statuses in groups.items():
        if all(status in {"succeeded", "failed", "invalidated"} for status in statuses):
            covered[digest].add(reference)
    active = []
    for workflow_id, workflow in process.workflows.items():
        if workflow.kind != "autopilot" or str(workflow.owner_actor_id) != str(actor_id):
            continue
        digest = workflow.payload.get("invocation_prompt_digest")
        reference = workflow.payload.get("invocation_prompt_reference")
        if digest in invocations and isinstance(reference, str):
            covered[digest].add(reference)
        if workflow.status.value == "active":
            active.append((workflow_id, workflow))
    used_recovery = set()
    for digest, count in invocations.items():
        if count <= len(covered[digest]):
            continue
        for workflow_id, workflow in active:
            if workflow_id in used_recovery or current_prompt_digest == digest:
                continue
            start_digest = workflow.payload.get("invocation_prompt_digest")
            if start_digest is not None and start_digest != current_prompt_digest:
                continue
            reference = next((reference for reference, source_digest in groups
                if source_digest == digest and workflow.goal in source_goals[(reference, digest)]
                and reference not in covered[digest]), None)
            if reference is None and sum(invocations.values()) - sum(map(len, covered.values())) == 1:
                if workflow.goal == task.definition.goal:
                    reference = "recovered-workflow:" + str(workflow_id)
            if reference is not None:
                covered[digest].add(reference)
                used_recovery.add(workflow_id)
                break
        if count > len(covered[digest]):
            break
    else:
        return
    raise TaskError("autopilot-phase-required",
                    "call phase_start for the explicit autopilot request before task_start")


def definitions():
    from neurath.runtime.task_schema import choice, text_field
    revision = {"type": "integer", "minimum": 0, "maximum": 2**53 - 1}
    def array(items, minimum=0, maximum=64):
        return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties),
                "additionalProperties": False}
    source = obj({"kind": choice("prompt", "ticket", "spec"), "reference": text_field(4096),
                  "revision": text_field(4096)})
    definition = obj({"key": text_field(512), "title": text_field(512), "goal": text_field(),
        "sources": array(source, maximum=31), "acceptance": array(text_field(), 1, 32),
        "dependencies": array(text_field(128))})
    exact_task = {"task_id": text_field(128), "expected_revision": revision,
                  "expected_task_revision": revision, "key": text_field(512)}
    entries = {
        "task_define": ("Define work progressively: append necessary follow-up as it becomes concrete, before losing it at task completion. First judge which unmet user requirement it advances, whether existing results already cover it, and whether its scope only perfects a chosen method. Put the bounded outcome in goal/acceptance and retain the original instruction sources; no separate reflection report. Peer-resumed turns may explicitly reference retained same-session user prompt sources without creating a fresh user receipt. Status questions do not authorize scope expansion.",
                        {"tasks": array(definition, 1), "expected_revision": revision, "key": text_field(512)}, False),
        "task_list": ("Read tasks, revision and TODO projection. all_terminal means execution ended, not success; inspect all_succeeded and unsuccessful_task_ids. Outcomes are owner reports.", {}, True),
        "task_start": ("Select work that still advances an unmet user requirement; reuse existing results and reconsider unnecessary methods. Start one pending task using its exact task and list revisions.", exact_task, False),
        "task_resolve": ("Before resolving, use task_define for discovered necessary follow-up not already tracked, with its original requirement source and bounded acceptance. Record an observed outcome once. Failure needs the unmet condition, actual blocker and next action; Stop rejection, elapsed time or a status question is not failure or cancellation evidence.",
                         {**exact_task, "status": choice("succeeded", "failed", "invalidated"),
                          "references": array(text_field(4096), 1, 32),
                          "summary": text_field(4096)}, False),
    }
    return {name: ("task-ledger", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


def service_for(root, *, identity, expected_turn, verified_policy_evidence=None,
                operation_name=None):
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.task_schema import TaskError
    handle = _handle(root, identity, expected_turn, verified_policy_evidence)
    from scripts.agent_harness.task_service import TaskService
    from neurath.agents.hooks import participation
    from neurath.agents.mcp import _prompt_receipt
    from neurath.hosts.identity import active_connection
    from neurath.memory.store import canonical

    def admission(process):
        actor = process.actors.get(handle.actor_id)
        if (actor is None or participation(process, actor) != (True, expected_turn)
                or canonical(_prompt_receipt(process, actor)) !=
                   canonical(verified_policy_evidence["user_prompt_receipt"])
                or not active_connection(root, identity.session)):
            raise TaskError("native-turn-changed", "task transaction lost its native prompt or connection")

    def start_admission(process, ledger, task_id):
        task = next((item for item in ledger.tasks if item.id == task_id), None)
        if task is not None:
            _require_autopilot_phase(root, identity, process, handle.actor_id, task, ledger)

    def resolve_admission(process, ledger, task_id):
        task = next((item for item in ledger.tasks if item.id == task_id), None)
        if task is not None and task.status.value == "pending":
            _require_autopilot_phase(root, identity, process, handle.actor_id, task, ledger)

    return TaskService(handle, worktree=root, admission=admission,
                       start_admission=start_admission if operation_name == "task_start" else None,
                       resolve_admission=resolve_admission if operation_name == "task_resolve" else None)


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence=None):
    from neurath.runtime.task_schema import TaskError
    service = service_for(root, identity=identity, expected_turn=expected_turn,
                          verified_policy_evidence=verified_policy_evidence,
                          operation_name=name)
    from scripts.agent_harness.task_ledger import TaskLedgerError, TaskRevisionConflict
    operation = {"task_define": service.define, "task_list": service.list,
                 "task_start": service.start, "task_resolve": service.resolve}[name]
    try:
        return operation(**fields)
    except TaskRevisionConflict as error:
        raise TaskError("revision-conflict", str(error)) from error
    except TaskLedgerError as error:
        raise TaskError("task-contract-rejected", str(error)) from error
