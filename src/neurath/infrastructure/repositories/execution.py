"""호스트 실행 상태의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.domain.aggregates.execution import Execution


@Repository()
class SQLAlchemyExecutionRepository(
    AbstractAsyncGenericRepository[Execution, str], IExecutionRepository
):
    """실제 턴·중단 상태·Stop 관찰을 가진 실행를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
