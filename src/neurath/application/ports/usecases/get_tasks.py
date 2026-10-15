"""Typed request and nominal contract for the get tasks operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task_projection import TaskProjection


@dataclass(frozen=True)
class GetTasksQuery:
    """Project the complete current task collection and its independently ready work."""

    project_id: str
    session_id: str


class IGetTasksUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: GetTasksQuery) -> TaskProjection:
        """Project the complete current task collection and its independently ready work."""
        raise NotImplementedError
