"""GetTasks 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IQueryUseCase

from neurath.application.dto.task import TaskBoardDTO
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository


@dataclass(frozen=True)
class GetTasksQuery(AbstractQuery):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
    """

    project_id: str
    session_id: str


@UseCase()
class GetTasksUseCase(IQueryUseCase[GetTasksQuery, TaskBoardDTO]):
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
    def run(self, query: GetTasksQuery) -> TaskBoardDTO:
        """명시한 요청을 적용하고 불변 결과를 반환한다.

        Args:
            query: 원문·범위·관찰에 연결된 입력.

        Returns:
            TaskBoardDTO: 현재 상태를 나타내는 불변 결과.
        """
        self.sessions.get(query.session_id).require_project(query.project_id)
        return TaskBoardDTO.from_entities(self.tasks.list(query.project_id), query.session_id)
