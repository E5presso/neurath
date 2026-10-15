"""Project identity is independent of an individual host session or working tree."""

from dataclasses import dataclass
from enum import StrEnum


class ProjectKind(StrEnum):
    """Supported local identity sources; remote URLs never identify projects."""

    FOLDER = "folder"
    GIT = "git"


@dataclass(frozen=True)
class ProjectLocation:
    """Canonical repository identity and the directory observed by a request."""

    kind: ProjectKind
    identity_path: str
    root_path: str
    working_directory: str


@dataclass(frozen=True)
class Project:
    """Stable identity retained when a plain directory becomes a Git repository."""

    id: str
    root_path: str
