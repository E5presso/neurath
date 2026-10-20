"""세션의 모든 태스크를 조회하고 같은 프로젝트의 선행 작업으로 시작 가능 여부를 계산한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import TaskStatus


@dataclass(frozen=True)
class GetTasksQuery(AbstractQuery):
    """전체 TODO와 실행 가능 여부를 조회할 소유 세션을 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 조회할 태스크의 소유 세션 ID.
    """

    project_id: str
    session_id: str


@dataclass(frozen=True)
class GetTasksResult:
    """세션의 전체 태스크와 시작 가능한 작업·종료·성공 여부를 반환한다.

    Attributes:
        tasks: 해당 세션의 전체 현재 태스크.
        ready_task_ids: pending·failed이며 모든 선행 작업이 성공한 태스크의 ID 목록.
        all_terminal: 목록이 비어 있지 않고 모두 succeeded·failed·invalidated인지 여부.
        all_succeeded: 목록이 비어 있지 않고 모든 태스크가 succeeded인지 여부.
    """

    tasks: Sequence[Task]
    ready_task_ids: Sequence[str]
    all_terminal: bool
    all_succeeded: bool


@UseCase(scope=Pod.Scope.CONTEXT)
class GetTasksUseCase(IAsyncQueryUseCase[GetTasksQuery, GetTasksResult]):
    """세션의 모든 태스크를 조회하고 같은 프로젝트의 선행 작업으로 시작 가능 여부를 계산한다.

    완료·실패·무효 태스크도 목록에 포함한다. all_terminal은 성공·실패·무효를,
    all_succeeded는 성공만 허용하며 빈 목록에서는 둘 다 False다.
    이 결과는 TODO 표시용 조회이며 태스크를 완료하거나 세션을 종료하지 않는다.
    """

    def __init__(self, sessions: ISessionRepository, tasks: ITaskRepository) -> None:
        """TODO 소유 세션과 프로젝트 전체의 의존 상태를 읽을 저장소를 받는다.

        Args:
            sessions: 조회할 소유 세션이 지정 프로젝트에 속하는지 확인한다.
            tasks: 전체 프로젝트의 태스크를 읽어 소유 세션 목록과 선행 성공 여부를 구성한다.
        """
        self.sessions = sessions
        self.tasks = tasks

    @override
    async def run(self, query: GetTasksQuery) -> GetTasksResult:
        """프로젝트 전체 의존 상태를 읽고 소유 세션의 TODO 조회 결과를 구성한다.

        Args:
            query: TODO를 조회할 프로젝트와 소유 세션 ID.

        Returns:
            GetTasksResult: 전체 소유 태스크, 시작 가능한 ID와 비어 있지 않은 목록의 종료·성공 판정.
        """
        (await self.sessions.get(query.session_id)).require_project(query.project_id)
        tasks = await self.tasks.list(query.project_id)
        selected = tuple(task for task in tasks if task.owner_session_id == query.session_id)
        terminal = (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.INVALIDATED)
        return GetTasksResult(
            tasks=selected,
            ready_task_ids=tuple(task.uid for task in selected if task.ready(tasks)),
            all_terminal=bool(selected) and all(task.status in terminal for task in selected),
            all_succeeded=bool(selected)
            and all(task.status is TaskStatus.SUCCEEDED for task in selected),
        )
