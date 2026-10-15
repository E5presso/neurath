"""Immutable facts observed outside the domain, without project identity decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectoryObservation:
    """Canonical directory and optional Git metadata returned by read-only observation.

    Attributes:
        working_directory: Canonical directory inspected by the host request.
        git_common_directory: Canonical Git common directory, if Git metadata exists.
        primary_worktree: Canonical first worktree reported by Git, if available.
    """

    working_directory: str
    git_common_directory: str | None = None
    primary_worktree: str | None = None
