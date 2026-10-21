"""pending 또는 failed 태스크에 현재 요구를 기준으로 새 시도를 만든다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class StartTaskCommand(AbstractCommand):
    """새 실행 시도를 시작할 태스크와 읽은 저장 revision을 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 현재 요구에 새 실행 시도를 만들 태스크 ID.
        expected_revision: 수정 전에 읽은 Task.revision. 요구 개정 번호와는 별개다.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int


@dataclass(frozen=True)
class StartTaskResult:
    """현재 요구 개정에 새 실행 시도가 연결된 활성 태스크를 반환한다.

    Attributes:
        task: 이전 시도를 보존하고 새 시도가 추가된 active 태스크.
    """

    task: Task


@UseCase()
class StartTaskUseCase(IAsyncCommandUseCase[StartTaskCommand, StartTaskResult]):
    """pending 또는 failed 태스크에 현재 요구를 기준으로 새 시도를 만든다.

    같은 프로젝트의 모든 선행 작업이 성공해야 하며 이미 active·waiting인 작업은
    다시 시작하지 않는다. 원장에 시도를 기록하는 동작이며 외부 명령을 실행하지 않는다.
    """

    def __init__(self, tasks: ITaskRepository) -> None:
        """태스크와 선행 작업의 상태를 조회하고 새 시도를 저장할 포트를 받는다.

        Args:
            tasks: 시작 대상·선행 작업을 조회하고 활성화된 태스크의 새 시도를 저장한다.
        """
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: StartTaskCommand) -> StartTaskResult:
        """소유 범위·revision·선행 성공을 확인하고 새 시도를 가진 태스크를 저장한다.

        Args:
            command: 시작할 태스크의 소유 범위와 읽은 저장 revision.

        Returns:
            StartTaskResult: 이전 시도를 보존하고 새 시도가 추가된 active 태스크.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.start(await self.tasks.list(command.project_id))
        return StartTaskResult(task=(await self.tasks.save(task)))
