"""사용자가 요청하고 독립 평가한 회고에서만 지속 교훈 후보를 저장한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.get_evaluation import GetEvaluationQuery, GetEvaluationUseCase
from neurath.application.usecases.save_lesson import SaveLessonCommand, SaveLessonUseCase
from neurath.domain.aggregates.memory import Memory


@immutable
class CreateLessonCommand(AbstractCommand):
    """요청된 회고와 관련된 개선 후보·적용 범위의 원문을 지정한다.

    Attributes:
        project_id: 회고 프로젝트.
        session_id: 회고 소유 세션.
        run_id: 실제 회고를 수행한 기존 실행.
        phase_key: 독립 회고 평가 단계.
        content: 원인·개선 후보·적용 범위를 명시한 본문.
        references: 실제 사용자 요청·문제·검토의 근거.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str
    content: str
    references: Sequence[str]


@UseCase()
class CreateLessonUseCase(IAsyncCommandUseCase[CreateLessonCommand, Memory]):
    """외부 후보 관찰을 마친 뒤 원장 변경을 짧은 트랜잭션에 반영한다."""

    def __init__(self, read: GetEvaluationUseCase, record: SaveLessonUseCase) -> None:
        """관찰과 원자 저장의 작업 단위를 분리해 받는다.

        Args:
            read: 트랜잭션 밖에서 현재 파일·Git 후보를 관찰한다.
            record: 관찰 중 관련 원장이 바뀌지 않았는지 확인하고 저장한다.
        """
        self.read = read
        self.record = record

    @override
    async def run(self, command: CreateLessonCommand) -> Memory:
        """현재 후보를 관찰한 뒤 같은 요구 개정에만 변경을 반영한다.

        Args:
            command: 요청 범위와 실제 보고 또는 연결 정보.

        Returns:
            Memory: 원자적으로 반영한 현재 원장.
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
            SaveLessonCommand(
                project_id=command.project_id,
                session_id=command.session_id,
                run_id=command.run_id,
                phase_key=command.phase_key,
                content=command.content,
                references=command.references,
                observed=snapshot.context,
                run_version=snapshot.run.version,
            )
        )
