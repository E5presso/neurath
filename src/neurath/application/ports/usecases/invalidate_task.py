"""Typed request and nominal contract for the invalidate task operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class InvalidateTaskCommand:
    """Apply a sourced cancellation without claiming a running attempt physically stopped."""

    project_id: str
    session_id: str
    task_id: str
    source_id: str
    reason: str
    expected_revision: int


class IInvalidateTaskUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: InvalidateTaskCommand) -> Task:
        """Apply a sourced cancellation without claiming a running attempt physically stopped."""
        raise NotImplementedError
