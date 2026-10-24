"""장애로 업무 저장이 불가능할 때 미완료 상태를 독립적인 복구 경로에 남긴다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.recovery_log import IRecoveryLogService, RecoveryReceipt


@immutable
class RecordRecoveryFailureCommand(AbstractCommand):
    """실패 원인과 원 호출의 참조를 전달한다.

    Attributes:
        detail: 실제로 관찰한 실패 또는 수행 결과.
        reference: 실패한 원 사건·호출의 참조.
    """

    detail: str
    reference: str


@UseCase()
class RecordRecoveryFailureUseCase(
    IAsyncCommandUseCase[RecordRecoveryFailureCommand, RecoveryReceipt]
):
    """실패한 DB 트랜잭션 밖에서 한 번만 복구 기록을 시도한다."""

    def __init__(self, recovery: IRecoveryLogService) -> None:
        """코어 저장소에 의존하지 않는 기록 계약을 받는다.

        Args:
            recovery: 로컬 복구 기록과 가능한 호스트 오류 출력.
        """
        self.recovery = recovery

    @override
    async def run(self, command: RecordRecoveryFailureCommand) -> RecoveryReceipt:
        """원인과 출처를 검증하고 실제 제출·저장 결과를 반환한다.

        Args:
            command: 실패한 원 요청의 설명과 참조.

        Returns:
            RecoveryReceipt: 기록과 제출 여부. 사용자 수신은 미확인.

        Raises:
            ValueError: 비어 있는 원인 또는 참조인 경우.
        """
        if not command.detail.strip() or not command.reference.strip():
            raise ValueError("Recovery record requires a failure and its source")
        return self.recovery.record(command.detail, command.reference)
