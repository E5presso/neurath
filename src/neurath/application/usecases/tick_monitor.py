"""관찰·알림을 짧은 원장 트랜잭션 밖에서 실행하고 실제 결과만 저장한다."""

import asyncio
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import IAsyncCommandUseCase

from neurath.application.monitor_records import MonitorDelivery, MonitorObservation
from neurath.application.ports.services.monitor import (
    IMonitorNotifierService,
    IMonitorObserverService,
)
from neurath.application.usecases.get_monitor import GetMonitorQuery, GetMonitorUseCase
from neurath.application.usecases.monitor_lifecycle import (
    MonitorCommand,
    MonitorEventCommand,
    PrepareMonitorNoticeUseCase,
    PrepareMonitorPollUseCase,
    RecordMonitorNoticeCommand,
    RecordMonitorNoticeUseCase,
    RecordMonitorObservationCommand,
    RecordMonitorObservationUseCase,
)
from neurath.domain.monitoring import NoticeStatus, TaskMonitor


@UseCase()
class TickMonitorUseCase(IAsyncCommandUseCase[MonitorCommand, TaskMonitor]):
    """모델 실행 없이 한 번 관찰하고 변화 사건의 유한 알림만 제출한다."""

    def __init__(
        self,
        prepare: PrepareMonitorPollUseCase,
        record: RecordMonitorObservationUseCase,
        query: GetMonitorUseCase,
        prepare_notice: PrepareMonitorNoticeUseCase,
        record_notice: RecordMonitorNoticeUseCase,
        observer: IMonitorObserverService,
        notifier: IMonitorNotifierService,
    ) -> None:
        """짧은 원장 작업과 외부 관찰·제출을 담당하는 계약을 받는다.

        Args:
            prepare: 커밋 후 사용할 단일 관찰 예약.
            record: 최신 취소에 대조한 관찰 저장.
            query: 외부 호출 직전과 최종 상태의 부작용 없는 조회.
            prepare_notice: 유한 제출 예산 예약.
            record_notice: 실제 제출·실패 저장.
            observer: 모델·사용자 훅 없이 외부 상태 조회.
            notifier: 실행자를 호출하지 않는 알림 제출.
        """
        self.prepare = prepare
        self.record = record
        self.query = query
        self.prepare_notice = prepare_notice
        self.record_notice = record_notice
        self.observer = observer
        self.notifier = notifier

    @override
    async def run(self, command: MonitorCommand) -> TaskMonitor:
        """원장 커밋 후 한 번 관찰하며 같은 상태에는 알림을 새로 작성하지 않는다.

        Args:
            command: 요청한 정확한 감시와 소유 세대.

        Returns:
            TaskMonitor: 첫 관찰·최신 상태·정확한 사건·실패와 필요한 조작.
        """
        prepared = await self.prepare.run(command)
        query = GetMonitorQuery(
            project_id=command.project_id,
            session_id=command.session_id,
            task_id=command.task_id,
            monitor_number=command.monitor_number,
        )
        if prepared is not None:
            await self._observe(command, prepared, query)
        current = await self.query.run(query)
        for event in current.events:
            if event.notice_status not in (NoticeStatus.WRITTEN, NoticeStatus.FAILED):
                continue
            await self._notify(
                MonitorEventCommand(
                    project_id=command.project_id,
                    session_id=command.session_id,
                    task_id=command.task_id,
                    monitor_number=command.monitor_number,
                    execution_id=command.execution_id,
                    generation=command.generation,
                    event_number=event.number,
                ),
                query,
            )
        return await self.query.run(query)

    async def _observe(
        self, command: MonitorCommand, prepared: TaskMonitor, query: GetMonitorQuery
    ) -> None:
        """예약 후 최신 취소를 다시 확인하고 관찰 실패도 원장에 보존한다.

        Args:
            command: 정확한 원장·자원 소유.
            prepared: 이미 커밋한 관찰 예약.
            query: 외부 호출 직전의 상태 조회.
        """
        current = await self.query.run(query)
        observation = MonitorObservation(state=None, reference=prepared.target)
        if current.active and current.poll_id == prepared.poll_id:
            try:
                observation = await asyncio.to_thread(
                    self.observer.observe, prepared.kind, prepared.target
                )
            except Exception as error:
                observation = MonitorObservation(
                    state=None,
                    reference=prepared.target,
                    error=f"{type(error).__name__}: {error}. Inspect the observer before continuing.",
                )
        assert prepared.poll_id is not None
        await self.record.run(
            RecordMonitorObservationCommand(
                project_id=command.project_id,
                session_id=command.session_id,
                task_id=command.task_id,
                monitor_number=command.monitor_number,
                execution_id=command.execution_id,
                generation=command.generation,
                poll_id=prepared.poll_id,
                state=observation.state,
                reference=observation.reference,
                error=observation.error,
            )
        )

    async def _notify(self, command: MonitorEventCommand, query: GetMonitorQuery) -> None:
        """커밋된 알림 시도만 제출하며 실패·결과 불명을 모델 호출로 재시도하지 않는다.

        Args:
            command: 정확한 변화 사건과 자원 소유.
            query: 외부 제출 직전의 현재 취소 조회.
        """
        prepared = await self.prepare_notice.run(command)
        if prepared is None:
            return
        current = await self.query.run(query)
        event = prepared.event(command.event_number)
        if not current.active:
            result = MonitorDelivery(
                status=NoticeStatus.FAILED,
                error="Cancelled before submission; no notification sent",
            )
            await self._record_notice(command, event.attempts, result)
            return
        try:
            result = await asyncio.to_thread(
                self.notifier.submit,
                f"{command.task_id}/{command.monitor_number}/{event.number}/{event.attempts}",
                f"{event.body}\nObserved state: {event.state}\nEvidence: {event.reference}",
            )
        except Exception as error:
            result = MonitorDelivery(
                status=NoticeStatus.FAILED,
                error=f"{type(error).__name__}: {error}. Check notification access; retry budget is finite.",
            )
        await self._record_notice(command, event.attempts, result)

    async def _record_notice(
        self, command: MonitorEventCommand, attempt: int, result: MonitorDelivery
    ) -> None:
        """취소 뒤에도 이미 시작한 정확한 제출의 결과는 보존한다.

        Args:
            command: 실제 제출 대상의 사건·소유 세대.
            attempt: 관찰한 정확한 제출 시도.
            result: 제출·실패·실제 전달 결과.
        """
        await self.record_notice.run(
            RecordMonitorNoticeCommand(
                project_id=command.project_id,
                session_id=command.session_id,
                task_id=command.task_id,
                monitor_number=command.monitor_number,
                execution_id=command.execution_id,
                generation=command.generation,
                event_number=command.event_number,
                attempt=attempt,
                status=result.status,
                error=result.error,
            )
        )
