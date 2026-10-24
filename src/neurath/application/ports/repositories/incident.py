"""장애 aggregate에 프레임워크 기본 저장·조회 계약을 적용한다."""

from abc import ABC
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.incident import Incident


class IIncidentRepository(IAsyncGenericRepository[Incident, UUID], ABC):
    """증상과 소유 근거 이력을 하나의 작업 단위로 저장한다."""
