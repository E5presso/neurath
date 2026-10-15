"""Resolve actual correction provenance without inventing a human reapproval ceremony."""

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.aggregates.task import Task
from neurath.domain.errors import InvalidTaskOperation


def require_correction(sources: ISourceRepository, task: Task, source_id: str) -> None:
    """Require a correction of this task's current attributed source revision."""
    source = sources.get(task.project_id, source_id)
    current_source = task.correction_source_id or task.source_id
    if source.kind is not SourceKind.CORRECTION or source.corrects_id != current_source:
        raise InvalidTaskOperation("Correction must reference the current task source")
