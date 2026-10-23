"""외부 관찰·알림 기술 경계의 불변 응답을 정의한다."""

from spakky.core.common.mutability import immutable

from neurath.domain.monitoring import NoticeStatus


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


@immutable
class MonitorDelivery:
    """외부 알림 제출과 확인 가능한 실제 전달을 구분한다.

    Attributes:
        status: 실제 제출·실패·확인한 전달 상태.
        error: 실패 사유와 필요한 조작.
    """

    status: NoticeStatus
    error: str = ""
