"""프로젝트 aggregate가 위치 값과 식별·승격·소유권 규칙을 관리한다."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from neurath.domain.errors import ProjectIdentityConflict
from neurath.domain.observations import DirectoryObservation


class ProjectKind(StrEnum):
    """원격 주소를 제외한 로컬 프로젝트 식별 방식을 나타낸다.

    Attributes:
        FOLDER: 일반 디렉터리의 정규 경로로 식별하는 방식.
        GIT: Git 공통 디렉터리의 정규 경로로 식별하는 방식.
    """

    FOLDER = "folder"
    GIT = "git"


@dataclass(frozen=True)
class ProjectLocation:
    """프로젝트에 종속되며 독립적인 생명주기를 갖지 않는 위치 값이다.

    Attributes:
        kind: 위치를 식별하는 로컬 경로의 종류.
        path: 해당 종류 안에서 위치를 구분하는 정규 경로.
    """

    kind: ProjectKind
    path: str


@dataclass(eq=False)
class Project:
    """소유한 위치와 Git 승격 전후의 안정적인 동일성을 관리한다.

    Attributes:
        id: 세션과 보존된 기록에서 참조하는 프로젝트 식별자.
        root_path: 최초 등록 시 선택한 프로젝트의 정규 루트 경로.
        locations: 이 프로젝트가 소유한 불변 위치 값의 모음.
    """

    id: str
    root_path: str
    locations: tuple[ProjectLocation, ...] = ()

    def __eq__(self, other: object) -> bool:
        """가변 상태와 관계없이 프로젝트 식별자로 동일성을 비교한다.

        Args:
            other: 동일성을 비교할 대상 객체.

        Returns:
            bool: 두 객체가 같은 프로젝트를 나타내는지 여부.
        """
        if not isinstance(other, Project):
            return NotImplemented
        return self.id == other.id

    @staticmethod
    def root_for(observation: DirectoryObservation) -> str:
        """Git은 기본 작업 트리, 일반 폴더는 관찰 경로를 루트로 선택한다.

        Args:
            observation: 도메인 판단을 포함하지 않는 파일 시스템과 Git 관찰 사실.

        Returns:
            str: 연결 작업 트리들이 공유하는 프로젝트의 정규 루트 경로.

        Raises:
            ValueError: Git 공통 디렉터리와 기본 작업 트리 정보가 불완전한 경우.
        """
        if observation.git_common_directory is None:
            if observation.primary_worktree is not None:
                raise ValueError("A primary worktree requires a Git common directory")
            return observation.working_directory
        if observation.primary_worktree is None:
            raise ValueError("A Git common directory requires a primary worktree")
        return observation.primary_worktree

    @classmethod
    def identify(cls, observation: DirectoryObservation) -> tuple[ProjectLocation, ...]:
        """Git 승격에 필요한 기존 폴더 별칭을 포함하여 위치 후보를 도출한다.

        Args:
            observation: 연결 작업 트리 정보를 포함하는 정규화된 외부 관찰 사실.

        Returns:
            tuple[ProjectLocation, ...]: 프로젝트 식별에 필요한 위치 값들.
        """
        folder = ProjectLocation(ProjectKind.FOLDER, cls.root_for(observation))
        if observation.git_common_directory is None:
            return (folder,)
        return (ProjectLocation(ProjectKind.GIT, observation.git_common_directory), folder)

    @staticmethod
    def owner_of(owners: tuple["Project", ...]) -> "Project | None":
        """충돌하는 프로젝트를 병합하지 않고 후보 위치의 기존 소유자를 선택한다.

        Args:
            owners: 후보 위치를 통해 조회한 기존 프로젝트들.

        Returns:
            Project | None: 유일한 기존 소유자이며 새 위치라면 None.

        Raises:
            ProjectIdentityConflict: 후보 위치들이 서로 다른 프로젝트에 속한 경우.
        """
        if len({owner.id for owner in owners}) > 1:
            raise ProjectIdentityConflict("Git and folder identities disagree; no records merged")
        return next(iter(owners), None)

    @classmethod
    def create(cls, observation: DirectoryObservation) -> "Project":
        """도메인의 루트와 위치 선택 규칙에 따라 새 프로젝트를 생성한다.

        Args:
            observation: 이번 요청의 정규 디렉터리와 Git 관찰 사실.

        Returns:
            Project: 독립적으로 생성한 식별자와 소유 위치를 가진 새 프로젝트.
        """
        return cls(str(uuid4()), cls.root_for(observation), cls.identify(observation))

    def associate(self, candidates: tuple[ProjectLocation, ...]) -> None:
        """기존 Git 동일성을 교체하지 않고 호환되는 위치를 소유 목록에 추가한다.

        모든 충돌을 확인한 뒤에만 aggregate의 위치 상태를 변경한다.

        Args:
            candidates: 이번 관찰에서 도출한 위치 값들.

        Raises:
            ProjectIdentityConflict: 기존 Git 동일성과 새 위치가 충돌하는 경우.
        """
        locations = self.locations + candidates
        git_paths = {location.path for location in locations if location.kind is ProjectKind.GIT}
        if len(git_paths) > 1:
            raise ProjectIdentityConflict("Folder already belongs to another repository")
        self.locations = tuple(dict.fromkeys(locations))
