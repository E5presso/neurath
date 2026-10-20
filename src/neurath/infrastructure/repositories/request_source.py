"""RequestSource의 기본 저장은 상속하고 프로젝트 목록만 조회한다."""

from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.domain.aggregates.request_source import RequestSource
from neurath.infrastructure.models.request_source import RequestSourceModel


@Repository()
class RequestSourceRepository(
    AbstractGenericRepository[RequestSource, str], IRequestSourceRepository
):
    """프레임워크 CRUD를 재구현하지 않는 저장소다."""

    @override
    def list(self, project_id: str) -> tuple[RequestSource, ...]:
        """프로젝트 범위의 모든 현재 레코드를 조회한다.

        Args:
            project_id: 조회 프로젝트.

        Returns:
            tuple[RequestSource, ...]: 원장과 같은 전체 자료.
        """
        records = self._session_manager.session.scalars(
            select(RequestSourceModel)
            .where(RequestSourceModel.project_id == project_id)
            .order_by(RequestSourceModel.created_at, RequestSourceModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)
