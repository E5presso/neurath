"""알림 제출만 수행하고 실행자를 호출하지 않는다."""

from abc import ABC, abstractmethod

from spakky.core.common.mutability import immutable

from neurath.domain.values.task_monitor import NoticeStatus


@immutable
class MonitorDelivery:
    """외부 알림 제출과 확인 가능한 실제 전달을 구분한다.

    Attributes:
        status: 실제 제출·실패·확인한 전달 상태.
        error: 실패 사유와 필요한 조작.
    """

    status: NoticeStatus
    error: str = ""


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
