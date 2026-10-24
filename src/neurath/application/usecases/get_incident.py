"""장애의 원 증상·확인 이력·이관과 대체 관계를 변경 없이 조회한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.domain.aggregates.incident import Incident


@immutable
class GetIncidentQuery(AbstractQuery):
    """실제 식별자로 조회할 장애를 선택한다.

    Attributes:
        incident_id: 조회하거나 변경할 원 장애 식별자.
    """

    incident_id: UUID


@UseCase()
class GetIncidentUseCase(IAsyncQueryUseCase[GetIncidentQuery, Incident]):
    """없는 자료를 정상 빈 상태로 숨기지 않는 장애 조회다."""

    def __init__(self, incidents: IIncidentRepository) -> None:
        """장애와 그 소유 근거를 조회할 계약을 받는다.

        Args:
            incidents: 저장된 장애 조회.
        """
        self.incidents = incidents

    @transactional
    @override
    async def run(self, query: GetIncidentQuery) -> Incident:
        """장애를 읽고 이관·대체를 실제 해결과 구분해 반환한다.

        Args:
            query: 조회할 사건의 실제 ID.

        Returns:
            Incident: 원래 출처와 전체 이력.
        """
        return await self.incidents.get(query.incident_id)
