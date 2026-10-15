"""Implement create task through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.create_task import CreateTaskCommand, ICreateTaskUseCase
from neurath.application.task_dependencies import validate_dependencies
from neurath.domain.aggregates.task import Task, TaskStatus
from neurath.domain.aggregates.task_change import TaskAction, TaskChange
from neurath.domain.errors import InvalidTaskOperation


class CreateTaskUseCase(ICreateTaskUseCase):
    """Define an attributed requirement and retain dependencies or a failed predecessor."""

    def __init__(
        self, sources: ISourceRepository, tasks: ITaskRepository, changes: IChangeRepository
    ) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.sources = sources
        self.tasks = tasks
        self.changes = changes

    @override
    def execute(self, request: CreateTaskCommand) -> Task:
        """Define an attributed requirement and retain dependencies or a failed predecessor."""
        source = self.sources.get(request.project_id, request.source_id)
        source.require_instruction()
        changed = Task(
            str(uuid4()),
            request.project_id,
            request.session_id,
            source.id,
            request.title,
            request.expected_outcome,
            request.dependencies,
            request.follows_task_id,
        )
        validate_dependencies(
            self.tasks, request.project_id, request.session_id, changed.id, changed.dependencies
        )
        if request.follows_task_id is not None:
            prior = self.tasks.get(request.project_id, request.session_id, request.follows_task_id)
            if prior.status is not TaskStatus.FAILED or prior.source_id != source.id:
                raise InvalidTaskOperation("Follow-up must retain the failed requirement's source")
        self.tasks.add(changed)
        self.changes.add(TaskChange(str(uuid4()), changed, TaskAction.CREATED, source.reference))
        return changed
