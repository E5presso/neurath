"""waiting 태스크의 마지막 대기를 해소하고 같은 시도를 active로 되돌린다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class ResumeTaskCommand(AbstractCommand):
    """외부 대기가 해소된 태스크와 해소 관찰을 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 외부 대기를 해소하고 같은 시도를 재개할 태스크 ID.
        expected_revision: 수정 전에 읽은 Task.revision. 요구 개정 번호와는 별개다.
        resolution: 마지막 외부 대기를 해소한 관찰 내용 또는 참조. 공백만 있는 값은 거부한다.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    resolution: str


@dataclass(frozen=True)
class ResumeTaskResult:
    """마지막 대기의 해소 기록과 같은 실행 시도를 유지한 활성 태스크를 반환한다.

    Attributes:
        task: 마지막 대기에 resolution이 기록된 active 태스크.
    """

    task: Task


@UseCase()
class ResumeTaskUseCase(IAsyncCommandUseCase[ResumeTaskCommand, ResumeTaskResult]):
    """waiting 태스크의 마지막 대기를 해소하고 같은 시도를 active로 되돌린다.

    해소 관찰은 비어 있지 않아야 한다. 새 시도를 만들거나 외부 실행을 다시
    제출하지 않으며, 대기하지 않는 태스크의 재개는 거부한다.
    """

    def __init__(self, tasks: ITaskRepository) -> None:
        """외부 대기와 재개 상태를 조회·저장할 포트를 받는다.

        Args:
            tasks: 대기 중인 태스크를 조회하고 해소 관찰·활성 상태를 저장한다.
        """
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: ResumeTaskCommand) -> ResumeTaskResult:
        """소유 범위·revision·대기 상태를 확인하고 해소 관찰을 저장한다.

        Args:
            command: 재개할 태스크, 읽은 revision과 외부 의존이 해소됐다는 관찰.

        Returns:
            ResumeTaskResult: 마지막 대기에 resolution이 기록된 active 태스크.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.resume(command.resolution)
        return ResumeTaskResult(task=(await self.tasks.save(task)))
