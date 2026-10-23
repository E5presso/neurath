"""사용자가 요청한 실행 재개를 현재 호스트 턴에만 적용한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.execution import Execution


@dataclass(frozen=True)
class ResumeExecutionCommand(AbstractCommand):
    """실제 재개 요청에 해당하는 실행과 현재 턴을 지정한다.

    Attributes:
        execution_id: 재개할 내부 실행 ID.
        turn_id: 호스트에서 확인한 현재 턴.
    """

    execution_id: str
    turn_id: str


@UseCase()
class ResumeExecutionUseCase(IAsyncCommandUseCase[ResumeExecutionCommand, Execution]):
    """현재 턴의 실행 정지만 해제하고 이전 작성 임대·태스크 이력은 보존한다.

    일반 UserPromptSubmit에서 자동 호출하지 않는다. memory resume을 담당하는
    호출자가 실제 재개 지시에 따라 사용한다. 이전 작성이 남아 있으면 다음 쓰기의
    임대 검사가 계속 충돌을 검출하므로 재개가 작성 종료 확인을 대신하지 않는다.
    """

    def __init__(self, executions: IExecutionRepository, sessions: ISessionRepository) -> None:
        """재개할 실행을 읽고 저장할 저장소를 받는다.

        Args:
            executions: 현재 턴과 중지 상태를 보존하는 실행 저장소.
            sessions: 인수 완료 여부를 확인할 세션 저장소.
        """
        self.executions = executions
        self.sessions = sessions

    @transactional
    @override
    async def run(self, command: ResumeExecutionCommand) -> Execution:
        """지정 턴을 검사하고 실행 정지를 해제한 상태를 저장한다.

        Args:
            command: 실제 재개 요청이 가리키는 실행과 현재 턴.

        Returns:
            Execution: 현재 턴에서 다시 실행할 수 있는 실행 상태.
        """
        execution = await self.executions.get(command.execution_id)
        (await self.sessions.get(execution.session_id)).require_current_owner()
        execution.resume(command.turn_id)
        return await self.executions.save(execution)
