"""Project and location entities own identity selection and association invariants."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from neurath.domain.errors import ProjectIdentityConflict
from neurath.domain.observations import DirectoryObservation


class ProjectKind(StrEnum):
    """Supported local identity sources; remote URLs never identify projects.

    Attributes:
        FOLDER: Identity namespace for a plain canonical directory.
        GIT: Identity namespace for a canonical Git common directory.
    """

    FOLDER = "folder"
    GIT = "git"


@dataclass(eq=False)
class ProjectLocation:
    """An identified location whose project association may be established once.

    Attributes:
        kind: Local identity source.
        path: Canonical path identifying this location within its kind.
        project_id: Stable owner, or None before the first association.
    """

    kind: ProjectKind
    path: str
    project_id: str | None = None

    def __eq__(self, other: object) -> bool:
        """Compare stable entity identity independently of mutable association state.

        Args:
            other: Object whose entity identity is compared.

        Returns:
            bool: Whether both objects represent the same ProjectLocation identity.
        """
        if not isinstance(other, ProjectLocation):
            return NotImplemented
        return self.kind == other.kind and self.path == other.path

    @staticmethod
    def root_for(observation: DirectoryObservation) -> str:
        """Choose the primary worktree for Git and the observed directory for folders.

        Args:
            observation: Filesystem and Git facts without domain decisions.

        Returns:
            str: Canonical project root shared by linked worktrees.

        Raises:
            ValueError: Git common-directory and primary-worktree facts are incomplete.
        """
        if observation.git_common_directory is None:
            if observation.primary_worktree is not None:
                raise ValueError("A primary worktree requires a Git common directory")
            return observation.working_directory
        if observation.primary_worktree is None:
            raise ValueError("A Git common directory requires a primary worktree")
        return observation.primary_worktree

    @classmethod
    def identify(cls, observation: DirectoryObservation) -> tuple["ProjectLocation", ...]:
        """Derive identity candidates, including the folder alias used for Git promotion.

        Args:
            observation: Canonical external facts, including linked-worktree metadata.

        Returns:
            tuple[ProjectLocation, ...]: Unassociated location entities needed to identify this project.
        """
        root = cls.root_for(observation)
        folder = cls(ProjectKind.FOLDER, root)
        if observation.git_common_directory is None:
            return (folder,)
        return (cls(ProjectKind.GIT, observation.git_common_directory), folder)

    @staticmethod
    def owner_of(locations: tuple["ProjectLocation", ...]) -> str | None:
        """Select an existing owner without merging conflicting project identities.

        Args:
            locations: Existing or newly observed candidate location entities.

        Returns:
            str | None: The sole associated project identifier, or None for new locations.

        Raises:
            ProjectIdentityConflict: The candidates belong to different projects.
        """
        owners = {location.project_id for location in locations if location.project_id is not None}
        if len(owners) > 1:
            raise ProjectIdentityConflict("Git and folder identities disagree; no records merged")
        return next(iter(owners), None)

    def associate(self, project_id: str) -> None:
        """Establish ownership while preserving this location's identity.

        Args:
            project_id: Stable owner to associate with this location.

        Raises:
            ProjectIdentityConflict: The location already belongs to another project.
        """
        if self.project_id is not None and self.project_id != project_id:
            raise ProjectIdentityConflict("Location already belongs to another project")
        self.project_id = project_id


@dataclass(eq=False)
class Project:
    """Stable project identity retained when a plain directory becomes a Git repository.

    Attributes:
        id: Stable project identifier referenced by sessions and retained records.
        root_path: Canonical root selected when the project was first registered.
    """

    id: str
    root_path: str

    def __eq__(self, other: object) -> bool:
        """Compare stable entity identity independently of mutable association state.

        Args:
            other: Object whose entity identity is compared.

        Returns:
            bool: Whether both objects represent the same Project identity.
        """
        if not isinstance(other, Project):
            return NotImplemented
        return self.id == other.id

    @classmethod
    def create(cls, observation: DirectoryObservation) -> "Project":
        """Create a project using the domain's root-selection policy.

        Args:
            observation: Canonical directory and Git facts for this request.

        Returns:
            Project: A new project with an independently generated stable identity.
        """
        return cls(str(uuid4()), ProjectLocation.root_for(observation))

    def associate(
        self, candidates: tuple[ProjectLocation, ...], existing: tuple[ProjectLocation, ...]
    ) -> None:
        """Promote compatible locations without replacing an existing Git identity.

        All conflicts are checked before any location association is changed.

        Args:
            candidates: Locations derived from the current observation.
            existing: All locations already associated with this project.

        Raises:
            ProjectIdentityConflict: Ownership or Git identities are incompatible.
        """
        locations = existing + candidates
        owner = ProjectLocation.owner_of(locations)
        if owner is not None and owner != self.id:
            raise ProjectIdentityConflict("Location already belongs to another project")
        git_paths = {location.path for location in locations if location.kind is ProjectKind.GIT}
        if len(git_paths) > 1:
            raise ProjectIdentityConflict("Folder already belongs to another repository")
        for location in candidates:
            location.associate(self.id)
