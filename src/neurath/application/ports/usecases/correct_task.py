"""Typed request and nominal contract for the correct task operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class CorrectTaskCommand:
    """Apply only explicitly corrected fields; retain unrelated tasks and original history."""

    project_id: str
    session_id: str
    task_id: str
    source_id: str
    expected_revision: int
    title: str | None = None
    expected_outcome: str | None = None
    dependencies: tuple[str, ...] | None = None


class ICorrectTaskUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: CorrectTaskCommand) -> Task:
        """Apply only explicitly corrected fields; retain unrelated tasks and original history."""
        raise NotImplementedError
