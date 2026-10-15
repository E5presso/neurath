"""Implement get task history through explicit repository dependencies."""

from typing import override

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.get_task_history import (
    GetTaskHistoryQuery,
    IGetTaskHistoryUseCase,
)
from neurath.domain.aggregates.task_change import TaskChange


class GetTaskHistoryUseCase(IGetTaskHistoryUseCase):
    """Read every requirement snapshot and operation reason in revision order."""

    def __init__(self, tasks: ITaskRepository, changes: IChangeRepository) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.tasks = tasks
        self.changes = changes

    @override
    def execute(self, request: GetTaskHistoryQuery) -> tuple[TaskChange, ...]:
        """Read every requirement snapshot and operation reason in revision order."""
        self.tasks.get(request.project_id, request.session_id, request.task_id)
        return self.changes.list(request.project_id, request.session_id, request.task_id)
