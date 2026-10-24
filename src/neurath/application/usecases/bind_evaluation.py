"""실행 전에 평가 후보와 기존 협업 배정을 같은 phase 시도로 연결한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.get_evaluation import GetEvaluationQuery, GetEvaluationUseCase
from neurath.application.usecases.record_evaluation_binding import (
    RecordEvaluationBindingCommand,
    RecordEvaluationBindingUseCase,
)
from neurath.domain.aggregates.workflow import WorkflowRun


@immutable
class BindEvaluationCommand(AbstractCommand):
    """평가할 현재 실행과 저장된 배정을 지정한다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 실행 소유 세션.
        run_id: 기존 스킬 실행.
        phase_key: 평가 단계 이름.
        delegation_id: 준비한 실제 검토 배정.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str
    delegation_id: UUID


@UseCase()
class BindEvaluationUseCase(IAsyncCommandUseCase[BindEvaluationCommand, WorkflowRun]):
    """외부 후보 관찰을 마친 뒤 원장 변경을 짧은 트랜잭션에 반영한다."""

    def __init__(self, read: GetEvaluationUseCase, record: RecordEvaluationBindingUseCase) -> None:
        """관찰과 원자 저장의 작업 단위를 분리해 받는다.

        Args:
            read: 트랜잭션 밖에서 현재 파일·Git 후보를 관찰한다.
            record: 관찰 중 관련 원장이 바뀌지 않았는지 확인하고 저장한다.
        """
        self.read = read
        self.record = record

    @override
    async def run(self, command: BindEvaluationCommand) -> WorkflowRun:
        """현재 후보를 관찰한 뒤 같은 요구 개정에만 변경을 반영한다.

        Args:
            command: 요청 범위와 실제 보고 또는 연결 정보.

        Returns:
            WorkflowRun: 원자적으로 반영한 현재 원장.
        """
        snapshot = await self.read.run(
            GetEvaluationQuery(
                project_id=command.project_id,
                session_id=command.session_id,
                run_id=command.run_id,
                phase_key=command.phase_key,
            )
        )
        return await self.record.run(
            RecordEvaluationBindingCommand(
                project_id=command.project_id,
                session_id=command.session_id,
                run_id=command.run_id,
                phase_key=command.phase_key,
                delegation_id=command.delegation_id,
                observed=snapshot.context,
                run_version=snapshot.run.version,
            )
        )
