"""Append-only snapshots explain each persisted change to a task requirement."""

from dataclasses import dataclass
from enum import StrEnum

from neurath.domain.aggregates.task import Task


class TaskAction(StrEnum):
    """The concrete operation responsible for a task snapshot."""

    CREATED = "created"
    CORRECTED = "corrected"
    INVALIDATED = "invalidated"
    STARTED = "started"
    WAITED = "waited"
    RESUMED = "resumed"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class TaskChange:
    """Preserve the entire requirement snapshot and its operation evidence."""

    id: str
    task: Task
    action: TaskAction
    reason: str
