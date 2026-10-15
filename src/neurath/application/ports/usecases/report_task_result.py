"""Typed request and nominal contract for the report task result operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.task_attempt import AttemptOutcome


@dataclass(frozen=True)
class ReportTaskResultCommand:
    """Preserve an actual result; a stale attempt never closes a corrected requirement."""

    project_id: str
    session_id: str
    attempt_id: str
    executor: str
    outcome: AttemptOutcome
    summary: str
    evidence: str
    remaining_work: str = ""


class IReportTaskResultUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: ReportTaskResultCommand) -> Task:
        """Preserve an actual result; a stale attempt never closes a corrected requirement."""
        raise NotImplementedError
