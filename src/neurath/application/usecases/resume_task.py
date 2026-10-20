"""ResumeTask 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.dto.task import TaskDTO
from neurath.application.ports.repositories.task import ITaskRepository


@dataclass(frozen=True)
class ResumeTaskCommand(AbstractCommand):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
        task_id: 대상 태스크.
        expected_revision: 관찰한 태스크 버전.
        resolution: 외부 의존 해소 관찰.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    resolution: str


@UseCase()
class ResumeTaskUseCase(ICommandUseCase[ResumeTaskCommand, TaskDTO]):
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, tasks: ITaskRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            tasks: 요청에 속하는 tasks 저장소.
        """
        self.tasks = tasks

    @override
    def run(self, command: ResumeTaskCommand) -> TaskDTO:
        """명시한 요청을 적용하고 불변 결과를 반환한다.

        Args:
            command: 원문·범위·관찰에 연결된 입력.

        Returns:
            TaskDTO: 현재 상태를 나타내는 불변 결과.
        """
        task = self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.resume(command.resolution)
        return TaskDTO.from_entity(self.tasks.save(task))
