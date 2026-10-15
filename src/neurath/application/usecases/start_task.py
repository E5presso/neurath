"""Implement start task through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_attempt import IAttemptRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.start_task import IStartTaskUseCase, StartTaskCommand
from neurath.application.task_dependencies import require_ready
from neurath.domain.aggregates.task_attempt import TaskAttempt
from neurath.domain.aggregates.task_change import TaskAction, TaskChange
from neurath.domain.errors import InvalidTaskOperation


class StartTaskUseCase(IStartTaskUseCase):
    """Start one current definition, fencing duplicate starts and unfinished dependencies."""

    def __init__(
        self, tasks: ITaskRepository, attempts: IAttemptRepository, changes: IChangeRepository
    ) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.tasks = tasks
        self.attempts = attempts
        self.changes = changes

    @override
    def execute(self, request: StartTaskCommand) -> TaskAttempt:
        """Start one current definition, fencing duplicate starts and unfinished dependencies."""
        if not request.executor.strip():
            raise InvalidTaskOperation("An attempt requires an attributed executor")
        task = self.tasks.get(request.project_id, request.session_id, request.task_id)
        require_ready(self.tasks, request.project_id, request.session_id, task.dependencies)
        attempt = TaskAttempt(
            str(uuid4()),
            task.project_id,
            task.session_id,
            task.id,
            task.definition_revision,
            request.executor,
        )
        changed = task.start(attempt.id, request.expected_revision)
        self.tasks.save(changed, request.expected_revision)
        self.attempts.add(attempt)
        self.changes.add(TaskChange(str(uuid4()), changed, TaskAction.STARTED, attempt.id))
        return attempt
