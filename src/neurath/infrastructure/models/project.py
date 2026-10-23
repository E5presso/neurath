"""프로젝트와 소유 위치를 선언적 관계로 매핑하고 명시적으로 변환한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.infrastructure.uuid_type import UUIDText


@Table(Project)
class ProjectModel(AbstractMappableTable[Project]):
    """Git 초기화 전후에 유지되는 프로젝트와 소유 위치를 매핑한다.

    Attributes:
        id: 저장된 프로젝트의 안정적인 식별자.
        version: 프레임워크가 관리하는 도메인 변경 토큰.
        created_at: 최초 메타데이터이며 이전 자료는 미상 시각을 나타내는 epoch.
        updated_at: 마지막으로 변경한 도메인 시각.
        root_path: Git 승격 후에도 유지하는 프로젝트의 정규 루트 경로.
        revision: 저장소의 정수 낙관적 잠금 카운터.
        locations: 프로젝트와 함께 저장하고 삭제하는 소유 위치 레코드들.
    """

    __tablename__ = "core_projects"
    id: Mapped[UUID] = mapped_column(UUIDText, primary_key=True)
    version: Mapped[UUID] = mapped_column(
        Uuid(), nullable=False, server_default="00000000000000000000000000000000"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
    )

    root_path: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": revision}
    locations: Mapped[list[ProjectLocationModel]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ProjectLocationModel.kind, ProjectLocationModel.path",
    )

    @classmethod
    @override
    def from_domain(cls, domain: Project) -> Self:
        """프로젝트·소유 위치를 ORM 객체로 변환하고 시각을 UTC 기준 무시간대 값으로 맞춘다.

        객체만 생성하며 DB 저장은 repository가 수행한다. SQLite가 시간대 정보를
        저장하지 않아도 같은 시각의 재저장이 변경으로 오인되지 않게 정규화한다.

        Args:
            domain: 동일성을 보존하여 변환할 프로젝트 aggregate.

        Returns:
            Self: 프로젝트와 소유 위치 전체를 포함하는 새 ORM 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            root_path=domain.root_path,
            revision=domain.revision,
            locations=[
                ProjectLocationModel.from_domain(item, domain.id) for item in domain.locations
            ],
        )

    @override
    def to_domain(self) -> Project:
        """저장 시각에 UTC를 복원하고 위치를 tuple로 담은 프로젝트를 반환한다.

        Returns:
            Project: 저장된 식별자와 모든 소유 위치를 가진 프로젝트.
        """
        return Project(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            root_path=self.root_path,
            revision=self.revision,
            locations=tuple(location.to_domain() for location in self.locations),
        )


@Table()
class ProjectLocationModel(AbstractTable):
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
    project_id: Mapped[UUID] = mapped_column(
        UUIDText, ForeignKey("core_projects.id"), nullable=False
    )

    @classmethod
    def from_domain(cls, location: ProjectLocation, project_id: UUID) -> Self:
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
        return ProjectLocation(kind=ProjectKind(self.kind), path=self.path)
