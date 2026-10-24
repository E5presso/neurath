"""확인 가능한 실제 SQLite 작성 경로만 보존 후 퇴역한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.store_transition import IStoreTransitionService, StoreFence


@immutable
class FenceHistoricalStoreCommand(AbstractCommand):
    """기술적으로 퇴역할 원본과 복구 위치를 지정한다.

    Attributes:
        source: 실제 기존 SQLite 경로.
        archive_directory: 원본/WAL을 보존할 위치.
    """

    source: str
    archive_directory: str


@UseCase()
class FenceHistoricalStoreUseCase(IAsyncCommandUseCase[FenceHistoricalStoreCommand, StoreFence]):
    """사용자 동의 플래그를 작성 정지의 근거로 사용하지 않는다."""

    def __init__(self, transition: IStoreTransitionService) -> None:
        """실제 파일 연결·SQLite 잠금·퇴역 계약을 받는다.

        Args:
            transition: 실제 작성 경로 전환 기술.
        """
        self.transition = transition

    @override
    async def run(self, command: FenceHistoricalStoreCommand) -> StoreFence:
        """원본 보존 뒤 확인 가능한 원 경로만 퇴역한다.

        Args:
            command: 원 SQLite와 복구 위치.

        Returns:
            StoreFence: 실제 퇴역 파일·사본·전환 사건 위치.
        """
        return self.transition.fence(command.source, command.archive_directory)
