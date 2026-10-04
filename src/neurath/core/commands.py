"""Closed public command schemas and native request context."""

from dataclasses import dataclass

from neurath.core.checks import COMMANDS as CHECK_COMMANDS
from neurath.core.codec import encode
from neurath.core.communication import COMMANDS as COMMUNICATION_COMMANDS
from neurath.core.domain import require
from neurath.core.memory_commands import COMMANDS as MEMORY_COMMANDS
from neurath.core.provider_commands import COMMANDS as PROVIDER_COMMANDS


@dataclass(frozen=True, slots=True)
class Context:
    actor_id: str
    session_id: str
    invocation_id: str


# Identity, source provenance and native observations have no public write command.
COMMANDS = {
    **CHECK_COMMANDS,
    **PROVIDER_COMMANDS,
    **COMMUNICATION_COMMANDS,
    **MEMORY_COMMANDS,
    "session_status": (set(), set(), True),
    "collaboration_discover": (set(), set(), True),
    "task_list": (set(), {"all_project"}, True),
    "task_read": ({"task_id"}, set(), True),
    "evidence_list": ({"task_id"}, set(), True),
    "publication_read": (
        {"task_id", "checkout", "publication_kind", "reference"},
        {"head", "asset_sha256"},
        True,
    ),
    "approval_record": (
        {"task_id", "source_id", "start", "end", "digest", "action", "target", "reason"},
        set(),
        False,
    ),
    "source_read": ({"source_id"}, {"start", "limit"}, True),
    "source_list": (set(), {"kind", "limit"}, True),
    "source_quote": ({"source_id", "start", "end", "digest"}, set(), True),
    "source_restore": ({"task_id", "source_id", "body"}, set(), False),
    "phase_read": ({"task_id"}, set(), True),
    "task_define": ({"goal", "source_ids", "acceptance"}, {"dependencies"}, False),
    "task_start": ({"task_id", "expected_revision"}, set(), False),
    "skill_start": ({"task_id", "expected_revision", "skill"}, set(), False),
    "task_wait": ({"task_id", "expected_revision", "reason", "source_id"}, set(), False),
    "task_resume": ({"task_id", "expected_revision"}, set(), False),
    "task_withdraw": (
        {"task_id", "expected_revision", "source_id", "start", "end", "digest", "reason"},
        set(),
        False,
    ),
    "task_adopt": (
        {"task_id", "expected_revision", "source_id", "start", "end", "digest", "reason"},
        set(),
        False,
    ),
    "task_complete": ({"task_id", "expected_revision", "outcomes"}, set(), False),
    "phase_complete": (
        {"task_id", "expected_revision", "phase_id", "outcomes", "inputs"},
        set(),
        False,
    ),
    "phase_restart": ({"task_id", "expected_revision", "source_id"}, {"changed_inputs"}, False),
    "report_record": ({"task_id", "body", "passed"}, {"subject"}, False),
    "assignment_prepare": (
        {"task_id", "expected_revision", "execution", "reason", "scope", "subject", "role"},
        {"recipient", "provider", "checkout"},
        False,
    ),
    "assignment_start": ({"task_id", "assignment_id"}, set(), False),
    "assignment_read": ({"task_id", "assignment_id"}, set(), True),
    "assignment_report": ({"task_id", "assignment_id", "verdict", "body", "subject"}, set(), False),
    "assignment_accept": ({"task_id", "assignment_id", "source_id", "subject"}, set(), False),
    "assignment_reject": ({"task_id", "assignment_id", "source_id"}, set(), False),
    "assignment_cancel": ({"task_id", "assignment_id", "reason"}, set(), False),
    "worktree_read": ({"checkout"}, set(), True),
    "worktree_claim": ({"task_id", "checkout"}, {"create"}, False),
    "worktree_release": ({"checkout", "generation"}, set(), False),
    "task_focus": ({"task_id"}, set(), False),
}


def validated(name, values):
    require(name in COMMANDS, "unknown-command", command=name)
    required, optional, readonly = COMMANDS[name]
    require(isinstance(values, dict), "invalid-input")
    require(
        set(values) <= required | optional | (set() if readonly else {"key"}), "unexpected-fields"
    )
    require(required <= set(values), "missing-fields", fields=sorted(required - set(values)))
    if not readonly:
        require(isinstance(values.get("key"), str) and bool(values["key"]), "command-key")
    for key in (
        "task_id",
        "source_id",
        "goal",
        "skill",
        "phase_id",
        "digest",
        "reason",
        "body",
        "assignment_id",
        "checkout",
        "scope",
        "execution",
        "role",
    ):
        if key in values:
            require(
                isinstance(values[key], str) and bool(values[key].strip()),
                "invalid-input",
                field=key,
            )
    if "expected_revision" in values:
        require(
            type(values["expected_revision"]) is int and values["expected_revision"] > 0,
            "invalid-revision",
        )
    require(len(encode(values).encode()) <= 65536, "input-too-large")
    return readonly
