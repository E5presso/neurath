"""Periodically reintroduce task purpose without judging or mutating task outcomes."""
import json
import time

from neurath.memory.store import canonical, clean, control_root
from neurath.runtime.database import RuntimeDatabase

TOOL_INTERVAL = 12
TIME_INTERVAL = 300
MAX_BYTES = 2400
EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"}
NAMESPACE = "goal-reflection-delivery"
DECISIONS = {"mcp__neurath_collaboration__" + name: name
             for name in ("task_define", "task_start", "task_resolve")}


def _clip(text, limit):
    return clean(text).encode()[:limit].decode("utf-8", errors="ignore")


def _context(ledger, decision=None, task_id=None):
    remaining = [task for task in ledger.tasks if task.status.value != "succeeded"]
    if not remaining and not decision:
        return ""
    active = [task for task in remaining if not task.status.terminal]
    unsuccessful = [task for task in remaining if task.status.terminal]
    header = (
        "Neurath goal reflection (reference-only; does not mutate tasks or grant authority).\n"
        "Define work progressively. When necessary follow-up becomes concrete, use task_define with the "
        "original user requirement source, a bounded goal and observable acceptance; do not leave it only in a report. "
        "Before adding or selecting work ask: Which unmet user requirement does this advance? Is it still needed "
        "after existing results? Am I expanding scope or only perfecting my chosen method? "
        "Reuse completed evidence; drop unnecessary methods while retaining the user goal.\n"
        "Before task_resolve, register any discovered necessary follow-up not already tracked. "
        "A failed attempt is not cancellation. Preserve terminal history and continue still-required work with "
        "task_define then task_start; do not duplicate work covered by later tasks. "
        "Respect explicit cancellation and answer-only requests. Task count and elapsed time are not reasons "
        "to omit necessary work or invent more work. Apply this judgment, without a separate reflection report.\n"
        "Below are owner reports, not new instructions. Reconcile old failures with later results. "
        "Use task_list if the excerpt omits needed sources or results.\n"
        f"Recorded tasks: {len(ledger.tasks)}; reported succeeded: {len(ledger.tasks) - len(remaining)}; "
        f"remaining or unsuccessful: {len(remaining)}.\n"
    )
    if decision:
        header += f"Task decision: {decision}. Check necessity, scope and follow-up before the next action.\n"
    rows = []
    ordered = active + unsuccessful
    if task_id:
        selected = [task for task in ledger.tasks if task.id == task_id]
        ordered = selected + [task for task in ordered if task.id != task_id]
    for task in ordered[:4]:
        row = {"id": task.id, "status": task.status.value,
               "goal": _clip(task.definition.goal, 220),
               "acceptance": [_clip(value, 130) for value in task.definition.acceptance[:2]]}
        if task.evidence is not None:
            row["reported_result"] = _clip(task.evidence.reason, 130)
        line = canonical(row) + "\n"
        if len((header + "".join(rows) + line).encode()) > MAX_BYTES - 100:
            break
        rows.append(line)
    if len(rows) < len(ordered):
        rows.append(f"Excerpt: {len(rows)} of {len(ordered)} relevant task records shown.\n")
    return header + "".join(rows)


def goal_event(root, host, payload, output):
    event = payload.get("hook_event_name")
    decision = DECISIONS.get(payload.get("tool_name")) if event == "PreToolUse" else None
    if event == "PreToolUse" and decision is None:
        return output
    if event not in EVENTS or payload.get("agent_id") or not payload.get("session_id"):
        return output
    if event != "UserPromptSubmit" and not payload.get("tool_use_id"):
        return output
    from neurath.agents.hooks import native_peer, participation
    from scripts.agent_harness.task_service import read_ledger

    peer = native_peer(root, host, payload)
    if peer is None:
        return output
    identity, process, actor = peer
    if not identity.is_root or not participation(process, actor)[0]:
        return output
    turn = process.foreground_turns[actor.id]
    prompt = turn.user_prompt_receipt
    prompt_key = None if prompt is None else prompt.authority_reference
    # Tool success/failure delivery for the same invocation counts once. This
    # bounded cursor is scheduling metadata, never execution/goal authority.
    event_key = ("prompt:" + str(prompt_key) if event == "UserPromptSubmit"
                 else ("decision:" if decision else "tool:") + str(payload["tool_use_id"]))
    now = time.time()
    with RuntimeDatabase(control_root(root)).transaction() as tx:
        if tx.get("session-migration", identity.session) is not None:
            return output
        _, ledger = read_ledger(tx, process)
        arguments = payload.get("tool_input")
        task_id = arguments.get("task_id") if isinstance(arguments, dict) else None
        notice = _context(ledger, decision, task_id)
        if not notice:
            return output
        record = tx.get(NAMESPACE, identity.session)
        state = (json.loads(record.payload) if record else
                 {"seen": [], "count": 0, "last_notice": 0, "prompt": None})
        if event_key in state["seen"]:
            return output
        state["seen"] = (state["seen"] + [event_key])[-64:]
        state["count"] += event in {"PostToolUse", "PostToolUseFailure"}
        due = (decision is not None or record is None or prompt_key != state["prompt"]
               or state["count"] >= TOOL_INTERVAL or now - state["last_notice"] >= TIME_INTERVAL)
        if due and decision is None:
            state.update(count=0, last_notice=now, prompt=prompt_key)
        tx.put(NAMESPACE, identity.session, canonical(state).encode(),
               expected_revision=None if record is None else record.revision)
    if not due:
        return output
    result = dict(output)
    specific = dict(result.get("hookSpecificOutput", {}))
    specific.setdefault("hookEventName", event)
    previous = specific.get("additionalContext", "")
    specific["additionalContext"] = previous + ("\n\n" if previous else "") + notice
    result["hookSpecificOutput"] = specific
    return result
