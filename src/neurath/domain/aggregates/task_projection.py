"""Read-only TODO projection and readiness calculated from the current task collection."""

from dataclasses import dataclass

from neurath.domain.aggregates.task import Task, TaskStatus


@dataclass(frozen=True)
class TaskProjection:
    """Expose the full ledger without inventing a second host-specific status store."""

    tasks: tuple[Task, ...]

    @property
    def ready(self) -> tuple[Task, ...]:
        """Select independent executable work even while other tasks wait or fail."""
        succeeded = {task.id for task in self.tasks if task.status is TaskStatus.SUCCEEDED}
        return tuple(
            task
            for task in self.tasks
            if task.status in (TaskStatus.PENDING, TaskStatus.FAILED)
            and set(task.dependencies) <= succeeded
        )

    @property
    def all_terminal(self) -> bool:
        """Describe terminal states without presenting failure or cancellation as success."""
        return bool(self.tasks) and all(
            task.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.INVALIDATED)
            for task in self.tasks
        )

    @property
    def all_succeeded(self) -> bool:
        """Require actual success on every current requirement, including follow-ups."""
        return bool(self.tasks) and all(task.status is TaskStatus.SUCCEEDED for task in self.tasks)
