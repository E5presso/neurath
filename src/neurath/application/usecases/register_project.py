"""프로젝트 조회·도메인 판단·aggregate 저장 순서를 조정한다."""

from spakky.core.stereotype.usecase import UseCase

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.observations import DirectoryObservation


@UseCase()
class RegisterProjectUseCase:
    """위치로 프로젝트를 조회하고 도메인 규칙을 적용하여 전체를 저장한다."""

    def __init__(self, projects: IProjectRepository) -> None:
        """한 요청에 속하는 프로젝트 저장소를 주입받는다.

        Args:
            projects: 프로젝트 aggregate의 조회와 저장을 제공하는 포트.
        """
        self.projects = projects

    def execute(self, observation: DirectoryObservation) -> Project:
        """기존 프로젝트 참조를 유지하면서 관찰한 위치를 등록한다.

        Args:
            observation: 도메인에서 해석할 정규화된 외부 관찰 사실.

        Returns:
            Project: 관찰 위치를 소유하는 저장된 프로젝트 aggregate.
        """
        candidates = Project.identify(observation)
        owners: list[Project] = []
        for location in candidates:
            owner = self.projects.find_by_location(location)
            if owner is not None:
                owners.append(owner)
        project = Project.owner_of(tuple(owners))
        if project is None:
            project = Project.create(observation)
        project.associate(candidates)
        return self.projects.save(project)
