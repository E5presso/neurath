"""Implement get tasks through explicit repository dependencies."""

from typing import override

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.usecases.get_tasks import GetTasksQuery, IGetTasksUseCase
from neurath.domain.aggregates.task_projection import TaskProjection


class GetTasksUseCase(IGetTasksUseCase):
    """Project the complete current task collection and its independently ready work."""

    def __init__(self, tasks: ITaskRepository) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.tasks = tasks

    @override
    def execute(self, request: GetTasksQuery) -> TaskProjection:
        """Project the complete current task collection and its independently ready work."""
        return TaskProjection(self.tasks.list(request.project_id, request.session_id))
