"""작성 임대의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.writer import Writer


class IWriterRepository(IAsyncGenericRepository[Writer, str], ABC):
    """작성 소유자·턴·도구 호출·세대를 가진 임대의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
