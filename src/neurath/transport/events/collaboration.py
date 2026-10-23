"""커밋된 요구 변경 사건을 배정 동기화 유스케이스에 전달한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.provider_records import ProviderObservation
from neurath.application.usecases.reconcile_delegations import (
    ReconcileDelegationsCommand,
    ReconcileDelegationsUseCase,
)
from neurath.application.usecases.record_provider import (
    RecordProviderCommand,
    RecordProviderUseCase,
)
from neurath.application.usecases.recover_provider import (
    RecoverProviderCommand,
    RecoverProviderUseCase,
)
from neurath.application.usecases.run_provider import RunProviderCommand, RunProviderUseCase
from neurath.domain.collaboration_events import (
    ProviderExecutionObserved,
    ProviderExecutionRequested,
    ProviderStopRequested,
    TaskDefinitionChanged,
)


@EventHandler()
class CollaborationEventHandler:
    """도메인 사건을 입력 계약으로 변환하며 배정 상태 판단은 하지 않는다."""

    def __init__(self, reconcile: ReconcileDelegationsUseCase) -> None:
        """요구 변경을 처리할 유스케이스를 받는다.

        Args:
            reconcile: 변경된 태스크의 배정만 동기화한다.
        """
        self.reconcile = reconcile

    @on_event(TaskDefinitionChanged)
    async def reconcile_assignments(self, event: TaskDefinitionChanged) -> None:
        """커밋된 태스크를 읽어 관련 배정에 변경을 전달한다.

        Args:
            event: 실제 요구 변경 사건.
        """
        await self.reconcile.run(ReconcileDelegationsCommand(task_id=event.task_id))


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
