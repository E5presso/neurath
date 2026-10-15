"""SQLAlchemy location lookup and insertion without ownership policy."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project_location import IProjectLocationRepository
from neurath.domain.aggregates.project import ProjectKind, ProjectLocation
from neurath.infrastructure.models.project import ProjectLocationModel


class ProjectLocationRepository(IProjectLocationRepository):
    """Persist associations already established by domain entities."""

    def __init__(self, session: Session) -> None:
        """Bind a request-local ORM session.

        Args:
            session: ORM resource owned by the request scope.
        """
        self.session = session

    @override
    def find(self, kind: ProjectKind, path: str) -> ProjectLocation | None:
        """Find a persisted location by its compound key.

        Args:
            kind: Local identity namespace.
            path: Canonical path in the namespace.

        Returns:
            ProjectLocation | None: The matching location, or None if absent.
        """
        record = self.session.get(ProjectLocationModel, (kind.value, path))
        return record.to_domain() if record is not None else None

    @override
    def list(self, project_id: str) -> tuple[ProjectLocation, ...]:
        """Load all persisted locations for one project.

        Args:
            project_id: Stable owner identifier.

        Returns:
            tuple[ProjectLocation, ...]: Associated location entities.
        """
        records = self.session.scalars(
            select(ProjectLocationModel).where(ProjectLocationModel.project_id == project_id)
        )
        return tuple(record.to_domain() for record in records)

    @override
    def add(self, location: ProjectLocation) -> None:
        """Insert a location without changing its association or committing.

        Args:
            location: New location with a domain-assigned project owner.
        """
        self.session.add(ProjectLocationModel.from_domain(location))
        self.session.flush()
