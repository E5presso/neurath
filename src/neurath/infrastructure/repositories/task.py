"""태스크 원장의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task


@Repository()
class SQLAlchemyTaskRepository(AbstractAsyncGenericRepository[Task, str], ITaskRepository):
    """요구 개정·실행 시도·외부 대기를 소유하는 태스크를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
