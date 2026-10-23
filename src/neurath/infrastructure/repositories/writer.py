"""작성 임대의 기본 Aggregate 저장 계약을 제공한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.writer import Writer
from neurath.infrastructure.models.writer import WriterModel


@Repository()
class SQLAlchemyWriterRepository(AbstractAsyncGenericRepository[Writer, UUID], IWriterRepository):
    """작성 소유자·턴·도구 호출·세대를 가진 임대를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_resource(self, resource: str) -> Writer | None:
        """정규 작업 폴더에 연결된 작성 임대 aggregate를 찾는다.

        Args:
            resource: 정규화한 작성 폴더 경로.

        Returns:
            Writer | None: 작업 폴더의 임대 기록이며 기록이 없으면 None. 해제 상태도 기록으로 반환한다.
        """
        record = await self._session_manager.session.scalar(
            select(WriterModel).where(WriterModel.resource == resource)
        )
        if record is None:
            return None
        return record.to_domain()

    @override
    async def find_by_execution_id(self, execution_id: UUID) -> Sequence[Writer]:
        """소유 범위의 상태 기록을 인수 판단용 aggregate로 조회한다.

        Args:
            execution_id: 조회할 소유 범위의 ID.

        Returns:
            Sequence[Writer]: 저장된 현재 상태 목록.
        """
        rows = await self._session_manager.session.scalars(
            select(WriterModel).where(WriterModel.execution_id == execution_id)
        )
        return tuple(row.to_domain() for row in rows)
