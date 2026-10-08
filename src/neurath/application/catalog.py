"""Public commands and closed input schemas. Identity is supplied by host ingress."""

from typing import Any

S = {"type": "string", "minLength": 1}
INTEGER = {"type": "integer", "minimum": 0}
STRINGS = {"type": "array", "items": S, "minItems": 1, "uniqueItems": True}
PAIR = {
    "type": "object",
    "properties": {"id": S, "description": S},
    "required": ["id", "description"],
    "additionalProperties": False,
}
PHASE = {
    "type": "object",
    "properties": {"id": S, "name": S},
    "required": ["id", "name"],
    "additionalProperties": False,
}
CATALOG: dict[str, dict[str, Any]] = {}


def command(
    name: str,
    description: str,
    fields: dict[str, Any],
    required: list[str],
    *,
    mutation: bool = True,
) -> None:
    properties = dict(fields)
    if mutation:
        properties["request_id"] = S
        required = [*required, "request_id"]
    CATALOG[name] = {
        "name": name,
        "description": description,
        "mutation": mutation,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


command("session.get", "Read the current native session.", {}, [], mutation=False)
command(
    "task.create",
    "Create an owned task from a native user source and explicit acceptance criteria.",
    {
        "source_id": S,
        "goal": S,
        "criteria": {"type": "array", "items": PAIR, "minItems": 1},
        "phases": {"type": "array", "items": PHASE},
    },
    ["source_id", "goal", "criteria"],
)
command(
    "task.get",
    "Read a task including its current revision.",
    {"task_id": S},
    ["task_id"],
    mutation=False,
)
command(
    "task.list",
    "List tasks, optionally filtered by status and owner.",
    {"status": {"enum": ["pending", "active", "waiting", "completed", "withdrawn"]}, "owner_id": S},
    [],
    mutation=False,
)
TASK = {"task_id": S, "expected_revision": INTEGER}
command(
    "task.adopt",
    "Adopt an unfinished task from an ended native session using a new native user instruction.",
    {**TASK, "source_id": S},
    [*TASK, "source_id"],
)
for action in ["activate", "resume", "complete"]:
    command(
        f"task.{action}",
        f"Explicitly {action} an owned task; domain preconditions are enforced.",
        TASK,
        list(TASK),
    )
command(
    "task.wait",
    "Preserve an unfinished task with its waiting reason.",
    {**TASK, "reason": S},
    [*TASK, "reason"],
)
command(
    "task.withdraw",
    "Withdraw an owned task only with a native approval linked to this task.",
    {**TASK, "approval_id": S},
    [*TASK, "approval_id"],
)
command(
    "task.revise",
    "Change goal and criteria from a new user source, invalidate old verification, and return to pending.",
    {
        **TASK,
        "source_id": S,
        "goal": S,
        "criteria": {"type": "array", "items": PAIR, "minItems": 1},
        "phases": {"type": "array", "items": PHASE},
    },
    [*TASK, "source_id", "goal", "criteria"],
)
command(
    "phase.start",
    "Start the next ordered phase of an active task.",
    {**TASK, "phase_id": S},
    [*TASK, "phase_id"],
)
command(
    "phase.complete",
    "Complete an active phase with successful evidence bound to its task and scope.",
    {**TASK, "phase_id": S, "evidence_ids": STRINGS},
    [*TASK, "phase_id", "evidence_ids"],
)
command(
    "criterion.satisfy",
    "Record evidence for one acceptance criterion without completing the task.",
    {**TASK, "criterion_id": S, "evidence_ids": STRINGS},
    [*TASK, "criterion_id", "evidence_ids"],
)
command(
    "evidence.record",
    "Record an attributed agent report. Native tool results and human approvals require trusted ingress.",
    {"task_id": S, "content": S, "criterion_id": S, "phase_id": S},
    ["task_id", "content"],
)
command(
    "evidence.list",
    "Read evidence without granting execution or completion authority.",
    {"task_id": S},
    ["task_id"],
    mutation=False,
)
command(
    "delegation.prepare",
    "Prepare a delegation while retaining parent task ownership.",
    {**TASK, "recipient_id": S, "instruction": S},
    [*TASK, "recipient_id", "instruction"],
)
D = {"delegation_id": S, "expected_revision": INTEGER}
for action in ["start", "accept"]:
    command(
        f"delegation.{action}",
        f"Explicitly {action} a delegation without completing its parent.",
        D,
        list(D),
    )
command(
    "delegation.report",
    "Submit an attributed recipient result for owner acceptance.",
    {**D, "report": S, "evidence_ids": {"type": "array", "items": S, "uniqueItems": True}},
    [*D, "report"],
)
for action in ["reject", "cancel"]:
    command(
        f"delegation.{action}",
        f"Explicitly {action} a delegation, retaining the parent task.",
        {**D, "reason": S},
        [*D, "reason"],
    )
command(
    "delegation.list", "Read delegations for a task.", {"task_id": S}, ["task_id"], mutation=False
)
command(
    "message.send",
    "Record a message for another native session; this does not accept any result.",
    {"recipient_id": S, "content": S, "task_id": S},
    ["recipient_id", "content"],
)
command("message.list", "Read messages addressed to the current session.", {}, [], mutation=False)
command(
    "message.ack",
    "Acknowledge message delivery, independently of delegation acceptance.",
    {"message_id": S, "expected_revision": INTEGER},
    ["message_id", "expected_revision"],
)
command(
    "checkpoint.save",
    "Save an owned task checkpoint without changing lifecycle state.",
    {**TASK, "note": S, "state": {"type": "object"}},
    [*TASK, "note"],
)
command(
    "checkpoint.list",
    "Read saved checkpoints for a task.",
    {"task_id": S},
    ["task_id"],
    mutation=False,
)
command(
    "lease.acquire",
    "Acquire exclusive ledger writer ownership for a resource; this grants no host permissions.",
    {"resource": S},
    ["resource"],
)
command(
    "lease.release",
    "Release only the current writer generation.",
    {"resource": S, "generation": {"type": "integer", "minimum": 1}, "expected_revision": INTEGER},
    ["resource", "generation", "expected_revision"],
)
command(
    "lease.check",
    "Verify the current writer generation before a host-authorized write.",
    {"resource": S, "generation": {"type": "integer", "minimum": 1}},
    ["resource", "generation"],
    mutation=False,
)

COMMANDS = CATALOG


def validate(schema: dict[str, Any], value: Any, path: str = "arguments") -> None:
    from neurath.domain.errors import ValidationError

    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path}: value is not in the allowed enum")
    kind = schema.get("type")
    valid = {
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "array": lambda: isinstance(value, list),
        "object": lambda: isinstance(value, dict),
    }
    if kind and not valid[kind]():
        raise ValidationError(f"{path}: expected {kind}")
    if kind == "string" and len(value.strip()) < schema.get("minLength", 0):
        raise ValidationError(f"{path}: nonempty text required")
    if kind == "integer" and value < schema.get("minimum", value):
        raise ValidationError(f"{path}: below minimum")
    if kind == "array":
        if len(value) < schema.get("minItems", 0):
            raise ValidationError(f"{path}: too few items")
        if schema.get("uniqueItems") and any(item in value[:i] for i, item in enumerate(value)):
            raise ValidationError(f"{path}: duplicate items")
        for i, item in enumerate(value):
            validate(schema["items"], item, f"{path}[{i}]")
    if kind == "object":
        fields = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            raise ValidationError(f"{path}: missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(fields):
            raise ValidationError(f"{path}: unknown fields: {sorted(set(value) - set(fields))}")
        for key, item in value.items():
            if key in fields:
                validate(fields[key], item, f"{path}.{key}")
