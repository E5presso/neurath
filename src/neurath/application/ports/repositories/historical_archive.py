"""보존 자료와 실제 선택 재개의 중복을 조회하는 저장 계약이다."""

from abc import ABC, abstractmethod
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.historical_archive import HistoricalArchive


class IHistoricalArchiveRepository(IAsyncGenericRepository[HistoricalArchive, UUID], ABC):
    """자료의 기본 저장과 원본·원 작업 조회를 제공한다."""

    @abstractmethod
    async def find_by_source_path_and_digest(
        self, source_path: str, digest: str
    ) -> HistoricalArchive | None:
        """같은 원본 사본이 이미 등록됐는지 조회한다.

        Args:
            source_path: 원본 파일 위치.
            digest: 일관된 사본의 내용 식별값.

        Returns:
            HistoricalArchive | None: 이미 보존한 자료 또는 None.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_directory_and_origin(
        self, directory: str, origin: str
    ) -> HistoricalArchive | None:
        """같은 프로젝트에서 원 작업을 이미 재개한 자료를 찾는다.

        Args:
            directory: 대상 프로젝트 루트.
            origin: 원본 계보의 작업 식별자.

        Returns:
            HistoricalArchive | None: 실제 재개 연결을 가진 자료 또는 None.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError
