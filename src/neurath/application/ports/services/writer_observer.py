"""작성 실행의 실제 생존 관찰을 저장된 임대 상태와 분리한다."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.writer import Writer
from neurath.domain.runtime_records import Liveness


class IWriterObserverService(ABC):
    """정확한 실행·턴·도구 호출의 실제 종료를 호스트에서 조회한다."""

    @abstractmethod
    def observe(self, writer: Writer) -> Liveness:
        """임대가 가리키는 실제 작성 실행의 종료 여부를 확인한다.

        Args:
            writer: 관찰할 소유자·턴·호출·세대의 스냅샷.

        Returns:
            Liveness: 실제 종료가 입증되지 않으면 UNKNOWN 또는 RUNNING.

        Raises:
            NotImplementedError: 호스트 어댑터가 생존 관찰을 구현하지 않은 경우.
        """
        raise NotImplementedError
