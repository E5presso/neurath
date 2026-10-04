"""Keep checked source identity across an observed native worktree removal."""

from pathlib import Path

from neurath.core.codec import encode
from neurath.core.domain import require
from neurath.core.native_results import check_result
from neurath.core.workspace import source_subject


def prepare(core, context, tool_id, target, task_id):
    require(isinstance(tool_id, str) and tool_id, "native-tool-id-required")
    identifier = encode([context.actor_id, context.session_id, tool_id])
    value = {"checkout": target, "task_id": task_id, "subject": source_subject(target)}
    with core.store.transaction() as tx:
        previous = tx.record("cleanup-invocation", identifier)
        require(previous is None or previous["value"] == value, "invocation-mismatch")
        if previous is None:
            tx.put_record("cleanup-invocation", identifier, value)


def finish(core, context, payload, event):
    identifier = encode([context.actor_id, context.session_id, payload.get("tool_use_id")])
    with core.store.transaction() as tx:
        record = tx.record("cleanup-invocation", identifier)
        if record is None:
            return
        value = record["value"]
        result = check_result(payload) if event == "PostToolUse" else None
        if result is None or result["exit_code"] != 0 or Path(value["checkout"]).exists():
            return
        previous = tx.record("retired-checkout", value["checkout"])
        tx.put_record(
            "retired-checkout",
            value["checkout"],
            value,
            0 if previous is None else previous["revision"],
        )
