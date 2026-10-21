"""작성 임대의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.writer import Writer


@Repository()
class SQLAlchemyWriterRepository(AbstractAsyncGenericRepository[Writer, str], IWriterRepository):
    """작성 소유자·턴·도구 호출·세대를 가진 임대를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
