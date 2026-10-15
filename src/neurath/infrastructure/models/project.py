"""Declarative project records with explicit domain conversion."""

from typing import Self

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.infrastructure.models.base import DatabaseModel


class ProjectModel(DatabaseModel):
    """Map the stable project identity retained across Git initialization.

    Attributes:
        id: Stable persisted entity identifier.
        root_path: Canonical project root retained across Git promotion.
    """

    __tablename__ = "core_projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    root_path: Mapped[str] = mapped_column(String, nullable=False)

    @classmethod
    def from_domain(cls, project: Project) -> Self:
        """Create a persistence record using named domain fields.

        Args:
            project: Project entity to convert without changing its identity.

        Returns:
            Self: New persistence record with explicitly copied domain fields.
        """
        return cls(id=project.id, root_path=project.root_path)

    def to_domain(self) -> Project:
        """Return a value independent of SQLAlchemy's identity map.

        Returns:
            Project: Detached project entity with the persisted stable identifier.
        """
        return Project(id=self.id, root_path=self.root_path)


class ProjectLocationModel(DatabaseModel):
    """Associate a canonical folder or common Git directory with its project.

    Attributes:
        kind: Persisted local identity namespace.
        path: Canonical location key.
        project_id: Stable identifier of the project to address.
    """

    __tablename__ = "core_project_locations"
    __table_args__ = (CheckConstraint("kind IN ('git', 'folder')", name="location_kind"),)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)

    @classmethod
    def from_domain(cls, location: ProjectLocation) -> Self:
        """Convert an associated domain location to a new persistence record.

        Args:
            location: Location entity after domain ownership checks.

        Returns:
            Self: An ORM record with the same identity and association.

        Raises:
            ValueError: The location has no owner to persist.
        """
        if location.project_id is None:
            raise ValueError("Cannot persist an unassociated location")
        return cls(kind=location.kind.value, path=location.path, project_id=location.project_id)

    def to_domain(self) -> ProjectLocation:
        """Convert the stored association to a location entity.

        Returns:
            ProjectLocation: Location entity detached from the ORM identity map.
        """
        return ProjectLocation(ProjectKind(self.kind), self.path, self.project_id)
