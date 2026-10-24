"""원래 증상과 출처를 보존한 장애를 등록한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.incident import IIncidentRepository
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.incident import Incident


@immutable
class OpenIncidentCommand(AbstractCommand):
    """장애의 첫 증상·출처와 선택적 프로젝트를 전달한다.

    Attributes:
        symptom: 처음 관찰한 증상 원문.
        references: 원문과 실행 결과로 돌아갈 출처 목록.
        project_id: 관련 프로젝트의 외래 키이며 전역 장애는 None.
        origin: journal에서 복원한 원문 출처이며 새 사건은 None.
    """

    symptom: str
    references: Sequence[str]
    project_id: UUID | None = None
    origin: str | None = None


@UseCase()
class OpenIncidentUseCase(IAsyncCommandUseCase[OpenIncidentCommand, Incident]):
    """존재하는 프로젝트 또는 전역 장애에 원 증상을 등록한다."""

    def __init__(self, incidents: IIncidentRepository, projects: IProjectRepository) -> None:
        """장애 저장과 관련 프로젝트 확인 계약을 받는다.

        Args:
            incidents: 원래 증상을 저장할 저장소.
            projects: 선택한 프로젝트 존재 확인.
        """
        self.incidents = incidents
        self.projects = projects

    @transactional
    @override
    async def run(self, command: OpenIncidentCommand) -> Incident:
        """프로젝트가 실제로 있음을 확인하고 미해결 장애를 저장한다.

        Args:
            command: 증상 원문·근거·선택 프로젝트.

        Returns:
            Incident: 원 작업 상태와 독립적인 장애 기록.
        """
        if command.origin is not None:
            existing = await self.incidents.find_by_origin(command.origin)
            if existing is not None:
                return existing
        if command.project_id is not None:
            await self.projects.get(command.project_id)
        return await self.incidents.save(
            Incident.create(
                command.project_id,
                command.symptom,
                command.references
                if command.origin is None
                else (command.origin, *command.references),
            )
        )
