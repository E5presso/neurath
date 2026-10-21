"""원문과 정정 출처의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.domain.aggregates.request_source import RequestSource


@Repository()
class SQLAlchemyRequestSourceRepository(
    AbstractAsyncGenericRepository[RequestSource, str], IRequestSourceRepository
):
    """원래 작성자와 정정 관계를 보존하는 원문를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
