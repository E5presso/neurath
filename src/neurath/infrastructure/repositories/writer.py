"""Writer의 기본 저장·잠금은 프레임워크에 위임한다."""

from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.writer import Writer
from neurath.infrastructure.models.writer import WriterModel


@Repository()
class SQLAlchemyWriterRepository(AbstractGenericRepository[Writer, str], IWriterRepository):
    """정규 작업 폴더의 현재 작성 소유자를 조회한다."""

    @override
    def find(self, resource: str) -> Writer | None:
        """정규 작업 폴더의 현재 작성 소유자를 조회한다.

        Args:
            resource: 조회할 정규 작업 폴더 식별자.

        Returns:
            Writer | None: 일치하는 기록이며 없으면 None.
        """
        record = self._session_manager.session.scalar(
            select(WriterModel).where(WriterModel.resource == resource)
        )
        if record is None:
            return None
        return record.to_domain()
