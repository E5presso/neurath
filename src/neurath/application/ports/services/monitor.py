"""감시 관찰과 알림 제출을 모델 실행과 분리한 명시적 포트다."""

from abc import ABC, abstractmethod

from neurath.application.monitor_records import MonitorDelivery, MonitorObservation
from neurath.domain.monitoring import MonitorKind


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


class IMonitorNotifierService(ABC):
    """알림 제출만 수행하고 실행자를 호출하지 않는다."""

    @abstractmethod
    def submit(self, reference: str, body: str) -> MonitorDelivery:
        """동일한 사건·시도에 연결한 알림을 제출한다.

        Args:
            reference: 태스크·감시·사건·제출 시도 참조.
            body: 기존 조건·후속 범위·실제 변화 알림.

        Returns:
            MonitorDelivery: 실제 제출 결과이며 전달 확인과 구분함.

        Raises:
            NotImplementedError: 어댑터가 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
