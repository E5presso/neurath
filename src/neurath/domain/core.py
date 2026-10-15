"""Identity and concurrency values for the request-scoped core (no persistence imports)."""

from dataclasses import dataclass
from typing import Literal


class CoreError(Exception):
    """An actionable core request failure."""


class ContextNotFound(CoreError):
    pass


class RevisionConflict(CoreError):
    pass


class ProjectIdentityConflict(CoreError):
    pass


class StorageNotReady(CoreError):
    pass


@dataclass(frozen=True)
class ProjectLocation:
    kind: Literal["folder", "git"]
    identity_path: str
    root_path: str
    working_directory: str


@dataclass(frozen=True)
class Project:
    id: str
    root_path: str


@dataclass(frozen=True)
class Session:
    id: str
    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int


@dataclass(frozen=True)
class CoreContext:
    project: Project
    session: Session
