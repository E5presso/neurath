"""Nominal persistence contract for Task records."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.task import Task


class ITaskRepository(ABC):
    """Persist scoped Task values without exposing ORM objects or transactions."""

    @abstractmethod
    def add(self, value: Task) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str, session_id: str, record_id: str) -> Task:
        """Return a record only inside the explicitly requested project and session."""
        raise NotImplementedError

    @abstractmethod
    def save(self, value: Task, expected_revision: int) -> None:
        """Persist an existing record after checking its prior state."""
        raise NotImplementedError

    @abstractmethod
    def list(self, project_id: str, session_id: str) -> tuple[Task, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        raise NotImplementedError
