"""Nominal persistence contract for RequestSource records."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.request_source import RequestSource


class ISourceRepository(ABC):
    """Persist scoped RequestSource values without exposing ORM objects or transactions."""

    @abstractmethod
    def add(self, value: RequestSource) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str, record_id: str) -> RequestSource:
        """Resolve an explicit source ID within the project, retaining its origin session."""
        raise NotImplementedError

    @abstractmethod
    def list(self, project_id: str, session_id: str) -> tuple[RequestSource, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        raise NotImplementedError
