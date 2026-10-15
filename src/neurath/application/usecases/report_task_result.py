"""Implement report task result through explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.task_attempt import IAttemptRepository
from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.application.ports.usecases.report_task_result import (
    IReportTaskResultUseCase,
    ReportTaskResultCommand,
)
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.task_attempt import AttemptOutcome
from neurath.domain.aggregates.task_change import TaskAction, TaskChange


class ReportTaskResultUseCase(IReportTaskResultUseCase):
    """Preserve an actual result; a stale attempt never closes a corrected requirement."""

    def __init__(
        self, tasks: ITaskRepository, attempts: IAttemptRepository, changes: IChangeRepository
    ) -> None:
        """Bind the repositories participating in this single atomic request."""
        self.tasks = tasks
        self.attempts = attempts
        self.changes = changes

    @override
    def execute(self, request: ReportTaskResultCommand) -> Task:
        """Preserve an actual result; a stale attempt never closes a corrected requirement."""
        attempt = self.attempts.get(request.project_id, request.session_id, request.attempt_id)
        reported = attempt.report(
            request.executor,
            request.outcome,
            request.summary,
            request.evidence,
            request.remaining_work,
        )
        task = self.tasks.get(request.project_id, request.session_id, attempt.task_id)
        if request.outcome is AttemptOutcome.SUBMITTED:
            self.attempts.save(reported)
            return task
        changed = task.apply_result(
            attempt.id,
            attempt.definition_revision,
            request.outcome is AttemptOutcome.SUCCEEDED,
            request.remaining_work,
        )
        self.attempts.save(reported)
        if changed != task:
            self.tasks.save(changed, task.revision)
            self.changes.add(
                TaskChange(str(uuid4()), changed, TaskAction.RESOLVED, request.evidence)
            )
        return changed
