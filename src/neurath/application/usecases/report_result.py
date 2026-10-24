"""시도의 관찰 결과를 확정하고 현재 요구 개정의 결과만 태스크 상태에 반영한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.get_evaluation import GetEvaluationQuery, GetEvaluationUseCase
from neurath.application.usecases.read_result_context import (
    ReadResultContextQuery,
    ReadResultContextUseCase,
)
from neurath.application.usecases.record_task_result import (
    RecordTaskResultCommand,
    RecordTaskResultUseCase,
)
from neurath.domain.aggregates.task import Task
from neurath.domain.values.task_attempt import Outcome, TaskResult


@immutable
class ReportResultCommand(AbstractCommand):
    """실행 시도에 확정할 관찰 결과와 태스크의 저장 revision을 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 시도의 관찰 결과를 확정할 태스크 ID.
        expected_revision: 읽은 Task.revision. 동일하게 확정된 결과의 재보고에는 재검사하지 않는다.
        attempt_number: 확정할 시도 번호. 정정 전 시도의 늦은 결과도 지정할 수 있다.
        result: 성공·실패·부분 수행과 관찰 참조·남은 일을 담은 결과.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    expected_revision: int
    attempt_number: int
    result: TaskResult


@immutable
class ReportResult:
    """확정 결과와 그 결과가 반영된 현재 상태를 가진 태스크를 반환한다.

    Attributes:
        task: 시도 결과와 현재 요구의 상태를 보존한 태스크.
    """

    task: Task


@UseCase()
class ReportResultUseCase(IAsyncCommandUseCase[ReportResultCommand, ReportResult]):
    """최종 평가의 외부 후보를 관찰한 뒤 짧은 원장 변경으로 결과를 기록한다."""

    def __init__(
        self,
        read: ReadResultContextUseCase,
        evaluations: GetEvaluationUseCase,
        record: RecordTaskResultUseCase,
    ) -> None:
        """실제 조회·외부 관찰·원자 저장 경계를 받는다.

        Args:
            read: 결과를 보고할 작업과 절차의 스냅샷.
            evaluations: 파일·Git 관찰이 트랜잭션 밖에서 수행되는 평가 조회.
            record: 현재 원장과 스냅샷을 대조하는 최종 저장.
        """
        self.read = read
        self.evaluations = evaluations
        self.record = record

    @override
    async def run(self, command: ReportResultCommand) -> ReportResult:
        """작업 완료를 외부 관찰의 잠금과 분리해 원자적으로 기록한다.

        Args:
            command: 원래 작업과 시도의 관찰 결과.

        Returns:
            ReportResult: 현재 요구에 적용한 태스크 결과.
        """
        snapshot = await self.read.run(
            ReadResultContextQuery(
                project_id=command.project_id,
                session_id=command.session_id,
                task_id=command.task_id,
            )
        )
        evaluations = []
        workflow = snapshot.workflow
        attempt = snapshot.task.attempt(command.attempt_number)
        if (
            workflow is not None
            and command.result.outcome is Outcome.SUCCEEDED
            and attempt.result is None
            and attempt.definition_number == snapshot.task.definition.number
        ):
            for phase in workflow.definition.phases:
                if not workflow.requires_evaluation(phase) or workflow.latest(phase) is None:
                    continue
                current = await self.evaluations.run(
                    GetEvaluationQuery(
                        project_id=command.project_id,
                        session_id=command.session_id,
                        run_id=workflow.uid,
                        phase_key=phase.key,
                    )
                )
                evaluations.append((phase.key, current.context))
        result = await self.record.run(
            RecordTaskResultCommand(
                project_id=command.project_id,
                session_id=command.session_id,
                task_id=command.task_id,
                expected_revision=command.expected_revision,
                attempt_number=command.attempt_number,
                result=command.result,
                workflow_version=None if workflow is None else workflow.version,
                evaluations=evaluations,
            )
        )
        return ReportResult(task=result.task)
