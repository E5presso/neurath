"""프로젝트와 소유 위치를 선언적 관계로 매핑하고 명시적으로 변환한다."""

from typing import Self

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.infrastructure.models.base import DatabaseModel


class ProjectModel(DatabaseModel):
    """Git 초기화 전후에 유지되는 프로젝트와 소유 위치를 매핑한다.

    Attributes:
        id: 저장된 프로젝트의 안정적인 식별자.
        root_path: Git 승격 후에도 유지하는 프로젝트의 정규 루트 경로.
        locations: 프로젝트와 함께 저장하고 삭제하는 소유 위치 레코드들.
    """

    __tablename__ = "core_projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    root_path: Mapped[str] = mapped_column(String, nullable=False)
    locations: Mapped[list[ProjectLocationModel]] = relationship(
        cascade="all, delete-orphan",
        order_by="ProjectLocationModel.kind, ProjectLocationModel.path",
    )

    @classmethod
    def from_domain(cls, project: Project) -> Self:
        """프로젝트의 명시적인 필드와 모든 소유 위치를 레코드로 변환한다.

        Args:
            project: 동일성을 보존하여 변환할 프로젝트 aggregate.

        Returns:
            Self: 프로젝트와 소유 위치 전체를 포함하는 새 ORM 레코드.
        """
        return cls(
            id=project.id,
            root_path=project.root_path,
            locations=[
                ProjectLocationModel.from_domain(item, project.id) for item in project.locations
            ],
        )

    def to_domain(self) -> Project:
        """ORM 동일성 맵과 독립적인 프로젝트 aggregate를 반환한다.

        Returns:
            Project: 저장된 식별자와 모든 소유 위치를 가진 프로젝트.
        """
        return Project(
            id=self.id,
            root_path=self.root_path,
            locations=tuple(location.to_domain() for location in self.locations),
        )


class ProjectLocationModel(DatabaseModel):
    """프로젝트에 종속된 위치 값을 물리적인 자식 테이블에 저장한다.

    Attributes:
        kind: 저장된 로컬 위치 식별 방식.
        path: 위치를 구분하는 정규 경로.
        project_id: 저장소가 기존 소유 관계를 유지할 때 사용하는 프로젝트 식별자.
    """

    __tablename__ = "core_project_locations"
    __table_args__ = (CheckConstraint("kind IN ('git', 'folder')", name="location_kind"),)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)

    @classmethod
    def from_domain(cls, location: ProjectLocation, project_id: str) -> Self:
        """위치 값과 aggregate의 식별자로 소유 관계 레코드를 생성한다.

        Args:
            location: 프로젝트가 소유한 불변 위치 값.
            project_id: 위치를 소유한 aggregate의 식별자.

        Returns:
            Self: 지정한 프로젝트에 종속되는 위치 레코드.
        """
        return cls(kind=location.kind.value, path=location.path, project_id=project_id)

    def to_domain(self) -> ProjectLocation:
        """저장된 자식 레코드를 프로젝트의 불변 위치 값으로 변환한다.

        Returns:
            ProjectLocation: ORM 동일성 맵과 독립적인 위치 값.
        """
        return ProjectLocation(ProjectKind(self.kind), self.path)
