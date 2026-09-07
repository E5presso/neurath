"""Public names are independent of persisted workflow and bundled source IDs."""

import re

SKILL_NAMES = {
    "audit-spec": "review-spec",
    "automate-qa": "qa",
    "create-ticket": "create-issue",
    "dependency-audit": "audit-deps",
    "evaluate-harness": "test-harness",
    "explore-ui": "design-ui",
    "investigate": "debug",
    "monitor-pr": "watch-pr",
    "plan-issues": "plan",
    "pr-review": "review-pr",
    "process-ticket": "implement-issue",
    "promote-memory": "memory-to-rules",
    "sync-dev-docs": "dev-docs",
    "sync-user-docs": "user-docs",
    "triage-comments": "pr-feedback",
    "update-dependencies": "update-deps",
    "update-project-status": "update-status",
}


def validate_skill_prefix(value):
    """Accept an explicit empty prefix or a lowercase slug ending in a hyphen."""
    if not isinstance(value, str) or (
        value and re.fullmatch(r"[a-z][a-z0-9-]*-", value) is None
    ):
        raise ValueError("skill prefix must be empty or a lowercase slug ending in '-'")
    return value


def public_name(skill_id, skill_prefix=""):
    return validate_skill_prefix(skill_prefix) + SKILL_NAMES.get(skill_id, skill_id)


def source_id(name):
    return next((key for key, value in SKILL_NAMES.items() if value == name), name)
