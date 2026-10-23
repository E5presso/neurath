"""Enclave의 선언형 매핑에 프레임워크 기본 CRUD를 연결한다."""

from collections.abc import Sequence
from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.enclave import IEnclaveRepository
from neurath.domain.aggregates.enclave import Enclave
from neurath.infrastructure.models.enclave import EnclaveModel


@Repository()
class SQLAlchemyEnclaveRepository(AbstractAsyncGenericRepository[Enclave, str], IEnclaveRepository):
    """Enclave aggregate를 기본 저장 계약으로 읽고 쓴다."""

    @override
    async def find_by_session_id(self, session_id: str) -> Sequence[Enclave]:
        """현재 세션의 공통·작업별 enclave를 이력과 함께 조회한다.

        Args:
            session_id: 소유 세션의 내부 ID.

        Returns:
            Sequence[Enclave]: ID 순서의 완전한 aggregate 목록.
        """
        rows = await self._session_manager.session.scalars(
            select(EnclaveModel)
            .where(EnclaveModel.session_id == session_id)
            .order_by(EnclaveModel.id)
        )
        return tuple(row.to_domain() for row in rows)
