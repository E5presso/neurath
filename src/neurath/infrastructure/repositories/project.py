"""식별 정책 없이 프로젝트 aggregate 전체를 SQLAlchemy로 조회·저장한다."""

from typing import override

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project, ProjectLocation
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel


class ProjectRepository(IProjectRepository):
    """주어진 ORM 세션에서 프로젝트와 소유 위치를 함께 조회·저장한다."""

    def __init__(self, session: Session) -> None:
        """요청이 이미 소유한 SQLAlchemy 세션을 주입받는다.

        Args:
            session: 요청 범위에서 수명을 관리하는 ORM 자원.
        """
        self.session = session

    @override
    def get(self, project_id: str) -> Project:
        """안정적인 식별자로 저장된 프로젝트 전체를 조회한다.

        Args:
            project_id: 조회할 프로젝트의 식별자.

        Returns:
            Project: ORM과 분리된 프로젝트 및 소유 위치 값들.

        Raises:
            ContextNotFound: 지정한 식별자의 프로젝트가 없는 경우.
        """
        record = self.session.get(ProjectModel, project_id)
        if record is None:
            raise ContextNotFound("Project does not exist")
        return record.to_domain()

    @override
    def find_by_location(self, location: ProjectLocation) -> Project | None:
        """위치 값을 소유하는 프로젝트 전체를 조회한다.

        Args:
            location: 소유 프로젝트를 조회할 위치 값.

        Returns:
            Project | None: 해당 위치의 소유자이며 없으면 None.
        """
        record = self.session.scalar(
            select(ProjectModel)
            .join(ProjectModel.locations)
            .where(
                ProjectLocationModel.kind == location.kind.value,
                ProjectLocationModel.path == location.path,
            )
        )
        if record is None:
            return None
        return record.to_domain()

    @override
    def save(self, project: Project) -> Project:
        """프로젝트와 소유 위치를 병합하고 현재 트랜잭션 안에서 반영한다.

        Args:
            project: 도메인 규칙을 적용한 신규 또는 기존 aggregate.

        Returns:
            Project: 저장된 프로젝트와 소유 위치 값들.

        Raises:
            ProjectIdentityConflict: 저장된 위치 소유자가 병합 대상과 다른 경우.
        """
        try:
            record = self.session.merge(ProjectModel(id=project.id, root_path=project.root_path))
            existing = {(item.kind, item.path): item for item in record.locations}
            locations: list[ProjectLocationModel] = []
            for location in project.locations:
                child = existing.get((location.kind.value, location.path))
                if child is None:
                    child = ProjectLocationModel.from_domain(location, project.id)
                locations.append(child)
            record.locations = locations
            self.session.flush()
        except IntegrityError as error:
            raise ProjectIdentityConflict("Location already belongs to another project") from error
        return record.to_domain()
