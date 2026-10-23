"""호스트 세션의 기본 Aggregate 저장 계약을 제공한다."""

from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.session import HostSession
from neurath.infrastructure.models.session import SessionModel


@Repository()
class SQLAlchemySessionRepository(
    AbstractAsyncGenericRepository[HostSession, UUID], ISessionRepository
):
    """프로젝트 소속과 작업 경로를 가진 세션를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_project_id_and_provider_and_host_session_id(
        self, project_id: UUID, provider: str, host_session_id: str
    ) -> HostSession | None:
        """프로젝트 안에서 실제 네이티브 식별자에 대응하는 세션을 찾는다.

        Args:
            project_id: 세션을 소유한 프로젝트.
            provider: 호스트 공급자.
            host_session_id: 실제 호스트의 세션 식별자.

        Returns:
            HostSession | None: 프로젝트·공급자·네이티브 ID가 일치하는 세션이며 미등록이면 None.
        """
        record = await self._session_manager.session.scalar(
            select(SessionModel).where(
                SessionModel.project_id == project_id,
                SessionModel.provider == provider,
                SessionModel.host_session_id == host_session_id,
            )
        )
        if record is None:
            return None
        return record.to_domain()
