"""Nominal persistence contract for project-scoped host sessions."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.session import HostSession


class ISessionRepository(ABC):
    """Read and persist sessions inside the caller's existing transaction."""

    @abstractmethod
    def find(self, project_id: str, provider: str, host_session_id: str) -> HostSession | None:
        """Return the matching scoped native session when it already exists.

        Args:
            project_id: Stable identifier of the project to address.
            provider: Host provider namespace for the native session identifier.
            host_session_id: Native session identifier supplied by the host provider.

        Returns:
            HostSession | None: Matching session in the given project/provider scope, or None.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str, session_id: str) -> HostSession:
        """Load a session only if it belongs to the explicitly addressed project.

        Args:
            project_id: Stable identifier of the project to address.
            session_id: Identifier of the session within the addressed project.

        Returns:
            HostSession: Session belonging to the explicitly addressed project.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def add(self, session: HostSession) -> None:
        """Persist a new host observation without committing the transaction.

        Args:
            session: Domain session entity to persist within the current transaction.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, session: HostSession) -> HostSession:
        """Persist an entity and return its stored version.

        Args:
            session: Domain session entity to persist within the current transaction.

        Returns:
            HostSession: Persisted session with its current storage version.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError
