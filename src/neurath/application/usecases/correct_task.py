"""Implement correct task through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.correct_task import CorrectTaskCommand, ICorrectTaskUseCase
from neurath.application.task_corrections import require_correction
from neurath.application.task_dependencies import validate_dependencies
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.task_change import TaskAction, TaskChange


class CorrectTaskUseCase(ICorrectTaskUseCase):
    """Apply only explicitly corrected fields; retain unrelated tasks and original history."""

    def __init__(
        self, sources: ISourceRepository, tasks: ITaskRepository, changes: IChangeRepository
    ) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.sources = sources
        self.tasks = tasks
        self.changes = changes

    @override
    def execute(self, request: CorrectTaskCommand) -> Task:
        """Apply only explicitly corrected fields; retain unrelated tasks and original history."""
        task = self.tasks.get(request.project_id, request.session_id, request.task_id)
        require_correction(self.sources, task, request.source_id)
        changed = task.correct(
            request.source_id,
            request.title if request.title is not None else task.title,
            request.expected_outcome
            if request.expected_outcome is not None
            else task.expected_outcome,
            request.dependencies if request.dependencies is not None else task.dependencies,
            request.expected_revision,
        )
        validate_dependencies(
            self.tasks, request.project_id, request.session_id, changed.id, changed.dependencies
        )
        self.tasks.save(changed, request.expected_revision)
        self.changes.add(TaskChange(str(uuid4()), changed, TaskAction.CORRECTED, request.source_id))
        return changed
