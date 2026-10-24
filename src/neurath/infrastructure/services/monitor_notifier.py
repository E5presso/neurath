"""오류 출력 제출을 실제 호스트 알림 수신과 구분해 보고한다."""

import sys
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.monitor_notifier import (
    IMonitorNotifierService,
    MonitorDelivery,
)
from neurath.domain.values.task_monitor import NoticeStatus


@Pod()
class StderrMonitorNotifierService(IMonitorNotifierService):
    """오류 출력 제출을 실제 호스트 알림 수신과 구분해 보고한다."""

    @override
    def submit(self, reference: str, body: str) -> MonitorDelivery:
        """전체 알림을 flush하고 반환된 제출만 확인한다.

        Args:
            reference: 정확한 사건·제출 시도 참조.
            body: 원 조건·허용 후속 범위와 실제 변화.

        Returns:
            MonitorDelivery: stdout·stderr 경계의 제출이며 실제 전달 확인은 아님.
        """
        print(
            f"""Monitor {reference}
{body}""",
            file=sys.stderr,
            flush=True,
        )
        return MonitorDelivery(status=NoticeStatus.SUBMITTED)
