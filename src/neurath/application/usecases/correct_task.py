"""CorrectTask 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task, validate_dependencies


@dataclass(frozen=True)
class CorrectTaskCommand(AbstractCommand):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
        task_id: 대상 태스크.
        expected_revision: 관찰한 태스크 버전.
        source_id: 실제 정정 출처.
        title: 바꿀 제목.
        required_result: 바꿀 결과.
        dependencies: 바꿀 의존 목록.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    source_id: str
    title: str | None = None
    required_result: str | None = None
    dependencies: Sequence[str] | None = None


@dataclass(frozen=True)
class CorrectTaskResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        task: 처리하거나 조회한 태스크와 보존된 전체 이력.
    """

    task: Task


@UseCase()
class CorrectTaskUseCase(ICommandUseCase[CorrectTaskCommand, CorrectTaskResult]):
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, tasks: ITaskRepository, sources: IRequestSourceRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            tasks: 요청에 속하는 tasks 저장소.
            sources: 요청에 속하는 sources 저장소.
        """
        self.tasks = tasks
        self.sources = sources

    @override
    def run(self, command: CorrectTaskCommand) -> CorrectTaskResult:
        """명시한 요청을 적용하고 결과를 반환한다.

        Args:
            command: 원문·범위·관찰에 연결된 입력.

        Returns:
            CorrectTaskResult: 처리한 원장과 현재 상태.
        """
        task = self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        dependencies = (
            task.definition.dependencies if command.dependencies is None else command.dependencies
        )
        validate_dependencies(self.tasks.list(command.project_id), task.uid, dependencies)
        task.correct(
            self.sources.get(command.source_id),
            command.title,
            command.required_result,
            command.dependencies,
        )
        return CorrectTaskResult(task=self.tasks.save(task))
