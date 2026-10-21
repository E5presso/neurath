"""호스트 세션의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.session import HostSession


class ISessionRepository(IAsyncGenericRepository[HostSession, str], ABC):
    """프로젝트 소속과 작업 경로를 가진 세션의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
