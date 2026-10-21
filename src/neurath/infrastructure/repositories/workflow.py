"""워크플로우 실행의 기본 Aggregate 저장 계약을 제공한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun


@Repository()
class SQLAlchemyWorkflowRepository(
    AbstractAsyncGenericRepository[WorkflowRun, str], IWorkflowRepository
):
    """단계 정의 개정과 시도 결과를 소유하는 워크플로우를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""
