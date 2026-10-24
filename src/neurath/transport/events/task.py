"""작업의 실제 대기 해소를 관련 실행 조정 유스케이스에 전달한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.usecases.resume_waiting_session import (
    ResumeWaitingSessionCommand,
    ResumeWaitingSessionUseCase,
)
from neurath.domain.events.task_resumed import TaskResumed


@EventHandler()
class TaskEventHandler:
    """Task의 커밋 뒤 실행과 피어의 정상 대기를 조정한다."""

    def __init__(self, resume: ResumeWaitingSessionUseCase) -> None:
        """같은 작업의 대기 해소를 담당하는 유스케이스를 받는다.

        Args:
            resume: 실제 대기 원인에 한정한 원장 조정.
        """
        self.resume = resume

    @on_event(TaskResumed)
    async def resumed(self, event: TaskResumed) -> None:
        """커밋된 작업 사건을 같은 작업의 실행 조정 입력으로 변환한다.

        Args:
            event: 실제 원 작업의 대기 해소 사건.
        """
        await self.resume.run(ResumeWaitingSessionCommand(task_id=event.task_id))
