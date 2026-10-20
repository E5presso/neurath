"""실제 실행 중단과 확인을 제공하는 호스트 제어 계약이다."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.execution import Execution
from neurath.domain.runtime_records import Liveness


class IExecutionControllerService(ABC):
    """현재 실행과 정확한 턴만 중단하고 확인된 결과를 반환한다."""

    @abstractmethod
    def interrupt(self, execution: Execution) -> Liveness:
        """실제 실행기에 중단을 요청하고 해당 실행의 종료를 확인한다.

        Args:
            execution: 중단할 실제 실행 연결과 턴의 스냅샷.

        Returns:
            Liveness: 확인된 종료 여부이며 요청 제출만으로 STOPPED를 반환하지 않음.

        Raises:
            NotImplementedError: 호스트 어댑터가 중단을 구현하지 않은 경우.
        """
        raise NotImplementedError
