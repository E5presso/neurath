"""Read-only filesystem and Git observation port."""

from abc import ABC, abstractmethod

from neurath.domain.observations import DirectoryObservation


class IDirectoryObserver(ABC):
    """Observe primitive external facts without selecting or associating projects."""

    @abstractmethod
    def observe(self, working_directory: str) -> DirectoryObservation:
        """Read canonical directory and optional Git metadata.

        Args:
            working_directory: User-selected existing directory to inspect.

        Returns:
            DirectoryObservation: Canonical directory, Git common directory, and primary worktree facts.

        Raises:
            NotImplementedError: An abstract port method is called without an implementation.
        """
        raise NotImplementedError
