"""미해결 장애를 이관하고 대상·사유를 남긴다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.domain.aggregates.incident import Incident


@immutable
class EscalateIncidentCommand(AbstractCommand):
    """조회한 장애의 개정과 이번 변경의 근거를 전달한다.

    Attributes:
        incident_id: 조회하거나 변경할 원 장애 식별자.
        revision: 호출자가 조회한 낙관적 개정.
        destination: 미해결 이관의 대상과 사유.
    """

    incident_id: UUID
    revision: int
    destination: str


@UseCase()
class EscalateIncidentUseCase(IAsyncCommandUseCase[EscalateIncidentCommand, Incident]):
    """미해결 장애를 이관하고 대상·사유를 남긴다."""

    def __init__(self, incidents: IIncidentRepository) -> None:
        """변경 대상 장애의 저장 계약을 받는다.

        Args:
            incidents: 기존 근거와 현재 개정을 보존하는 저장소.
        """
        self.incidents = incidents

    @transactional
    @override
    async def run(self, command: EscalateIncidentCommand) -> Incident:
        """최신 개정을 확인하고 도메인이 검증한 변경만 원자적으로 저장한다.

        Args:
            command: 조회한 개정과 변경 근거.

        Returns:
            Incident: 기존 이력을 보존한 현재 장애.
        """
        incident = await self.incidents.get(command.incident_id)
        incident.require_revision(command.revision)
        incident.escalate(command.destination)
        return await self.incidents.save(incident)
