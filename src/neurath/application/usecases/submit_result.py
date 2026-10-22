"""미확정 시도에 후보 자료를 저장하며 성공 판정은 report_result에 남긴다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import SubmittedResult


@dataclass(frozen=True)
class SubmitResultCommand(AbstractCommand):
    """아직 확정되지 않은 실행 시도에 저장할 후보 설명·산출물 참조를 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 태스크를 소유한 세션 ID. 다른 세션의 작업은 변경하지 않는다.
        task_id: 미확정 시도에 후보 자료를 제출할 태스크 ID.
        expected_revision: 수정 전에 읽은 Task.revision. 요구 개정 번호와는 별개다.
        attempt_number: 결과가 아직 확정되지 않은 현재 또는 과거 시도 번호.
        submission: 확정 전 후보 설명과 산출물 참조. 같은 값은 유지하고 다른 값은 교체한다.
    """

    project_id: str
    session_id: str
    task_id: str
    expected_revision: int
    attempt_number: int
    submission: SubmittedResult


@dataclass(frozen=True)
class SubmitResult:
    """후보 제출이 반영되고 실행 상태는 유지된 태스크를 반환한다.

    Attributes:
        task: 지정 시도의 submission이 갱신된 태스크. 제출만으로 상태가 바뀌지 않는다.
    """

    task: Task


@UseCase()
class SubmitResultUseCase(IAsyncCommandUseCase[SubmitResultCommand, SubmitResult]):
    """미확정 시도에 후보 자료를 저장하며 성공 판정은 report_result에 남긴다.

    정정 전 시도에도 후보를 기록할 수 있다. 같은 후보는 변경 없이 유지하고
    다른 후보는 해당 시도의 submission을 교체한다. 이미 결과가 확정된 시도에는 제출할 수 없다.
    """

    def __init__(self, tasks: ITaskRepository) -> None:
        """미확정 시도의 후보 자료를 조회·저장할 포트를 받는다.

        Args:
            tasks: 대상 태스크의 시도를 조회하고 갱신한 후보 설명·참조를 저장한다.
        """
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: SubmitResultCommand) -> SubmitResult:
        """소유 범위·revision을 확인하고 지정 시도의 후보 자료를 저장한다.

        Args:
            command: 제출할 시도 번호·후보 자료와 태스크의 소유 범위·읽은 revision.

        Returns:
            SubmitResult: 지정 시도의 submission이 갱신된 태스크. 제출만으로 상태가 바뀌지 않는다.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        task.submit(command.attempt_number, command.submission)
        return SubmitResult(task=(await self.tasks.save(task)))
