"""SQLAlchemy implementation of local project identity resolution."""

from typing import override
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel


class ProjectRepository(IProjectRepository):
    """Persist aliases in the supplied ORM Session without committing independently."""

    def __init__(self, session: Session) -> None:
        """Bind the request's existing SQLAlchemy transaction."""
        self.session = session

    def _find_alias(self, kind: ProjectKind, path: str) -> str | None:
        """Look up one canonical alias without changing persisted identity."""
        return self.session.scalar(
            select(ProjectLocationModel.project_id).where(
                ProjectLocationModel.kind == kind.value, ProjectLocationModel.path == path
            )
        )

    @override
    def resolve(self, location: ProjectLocation) -> Project:
        """Create or promote a project while refusing incompatible alias merges."""
        identity_id = self._find_alias(location.kind, location.identity_path)
        folder_id = self._find_alias(ProjectKind.FOLDER, location.root_path)
        if identity_id is not None and folder_id is not None and identity_id != folder_id:
            raise ProjectIdentityConflict("Git and folder identities disagree; no records merged")
        project_id = identity_id if identity_id is not None else folder_id
        if project_id is not None and location.kind is ProjectKind.GIT:
            other_git = self.session.scalar(
                select(ProjectLocationModel.path).where(
                    ProjectLocationModel.project_id == project_id,
                    ProjectLocationModel.kind == ProjectKind.GIT.value,
                    ProjectLocationModel.path != location.identity_path,
                )
            )
            if other_git is not None:
                raise ProjectIdentityConflict("Folder already belongs to another repository")
        if project_id is None:
            project_id = str(uuid4())
            project = Project(id=project_id, root_path=location.root_path)
            self.session.add(ProjectModel.from_domain(project))
            self.session.flush()
        if identity_id is None:
            self.session.add(
                ProjectLocationModel(
                    kind=location.kind.value, path=location.identity_path, project_id=project_id
                )
            )
        if folder_id is None and location.kind is ProjectKind.GIT:
            self.session.add(
                ProjectLocationModel(
                    kind=ProjectKind.FOLDER.value, path=location.root_path, project_id=project_id
                )
            )
        self.session.flush()
        return self.get(project_id)

    @override
    def get(self, project_id: str) -> Project:
        """Return a detached domain project or a scoped lookup error."""
        record = self.session.get(ProjectModel, project_id)
        if record is None:
            raise ContextNotFound("Project does not exist")
        return record.to_domain()
