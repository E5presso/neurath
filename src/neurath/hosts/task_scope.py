"""Explicit task scope for native child work on a peer-resumed root turn."""


def instruction_scope(root, state, task_id, expected_task_revision):
    from neurath.hosts.identity import _locator, active_connection
    from neurath.runtime.database import RuntimeDatabase
    from scripts.agent_harness.session_kernel import SessionStateStore
    from scripts.agent_harness.task_ledger import TaskLedgerError, TaskStatus
    from scripts.agent_harness.task_service import read_ledger, validate_instruction_sources

    locator = _locator(root)
    if not active_connection(root, str(state.session.id)):
        raise TaskLedgerError("task delegation requires an active native connection")
    with RuntimeDatabase(locator.control_root).transaction() as tx:
        current = SessionStateStore(locator.locate(state.session.id).process_state).read_transaction(
            tx, state.session.id)
        actor = current.session.root_actor_id
        turn = current.foreground_turns.get(actor)
        observed = state.foreground_turns.get(actor)
        if (current.session.status.value != "active" or current.actors[actor].status.value != "active"
                or turn is None or turn.status.value != "active" or observed is None
                or (turn.generation, turn.vendor_turn_id, turn.user_prompt_receipt) !=
                   (observed.generation, observed.vendor_turn_id, observed.user_prompt_receipt)):
            raise TaskLedgerError("task delegation requires the current active root turn")
        if tx.get("session-migration", str(state.session.id)) is not None:
            raise TaskLedgerError("migrated source cannot delegate task work")
        _, ledger = read_ledger(tx, current)
        task = next((task for task in ledger.tasks if task.id == task_id), None)
        if (task is None or type(expected_task_revision) is not int
                or task.revision != expected_task_revision or task.status is not TaskStatus.IN_PROGRESS):
            raise TaskLedgerError("task delegation requires an exact in-progress task")
        validate_instruction_sources(tx, current, task.definition.sources)
        return {"task_id": task.id, "task_revision": task.revision,
                "definition_digest": task.definition.digest}


def validate_scope(root, state, scope):
    if not isinstance(scope, dict) or set(scope) != {"task_id", "task_revision", "definition_digest"}:
        raise ValueError("invalid task delegation scope")
    current = instruction_scope(root, state, scope["task_id"], scope["task_revision"])
    if scope != current:
        raise ValueError("task delegation scope changed")
    return current
