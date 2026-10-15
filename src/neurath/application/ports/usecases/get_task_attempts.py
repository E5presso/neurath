"""Typed request and nominal contract for the get task attempts operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task_attempt import TaskAttempt


@dataclass(frozen=True)
class GetTaskAttemptsQuery:
    """Read all execution attempts including failed, unfinished and superseded attempts."""

    project_id: str
    session_id: str
    task_id: str


class IGetTaskAttemptsUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: GetTaskAttemptsQuery) -> tuple[TaskAttempt, ...]:
        """Read all execution attempts including failed, unfinished and superseded attempts."""
        raise NotImplementedError
