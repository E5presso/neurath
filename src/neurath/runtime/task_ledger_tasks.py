"""Named measurable task operations bound to the current native session."""


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
    assessment = obj({"summary": text_field(4096), "acceptance": array(obj({
        "condition": text_field(), "outcome": choice("met", "unmet"),
        "explanation": text_field(4096), "reference": text_field(4096)}), 1, 32)})
    decision = obj({"source_reference": text_field(4096), "source_digest": text_field(64),
        "disposition": choice("cancelled", "duplicate", "superseded", "no-longer-required"),
        "reason": text_field(4096),
        "covering_sources": array(obj({"path": text_field(4096), "sha256": text_field(64)}),
                                  maximum=32),
        "covering_workflows": array(obj({"id": text_field(256), "revision": revision}),
                                    maximum=32)})
    definition = obj({"key": text_field(512), "title": text_field(512), "goal": text_field(),
        "sources": array(source, maximum=31), "acceptance": array(text_field(), 1, 32),
        "evidence_contract": text_field(256), "dependencies": array(text_field(128))})
    exact_task = {"task_id": text_field(128), "expected_revision": revision,
                  "expected_task_revision": revision, "key": text_field(512)}
    entries = {
        "task_define": ("Append measurable tasks and issue stable IDs. The native prompt receipt is retained; prior tasks and terminal history remain. Evidence contract names the task's execution workflow, which may start later.",
                        {"tasks": array(definition, 1), "expected_revision": revision, "key": text_field(512)}, False),
        "task_list": ("Read the canonical task list, revision and native TODO projection. An empty or missing list is not completed work.", {}, True),
        "task_start": ("Start one pending task using its exact task and list revisions.", exact_task, False),
        "task_resolve": ("Resolve success/failure from an exact bound terminal workflow and the native root's complete acceptance assessment. Assurance is agent-assessment over observed canonical evidence, not independent proof. An optional submitted independent review remains validated. Invalidation accepts an authenticated prompt-bound root decision or the existing independent decision review. Workflow-owned phase review requirements remain unchanged.",
                         {**exact_task, "status": choice("succeeded", "failed", "invalidated"),
                          "references": array(text_field(4096), 1, 32),
                          "assessment": {"anyOf": [{"type": "null"}, assessment], "default": None},
                          "decision": {"anyOf": [{"type": "null"}, decision], "default": None}}, False),
    }
    return {name: ("task-ledger", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence=None):
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.task_schema import TaskError
    handle = _handle(root, identity, expected_turn, verified_policy_evidence)
    from scripts.agent_harness.task_ledger import TaskLedgerError, TaskRevisionConflict
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

    service = TaskService(handle, worktree=root, admission=admission)
    operation = {"task_define": service.define, "task_list": service.list,
                 "task_start": service.start, "task_resolve": service.resolve}[name]
    try:
        return operation(**fields)
    except TaskRevisionConflict as error:
        raise TaskError("revision-conflict", str(error)) from error
    except TaskLedgerError as error:
        raise TaskError("task-contract-rejected", str(error)) from error
