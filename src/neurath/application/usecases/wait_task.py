"""active 태스크에 해소되지 않은 외부 대기를 추가하고 waiting으로 바꾼다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import ExternalWait


@dataclass(frozen=True)
class WaitTaskCommand(AbstractCommand):
    """활성 태스크가 기다릴 외부 대상·해소 조건·후속 범위를 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 현재 시도를 외부 의존 대기로 전환할 태스크 ID.
        expected_revision: 수정 전에 읽은 Task.revision. 요구 개정 번호와는 별개다.
        condition: 대상·해소 조건·후속 범위·관찰을 가진 대기 값. resolution은 None이어야 한다.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    condition: ExternalWait


@dataclass(frozen=True)
class WaitTaskResult:
    """외부 대기가 추가되고 현재 실행 시도를 유지한 대기 태스크를 반환한다.

    Attributes:
        task: 대기 이력이 추가된 waiting 태스크.
    """

    task: Task


@UseCase()
class WaitTaskUseCase(IAsyncCommandUseCase[WaitTaskCommand, WaitTaskResult]):
    """active 태스크에 해소되지 않은 외부 대기를 추가하고 waiting으로 바꾼다.

    대상·해소 조건·후속 범위·관찰이 필요하며 이미 resolution이 있는 대기는 거부한다.
    대기 정보를 저장할 뿐 외부 상태를 조회하거나 감시 작업을 시작하지 않는다.
    """

    def __init__(self, tasks: ITaskRepository) -> None:
        """활성 태스크에 외부 대기를 추가할 저장소를 받는다.

        Args:
            tasks: 현재 활성 태스크를 조회하고 대기 이력·waiting 상태를 저장한다.
        """
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: WaitTaskCommand) -> WaitTaskResult:
        """소유 범위·revision·활성 상태를 확인하고 외부 대기 조건을 저장한다.

        Args:
            command: 대기할 태스크, 읽은 revision과 아직 해소되지 않은 외부 의존.

        Returns:
            WaitTaskResult: 대기 이력이 추가된 waiting 태스크.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.wait(command.condition)
        return WaitTaskResult(task=(await self.tasks.save(task)))
