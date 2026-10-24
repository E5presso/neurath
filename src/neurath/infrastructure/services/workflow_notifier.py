"""호출 프로세스의 오류 출력에 결과 불명과 시도 식별자를 전달한다."""

import sys
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.workflow_notifier import IWorkflowNotifierService


@Pod()
class StderrWorkflowNotifierService(IWorkflowNotifierService):
    """호출 프로세스의 오류 출력에 결과 불명과 시도 식별자를 전달한다."""

    @override
    def waiting(self, request_id: str, reason: str) -> None:
        """대기 이유를 stderr에 출력하며 네이티브 UI 수신을 주장하지 않는다.

        Args:
            request_id: 관찰이 필요한 실행 시도.
            reason: 결과 불명과 재실행하지 않은 이유.
        """
        print(f"Workflow {request_id}: {reason}", file=sys.stderr, flush=True)
