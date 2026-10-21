"""저장된 단계 요청을 DB 잠금 밖에서 실행하고 결과 유스케이스에 전달한다."""

import asyncio

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.ports.services.phase_executor import (
    IPhaseExecutorService,
    IWorkflowNotifierService,
)
from neurath.application.usecases.report_phase import ReportPhaseCommand, ReportPhaseUseCase
from neurath.domain.workflow_events import PhaseExecutionRequested
from neurath.domain.workflow_records import PhaseAttempt, PhaseDefinition, PhaseResult, PhaseStatus


@EventHandler()
class WorkflowEventHandler:
    """예약 커밋 이후 실행·복구하고 별도 결과 트랜잭션을 호출한다."""

    def __init__(
        self,
        executor: IPhaseExecutorService,
        notifier: IWorkflowNotifierService,
        report: ReportPhaseUseCase,
    ) -> None:
        """실제 실행·알림과 결과 저장의 의존성을 주입받는다.

        Args:
            executor: 외부 실행과 기존 시도의 결과 관찰을 수행한다.
            notifier: 결과가 확정되지 않은 시도를 알린다.
            report: 새 트랜잭션에서 시도 결과를 반영한다.
        """
        self.executor = executor
        self.notifier = notifier
        self.report = report

    @on_event(PhaseExecutionRequested)
    async def execute(self, event: PhaseExecutionRequested) -> None:
        """커밋된 시도를 처리하고 실패·대기를 포함한 관찰 결과를 저장한다.

        Args:
            event: 당시 실행 정의와 보존된 시도를 담은 사건.
        """
        request_id = f"{event.run_id}:{event.attempt.number}"
        try:
            result = await self._execute_or_reconcile(
                request_id, event.phase, event.attempt, fresh=event.fresh
            )
        except Exception as error:
            result = PhaseResult(
                status=PhaseStatus.WAITING,
                target_revision=event.phase.target_revision,
                summary=f"External result is unconfirmed: {type(error).__name__}: {error}",
            )
        await self.report.run(
            ReportPhaseCommand(
                event.project_id, event.session_id, event.run_id, event.attempt.number, result
            )
        )
        if result.status is PhaseStatus.WAITING and result != event.attempt.result:
            self.notifier.waiting(request_id, result.summary)

    async def _execute_or_reconcile(
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
            return await asyncio.to_thread(self.executor.execute, request_id, phase)
        result = await asyncio.to_thread(self.executor.lookup, request_id, phase)
        if result is not None:
            return result
        if self.executor.supports_deduplication:
            result = await asyncio.to_thread(self.executor.execute, request_id, phase)
        if result is not None:
            return result
        if attempt.result is not None:
            return attempt.result
        return PhaseResult(
            status=PhaseStatus.WAITING,
            target_revision=phase.target_revision,
            summary="External result is unknown; lookup or verified deduplication is required",
        )
