"""장애와 소유 근거를 표준 SQLAlchemy aggregate 저장으로 처리한다."""

from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.domain.aggregates.incident import Incident
from neurath.infrastructure.models.incident import IncidentModel


@Repository()
class SQLAlchemyIncidentRepository(
    AbstractAsyncGenericRepository[Incident, UUID], IIncidentRepository
):
    """프레임워크의 CRUD·낙관적 잠금과 등록된 매핑을 그대로 사용한다."""

    @override
    async def find_by_origin(self, origin: str) -> Incident | None:
        """JSON 출처의 첫 항목을 대조해 기존 사건을 그대로 복원한다.

        Args:
            origin: 같은 journal 행의 식별자.

        Returns:
            Incident | None: 이미 연결한 사건 또는 None.
        """
        row = await self._session_manager.session.scalar(
            select(IncidentModel).where(IncidentModel.references[0].as_string() == origin)
        )
        return None if row is None else row.to_domain()
