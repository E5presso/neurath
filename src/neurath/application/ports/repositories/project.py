"""Primitive storage contract for stable project records."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.project import Project


class IProjectRepository(ABC):
    """Load and store project entities without identity-resolution policy."""

    @abstractmethod
    def get(self, project_id: str) -> Project:
        """Load an existing project.

        Args:
            project_id: Stable identifier to look up.

        Returns:
            Project: The persisted project entity.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def add(self, project: Project) -> None:
        """Store a newly created project in the current transaction.

        Args:
            project: New entity whose identity was assigned by the domain.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError
