"""Typed request and nominal contract for the start task operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task_attempt import TaskAttempt


@dataclass(frozen=True)
class StartTaskCommand:
    """Start one current definition, fencing duplicate starts and unfinished dependencies."""

    project_id: str
    session_id: str
    task_id: str
    executor: str
    expected_revision: int


class IStartTaskUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: StartTaskCommand) -> TaskAttempt:
        """Start one current definition, fencing duplicate starts and unfinished dependencies."""
        raise NotImplementedError
