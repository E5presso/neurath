"""provider 사건을 실행·결과 기록 유스케이스에만 연결한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.ports.services.provider import ProviderObservation
from neurath.application.usecases.record_provider import (
    RecordProviderCommand,
    RecordProviderUseCase,
)
from neurath.application.usecases.recover_provider import (
    RecoverProviderCommand,
    RecoverProviderUseCase,
)
from neurath.application.usecases.run_provider import RunProviderCommand, RunProviderUseCase
from neurath.domain.events.provider_execution_observed import ProviderExecutionObserved
from neurath.domain.events.provider_execution_requested import ProviderExecutionRequested
from neurath.domain.events.provider_stop_requested import ProviderStopRequested


@EventHandler()
class ProviderEventHandler:
    """provider 사건을 실행·결과 기록 유스케이스에만 연결한다."""

    def __init__(
        self,
        run: RunProviderUseCase,
        record: RecordProviderUseCase,
        recover: RecoverProviderUseCase,
    ) -> None:
        """외부 실행과 DB 결과 저장의 독립된 유스케이스를 받는다.

        Args:
            run: 커밋된 계획의 실제 외부 실행.
            record: 원 실행 관찰의 저장.
            recover: 중단 요청에 해당하는 실제 실행을 관찰·중단한다.
        """
        self.run = run
        self.record = record
        self.recover = recover

    @on_event(ProviderExecutionRequested)
    async def run_provider(self, event: ProviderExecutionRequested) -> None:
        """커밋된 배정의 원 입력을 실행 유스케이스로 전달한다.

        Args:
            event: 저장이 끝난 실행 요청.
        """
        await self.run.run(
            RunProviderCommand(delegation_id=event.delegation_id, prompt=event.prompt)
        )

    @on_event(ProviderExecutionObserved)
    async def record_provider(self, event: ProviderExecutionObserved) -> None:
        """실제 실행의 관찰을 원 배정에 기록한다.

        Args:
            event: 실제 외부 상태와 출력.
        """
        await self.record.run(
            RecordProviderCommand(
                delegation_id=event.delegation_id,
                observation=ProviderObservation(
                    reference=event.reference,
                    status=event.status,
                    native_session_id=event.native_session_id,
                    output=event.output,
                    error=event.error,
                ),
            )
        )

    @on_event(ProviderStopRequested)
    async def stop_provider(self, event: ProviderStopRequested) -> None:
        """커밋된 중단 요청을 원 실행 복구·중단 유스케이스에 전달한다.

        Args:
            event: 원 요청 변경에 영향받은 배정.
        """
        await self.recover.run(
            RecoverProviderCommand(delegation_id=event.delegation_id, peer_id=event.sender_id)
        )
