"""같은 호스트 대화의 감시 콜백을 현재 원장과 실제 관찰에 연결한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.read_result_context import (
    ReadResultContextQuery,
    ReadResultContextUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.tick_monitor import TickMonitorCommand, TickMonitorUseCase
from neurath.domain.errors import ContextNotFound
from neurath.domain.values.task_monitor import MonitorEvent, NoticeStatus, TaskMonitor


@immutable
class PollTaskMonitorCommand(AbstractCommand):
    """스케줄러가 같은 대화에 전달한 실제 호스트 주소와 원 감시를 지정한다.

    Attributes:
        task_id: 원 요청의 대기 작업.
        monitor_number: 등록된 감시 순번.
        session: 실제 네이티브 세션 주소.
        directory: 호스트가 관찰한 현재 폴더.
        provider: 실제 호스트 공급자.
        transition_event_id: 실제 전환 큐 사건이며 일반 콜백은 None.
    """

    task_id: UUID
    monitor_number: int
    session: str = ""
    directory: str = ""
    provider: str = ""
    transition_event_id: UUID | None = None


@immutable
class PollTaskMonitorResult:
    """모델에 전달할 실제 변화와 출력 이후 제출할 사건을 반환한다.

    Attributes:
        monitor: 실제 관찰 뒤의 감시 상태.
        peer_id: 콜백을 받은 실제 피어.
        events: 아직 제출하지 않은 새 변화 사건.
        attention: 새 실패 또는 예산 종료에 대한 한 번의 안내.
    """

    monitor: TaskMonitor
    peer_id: UUID
    events: Sequence[MonitorEvent]
    attention: str = ""


@UseCase()
class PollTaskMonitorUseCase(IAsyncCommandUseCase[PollTaskMonitorCommand, PollTaskMonitorResult]):
    """변화 없는 콜백은 모델 작업을 요구하지 않고 실제 변화만 원 대화로 반환한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        read: ReadResultContextUseCase,
        tick: TickMonitorUseCase,
    ) -> None:
        """현재 호스트 조회와 기존 단일 관찰의 작업 단위를 받는다.

        Args:
            context: 콜백의 실제 세션 범위.
            read: 현재 작업 소유와 감시 이력.
            tick: 모델 실행 없는 실제 외부 관찰.
        """
        self.context = context
        self.read = read
        self.tick = tick

    @override
    async def run(self, command: PollTaskMonitorCommand) -> PollTaskMonitorResult:
        """원 소유 범위와 감시를 읽고 동일 실행의 관찰 결과만 반환한다.

        Args:
            command: 등록된 감시를 가리키는 호스트 콜백.

        Returns:
            PollTaskMonitorResult: 출력에 사용할 새 사건·안내와 실제 감시.

        Raises:
            ContextNotFound: 콜백의 실제 호스트 피어가 관찰되지 않은 경우.
        """
        scope = await self.context.run(
            ResolveSessionContextQuery(
                session=command.session, directory=command.directory, provider=command.provider
            )
        )
        if scope.peer is None:
            raise ContextNotFound("Monitor callback requires an observed host peer")
        work = await self.read.run(
            ReadResultContextQuery(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                task_id=command.task_id,
            )
        )
        previous = work.task.monitor(command.monitor_number)
        current = await self.tick.run(
            TickMonitorCommand(
                project_id=scope.session.project_id,
                session_id=scope.session.uid,
                task_id=work.task.uid,
                monitor_number=previous.number,
                execution_id=previous.owner_execution_id,
                generation=previous.generation,
                notify=False,
                transition_event_id=command.transition_event_id,
            )
        )
        events = tuple(
            event
            for event in current.events
            if current.active
            and event.notice_status is NoticeStatus.WRITTEN
            and not event.acknowledged
        )
        attention = ""
        if (current.error, current.stop_reason) != (previous.error, previous.stop_reason):
            attention = current.error or current.stop_reason
        return PollTaskMonitorResult(
            monitor=current, peer_id=scope.peer.uid, events=events, attention=attention
        )
