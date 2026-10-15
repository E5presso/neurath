"""Nominal persistence contract for TaskChange records."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.task_change import TaskChange


class IChangeRepository(ABC):
    """Persist scoped TaskChange values without exposing ORM objects or transactions."""

    @abstractmethod
    def add(self, value: TaskChange) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        raise NotImplementedError

    @abstractmethod
    def list(self, project_id: str, session_id: str, task_id: str) -> tuple[TaskChange, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        raise NotImplementedError
