"""현재 요구에 대한 정정으로 태스크를 invalidated 상태로 바꾼다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class InvalidateTaskCommand(AbstractCommand):
    """현재 요구를 무효화하는 정정 출처와 취소 사유를 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 현재 요구를 무효화할 태스크 ID.
        expected_revision: 수정 전에 읽은 Task.revision. 요구 개정 번호와는 별개다.
        source_id: 현재 요구의 source_id를 정정 대상으로 가리키는 출처 ID.
        reason: 요구를 무효화하는 이유. 공백만 있는 값은 허용하지 않는다.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    source_id: str
    reason: str


@dataclass(frozen=True)
class InvalidateTaskResult:
    """무효화 사유와 기존 요구·시도를 보존한 태스크를 반환한다.

    Attributes:
        task: invalidated 상태와 정정 개정·사유가 기록된 태스크.
    """

    task: Task


@UseCase()
class InvalidateTaskUseCase(IAsyncCommandUseCase[InvalidateTaskCommand, InvalidateTaskResult]):
    """현재 요구에 대한 정정으로 태스크를 invalidated 상태로 바꾼다.

    정정 출처를 새 요구 개정에 연결하고 현재 시도 연결을 해제하되 과거 이력은 보존한다.
    같은 프로젝트의 현재 요구를 정정하는 출처와 비어 있지 않은 이유가 필요하다.
    원장의 무효화이며 외부 프로세스 중단을 수행하지 않는다.
    """

    def __init__(self, tasks: ITaskRepository, sources: IRequestSourceRepository) -> None:
        """무효화 대상과 정정 원문을 읽고 변경을 저장할 포트를 받는다.

        Args:
            tasks: 무효화 대상의 현재 요구를 조회하고 무효화 개정·사유를 저장한다.
            sources: 현재 요구를 정정하는 취소·범위 변경 원문을 조회한다.
        """
        self.tasks = tasks
        self.sources = sources

    @transactional
    @override
    async def run(self, command: InvalidateTaskCommand) -> InvalidateTaskResult:
        """소유 범위와 revision을 확인하고 정정 출처·무효화 사유를 저장한다.

        Args:
            command: 무효화할 태스크, 읽은 revision, 현재 요구의 정정 출처와 이유.

        Returns:
            InvalidateTaskResult: invalidated 상태와 정정 개정·사유가 기록된 태스크.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.invalidate((await self.sources.get(command.source_id)), command.reason)
        return InvalidateTaskResult(task=(await self.tasks.save(task)))
