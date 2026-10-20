"""CreateTask 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class CreateTaskCommand(AbstractCommand):
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
    dependencies: Sequence[str] = ()
    follow_up_of: str | None = None


@dataclass(frozen=True)
class CreateTaskResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        task: 처리하거나 조회한 태스크와 보존된 전체 이력.
    """

    task: Task


@UseCase()
class CreateTaskUseCase(ICommandUseCase[CreateTaskCommand, CreateTaskResult]):
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

    @override
    def run(self, command: CreateTaskCommand) -> CreateTaskResult:
        """명시한 요청을 적용하고 결과를 반환한다.

        Args:
            command: 원문·범위·관찰에 연결된 입력.

        Returns:
            CreateTaskResult: 처리한 원장과 현재 상태.
        """
        self.sessions.get(command.session_id).require_project(command.project_id)
        source = self.sources.get(command.source_id)
        task = Task.create(
            command.project_id,
            command.session_id,
            source,
            command.title,
            command.required_result,
            command.dependencies,
            command.follow_up_of,
        )
        task.validate_dependencies(self.tasks.list(command.project_id))
        if command.follow_up_of is not None:
            parent = self.tasks.get(command.follow_up_of)
            parent.require_project(command.project_id)
        return CreateTaskResult(task=self.tasks.save(task))
