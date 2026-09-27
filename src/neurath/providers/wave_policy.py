"""Pure provider-wave rules: graph validity, scheduling and consumption.

These decisions accept materialized snapshots. They do not open a database,
launch a worker, inspect native authority or change a lease.
"""

import hashlib
from dataclasses import dataclass

from neurath.agents.contracts import TERMINAL, bounded
from neurath.serialization import canonical


@dataclass(frozen=True)
class TaskScope:
    session_id: str
    actor_id: str
    task_id: str
    task_revision: int
    definition_digest: str

    def __post_init__(self):
        for name in ("session_id", "actor_id", "task_id", "definition_digest"):
            bounded(getattr(self, name), name)
        if type(self.task_revision) is not int or self.task_revision < 1:
            raise ValueError("invalid task revision")


@dataclass(frozen=True)
class Entry:
    entry_id: str
    depends_on: tuple[str, ...]
    request: dict


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def normalize_entries(items: list[dict]) -> list[Entry]:
    if not isinstance(items, list) or not 1 <= len(items) <= 32:
        raise ValueError("wave requires one to 32 entries")
    result, names = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"entry_id", "depends_on", "request"}:
            raise ValueError("entry requires entry_id, depends_on and admitted request")
        name = bounded(item["entry_id"], "entry ID", 128)
        deps = item["depends_on"]
        if (
            name in names
            or not isinstance(deps, list)
            or any(not isinstance(d, str) for d in deps)
            or len(set(deps)) != len(deps)
            or not isinstance(item["request"], dict)
        ):
            raise ValueError("invalid wave entry")
        names.add(name)
        result.append(Entry(name, tuple(deps), item["request"]))
    visited = set()
    while len(visited) < len(result):
        ready = {
            e.entry_id for e in result if e.entry_id not in visited and set(e.depends_on) <= visited
        }
        if not ready:
            raise ValueError("wave dependencies contain a cycle or unknown entry")
        visited.update(ready)
    return result


def entry_state(entry: dict) -> str:
    consumed = entry["consumption"]
    if consumed and consumed["verdict"] == "rejected":
        return "rejected"
    if (
        consumed
        and consumed["verdict"] == "accepted"
        and entry["status"] == "completed"
        and consumed["run_id"] == entry["run_id"]
        and consumed["generation"] == entry["generation"]
        and consumed["result_digest"] == entry["result_digest"]
    ):
        return "succeeded"
    return entry["status"]


def request_scope(request):
    return {
        "assignment": request.get("assignment"),
        "provider": request.get("provider", "codex"),
        "worktree": request.get("worktree"),
    }


@dataclass(frozen=True)
class Schedule:
    """Ordered entry IDs whose state changes in one scheduling transaction."""

    blocked: tuple[str, ...]
    ready: tuple[str, ...]


def descendants(entries: list[dict], ancestors: set[str]) -> set[str]:
    reached = set(ancestors)
    while True:
        expanded = reached | {e["entry_id"] for e in entries if set(e["depends_on"]) & reached}
        if expanded == reached:
            return reached
        reached = expanded


def schedule(entries: list[dict], max_parallel: int) -> Schedule:
    """Reserve capacity only for dependencies with an exact accepted result."""
    by_name = {entry["entry_id"]: entry for entry in entries}
    blocked = {
        name
        for name, entry in by_name.items()
        if entry["status"] == "blocked" or entry_state(entry) == "rejected"
    }
    while True:
        expanded = blocked | {
            name
            for name, entry in by_name.items()
            if entry["run_id"] is None and set(entry["depends_on"]) & blocked
        }
        if expanded == blocked:
            break
        blocked = expanded
    active = sum(e["run_id"] is not None and e["status"] not in TERMINAL for e in entries)
    slots = max(0, max_parallel - active)
    ready = tuple(
        entry["entry_id"]
        for entry in entries
        if entry["run_id"] is None
        and entry["entry_id"] not in blocked
        and all(entry_state(by_name[d]) == "succeeded" for d in entry["depends_on"])
    )
    return Schedule(
        tuple(e["entry_id"] for e in entries if e["entry_id"] in blocked and e["run_id"] is None),
        ready[:slots],
    )
