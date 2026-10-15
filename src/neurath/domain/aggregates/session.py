"""Host-session identity and revision rules within a specific project."""

from dataclasses import dataclass, replace

from neurath.domain.aggregates.project import Project
from neurath.domain.errors import RevisionConflict


@dataclass(frozen=True)
class HostSession:
    """Persisted host observation; its native identifier is not authentication."""

    id: str
    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int

    def move(self, working_directory: str, expected_revision: int) -> "HostSession":
        """Return the next revision only when the caller observed the current one."""
        if expected_revision != self.revision:
            raise RevisionConflict("Session changed; read current context before updating")
        return replace(self, working_directory=working_directory, revision=self.revision + 1)


@dataclass(frozen=True)
class SessionContext:
    """A project and one session belonging to it, detached from ORM state."""

    project: Project
    session: HostSession
