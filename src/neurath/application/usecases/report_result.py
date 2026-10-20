"""시도의 관찰 결과를 확정하고 현재 요구 개정의 결과만 태스크 상태에 반영한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import Outcome, TaskResult


@dataclass(frozen=True)
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

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    attempt_number: int
    result: TaskResult


@dataclass(frozen=True)
class ReportResult:
    """확정 결과와 그 결과가 반영된 현재 상태를 가진 태스크를 반환한다.

    Attributes:
        task: 시도 결과와 현재 요구의 상태를 보존한 태스크.
    """

    task: Task


@UseCase(scope=Pod.Scope.CONTEXT)
class ReportResultUseCase(IAsyncCommandUseCase[ReportResultCommand, ReportResult]):
    """시도의 관찰 결과를 확정하고 현재 요구 개정의 결과만 태스크 상태에 반영한다.

    성공은 succeeded, 실패는 failed, 부분 수행은 pending이 된다. 정정 전 시도의
    늦은 결과는 이력에만 남는다. 같은 확정 결과의 재보고는 revision이 오래돼도
    멱등적으로 처리하지만, 다른 결과로 덮어쓰는 보고는 거부한다.
    관찰 참조는 전달받아 저장하며 외부 명령 실행이나 증거 인증을 수행하지 않는다.
    """

    def __init__(self, tasks: ITaskRepository, workflows: IWorkflowRepository) -> None:
        """시도의 관찰 결과와 태스크 상태를 저장할 포트를 받는다.

        Args:
            tasks: 결과를 보고할 태스크를 조회하고 확정 결과·상태를 함께 저장한다.
            workflows: 선택한 절차가 현재 요구를 완료했는지 확인할 저장소.
        """
        self.tasks = tasks
        self.workflows = workflows

    @override
    async def run(self, command: ReportResultCommand) -> ReportResult:
        """시도의 결과를 기록하고 현재 요구에 적용되는 상태 변경을 저장한다.

        Args:
            command: 소유 범위·태스크 ID·시도 번호, 관찰 결과와 읽은 저장 revision.

        Returns:
            ReportResult: 시도 결과와 현재 요구의 상태를 보존한 태스크.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        attempt = task.attempt(command.attempt_number)
        workflow = None
        if (
            command.result.outcome is Outcome.SUCCEEDED
            and attempt.definition_number == task.definition.number
            and attempt.result is None
        ):
            workflow = await self.workflows.find_by_task(task.uid)
        if workflow is not None:
            workflow.require_complete(task.definition.number)
        task.report(command.attempt_number, command.result, command.expected_revision)
        return ReportResult(task=(await self.tasks.save(task)))
