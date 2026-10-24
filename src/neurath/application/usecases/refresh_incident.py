"""장애를 실제로 다시 진단한 결과를 원래 확인 이력에 추가한다."""

import json
from dataclasses import asdict
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.diagnose import DiagnoseQuery, DiagnoseUseCase
from neurath.application.usecases.get_incident import GetIncidentQuery, GetIncidentUseCase
from neurath.application.usecases.record_incident_evidence import (
    RecordIncidentEvidenceCommand,
    RecordIncidentEvidenceUseCase,
)
from neurath.domain.aggregates.incident import Incident
from neurath.domain.enums.incident_evidence_kind import IncidentEvidenceKind
from neurath.domain.values.incident_evidence import IncidentEvidence


@immutable
class RefreshIncidentCommand(AbstractCommand):
    """다시 관찰할 장애와 실제 진단 대상을 지정한다.

    Attributes:
        incident_id: 조회하거나 변경할 원 장애 식별자.
        revision: 호출자가 조회한 낙관적 개정.
        query: 이번 재관찰의 파일·폴더·호스트 선택.
    """

    incident_id: UUID
    revision: int
    query: DiagnoseQuery


@UseCase()
class RefreshIncidentUseCase(IAsyncCommandUseCase[RefreshIncidentCommand, Incident]):
    """조회·재관찰·근거 저장을 조정하며 재관찰을 해결로 바꾸지 않는다."""

    def __init__(
        self,
        get: GetIncidentUseCase,
        diagnose: DiagnoseUseCase,
        record: RecordIncidentEvidenceUseCase,
    ) -> None:
        """각 요청의 트랜잭션과 실제 진단을 담당할 유스케이스를 받는다.

        Args:
            get: 사건의 존재와 현재 개정 확인.
            diagnose: 쓰기 잠금 없이 실제 재관찰.
            record: 재관찰 결과를 새 트랜잭션에서 저장.
        """
        self.get = get
        self.diagnose = diagnose
        self.record = record

    @override
    async def run(self, command: RefreshIncidentCommand) -> Incident:
        """현재 장애를 확인하고 실제 관찰한 항목별 결과만 추가한다.

        Args:
            command: 기대 개정과 진단 대상.

        Returns:
            Incident: 이전 증상을 유지한 재관찰 이력.
        """
        incident = await self.get.run(GetIncidentQuery(incident_id=command.incident_id))
        incident.require_revision(command.revision)
        findings = await self.diagnose.run(command.query)
        return await self.record.run(
            RecordIncidentEvidenceCommand(
                incident_id=incident.uid,
                revision=command.revision,
                evidence=IncidentEvidence(
                    kind=IncidentEvidenceKind.OBSERVATION,
                    detail=json.dumps([asdict(item) for item in findings], ensure_ascii=False),
                    references=(f"diagnose:{command.query}",),
                ),
            )
        )
