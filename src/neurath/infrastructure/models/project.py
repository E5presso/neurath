"""Declarative project records with explicit domain conversion."""

from typing import Self

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.project import Project
from neurath.infrastructure.models.base import DatabaseModel


class ProjectModel(DatabaseModel):
    """Map the stable project identity retained across Git initialization."""

    __tablename__ = "core_projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    root_path: Mapped[str] = mapped_column(String, nullable=False)

    @classmethod
    def from_domain(cls, project: Project) -> Self:
        """Create a persistence record using named domain fields."""
        return cls(id=project.id, root_path=project.root_path)

    def to_domain(self) -> Project:
        """Return a value independent of SQLAlchemy's identity map."""
        return Project(id=self.id, root_path=self.root_path)


class ProjectLocationModel(DatabaseModel):
    """Associate a canonical folder or common Git directory with its project."""

    __tablename__ = "core_project_locations"
    __table_args__ = (CheckConstraint("kind IN ('git', 'folder')", name="location_kind"),)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)
