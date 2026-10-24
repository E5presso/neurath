"""전환 중 실제 받은 사건을 원 순서대로 기존 훅 트랜잭션에 재생한다."""

import re
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.store_transition import IStoreTransitionService
from neurath.application.usecases.poll_task_monitor import (
    PollTaskMonitorCommand,
    PollTaskMonitorUseCase,
)
from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
from neurath.domain.enums.hook_event import HookEvent


@immutable
class ReplayTransitionEventsCommand(AbstractCommand):
    """실제 전환 폴더의 미처리 사건을 지정한다.

    Attributes:
        directory: 원 SQLite 경로가 가리키는 전환 폴더.
    """

    directory: str


@immutable
class ReplayTransitionEventsResult:
    """코어 반영과 호스트 응답 전달을 분리한 결과다.

    Attributes:
        applied: 이번 호출에서 코어 반영을 확인한 사건 수.
        remaining: 아직 적용 확인되지 않은 사건 수.
        host_delivery: 실제 호스트로 원 응답을 전달했는지 여부.
    """

    applied: int
    remaining: int
    host_delivery: str = "unverified"


@UseCase()
class ReplayTransitionEventsUseCase(
    IAsyncCommandUseCase[ReplayTransitionEventsCommand, ReplayTransitionEventsResult]
):
    """후속 사건을 앞질러 처리하거나 저장 성공을 실제 모델 전달로 표시하지 않는다."""

    def __init__(
        self,
        transition: IStoreTransitionService,
        receive: ReceiveHookUseCase,
        monitor: PollTaskMonitorUseCase,
    ) -> None:
        """내구성 사건과 기존 원자 훅 처리를 받는다.

        Args:
            transition: 접수 순서와 실제 적용 기록.
            receive: 현재 코어의 기존 훅 상태 전이.
            monitor: 현재 소유·취소·예약을 대조하는 정상 감시 관찰.
        """
        self.transition = transition
        self.receive = receive
        self.monitor = monitor

    @override
    async def run(self, command: ReplayTransitionEventsCommand) -> ReplayTransitionEventsResult:
        """각 사건의 코어 커밋 이후에만 큐의 적용 확인을 저장한다.

        Args:
            command: 실제 전환 사건 위치.

        Returns:
            ReplayTransitionEventsResult: 반영 수와 남은 사건·전달 미확인.

        Raises:
            ValueError: 보존된 감시 콜백 형식을 현재 감시로 해석할 수 없는 경우.
        """
        applied = 0
        for event in self.transition.pending(command.directory):
            data = dict(event.command)
            data["event"] = HookEvent(data["event"])
            data["delegation_id"] = (
                None if data["delegation_id"] is None else UUID(data["delegation_id"])
            )
            data["migration_event_id"] = event.uid
            if data["event"] is HookEvent.USER_PROMPT_SUBMIT and data["prompt"].startswith(
                "NEURATH_MONITOR_TICK "
            ):
                callback = re.fullmatch(
                    r"NEURATH_MONITOR_TICK ([0-9a-fA-F-]{36}) ([1-9][0-9]*)", data["prompt"].strip()
                )
                if callback is None:
                    raise ValueError(
                        "Queued monitor callback is malformed; original event remains pending"
                    )
                observed = await self.monitor.run(
                    PollTaskMonitorCommand(
                        task_id=UUID(callback[1]),
                        monitor_number=int(callback[2]),
                        session=data["host_session_id"],
                        directory=data["working_directory"],
                        provider=data["provider"],
                        transition_event_id=event.uid,
                    )
                )
                if observed.monitor.poll_id is not None:
                    raise ValueError(
                        "Existing monitor observation is unfinished; preserve the queued callback until resource recovery"
                    )
            else:
                await self.receive.run(ReceiveHookCommand(**data))
            self.transition.acknowledge(command.directory, event.uid)
            applied += 1
        return ReplayTransitionEventsResult(
            applied=applied, remaining=len(self.transition.pending(command.directory))
        )
