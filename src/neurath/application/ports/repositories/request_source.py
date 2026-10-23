"""원문과 정정 출처의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.request_source import RequestSource


class IRequestSourceRepository(IAsyncGenericRepository[RequestSource, UUID], ABC):
    """원래 작성자와 정정 관계를 보존하는 원문의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
