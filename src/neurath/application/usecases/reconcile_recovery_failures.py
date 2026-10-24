"""복구된 코어에서 독립 journal의 원 증상을 기존 장애 이력으로 멱등 연결한다."""

from collections.abc import Sequence
from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.recovery_log import IRecoveryLogService
from neurath.application.usecases.open_incident import OpenIncidentCommand, OpenIncidentUseCase
from neurath.domain.aggregates.incident import Incident


@immutable
class ReconcileRecoveryFailuresCommand(AbstractCommand):
    """원문을 다시 입력하지 않고 복원할 journal을 선택한다.

    Attributes:
        journal: 명시한 원 파일 또는 사용자 기본 journal.
    """

    journal: str | None = None


@UseCase()
class ReconcileRecoveryFailuresUseCase(
    IAsyncCommandUseCase[ReconcileRecoveryFailuresCommand, Sequence[Incident]]
):
    """원본 읽기는 트랜잭션 밖에서 수행하고 기존 사건 등록 경계를 재사용한다."""

    def __init__(self, recovery: IRecoveryLogService, open_incident: OpenIncidentUseCase) -> None:
        """독립 원문과 기존 장애 등록을 연결한다.

        Args:
            recovery: journal의 원문 읽기.
            open_incident: 같은 출처의 기존 사건 재사용과 신규 저장.
        """
        self.recovery = recovery
        self.open_incident = open_incident

    @override
    async def run(self, command: ReconcileRecoveryFailuresCommand) -> Sequence[Incident]:
        """원문 전체 형식을 검증하고 각 기록을 중복 없이 기존 Incident에 연결한다.

        Args:
            command: 복원할 원 journal 선택.

        Returns:
            Sequence[Incident]: 해결·미해결을 그대로 보존한 관련 사건.
        """
        records = self.recovery.read(command.journal)
        incidents = []
        for record in records:
            incidents.append(
                await self.open_incident.run(
                    OpenIncidentCommand(
                        symptom=record.detail,
                        origin=record.origin,
                        references=(record.reference, record.journal_reference),
                    )
                )
            )
        return tuple(incidents)
