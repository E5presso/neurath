"""SQLAlchemy storage of project records without identity-resolution decisions."""

from typing import override

from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.errors import ContextNotFound
from neurath.infrastructure.models.project import ProjectModel


class ProjectRepository(IProjectRepository):
    """Load and insert projects in the supplied ORM Session."""

    def __init__(self, session: Session) -> None:
        """Bind the request's existing SQLAlchemy session.

        Args:
            session: ORM resource owned by the request scope.
        """
        self.session = session

    @override
    def get(self, project_id: str) -> Project:
        """Load a persisted project by its stable identifier.

        Args:
            project_id: Identifier of the requested project.

        Returns:
            Project: A detached project entity.

        Raises:
            ContextNotFound: No project has the requested identifier.
        """
        record = self.session.get(ProjectModel, project_id)
        if record is None:
            raise ContextNotFound("Project does not exist")
        return record.to_domain()

    @override
    def add(self, project: Project) -> None:
        """Insert a new project without committing the transaction.

        Args:
            project: Entity created by domain policy.
        """
        self.session.add(ProjectModel.from_domain(project))
        self.session.flush()
