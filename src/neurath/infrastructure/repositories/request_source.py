"""RequestSource의 기본 저장은 상속하고 프로젝트 목록만 조회한다."""

from collections.abc import Sequence
from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.domain.aggregates.request_source import RequestSource
from neurath.infrastructure.models.request_source import RequestSourceModel


@Repository()
class SQLAlchemyRequestSourceRepository(
    AbstractGenericRepository[RequestSource, str], IRequestSourceRepository
):
    """원문·정정을 SQLite에 매핑하고 프로젝트 전체 목록을 도메인 객체로 조회한다."""

    @override
    def list(self, project_id: str) -> Sequence[RequestSource]:
        """프로젝트의 원문·정정을 생성 시각·ID 순으로 조회해 tuple로 반환한다.

        Args:
            project_id: 조회 범위를 제한할 프로젝트 ID.

        Returns:
            Sequence[RequestSource]: ORM 객체와 분리된 전체 원문·정정 목록. 없으면 빈 tuple.
        """
        records = self._session_manager.session.scalars(
            select(RequestSourceModel)
            .where(RequestSourceModel.project_id == project_id)
            .order_by(RequestSourceModel.created_at, RequestSourceModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)
