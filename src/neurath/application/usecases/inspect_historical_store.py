"""현재 코어가 없어도 원본 형식을 읽기 전용으로 관찰한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.historical_store import (
    HistoricalInspection,
    IHistoricalStoreService,
)


@immutable
class InspectHistoricalStoreQuery(AbstractQuery):
    """실제로 관찰할 원본 파일을 지정한다.

    Attributes:
        source: 읽을 SQLite 파일.
    """

    source: str


@UseCase()
class InspectHistoricalStoreUseCase(
    IAsyncQueryUseCase[InspectHistoricalStoreQuery, HistoricalInspection]
):
    """자료 부재·오류·미인식을 정상 빈 상태로 바꾸지 않는다."""

    def __init__(self, store: IHistoricalStoreService) -> None:
        """원본 읽기 계약을 받는다.

        Args:
            store: 읽기 전용 형식 관찰.
        """
        self.store = store

    @override
    async def run(self, query: InspectHistoricalStoreQuery) -> HistoricalInspection:
        """DB 생성이나 현재 권한 변경 없이 원본을 읽는다.

        Args:
            query: 원본 위치.

        Returns:
            HistoricalInspection: 전체 자료 수와 형식 인식 여부.
        """
        return self.store.inspect(query.source)
