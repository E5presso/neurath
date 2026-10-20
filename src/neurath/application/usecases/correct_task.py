"""현재 요구를 가리키는 정정 출처로 태스크의 지정한 필드만 변경한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@dataclass(frozen=True)
class CorrectTaskCommand(AbstractCommand):
    """현재 요구를 정정한 출처와 변경할 제목·결과·의존 목록을 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 정정할 태스크 ID.
        expected_revision: 수정 전에 읽은 Task.revision. 요구 개정 번호와는 별개다.
        source_id: 현재 TaskDefinition.source_id를 corrects_id로 가리키는 정정 출처 ID.
        title: 새 제목. None이면 기존 제목을 유지한다.
        required_result: 새 달성 결과. None이면 기존 결과를 유지한다.
        dependencies: 새 선행 태스크 ID 목록. None이면 유지하고 빈 목록이면 모두 해제한다.
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
    """정정이 반영된 현재 요구와 이전 개정·시도를 함께 반환한다.

    Attributes:
        task: 새 요구 개정 또는 변경 없는 기존 요구를 가진 태스크.
    """

    task: Task


@UseCase()
class CorrectTaskUseCase(ICommandUseCase[CorrectTaskCommand, CorrectTaskResult]):
    """현재 요구를 가리키는 정정 출처로 태스크의 지정한 필드만 변경한다.

    값이 달라지면 요구 개정을 추가하고 pending으로 되돌리며 과거 시도는 보존한다.
    None인 필드는 유지하고, 모든 값이 같으면 요구 개정과 실행 상태를 유지한다.
    다른 프로젝트의 출처, 현재 요구와 관계없는 정정, 잘못된 의존은 수용하지 않는다.
    """

    def __init__(self, tasks: ITaskRepository, sources: IRequestSourceRepository) -> None:
        """정정할 태스크·의존 그래프와 정정 출처를 읽을 저장소를 받는다.

        Args:
            tasks: 정정 대상·선행 작업을 조회하고 새 요구 개정을 저장한다.
            sources: 현재 요구를 정정하는 원문을 조회한다.
        """
        self.tasks = tasks
        self.sources = sources

    @override
    def run(self, command: CorrectTaskCommand) -> CorrectTaskResult:
        """소유 범위·저장 revision·의존을 확인하고 정정한 태스크를 저장한다.

        Args:
            command: 정정할 태스크, 읽은 revision, 현재 출처를 정정하는 source_id와 변경 필드.

        Returns:
            CorrectTaskResult: 새 요구 개정 또는 변경 없는 기존 요구를 가진 태스크.
        """
        task = self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.validate_dependencies(self.tasks.list(command.project_id), command.dependencies)
        task.correct(
            self.sources.get(command.source_id),
            command.title,
            command.required_result,
            command.dependencies,
        )
        return CorrectTaskResult(task=self.tasks.save(task))
