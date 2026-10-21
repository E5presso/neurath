"""호스트 세션의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.session import HostSession


@Repository()
class SQLAlchemySessionRepository(
    AbstractAsyncGenericRepository[HostSession, str], ISessionRepository
):
    """프로젝트 소속과 작업 경로를 가진 세션를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
