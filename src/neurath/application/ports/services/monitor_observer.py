"""요청한 외부 상태만 결정론적으로 관찰한다."""

from abc import ABC, abstractmethod

from spakky.core.common.mutability import immutable

from neurath.domain.values.task_monitor import MonitorKind


@immutable
class MonitorObservation:
    """완결 상태와 조각·실패를 구분하는 실제 관찰이다.

    Attributes:
        state: 완결 상태이며 아직 출력 조각뿐이면 None.
        reference: 실제 관찰 대상과 근거.
        error: 관찰 실패와 필요한 조작.
    """

    state: str | None
    reference: str
    error: str = ""


class IMonitorObserverService(ABC):
    """요청한 외부 상태만 결정론적으로 관찰한다."""

    @abstractmethod
    def observe(self, kind: MonitorKind, target: str) -> MonitorObservation:
        """모델이나 사용자 훅 없이 대상 상태를 읽는다.

        Args:
            kind: 지원하는 외부 관찰 종류.
            target: 검증하고 저장한 정확한 대상.

        Returns:
            MonitorObservation: 완결 상태·조각·실패의 구분.

        Raises:
            NotImplementedError: 어댑터가 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
