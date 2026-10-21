"""프로젝트와 소유 위치의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project


@Repository()
class SQLAlchemyProjectRepository(AbstractAsyncGenericRepository[Project, str], IProjectRepository):
    """프로젝트의 위치 값들을 포함한 aggregate를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
