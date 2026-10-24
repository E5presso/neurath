"""장애 aggregate에 프레임워크 기본 저장·조회 계약을 적용한다."""

from abc import ABC, abstractmethod
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.incident import Incident


class IIncidentRepository(IAsyncGenericRepository[Incident, UUID], ABC):
    """증상과 소유 근거 이력을 하나의 작업 단위로 저장한다."""

    @abstractmethod
    async def find_by_origin(self, origin: str) -> Incident | None:
        """이미 연결한 journal 원문 출처의 사건을 찾는다.

        Args:
            origin: 원문 행의 안정된 출처.

        Returns:
            Incident | None: 기존 사건이며 없으면 None.

        Raises:
            NotImplementedError: 구현하지 않은 계약을 호출한 경우.
        """
        raise NotImplementedError
