"""Writer 기본 CRUD를 재사용하고 현재 식별자 조회만 추가한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.writer import Writer


class IWriterRepository(IAsyncGenericRepository[Writer, str], ABC):
    """정규 작업 폴더의 현재 작성 소유자를 조회한다."""

    @abstractmethod
    async def find(self, resource: str) -> Writer | None:
        """정규 작업 폴더의 현재 작성 소유자를 조회한다.

        Args:
            resource: 조회할 정규 작업 폴더 식별자.

        Returns:
            Writer | None: 일치하는 기록이며 없으면 None.

        Raises:
            NotImplementedError: 구체 저장소가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
