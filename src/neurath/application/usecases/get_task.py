"""GetTask 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IQueryUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class GetTaskQuery(AbstractQuery):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
        task_id: 대상 태스크.
    """

    project_id: str
    session_id: str
    task_id: str


@dataclass(frozen=True)
class GetTaskResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        task: 처리하거나 조회한 태스크와 보존된 전체 이력.
    """

    task: Task


@UseCase()
class GetTaskUseCase(IQueryUseCase[GetTaskQuery, GetTaskResult]):
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, tasks: ITaskRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            tasks: 요청에 속하는 tasks 저장소.
        """
        self.tasks = tasks

    @override
    def run(self, query: GetTaskQuery) -> GetTaskResult:
        """명시한 요청을 적용하고 결과를 반환한다.

        Args:
            query: 원문·범위·관찰에 연결된 입력.

        Returns:
            GetTaskResult: 처리한 원장과 현재 상태.
        """
        task = self.tasks.get(query.task_id)
        task.require_scope(query.project_id, query.session_id)
        return GetTaskResult(task=task)
