"""Memory의 선언형 매핑에 프레임워크 기본 CRUD를 연결한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.domain.aggregates.memory import Memory


@Repository()
class SQLAlchemyMemoryRepository(AbstractAsyncGenericRepository[Memory, str], IMemoryRepository):
    """Memory aggregate를 기본 저장 계약으로 읽고 쓴다."""
