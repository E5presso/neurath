"""GetTasks 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IQueryUseCase

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import TaskStatus


@dataclass(frozen=True)
class GetTasksQuery(AbstractQuery):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
    """

    project_id: str
    session_id: str


@dataclass(frozen=True)
class GetTasksResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        tasks: 해당 세션의 전체 현재 태스크.
        ready_task_ids: 독립적으로 시작 가능한 태스크 식별자.
        all_terminal: 비어 있지 않은 목록의 모든 작업이 종료 상태인지 여부.
        all_succeeded: 비어 있지 않은 목록의 모든 요구가 성공했는지 여부.
    """

    tasks: Sequence[Task]
    ready_task_ids: Sequence[str]
    all_terminal: bool
    all_succeeded: bool


@UseCase()
class GetTasksUseCase(IQueryUseCase[GetTasksQuery, GetTasksResult]):
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, sessions: ISessionRepository, tasks: ITaskRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            sessions: 요청에 속하는 sessions 저장소.
            tasks: 요청에 속하는 tasks 저장소.
        """
        self.sessions = sessions
        self.tasks = tasks

    @override
    def run(self, query: GetTasksQuery) -> GetTasksResult:
        """명시한 요청을 적용하고 결과를 반환한다.

        Args:
            query: 원문·범위·관찰에 연결된 입력.

        Returns:
            GetTasksResult: 처리한 원장과 현재 상태.
        """
        self.sessions.get(query.session_id).require_project(query.project_id)
        tasks = self.tasks.list(query.project_id)
        selected = tuple(task for task in tasks if task.owner_session_id == query.session_id)
        terminal = (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.INVALIDATED)
        return GetTasksResult(
            tasks=selected,
            ready_task_ids=tuple(task.uid for task in selected if task.ready(tasks)),
            all_terminal=bool(selected) and all(task.status in terminal for task in selected),
            all_succeeded=bool(selected)
            and all(task.status is TaskStatus.SUCCEEDED for task in selected),
        )
