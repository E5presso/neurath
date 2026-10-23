"""작성 임대의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.writer import Writer


class IWriterRepository(IAsyncGenericRepository[Writer, str], ABC):
    """작성 소유자·턴·도구 호출·세대를 가진 임대의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find_by_resource(self, resource: str) -> Writer | None:
        """정규 작업 폴더에 연결된 작성 임대 aggregate를 찾는다.

        Args:
            resource: 정규화한 작성 폴더 경로.

        Returns:
            Writer | None: 작업 폴더의 임대 기록이며 기록이 없으면 None. 해제 상태도 기록으로 반환한다.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_execution_id(self, execution_id: str) -> Sequence[Writer]:
        """인수 확인에 필요한 범위의 실행 또는 작성 기록을 조회한다.

        Args:
            execution_id: 조회할 소유 범위의 ID.

        Returns:
            Sequence[Writer]: 상태를 생략하지 않은 aggregate 목록.

        Raises:
            NotImplementedError: 추상 조회를 직접 호출한 경우.
        """
        raise NotImplementedError
