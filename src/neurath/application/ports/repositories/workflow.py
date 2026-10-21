"""워크플로우 실행의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.workflow import WorkflowRun


class IWorkflowRepository(IAsyncGenericRepository[WorkflowRun, str], ABC):
    """단계 정의 개정과 시도 결과를 소유하는 워크플로우의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
