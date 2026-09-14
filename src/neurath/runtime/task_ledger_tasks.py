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


def service_for(root, *, identity, expected_turn, verified_policy_evidence=None):
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

    return TaskService(handle, worktree=root, admission=admission)


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence=None):
    from neurath.runtime.task_schema import TaskError
    service = service_for(root, identity=identity, expected_turn=expected_turn,
                          verified_policy_evidence=verified_policy_evidence)
    from scripts.agent_harness.task_ledger import TaskLedgerError, TaskRevisionConflict
    operation = {"task_define": service.define, "task_list": service.list,
                 "task_start": service.start, "task_resolve": service.resolve}[name]
    try:
        return operation(**fields)
    except TaskRevisionConflict as error:
        raise TaskError("revision-conflict", str(error)) from error
    except TaskLedgerError as error:
        raise TaskError("task-contract-rejected", str(error)) from error
