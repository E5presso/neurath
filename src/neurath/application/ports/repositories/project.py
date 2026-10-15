"""Nominal contract for persistent project identity and aliases."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.project import Project, ProjectLocation


class IProjectRepository(ABC):
    """Resolve observed local identities without merging unrelated projects."""

    @abstractmethod
    def resolve(self, location: ProjectLocation) -> Project:
        """Find or register a project, preserving a pre-existing folder identity."""
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str) -> Project:
        """Load an existing project or raise ContextNotFound."""
        raise NotImplementedError
