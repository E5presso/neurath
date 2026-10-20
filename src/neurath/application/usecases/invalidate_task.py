"""InvalidateTask 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from dataclasses import dataclass

from spakky.core.stereotype.usecase import UseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.task_context import TaskContext


@dataclass(frozen=True)
class InvalidateTaskCommand:
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
        task_id: 대상 태스크.
        expected_revision: 관찰한 태스크 버전.
        source_id: 현재 요구의 실제 정정.
        reason: 무효화한 이유.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    source_id: str
    reason: str


@UseCase()
class InvalidateTaskUseCase:
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, tasks: ITaskRepository, sources: IRequestSourceRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            tasks: 요청에 속하는 tasks 저장소.
            sources: 요청에 속하는 sources 저장소.
        """
        self.tasks = tasks
        self.sources = sources

    def execute(self, request: InvalidateTaskCommand) -> TaskContext:
        """명시한 요청을 적용하고 불변 결과를 반환한다.

        Args:
            request: 원문·범위·관찰에 연결된 입력.

        Returns:
            TaskContext: 현재 상태를 나타내는 불변 결과.
        """
        task = self.tasks.get(request.task_id)
        task.require_scope(request.project_id, request.session_id)
        task.require_revision(request.expected_revision)
        task.invalidate(self.sources.get(request.source_id), request.reason)
        return TaskContext.from_entity(self.tasks.save(task))
