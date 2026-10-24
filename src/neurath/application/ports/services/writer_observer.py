"""작성 실행의 실제 생존 관찰을 저장된 임대 상태와 분리한다."""

from abc import ABC, abstractmethod
from uuid import UUID

from neurath.domain.enums.liveness import Liveness


class IWriterObserverService(ABC):
    """정확한 실행·턴·도구 호출의 실제 종료를 호스트에서 조회한다."""

    @abstractmethod
    def observe(self, execution_id: UUID, turn_id: str, tool_use_id: str) -> Liveness:
        """임대가 가리키는 실제 작성 실행의 종료 여부를 확인한다.

        Args:
            execution_id: 관찰할 실제 실행.
            turn_id: 해당 호스트 턴.
            tool_use_id: 정확한 작성 호출.

        Returns:
            Liveness: 실제 종료가 입증되지 않으면 UNKNOWN 또는 RUNNING.

        Raises:
            NotImplementedError: 호스트 어댑터가 생존 관찰을 구현하지 않은 경우.
        """
        raise NotImplementedError
