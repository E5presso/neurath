"""저장된 단계 시도를 외부 실행기에서 처리하고 관찰 결과를 발행한다."""

import asyncio
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.event.event_publisher import IAsyncEventPublisher

from neurath.application.ports.services.phase_executor import IPhaseExecutorService
from neurath.domain.workflow_events import PhaseExecutionObserved
from neurath.domain.workflow_records import PhaseAttempt, PhaseDefinition, PhaseResult, PhaseStatus


@immutable
class RunPhaseCommand(AbstractCommand):
    """이미 커밋한 시도의 외부 실행 또는 복구를 요청한다.

    Attributes:
        project_id: 시도를 소유한 프로젝트.
        session_id: 시도를 소유한 세션.
        run_id: 워크플로우 식별자.
        phase: 시도 당시 고정된 실행 정의.
        attempt: 저장된 시도와 기존 관찰 결과.
        fresh: 새 시도이면 실행하고 기존 시도이면 결과를 먼저 조회한다.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase: PhaseDefinition
    attempt: PhaseAttempt
    fresh: bool


@UseCase()
class RunPhaseUseCase(IAsyncCommandUseCase[RunPhaseCommand, None]):
    """DB 트랜잭션을 열지 않고 외부 실행·복구 및 결과 불명 판정을 수행한다."""

    def __init__(self, executor: IPhaseExecutorService, publisher: IAsyncEventPublisher) -> None:
        """외부 실행기와 결과 전달용 프레임워크 발행자를 받는다.

        Args:
            executor: 실제 실행과 기존 시도의 결과 조회를 수행한다.
            publisher: 관찰 결과를 후속 저장 유스케이스에 전달한다.
        """
        self.executor = executor
        self.publisher = publisher

    @override
    async def run(self, command: RunPhaseCommand) -> None:
        """시도를 실행하거나 복구하고 확인한 결과만 후속 사건으로 전달한다.

        Args:
            command: 실행 정의와 동일 시도를 식별하는 저장된 요청.
        """
        request_id = f"{command.run_id}:{command.attempt.number}"
        try:
            result = await self._execute_or_reconcile(
                request_id, command.phase, command.attempt, fresh=command.fresh
            )
        except Exception as error:
            result = PhaseResult(
                status=PhaseStatus.WAITING,
                target_revision=command.phase.target_revision,
                summary=f"External result is unconfirmed: {type(error).__name__}: {error}",
            )
        await self.publisher.publish(
            PhaseExecutionObserved(
                project_id=command.project_id,
                session_id=command.session_id,
                run_id=command.run_id,
                attempt_number=command.attempt.number,
                result=result,
            )
        )

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
