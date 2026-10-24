"""등록 사본의 기능 자료를 현재 작업과 구분해 제한된 페이지로 읽는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.historical_store import (
    HistoricalRecord,
    IHistoricalStoreService,
)
from neurath.application.usecases.get_historical_archive import (
    GetHistoricalArchiveQuery,
    GetHistoricalArchiveUseCase,
)


@immutable
class ReadHistoricalRecordsQuery(AbstractQuery):
    """기능 영역과 다음 조회 위치를 지정한다.

    Attributes:
        archive_id: 읽을 보존 자료.
        category: 원문·작업·절차 등 기능 영역.
        offset: 이전 페이지 다음 위치.
        limit: 최대 출력 항목 수.
    """

    archive_id: UUID
    category: str
    offset: int = 0
    limit: int = 20


@immutable
class ReadHistoricalRecordsResult:
    """누락을 빈 성공으로 보이지 않게 전체 수와 다음 위치를 함께 반환한다.

    Attributes:
        records: 선택 페이지의 원문·상태·참조.
        total: 마지막 페이지에서만 확인한 전체 수.
        next_offset: 남은 자료가 있을 때 다음 위치.
    """

    records: Sequence[HistoricalRecord]
    total: int | None
    next_offset: int | None


@UseCase()
class ReadHistoricalRecordsUseCase(
    IAsyncQueryUseCase[ReadHistoricalRecordsQuery, ReadHistoricalRecordsResult]
):
    """DB 트랜잭션을 끝낸 후 보존된 외부 사본을 읽는다."""

    def __init__(
        self, archives: GetHistoricalArchiveUseCase, store: IHistoricalStoreService
    ) -> None:
        """등록 정보와 외부 과거 형식 읽기를 받는다.

        Args:
            archives: 등록 사본 정보.
            store: 과거 형식별 자료 해석.
        """
        self.archives = archives
        self.store = store

    @override
    async def run(self, query: ReadHistoricalRecordsQuery) -> ReadHistoricalRecordsResult:
        """출력량을 제한하고 아직 읽지 않은 자료의 위치를 반환한다.

        Args:
            query: 기능 영역과 페이지.

        Returns:
            ReadHistoricalRecordsResult: 조회 결과와 후속 위치.

        Raises:
            ValueError: 페이지 범위가 잘못된 경우.
        """
        if query.offset < 0 or not 1 <= query.limit <= 100:
            raise ValueError("Historical page requires offset >= 0 and limit 1..100")
        archive = await self.archives.run(GetHistoricalArchiveQuery(archive_id=query.archive_id))
        page = self.store.read(archive.snapshot_path, query.category, query.offset, query.limit)
        return ReadHistoricalRecordsResult(
            records=page.records, total=page.total, next_offset=page.next_offset
        )
