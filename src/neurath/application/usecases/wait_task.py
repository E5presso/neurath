"""Implement wait task through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.wait_task import IWaitTaskUseCase, WaitTaskCommand
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.task_change import TaskAction, TaskChange


class WaitTaskUseCase(IWaitTaskUseCase):
    """Record a concrete external dependency while leaving independent work ready."""

    def __init__(self, tasks: ITaskRepository, changes: IChangeRepository) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.tasks = tasks
        self.changes = changes

    @override
    def execute(self, request: WaitTaskCommand) -> Task:
        """Record a concrete external dependency while leaving independent work ready."""
        task = self.tasks.get(request.project_id, request.session_id, request.task_id)
        changed = task.wait(request.dependency, request.expected_revision)
        self.tasks.save(changed, request.expected_revision)
        self.changes.add(
            TaskChange(str(uuid4()), changed, TaskAction.WAITED, request.dependency.evidence)
        )
        return changed
