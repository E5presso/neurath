"""Typed request and nominal contract for the get task history operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task_change import TaskChange


@dataclass(frozen=True)
class GetTaskHistoryQuery:
    """Read every requirement snapshot and operation reason in revision order."""

    project_id: str
    session_id: str
    task_id: str


class IGetTaskHistoryUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: GetTaskHistoryQuery) -> tuple[TaskChange, ...]:
        """Read every requirement snapshot and operation reason in revision order."""
        raise NotImplementedError
