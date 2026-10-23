"""워크플로우 사건을 담당 유스케이스의 Command로 변환한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.usecases.notify_phase_wait import (
    NotifyPhaseWaitCommand,
    NotifyPhaseWaitUseCase,
)
from neurath.application.usecases.report_phase import ReportPhaseCommand, ReportPhaseUseCase
from neurath.application.usecases.run_phase import RunPhaseCommand, RunPhaseUseCase
from neurath.domain.workflow_events import (
    PhaseExecutionObserved,
    PhaseExecutionRequested,
    PhaseWaitingRecorded,
)


@EventHandler()
class WorkflowEventHandler:
    """이벤트 수신을 실행·결과 저장·알림 유스케이스에 각각 연결한다."""

    def __init__(
        self,
        execution: RunPhaseUseCase,
        report: ReportPhaseUseCase,
        notification: NotifyPhaseWaitUseCase,
    ) -> None:
        """각 사건의 작업을 담당하는 유스케이스를 주입받는다.

        Args:
            execution: 커밋된 시도의 외부 실행을 처리한다.
            report: 관찰 결과를 원장에 저장한다.
            notification: 저장된 대기 상태를 안내한다.
        """
        self.execution = execution
        self.report = report
        self.notification = notification

    @on_event(PhaseExecutionRequested)
    async def execute(self, event: PhaseExecutionRequested) -> None:
        """저장된 실행 요청을 외부 실행 유스케이스의 입력으로 변환한다.

        Args:
            event: 커밋된 시도와 당시 실행 정의.
        """
        await self.execution.run(
            RunPhaseCommand(
                project_id=event.project_id,
                session_id=event.session_id,
                run_id=event.run_id,
                phase=event.phase,
                attempt=event.attempt,
                fresh=event.fresh,
            )
        )

    @on_event(PhaseExecutionObserved)
    async def report_result(self, event: PhaseExecutionObserved) -> None:
        """관찰 결과를 저장하고 새 외부 대기의 안내를 요청하는 입력으로 변환한다.

        Args:
            event: 외부 실행기가 확인한 시도 결과.
        """
        await self.report.run(
            ReportPhaseCommand(
                project_id=event.project_id,
                session_id=event.session_id,
                run_id=event.run_id,
                attempt_number=event.attempt_number,
                result=event.result,
                notify_waiting=True,
            )
        )

    @on_event(PhaseWaitingRecorded)
    async def notify(self, event: PhaseWaitingRecorded) -> None:
        """커밋된 대기 사건을 알림 유스케이스의 입력으로 변환한다.

        Args:
            event: 저장된 대기 원인과 시도 식별자.
        """
        await self.notification.run(
            NotifyPhaseWaitCommand(request_id=event.request_id, reason=event.reason)
        )
