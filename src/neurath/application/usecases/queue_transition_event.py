"""실제 DB 전환 중 받은 호스트 사건을 코어 밖의 내구성 기록으로 보존한다."""

from dataclasses import asdict
from typing import Any, override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.store_transition import IStoreTransitionService
from neurath.application.usecases.receive_hook import ReceiveHookCommand


@immutable
class QueueTransitionEventCommand(AbstractCommand):
    """호스트에서 실제 받은 원문과 정규화한 사건을 전달한다.

    Attributes:
        hook: 기존 훅 계약으로 해석한 실제 사건.
        payload: 원 호스트 JSON.
    """

    hook: ReceiveHookCommand
    payload: dict[str, Any]


@UseCase()
class QueueTransitionEventUseCase(IAsyncCommandUseCase[QueueTransitionEventCommand, UUID | None]):
    """정상 코어에서는 아무 기록도 만들지 않고 전환 중에만 사건을 보존한다."""

    def __init__(self, transition: IStoreTransitionService) -> None:
        """원 접속 경로와 내구성 사건 기록 계약을 받는다.

        Args:
            transition: 실제 전환 경로 관찰·기록.
        """
        self.transition = transition

    @override
    async def run(self, command: QueueTransitionEventCommand) -> UUID | None:
        """내구적으로 보존한 사건만 ID를 반환한다.

        Args:
            command: 원 호스트 사건.

        Returns:
            UUID | None: 전환 사건 ID 또는 정상 코어의 None.
        """
        return self.transition.enqueue(asdict(command.hook), command.payload)
