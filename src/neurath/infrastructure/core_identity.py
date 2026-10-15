"""Project/session repository; instances belong to one transaction only."""

from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from neurath.domain.core import (
    ContextNotFound,
    Project,
    ProjectIdentityConflict,
    ProjectLocation,
    RevisionConflict,
    Session,
)
from neurath.infrastructure.core_schema import project_locations, projects, sessions


class SqlIdentities:
    def __init__(self, connection: Connection):
        self.connection = connection

    def _location(self, kind: str, path: str) -> str | None:
        return self.connection.scalar(
            select(project_locations.c.project_id).where(
                project_locations.c.kind == kind, project_locations.c.path == path
            )
        )

    def resolve_project(self, location: ProjectLocation) -> Project:
        identity = self._location(location.kind, location.identity_path)
        folder = self._location("folder", location.root_path)
        if identity and folder and identity != folder:
            raise ProjectIdentityConflict("Git and folder identities disagree; no records merged")
        project_id = identity or folder
        if project_id and location.kind == "git":
            other_git = self.connection.scalar(
                select(project_locations.c.path).where(
                    project_locations.c.project_id == project_id,
                    project_locations.c.kind == "git",
                    project_locations.c.path != location.identity_path,
                )
            )
            if other_git:
                raise ProjectIdentityConflict(
                    "Folder already belongs to a different local repository"
                )
        if project_id is None:
            project_id = str(uuid4())
            self.connection.execute(
                insert(projects).values(id=project_id, root_path=location.root_path)
            )
        if identity is None:
            self.connection.execute(
                insert(project_locations).values(
                    kind=location.kind, path=location.identity_path, project_id=project_id
                )
            )
        # Retain the root alias when Git is initialized later, including a first
        # post-init request arriving from a linked worktree.
        if folder is None and location.kind == "git":
            self.connection.execute(
                insert(project_locations).values(
                    kind="folder", path=location.root_path, project_id=project_id
                )
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> Project:
        row = (
            self.connection.execute(select(projects).where(projects.c.id == project_id))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ContextNotFound("Project does not exist")
        return Project(**row)

    def find_session(self, project_id: str, provider: str, host_session_id: str) -> Session | None:
        row = (
            self.connection.execute(
                select(sessions).where(
                    sessions.c.project_id == project_id,
                    sessions.c.provider == provider,
                    sessions.c.host_session_id == host_session_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return Session(**row) if row else None

    def get_session(self, project_id: str, session_id: str) -> Session:
        row = (
            self.connection.execute(
                select(sessions).where(
                    sessions.c.project_id == project_id, sessions.c.id == session_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ContextNotFound("Session does not exist in the requested project")
        return Session(**row)

    def add_session(
        self, project_id: str, provider: str, host_session_id: str, cwd: str
    ) -> Session:
        session = Session(str(uuid4()), project_id, provider, host_session_id, cwd, 1)
        self.connection.execute(
            insert(sessions).values(
                id=session.id,
                project_id=project_id,
                provider=provider,
                host_session_id=host_session_id,
                working_directory=cwd,
                revision=1,
            )
        )
        return session

    def move_session(self, session: Session, cwd: str, expected_revision: int) -> Session:
        result = self.connection.execute(
            update(sessions)
            .where(
                sessions.c.id == session.id,
                sessions.c.project_id == session.project_id,
                sessions.c.revision == expected_revision,
            )
            .values(working_directory=cwd, revision=expected_revision + 1)
        )
        if result.rowcount != 1:
            raise RevisionConflict("Session changed; read current context before updating")
        return self.get_session(session.project_id, session.id)
