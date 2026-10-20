"""RequestSource 기본 CRUD를 상속하고 프로젝트 목록 조회만 확장한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.request_source import RequestSource


class IRequestSourceRepository(IAsyncGenericRepository[RequestSource, str], ABC):
    """원문·정정 aggregate의 기본 저장 계약과 프로젝트 전체 목록 조회를 제공한다."""

    @abstractmethod
    async def list(self, project_id: str) -> Sequence[RequestSource]:
        """세션·상태로 필터링하지 않은 프로젝트의 전체 원문·정정 목록을 조회한다.

        Args:
            project_id: 목록을 제한할 프로젝트 ID.

        Returns:
            Sequence[RequestSource]: 프로젝트에 속한 모든 원문·정정 객체. 없으면 빈 Sequence.

        Raises:
            NotImplementedError: 구체 어댑터가 목록 조회를 구현하지 않은 경우.
        """
        raise NotImplementedError
