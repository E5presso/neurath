"""호스트 입력을 프로젝트·세션 범위에 연결해 현재 훅 처리 유스케이스에 전달한다."""

import asyncio
from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.data.persistency.transaction import AbstractAsyncTransaction
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.application.usecases.handle_hook import (
    HandleHookCommand,
    HandleHookUseCase,
)
from neurath.application.usecases.register_session import (
    RegisterSessionCommand,
    RegisterSessionUseCase,
)
from neurath.domain.runtime_records import HookAction


@dataclass(frozen=True)
class ReceiveHookCommand(AbstractCommand):
    """CLI가 해석한 호스트 사건이며 내부 프로젝트·세션 ID는 유스케이스가 확인한다.

    Attributes:
        provider: 실제 사건을 전달한 호스트 공급자.
        host_session_id: 호스트가 준 네이티브 세션 ID.
        working_directory: 호스트가 준 작업 디렉터리.
        event: 관찰한 사건 이름.
        start_source: 시작·재개·포크·압축의 호스트 원인.
        turn_id: 실제 턴 또는 prompt ID.
        agent_id: 실제 네이티브 자식 ID.
        tool_use_id: 실제 도구 호출 ID.
        writes: 해당 도구가 작업 폴더에 쓰는 도구인지 여부.
        finished: 호스트 계약상 실제 종료가 확인됐는지 여부.
        interrupted: 실제 중단 여부.
        repeated: Stop 계속 수행 플래그.
        reason: 호스트가 전달한 실패·종료 사유.
    """

    provider: str
    host_session_id: str
    working_directory: str
    event: str
    start_source: str = ""
    turn_id: str = ""
    agent_id: str = ""
    tool_use_id: str = ""
    writes: bool = False
    finished: bool = False
    interrupted: bool = False
    repeated: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ReceiveHookResult:
    """CLI가 호스트 응답으로 표현할 제어와 안내만 반환한다.

    Attributes:
        action: 현재 실행에 대한 허용·계속·중지 판정.
        message: 호스트에 전달할 중지 사유와 TODO.
    """

    action: HookAction
    message: str


@UseCase(scope=Pod.Scope.CONTEXT)
class ReceiveHookUseCase(IAsyncCommandUseCase[ReceiveHookCommand, ReceiveHookResult]):
    """외부 위치를 관찰하고 세션 등록과 훅 적용을 같은 요청 트랜잭션에서 조정한다."""

    def __init__(
        self,
        directories: IDirectoryObserverService,
        sessions: RegisterSessionUseCase,
        hooks: HandleHookUseCase,
        transaction: AbstractAsyncTransaction,
    ) -> None:
        """관찰 서비스와 기존 세션 등록·훅 처리 유스케이스를 주입받는다.

        Args:
            directories: 프로젝트 위치와 공유 작성 폴더를 실제 조회하는 서비스.
            sessions: 관찰한 프로젝트의 네이티브 세션을 등록·재사용하는 유스케이스.
            hooks: 내부 범위에 연결한 사건을 처리하는 유스케이스.
            transaction: 세션 등록과 사건 적용을 원자적으로 저장할 표준 트랜잭션.
        """
        self.directories = directories
        self.sessions = sessions
        self.hooks = hooks
        self.transaction = transaction

    @override
    async def run(self, command: ReceiveHookCommand) -> ReceiveHookResult:
        """실제 위치와 세션을 확인한 뒤 해당 범위에서 훅 사건을 적용한다.

        Args:
            command: 내부 범위를 꾸미지 않은 실제 호스트 사건.

        Returns:
            ReceiveHookResult: 현재 상태에 따른 호스트 판정과 TODO.
        """
        observation = await asyncio.to_thread(self.directories.observe, command.working_directory)
        resource = ""
        if command.writes:
            resource = await asyncio.to_thread(
                self.directories.workspace, command.working_directory
            )
        async with self.transaction:
            actor = await self.sessions.run(
                RegisterSessionCommand(observation, command.provider, command.host_session_id)
            )
            result = await self.hooks.run(
                HandleHookCommand(
                    project_id=actor.project.uid,
                    session_id=actor.session.uid,
                    event=command.event,
                    start_source=command.start_source,
                    turn_id=command.turn_id,
                    agent_id=command.agent_id,
                    tool_use_id=command.tool_use_id,
                    resource=resource,
                    finished=command.finished,
                    interrupted=command.interrupted,
                    repeated=command.repeated,
                    reason=command.reason,
                )
            )

            return ReceiveHookResult(action=result.action, message=result.message)
