"""새 코어 기록을 버리지 않고 현재 호환 버전으로 읽을 복구 사본을 만든다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.historical_store import (
    HistoricalSnapshot,
    IHistoricalStoreService,
)


@immutable
class RecoverHistoricalStoreCommand(AbstractCommand):
    """보존할 현재 자료와 새 복구 파일을 지정한다.

    Attributes:
        source: 새 기록을 포함한 현재 코어.
        destination: 기존 파일을 덮어쓰지 않을 복구 위치.
    """

    source: str
    destination: str


@UseCase()
class RecoverHistoricalStoreUseCase(
    IAsyncCommandUseCase[RecoverHistoricalStoreCommand, HistoricalSnapshot]
):
    """원본이나 현재 자료를 구버전으로 대체하지 않는 호환 복구 경로다."""

    def __init__(self, store: IHistoricalStoreService) -> None:
        """현재 코어 검증과 사본 생성 계약을 받는다.

        Args:
            store: 버전 검증·일관된 사본 생성.
        """
        self.store = store

    @override
    async def run(self, command: RecoverHistoricalStoreCommand) -> HistoricalSnapshot:
        """새 기록·미완료·원본 연결을 포함한 호환 복구 사본을 반환한다.

        Args:
            command: 현재 자료와 목적 파일.

        Returns:
            HistoricalSnapshot: 아직 운영 전환하지 않은 복구 자료.
        """
        return await self.store.recover(command.source, command.destination)
