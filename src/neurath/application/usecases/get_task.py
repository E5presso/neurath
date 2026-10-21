"""지정한 소유 세션의 태스크 한 건과 보존된 이력을 조회한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class GetTaskQuery(AbstractQuery):
    """소유 프로젝트·세션 안에서 상세 조회할 태스크를 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 조회할 태스크의 소유 세션 ID.
        task_id: 현재 상태와 전체 이력을 조회할 태스크 ID.
    """

    project_id: str
    session_id: str
    task_id: str


@dataclass(frozen=True)
class GetTaskResult:
    """조회한 태스크의 현재 상태와 전체 요구·시도·대기 이력을 반환한다.

    Attributes:
        task: 저장된 현재 요구와 모든 시도·대기 기록을 가진 태스크.
    """

    task: Task


@UseCase()
class GetTaskUseCase(IAsyncQueryUseCase[GetTaskQuery, GetTaskResult]):
    """지정한 소유 세션의 태스크 한 건과 보존된 이력을 조회한다.

    프로젝트 또는 소유 세션이 다르면 ContextNotFound가 발생한다.
    조회는 작업 상태나 소유권을 변경하지 않는다.
    """

    def __init__(self, tasks: ITaskRepository) -> None:
        """상세 조회할 태스크를 읽는 저장소를 받는다.

        Args:
            tasks: 태스크 ID로 현재 상태와 소유 이력을 조회한다.
        """
        self.tasks = tasks

    @transactional
    @override
    async def run(self, query: GetTaskQuery) -> GetTaskResult:
        """태스크의 소유 범위를 확인하고 현재 상태와 이력을 반환한다.

        Args:
            query: 조회할 태스크 ID와 그 태스크가 속해야 하는 프로젝트·소유 세션.

        Returns:
            GetTaskResult: 저장된 현재 요구와 모든 시도·대기 기록을 가진 태스크.
        """
        task = await self.tasks.get(query.task_id)
        task.require_scope(query.project_id, query.session_id)
        return GetTaskResult(task=task)
