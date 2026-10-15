"""Validate task dependency graphs without coupling orchestration to storage."""

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import TaskStatus
from neurath.domain.errors import InvalidTaskOperation


def validate_dependencies(
    tasks: ITaskRepository,
    project_id: str,
    session_id: str,
    task_id: str,
    dependency_ids: tuple[str, ...],
) -> None:
    """Reject foreign-scope dependencies and cycles including indirect correction cycles."""
    visited: set[str] = set()
    pending = list(dependency_ids)
    while pending:
        current = pending.pop()
        if current == task_id:
            raise InvalidTaskOperation("Task dependencies cannot form a cycle")
        if current in visited:
            continue
        visited.add(current)
        dependency = tasks.get(project_id, session_id, current)
        pending.extend(dependency.dependencies)


def require_ready(
    tasks: ITaskRepository, project_id: str, session_id: str, dependency_ids: tuple[str, ...]
) -> None:
    """Require actual success for all predecessors before beginning dependent work."""
    for dependency_id in dependency_ids:
        if tasks.get(project_id, session_id, dependency_id).status is not TaskStatus.SUCCEEDED:
            raise InvalidTaskOperation("Task has an unfinished dependency")
