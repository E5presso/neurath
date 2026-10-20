"""시도 저장과 결과 반영 사이에 DB 잠금 없이 외부 실행·복구를 수행한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.persistency.transaction import AbstractTransaction
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.services.phase_executor import (
    IPhaseExecutorService,
    IWorkflowNotifierService,
)
from neurath.application.usecases.report_phase import ReportPhaseCommand, ReportPhaseUseCase
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.workflow_records import PhaseAttempt, PhaseDefinition, PhaseResult, PhaseStatus


@dataclass(frozen=True)
class ExecutePhaseCommand(AbstractCommand):
    """실행하거나 기존 미확정 시도를 조정할 run을 지정한다.

    Attributes:
        project_id: run의 프로젝트 ID.
        session_id: 실행 소유 세션 ID.
        run_id: 처리할 run ID.
        expected_revision: 새 시도를 시작할 때 대조할 run 저장 버전.
    """

    project_id: str
    session_id: str
    run_id: str
    expected_revision: int


@dataclass(frozen=True)
class ExecutePhaseResult:
    """실행 또는 결과 조회를 반영한 run과 실제 처리한 시도를 반환한다.

    Attributes:
        run: 현재 단계와 보존된 시도 결과.
        request_id: 외부 실행·관찰에 사용한 시도 ID. 이미 완료됐으면 None.
    """

    run: WorkflowRun
    request_id: str | None


@UseCase()
class ExecutePhaseUseCase(ICommandUseCase[ExecutePhaseCommand, ExecutePhaseResult]):
    """시도를 먼저 커밋하고 외부 실행 후 별도 트랜잭션으로 결과를 저장한다.

    호출자가 바깥 트랜잭션을 열지 않고 run을 호출한다. 재개 시 먼저 동일 시도를
    조회하며 조회·중복 제거가 모두 없으면 waiting을 보존하고 대기를 알린다.
    """

    def __init__(
        self,
        workflows: IWorkflowRepository,
        tasks: ITaskRepository,
        transaction: AbstractTransaction,
        executor: IPhaseExecutorService,
        notifier: IWorkflowNotifierService,
        report: ReportPhaseUseCase,
    ) -> None:
        """원장 저장·짧은 트랜잭션·실행과 알림을 담당하는 의존성을 받는다.

        Args:
            workflows: 정의와 시도를 읽고 저장하는 포트.
            tasks: 현재 요구와 소유 범위를 확인하는 포트.
            transaction: 각 저장 구간을 열고 닫는 프레임워크 트랜잭션.
            executor: DB 잠금 밖에서 실행·조회하는 호스트 어댑터.
            notifier: 결과 불명의 원인과 시도 ID를 전달하는 어댑터.
            report: 단계 결과와 연결 태스크의 대기를 같은 트랜잭션에서 반영한다.
        """
        self.workflows = workflows
        self.tasks = tasks
        self.transaction = transaction
        self.executor = executor
        self.notifier = notifier
        self.report = report

    @override
    def run(self, command: ExecutePhaseCommand) -> ExecutePhaseResult:
        """다음 단계를 실행하거나 기존 시도의 결과를 조회하여 조정한다.

        Args:
            command: run의 소유 범위와 새 실행을 위한 저장 버전.

        Returns:
            ExecutePhaseResult: 완료·실패·대기와 실제 처리한 시도의 ID.
        """
        with self.transaction:
            run = self.workflows.get(command.run_id)
            run.require_scope(command.project_id, command.session_id)
            phase = run.current
            if phase is None:
                return ExecutePhaseResult(run=run, request_id=None)
            attempt = next(
                (
                    item
                    for item in reversed(run.attempts)
                    if item.phase_key == phase.key
                    and item.status in (PhaseStatus.RUNNING, PhaseStatus.WAITING)
                ),
                None,
            )
            fresh = attempt is None
            run.require_task(self.tasks.get(run.task_id), recovering=not fresh)
            if attempt is None:
                run.require_revision(command.expected_revision)
                attempt = run.begin()
                self.workflows.save(run)
            phase = run.phase_for(attempt)
        request_id = f"{run.uid}:{attempt.number}"
        try:
            result = self._execute_or_reconcile(request_id, phase, attempt, fresh=fresh)
        except Exception as error:
            result = PhaseResult(
                status=PhaseStatus.WAITING,
                target_revision=phase.target_revision,
                summary=f"External result is unconfirmed: {type(error).__name__}: {error}",
            )
        with self.transaction:
            current = self.report.run(
                ReportPhaseCommand(
                    command.project_id, command.session_id, command.run_id, attempt.number, result
                )
            ).run
        if result.status is PhaseStatus.WAITING and result != attempt.result:
            self.notifier.waiting(request_id, result.summary)
        return ExecutePhaseResult(run=current, request_id=request_id)

    def _execute_or_reconcile(
        self,
        request_id: str,
        phase: PhaseDefinition,
        attempt: PhaseAttempt,
        *,
        fresh: bool,
    ) -> PhaseResult:
        """새 시도를 실행하거나 기존 시도의 조회 결과를 우선 반환한다.

        조회로 결과를 찾으면 중복 제거 기능을 조회하거나 재제출하지 않는다.
        재제출 보장이 없는 실행은 기존 대기 결과를 유지한다.

        Args:
            request_id: 외부 실행에 사용할 동일 시도의 ID.
            phase: 시도 당시 고정한 실행 대상과 조건.
            attempt: 실행 또는 복구할 보존된 시도.
            fresh: 이번 요청에서 새로 예약한 시도인지 여부.

        Returns:
            PhaseResult: 실제 실행·조회 결과 또는 보존할 결과 불명 상태.
        """
        if fresh:
            return self.executor.execute(request_id, phase)
        result = self.executor.lookup(request_id, phase)
        if result is not None:
            return result
        if self.executor.supports_deduplication:
            result = self.executor.execute(request_id, phase)
        if result is not None:
            return result
        if attempt.result is not None:
            return attempt.result
        return PhaseResult(
            status=PhaseStatus.WAITING,
            target_revision=phase.target_revision,
            summary="External result is unknown; lookup or verified deduplication is required",
        )
