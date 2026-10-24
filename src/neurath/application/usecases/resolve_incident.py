"""순서가 맞는 재현·수정·회귀 성공 근거로 장애를 해결한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.domain.aggregates.incident import Incident


@immutable
class ResolveIncidentCommand(AbstractCommand):
    """조회한 장애의 개정과 이번 변경의 근거를 전달한다.

    Attributes:
        incident_id: 조회하거나 변경할 원 장애 식별자.
        revision: 호출자가 조회한 낙관적 개정.
        explanation: 실제 해결을 설명하는 본문.
    """

    incident_id: UUID
    revision: int
    explanation: str


@UseCase()
class ResolveIncidentUseCase(IAsyncCommandUseCase[ResolveIncidentCommand, Incident]):
    """순서가 맞는 재현·수정·회귀 성공 근거로 장애를 해결한다."""

    def __init__(self, incidents: IIncidentRepository) -> None:
        """변경 대상 장애의 저장 계약을 받는다.

        Args:
            incidents: 기존 근거와 현재 개정을 보존하는 저장소.
        """
        self.incidents = incidents

    @transactional
    @override
    async def run(self, command: ResolveIncidentCommand) -> Incident:
        """최신 개정을 확인하고 도메인이 검증한 변경만 원자적으로 저장한다.

        Args:
            command: 조회한 개정과 변경 근거.

        Returns:
            Incident: 기존 이력을 보존한 현재 장애.
        """
        incident = await self.incidents.get(command.incident_id)
        incident.require_revision(command.revision)
        incident.resolve(command.explanation)
        return await self.incidents.save(incident)
