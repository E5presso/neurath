"""CreateTask 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from dataclasses import dataclass

from spakky.core.stereotype.usecase import UseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.task_context import TaskContext
from neurath.domain.aggregates.task import Task, validate_dependencies
from neurath.domain.errors import ContextNotFound


@dataclass(frozen=True)
class CreateTaskCommand:
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
        source_id: 기존 원문 참조.
        title: 수행할 일.
        required_result: 달성할 결과.
        dependencies: 실제 선행 작업들.
        follow_up_of: 원래 미달 요구의 작업.
    """

    project_id: str
    session_id: str
    source_id: str
    title: str
    required_result: str
    dependencies: tuple[str, ...] = ()
    follow_up_of: str | None = None


@UseCase()
class CreateTaskUseCase:
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(
        self,
        sessions: ISessionRepository,
        sources: IRequestSourceRepository,
        tasks: ITaskRepository,
    ) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            sessions: 요청에 속하는 sessions 저장소.
            sources: 요청에 속하는 sources 저장소.
            tasks: 요청에 속하는 tasks 저장소.
        """
        self.sessions = sessions
        self.sources = sources
        self.tasks = tasks

    def execute(self, request: CreateTaskCommand) -> TaskContext:
        """명시한 요청을 적용하고 불변 결과를 반환한다.

        Args:
            request: 원문·범위·관찰에 연결된 입력.

        Returns:
            TaskContext: 현재 상태를 나타내는 불변 결과.

        Raises:
            ContextNotFound: 후속 작업의 원래 태스크가 다른 프로젝트에 속하는 경우.
        """
        self.sessions.get(request.session_id).require_project(request.project_id)
        source = self.sources.get(request.source_id)
        task = Task.create(
            request.project_id,
            request.session_id,
            source,
            request.title,
            request.required_result,
            request.dependencies,
            request.follow_up_of,
        )
        validate_dependencies(
            self.tasks.list(request.project_id), task.uid, task.definition.dependencies
        )
        if request.follow_up_of is not None:
            parent = self.tasks.get(request.follow_up_of)
            if parent.project_id != request.project_id:
                raise ContextNotFound("Follow-up task belongs to another project")
        return TaskContext.from_entity(self.tasks.save(task))
