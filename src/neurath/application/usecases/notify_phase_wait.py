"""커밋된 단계 대기 상태를 사용자에게 안내한다."""

import asyncio
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.phase_executor import IWorkflowNotifierService


@dataclass(frozen=True)
class NotifyPhaseWaitCommand(AbstractCommand):
    """이미 저장한 외부 대기 상태의 안내 대상을 지정한다.

    Attributes:
        request_id: 대기 중인 외부 시도 식별자.
        reason: 저장된 대기 원인.
    """

    request_id: str
    reason: str


@UseCase()
class NotifyPhaseWaitUseCase(IAsyncCommandUseCase[NotifyPhaseWaitCommand, None]):
    """저장 성공 이후 알림 서비스를 호출하며 원장 상태는 변경하지 않는다."""

    def __init__(self, notifier: IWorkflowNotifierService) -> None:
        """사용자에게 대기 원인을 전달하는 서비스를 받는다.

        Args:
            notifier: 실제 알림 출력 또는 전달을 담당한다.
        """
        self.notifier = notifier

    @override
    async def run(self, command: NotifyPhaseWaitCommand) -> None:
        """이미 커밋한 상태의 안내를 수행하고 전달 실패를 전파한다.

        Args:
            command: 외부 시도와 저장된 대기 사유.
        """
        await asyncio.to_thread(self.notifier.waiting, command.request_id, command.reason)
