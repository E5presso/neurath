"""호스트 실행 상태의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.execution import Execution


class IExecutionRepository(IAsyncGenericRepository[Execution, str], ABC):
    """실제 턴·중단 상태·Stop 관찰을 가진 실행의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
