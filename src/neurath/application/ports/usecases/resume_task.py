"""Typed request and nominal contract for the resume task operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class ResumeTaskCommand:
    """Resume an externally waiting task only with observed release evidence."""

    project_id: str
    session_id: str
    task_id: str
    evidence: str
    expected_revision: int


class IResumeTaskUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: ResumeTaskCommand) -> Task:
        """Resume an externally waiting task only with observed release evidence."""
        raise NotImplementedError
