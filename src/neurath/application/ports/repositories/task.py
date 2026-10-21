"""태스크 원장의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.task import Task


class ITaskRepository(IAsyncGenericRepository[Task, str], ABC):
    """요구 개정·실행 시도·외부 대기를 소유하는 태스크의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
