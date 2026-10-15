"""Implement get task attempts through explicit repository dependencies."""

from typing import override

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_attempt import IAttemptRepository
from neurath.application.ports.usecases.get_task_attempts import (
    GetTaskAttemptsQuery,
    IGetTaskAttemptsUseCase,
)
from neurath.domain.aggregates.task_attempt import TaskAttempt


class GetTaskAttemptsUseCase(IGetTaskAttemptsUseCase):
    """Read all execution attempts including failed, unfinished and superseded attempts."""

    def __init__(self, tasks: ITaskRepository, attempts: IAttemptRepository) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.tasks = tasks
        self.attempts = attempts

    @override
    def execute(self, request: GetTaskAttemptsQuery) -> tuple[TaskAttempt, ...]:
        """Read all execution attempts including failed, unfinished and superseded attempts."""
        self.tasks.get(request.project_id, request.session_id, request.task_id)
        return self.attempts.list(request.project_id, request.session_id, request.task_id)
