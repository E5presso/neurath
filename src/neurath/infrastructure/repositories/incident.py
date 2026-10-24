"""장애와 소유 근거를 표준 SQLAlchemy aggregate 저장으로 처리한다."""

from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.domain.aggregates.incident import Incident


@Repository()
class SQLAlchemyIncidentRepository(
    AbstractAsyncGenericRepository[Incident, UUID], IIncidentRepository
):
    """프레임워크의 CRUD·낙관적 잠금과 등록된 매핑을 그대로 사용한다."""
