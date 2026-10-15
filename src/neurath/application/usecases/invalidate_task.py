"""Implement invalidate task through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.invalidate_task import (
    IInvalidateTaskUseCase,
    InvalidateTaskCommand,
)
from neurath.application.task_corrections import require_correction
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.task_change import TaskAction, TaskChange


class InvalidateTaskUseCase(IInvalidateTaskUseCase):
    """Apply a sourced cancellation without claiming a running attempt physically stopped."""

    def __init__(
        self, sources: ISourceRepository, tasks: ITaskRepository, changes: IChangeRepository
    ) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.sources = sources
        self.tasks = tasks
        self.changes = changes

    @override
    def execute(self, request: InvalidateTaskCommand) -> Task:
        """Apply a sourced cancellation without claiming a running attempt physically stopped."""
        task = self.tasks.get(request.project_id, request.session_id, request.task_id)
        require_correction(self.sources, task, request.source_id)
        changed = task.invalidate(request.source_id, request.reason, request.expected_revision)
        self.tasks.save(changed, request.expected_revision)
        self.changes.add(TaskChange(str(uuid4()), changed, TaskAction.INVALIDATED, request.reason))
        return changed
