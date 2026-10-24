"""현재 호스트의 보존된 원문에 작업을 연결하고 필요한 경우 같은 요청에서 시작한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.create_task import CreateTaskCommand, CreateTaskUseCase
from neurath.application.usecases.get_sources import GetSourcesQuery, GetSourcesUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.aggregates.task import Task
from neurath.domain.errors import ContextNotFound


@immutable
class CreateCurrentTaskCommand(AbstractCommand):
    """에이전트가 현재 요청에서 수행할 결과만 지정한다.

    Attributes:
        title: 수행할 작업 제목.
        required_result: 실제로 필요한 결과.
        source_id: 이전 원문을 명시적으로 재사용할 때의 ID.
        dependencies: 선행 작업의 실제 ID.
        start: 지금 수행하기로 한 작업의 시작을 함께 기록한다.
    """

    title: str
    required_result: str
    source_id: UUID | None = None
    dependencies: Sequence[UUID] = ()
    start: bool = False


@UseCase()
class CreateCurrentTaskUseCase(IAsyncCommandUseCase[CreateCurrentTaskCommand, Task]):
    """현재 호스트 맥락을 찾아 내부 UUID 관리 없이 기존 작업 원장을 사용한다."""

    def __init__(
        self,
        resolve: ResolveSessionContextUseCase,
        sources: GetSourcesUseCase,
        create: CreateTaskUseCase,
        start: StartTaskUseCase,
    ) -> None:
        """맥락 조회와 기존 원장 작업 단위를 받는다.

        Args:
            resolve: 현재 호스트 범위.
            sources: 보존한 실제 원문.
            create: 원문과 결과의 검증·저장.
            start: 요청한 경우만 기록하는 실제 수행 시작.
        """
        self.resolve = resolve
        self.sources = sources
        self.create = create
        self.start = start

    @override
    async def run(self, command: CreateCurrentTaskCommand) -> Task:
        """현재 원문 또는 선택한 과거 원문에 작업을 연결한다.

        Args:
            command: 요청한 결과와 선택한 원문.

        Returns:
            Task: 생성한 작업의 실제 상태.

        Raises:
            ContextNotFound: 보존한 호스트 원문이 없는 경우.
        """
        scope = await self.resolve.run(ResolveSessionContextQuery())
        source_id = command.source_id
        if source_id is None:
            records = await self.sources.run(
                GetSourcesQuery(project_id=scope.session.project_id, session_id=scope.session.uid)
            )
            source = next(
                (
                    item
                    for item in reversed(records.sources)
                    if item.session_id == scope.session.uid
                    and item.kind not in (SourceKind.STATUS, SourceKind.SUMMARY)
                ),
                None,
            )
            if source is None:
                raise ContextNotFound(
                    "No observed source exists. Check the UserPromptSubmit hook or select an existing source from context show --section sources."
                )
            source_id = source.uid
        task = (
            await self.create.run(
                CreateTaskCommand(
                    project_id=scope.session.project_id,
                    session_id=scope.session.uid,
                    source_id=source_id,
                    title=command.title,
                    required_result=command.required_result,
                    dependencies=command.dependencies,
                )
            )
        ).task
        if not command.start:
            return task
        return (
            await self.start.run(
                StartTaskCommand(
                    project_id=task.project_id,
                    session_id=task.owner_session_id,
                    task_id=task.uid,
                    expected_revision=task.revision,
                )
            )
        ).task
