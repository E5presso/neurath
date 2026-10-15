"""Stateless identity use cases shared by CLI and hook transports.

Only configuration/dependencies live on Core. Every method owns a fresh transaction,
returns immutable values, and releases the connection before returning to the host.
"""

from contextlib import AbstractContextManager
from typing import Protocol

from neurath.domain.core import CoreContext, ContextNotFound, Project, ProjectLocation, Session


class IdentityRepository(Protocol):
    def resolve_project(self, location: ProjectLocation) -> Project: ...
    def get_project(self, project_id: str) -> Project: ...
    def find_session(
        self, project_id: str, provider: str, host_session_id: str
    ) -> Session | None: ...
    def get_session(self, project_id: str, session_id: str) -> Session: ...
    def add_session(
        self, project_id: str, provider: str, host_session_id: str, cwd: str
    ) -> Session: ...
    def move_session(self, session: Session, cwd: str, expected_revision: int) -> Session: ...


class UnitOfWork(Protocol):
    identities: IdentityRepository


class Database(Protocol):
    def transaction(self, *, write: bool = False) -> AbstractContextManager[UnitOfWork]: ...


class ProjectResolver(Protocol):
    def resolve(self, working_directory: str) -> ProjectLocation: ...


class Core:
    def __init__(self, database: Database, projects: ProjectResolver):
        self.database = database
        self.projects = projects

    def open_session(
        self, working_directory: str, provider: str, host_session_id: str
    ) -> CoreContext:
        """Register an observed host session; repeat calls preserve its identity and cwd.

        Moving an existing session explicitly uses move_session and a revision. A
        delayed registration cannot overwrite a newer working-directory observation.
        """
        if not provider.strip() or not host_session_id.strip():
            raise ValueError("provider and host_session_id must be non-empty")
        location = self.projects.resolve(working_directory)  # Git runs outside DB transaction.
        with self.database.transaction(write=True) as work:
            project = work.identities.resolve_project(location)
            session = work.identities.find_session(project.id, provider, host_session_id)
            if session is None:
                session = work.identities.add_session(
                    project.id, provider, host_session_id, location.working_directory
                )
            return CoreContext(project, session)

    def get_context(self, project_id: str, session_id: str) -> CoreContext:
        """Read only the explicitly addressed project/session, without registration."""
        with self.database.transaction() as work:
            session = work.identities.get_session(project_id, session_id)
            return CoreContext(work.identities.get_project(project_id), session)

    def move_session(
        self, project_id: str, session_id: str, working_directory: str, expected_revision: int
    ) -> CoreContext:
        location = self.projects.resolve(working_directory)
        with self.database.transaction(write=True) as work:
            session = work.identities.get_session(project_id, session_id)
            project = work.identities.resolve_project(location)
            if project.id != project_id:
                raise ContextNotFound("Working directory belongs to another project")
            session = work.identities.move_session(
                session, location.working_directory, expected_revision
            )
            return CoreContext(project, session)
