"""Immutable request-result snapshots detached from mutable domain entities."""

from dataclasses import dataclass

from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession


@dataclass(frozen=True)
class ProjectContext:
    """Project state as observed by one completed request.

    Attributes:
        id: Stable project identifier.
        root_path: Canonical project root.
    """

    id: str
    root_path: str


@dataclass(frozen=True)
class HostSessionContext:
    """Session state as observed by one completed request.

    Attributes:
        id: Stable session identifier.
        project_id: Stable containing project identifier.
        provider: Host provider namespace.
        host_session_id: Native host identifier.
        working_directory: Canonical last accepted directory.
        revision: Persisted optimistic version at the time of this result.
    """

    id: str
    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int


@dataclass(frozen=True)
class SessionContext:
    """Value result whose equality compares state rather than entity identity.

    Attributes:
        project: Immutable project state.
        session: Immutable session state belonging to that project.
    """

    project: ProjectContext
    session: HostSessionContext

    @classmethod
    def from_entities(cls, project: Project, session: HostSession) -> "SessionContext":
        """Copy entities into a stable, independent request result.

        Args:
            project: Project entity addressed by the request.
            session: Session entity after persistence or lookup.

        Returns:
            SessionContext: Immutable snapshots with no live entity or ORM references.
        """
        return cls(
            ProjectContext(project.id, project.root_path),
            HostSessionContext(
                session.id,
                session.project_id,
                session.provider,
                session.host_session_id,
                session.working_directory,
                session.revision,
            ),
        )
