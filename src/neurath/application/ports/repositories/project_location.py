"""Primitive location lookup and storage contract."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.project import ProjectKind, ProjectLocation


class IProjectLocationRepository(ABC):
    """Persist domain associations without deciding promotion or ownership rules."""

    @abstractmethod
    def find(self, kind: ProjectKind, path: str) -> ProjectLocation | None:
        """Look up a location by its compound identity.

        Args:
            kind: Local identity namespace.
            path: Canonical path within that namespace.

        Returns:
            ProjectLocation | None: The persisted location, or None if it has not been stored.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def list(self, project_id: str) -> tuple[ProjectLocation, ...]:
        """Read all locations associated with one project.

        Args:
            project_id: Stable owner identifier to query.

        Returns:
            tuple[ProjectLocation, ...]: Persisted location entities for the project.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def add(self, location: ProjectLocation) -> None:
        """Persist a new location whose owner was assigned by the domain.

        Args:
            location: New associated location entity.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError
