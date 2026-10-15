"""Nominal persistence contract for TaskAttempt records."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.task_attempt import TaskAttempt


class IAttemptRepository(ABC):
    """Persist scoped TaskAttempt values without exposing ORM objects or transactions."""

    @abstractmethod
    def add(self, value: TaskAttempt) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str, session_id: str, record_id: str) -> TaskAttempt:
        """Return a record only inside the explicitly requested project and session."""
        raise NotImplementedError

    @abstractmethod
    def save(self, value: TaskAttempt) -> None:
        """Persist an existing record after checking its prior state."""
        raise NotImplementedError

    @abstractmethod
    def list(self, project_id: str, session_id: str, task_id: str) -> tuple[TaskAttempt, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        raise NotImplementedError
