"""관찰 위치의 기존 소유 프로젝트를 찾고, 없으면 새 프로젝트를 등록한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class RegisterProjectCommand(AbstractCommand):
    """프로젝트를 찾거나 등록하는 데 사용할 디렉터리·Git 관찰을 전달한다.

    Attributes:
        observation: 요청 전에 조사한 작업 디렉터리와 선택적 Git 메타데이터.
    """

    observation: DirectoryObservation


@dataclass(frozen=True)
class RegisterProjectResult:
    """관찰한 로컬 위치들을 소유하는 기존 또는 신규 프로젝트를 반환한다.

    Attributes:
        project: 관찰 위치를 소유하는 프로젝트.
    """

    project: Project


@UseCase()
class RegisterProjectUseCase(ICommandUseCase[RegisterProjectCommand, RegisterProjectResult]):
    """관찰 위치의 기존 소유 프로젝트를 찾고, 없으면 새 프로젝트를 등록한다.

    Git 공통 디렉터리와 기본 작업 트리의 폴더 위치를 함께 조회하여 linked worktree와
    Git 초기화 전 폴더의 ID를 이어간다. 위치들이 서로 다른 프로젝트를 가리키면
    병합하지 않고 ProjectIdentityConflict를 발생시킨다. 파일 시스템 관찰은 호출자가 먼저 수행한다.
    """

    def __init__(self, projects: IProjectRepository) -> None:
        """위치의 기존 소유자를 찾고 프로젝트를 저장할 포트를 받는다.

        Args:
            projects: Git·폴더 위치로 소유 프로젝트를 조회하고 위치 관계를 함께 저장한다.
        """
        self.projects = projects

    @override
    def run(self, command: RegisterProjectCommand) -> RegisterProjectResult:
        """위치 후보의 소유자를 선택하고 새로 확인한 위치를 프로젝트에 연결해 저장한다.

        Args:
            command: 정규 작업 경로와 선택적인 Git 공통 디렉터리·기본 작업 트리 관찰.

        Returns:
            RegisterProjectResult: 관찰 위치를 연결한 기존 프로젝트 또는 새 uid의 프로젝트.
        """
        candidates = Project.identify(command.observation)
        owners: list[Project] = []
        for location in candidates:
            owner = self.projects.find_by_location(location)
            if owner is not None:
                owners.append(owner)
        project = Project.owner_of(owners)
        if project is None:
            project = Project.create(command.observation)
        project.associate(candidates)
        return RegisterProjectResult(project=self.projects.save(project))
