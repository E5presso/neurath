"""Typed request and nominal contract for the wait task operation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from neurath.domain.aggregates.task import ExternalWait, Task


@dataclass(frozen=True)
class WaitTaskCommand:
    """Record a concrete external dependency while leaving independent work ready."""

    project_id: str
    session_id: str
    task_id: str
    dependency: ExternalWait
    expected_revision: int


class IWaitTaskUseCase(ABC):
    """Define one operation without an implicit persistence or host lifecycle."""

    @abstractmethod
    def execute(self, request: WaitTaskCommand) -> Task:
        """Record a concrete external dependency while leaving independent work ready."""
        raise NotImplementedError
