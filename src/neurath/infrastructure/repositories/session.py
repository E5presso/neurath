"""세션의 기본 CRUD와 낙관적 잠금을 프레임워크 구현에 위임한다."""

from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.session import HostSession
from neurath.infrastructure.models.session import SessionModel


@Repository(scope=Pod.Scope.CONTEXT)
class SQLAlchemySessionRepository(
    AbstractAsyncGenericRepository[HostSession, str], ISessionRepository
):
    """기본 메서드를 상속하고 프로젝트·공급자·네이티브 ID 조회만 확장한다."""

    @override
    async def find(
        self, project_id: str, provider: str, host_session_id: str
    ) -> HostSession | None:
        """프로젝트와 공급자 범위 안에서만 네이티브 식별자를 찾는다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
            host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.

        Returns:
            HostSession | None: 해당 프로젝트·공급자 범위의 세션이며 없으면 None.
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
