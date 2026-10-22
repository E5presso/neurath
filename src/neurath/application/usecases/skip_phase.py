"""현재 선택 단계의 생략 조건과 근거를 기록한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun


@dataclass(frozen=True)
class SkipPhaseCommand(AbstractCommand):
    """정의된 선택 분기를 생략할 조건과 그 근거를 지정한다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        run_id: 선택 단계를 생략할 run ID.
        expected_revision: 읽은 run 저장 버전.
        condition: 정의에 있는 생략 조건.
        reason: 조건을 충족한 근거.
    """

    project_id: str
    session_id: str
    run_id: str
    expected_revision: int
    condition: str
    reason: str


@dataclass(frozen=True)
class SkipPhaseResult:
    """생략 이력이 추가된 run. 필수 단계나 미확정 실행은 생략하지 않는다.

    Attributes:
        run: 생략 이력이 추가된 run. 필수 단계나 미확정 실행은 생략하지 않는다.
    """

    run: WorkflowRun


@UseCase()
class SkipPhaseUseCase(IAsyncCommandUseCase[SkipPhaseCommand, SkipPhaseResult]):
    """현재 선택 단계의 생략 조건과 근거를 기록한다.

    현재 단계가 선택 단계이고 조건이 일치할 때만 skipped 이력을 추가한다.
    필수 단계나 결과가 아직 불명인 외부 실행은 생략으로 없애지 않는다.
    """

    def __init__(self, workflows: IWorkflowRepository) -> None:
        """태스크와 연결된 절차의 조회·저장 포트를 받는다.

        Args:
            workflows: run의 정의·시도를 조회하고 변경 전체를 저장한다.
        """
        self.workflows = workflows

    @transactional
    @override
    async def run(self, command: SkipPhaseCommand) -> SkipPhaseResult:
        """현재 선택 단계의 생략 조건과 근거를 기록한다.

        Args:
            command: 소유 run과 읽은 revision, 정의의 생략 조건 및 충족 근거.

        Returns:
            SkipPhaseResult: 생략 이력이 추가된 run. 필수 단계나 미확정 실행은 생략하지 않는다.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        run.require_revision(command.expected_revision)
        run.skip(command.condition, command.reason)
        return SkipPhaseResult(run=(await self.workflows.save(run)))
