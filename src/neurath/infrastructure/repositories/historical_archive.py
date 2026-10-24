"""보존 자료의 기본 CRUD와 원본·원 작업 연결 조회를 제공한다."""

from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.historical_archive import IHistoricalArchiveRepository
from neurath.domain.aggregates.historical_archive import HistoricalArchive
from neurath.infrastructure.models.historical_archive import (
    HistoricalAdoptionModel,
    HistoricalArchiveModel,
)


@Repository()
class SQLAlchemyHistoricalArchiveRepository(
    AbstractAsyncGenericRepository[HistoricalArchive, UUID], IHistoricalArchiveRepository
):
    """표준 저장과 조회를 사용하며 재개 판단은 도메인/유스케이스에 남긴다."""

    @override
    async def find_by_source_path_and_digest(
        self, source_path: str, digest: str
    ) -> HistoricalArchive | None:
        """같은 원본의 일관된 사본을 조회한다.

        Args:
            source_path: 원본 위치.
            digest: 사본 내용 식별값.

        Returns:
            HistoricalArchive | None: 일치하는 자료 또는 None.
        """
        row = await self._session_manager.session.scalar(
            select(HistoricalArchiveModel).where(
                HistoricalArchiveModel.source_path == source_path,
                HistoricalArchiveModel.digest == digest,
            )
        )
        return None if row is None else row.to_domain()

    @override
    async def find_by_directory_and_origin(
        self, directory: str, origin: str
    ) -> HistoricalArchive | None:
        """현재 프로젝트에 이미 연결한 원 작업을 조회한다.

        Args:
            directory: 명시한 프로젝트 루트.
            origin: 원 작업 계보 식별자.

        Returns:
            HistoricalArchive | None: 재개 연결이 있는 자료 또는 None.
        """
        row = await self._session_manager.session.scalar(
            select(HistoricalArchiveModel)
            .join(HistoricalAdoptionModel)
            .where(
                HistoricalAdoptionModel.directory == directory,
                HistoricalAdoptionModel.origin == origin,
            )
        )
        return None if row is None else row.to_domain()
