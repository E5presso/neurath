"""Port for observing local project identity before a database transaction."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.project import ProjectLocation


class IProjectLocator(ABC):
    """Resolve a directory to a canonical local Git repository or plain folder."""

    @abstractmethod
    def locate(self, working_directory: str) -> ProjectLocation:
        """Inspect local metadata without changing the repository or filesystem."""
        raise NotImplementedError
