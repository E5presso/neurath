"""Typed request and nominal contract for the create task operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class CreateTaskCommand:
    """Define an attributed requirement and retain dependencies or a failed predecessor."""

    project_id: str
    session_id: str
    source_id: str
    title: str
    expected_outcome: str
    dependencies: tuple[str, ...] = ()
    follows_task_id: str | None = None


class ICreateTaskUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: CreateTaskCommand) -> Task:
        """Define an attributed requirement and retain dependencies or a failed predecessor."""
        raise NotImplementedError
