"""같은 프로젝트의 원문을 재사용하여 소유 세션의 새 태스크를 등록한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class CreateTaskCommand(AbstractCommand):
    """보존한 원문에 연결할 새 작업의 목표·선행 작업·소유 세션을 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        source_id: 태스크 목표의 근거로 재사용할 같은 프로젝트의 원문 ID.
        title: TODO에서 수행할 일을 식별할 제목.
        required_result: 이 작업으로 달성해야 할 구체적인 결과.
        dependencies: 시작 전에 성공해야 하는 같은 프로젝트의 태스크 ID 목록.
        follow_up_of: 미달 요구를 이어받는 원래 태스크 ID. 독립 작업이면 None.
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
    """최초 요구 개정이 연결된 새 pending 태스크를 반환한다.

    Attributes:
        task: 새 uid와 첫 요구 개정을 가진 pending 태스크.
    """

    task: Task


@UseCase()
class CreateTaskUseCase(IAsyncCommandUseCase[CreateTaskCommand, CreateTaskResult]):
    """같은 프로젝트의 원문을 재사용하여 소유 세션의 새 태스크를 등록한다.

    상태 질문·요약은 목표 출처로 쓰지 않으며 선행 작업의 존재·중복·순환을 확인한다.
    후속 작업이면 원래 태스크의 프로젝트도 확인한다. 최초 정의만 저장하며
    실행 시도를 시작하거나 외부 작업을 제출하지 않는다.
    """

    def __init__(
        self,
        sessions: ISessionRepository,
        sources: IRequestSourceRepository,
        tasks: ITaskRepository,
    ) -> None:
        """새 작업의 세션·원문·의존 범위를 확인하고 저장할 포트를 받는다.

        Args:
            sessions: 새 작업을 소유할 세션의 프로젝트 소속을 확인한다.
            sources: 목표의 근거로 연결할 기존 원문을 조회한다.
            tasks: 선행·후속 관계의 대상을 조회하고 새 태스크를 저장한다.
        """
        self.sessions = sessions
        self.sources = sources
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: CreateTaskCommand) -> CreateTaskResult:
        """세션·출처·의존 범위를 확인하고 최초 정의를 가진 태스크를 저장한다.

        Args:
            command: 새 태스크의 소유 범위, 원문 ID, 제목·달성 결과와 선택적 선행·후속 관계.

        Returns:
            CreateTaskResult: 새 uid와 첫 요구 개정을 가진 pending 태스크.
        """
        (await self.sessions.get(command.session_id)).require_project(command.project_id)
        source = await self.sources.get(command.source_id)
        task = Task.create(
            command.project_id,
            command.session_id,
            source,
            command.title,
            command.required_result,
            command.dependencies,
            command.follow_up_of,
        )
        task.validate_dependencies(await self.tasks.list(command.project_id))
        if command.follow_up_of is not None:
            parent = await self.tasks.get(command.follow_up_of)
            parent.require_project(command.project_id)
        return CreateTaskResult(task=(await self.tasks.save(task)))
