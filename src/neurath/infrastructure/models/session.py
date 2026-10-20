"""명시적인 필드 변환으로 호스트 세션을 선언적으로 매핑한다."""

from typing import Self

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.session import HostSession
from neurath.infrastructure.models.base import DatabaseModel


class SessionModel(DatabaseModel):
    """범위가 지정된 네이티브 식별자와 작업 경로의 낙관적 버전을 저장한다.

    Attributes:
        id: 저장된 엔티티의 안정적인 식별자.
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
        host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.
        working_directory: 가장 최근에 수용한 정규 작업 디렉터리.
        revision: 쓰기 시 SQLAlchemy가 생성하여 저장한 낙관적 버전.
    """

    __tablename__ = "core_sessions"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", "host_session_id", name="uq_core_host_session"),
        UniqueConstraint("project_id", "id", name="uq_core_session_scope"),
        CheckConstraint("revision >= 1", name="session_revision_positive"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    host_session_id: Mapped[str] = mapped_column(String, nullable=False)
    working_directory: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    def from_domain(cls, session: HostSession) -> Self:
        """모든 호스트 세션 필드를 명시적으로 새 ORM 레코드에 매핑한다.

        Args:
            session: 현재 트랜잭션에 저장할 도메인 세션 엔티티.

        Returns:
            Self: 도메인 필드를 명시적으로 복사한 새 저장 레코드.
        """
        return cls(
            id=session.id,
            project_id=session.project_id,
            provider=session.provider,
            host_session_id=session.host_session_id,
            working_directory=session.working_directory,
            revision=session.revision,
        )

    def to_domain(self) -> HostSession:
        """저장된 관찰을 ORM 세션 수명과 분리한다.

        Returns:
            HostSession: 저장된 버전을 가진 분리된 세션 엔티티.
        """
        return HostSession(
            id=self.id,
            project_id=self.project_id,
            provider=self.provider,
            host_session_id=self.host_session_id,
            working_directory=self.working_directory,
            revision=self.revision,
        )
