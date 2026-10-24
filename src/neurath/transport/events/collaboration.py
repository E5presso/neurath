"""커밋된 요구 변경을 배정 동기화 유스케이스에 전달한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.usecases.reconcile_delegations import (
    ReconcileDelegationsCommand,
    ReconcileDelegationsUseCase,
)
from neurath.domain.events.task_definition_changed import TaskDefinitionChanged


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
