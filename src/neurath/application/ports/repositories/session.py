"""Nominal persistence contract for project-scoped host sessions."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.session import HostSession


class ISessionRepository(ABC):
    """Read and persist sessions inside the caller's existing transaction."""

    @abstractmethod
    def find(self, project_id: str, provider: str, host_session_id: str) -> HostSession | None:
        """Return the matching scoped native session when it already exists."""
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str, session_id: str) -> HostSession:
        """Load a session only if it belongs to the explicitly addressed project."""
        raise NotImplementedError

    @abstractmethod
    def add(self, session: HostSession) -> None:
        """Persist a new host observation without committing the transaction."""
        raise NotImplementedError

    @abstractmethod
    def save(self, session: HostSession, expected_revision: int) -> None:
        """Persist the next session revision or raise RevisionConflict."""
        raise NotImplementedError
