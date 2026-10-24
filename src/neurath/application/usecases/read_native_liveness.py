"""요청 프로세스의 메모리가 아니라 저장된 실제 호스트 사건으로 동기 작성을 관찰한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.enums.execution_status import ExecutionStatus
from neurath.domain.enums.liveness import Liveness


@immutable
class ReadNativeLivenessQuery(AbstractQuery):
    """실제 호스트에서 관찰한 정확한 작성 호출을 지정한다.

    Attributes:
        execution_id: 원 실행 식별자.
        turn_id: 작성이 시작된 호스트 턴.
        tool_use_id: 동일 작성 호출 식별자.
    """

    execution_id: UUID
    turn_id: str
    tool_use_id: str


@UseCase()
class ReadNativeLivenessUseCase(IAsyncQueryUseCase[ReadNativeLivenessQuery, Liveness]):
    """동기 파일 도구의 실제 종료 경계를 읽고 외부 프로세스 종료를 추정하지 않는다."""

    def __init__(self, executions: IExecutionRepository, writers: IWriterRepository) -> None:
        """요청 간 유지되는 실제 호스트 관찰의 저장 계약을 받는다.

        Args:
            executions: 실제 턴과 종료 사건.
            writers: 실제 파일 변경 호출과 해제 관찰.
        """
        self.executions = executions
        self.writers = writers

    @transactional
    @override
    async def run(self, query: ReadNativeLivenessQuery) -> Liveness:
        """동기 호출에 해당하는 호스트 사건만 종료의 근거로 사용한다.

        Args:
            query: 관찰할 정확한 원 실행·턴·호출.

        Returns:
            Liveness: 해당 사건이 없거나 외부 프로세스면 UNKNOWN.
        """
        execution = await self.executions.get(query.execution_id)
        writers = await self.writers.find_by_execution_id(query.execution_id)
        writer = next(
            (
                item
                for item in writers
                if item.turn_id == query.turn_id and item.tool_use_id == query.tool_use_id
            ),
            None,
        )
        if writer is None or not writer.native_sync:
            return Liveness.UNKNOWN
        if execution.status is ExecutionStatus.ENDED or execution.turn_id != query.turn_id:
            return Liveness.STOPPED
        if execution.status is ExecutionStatus.RUNNING:
            return Liveness.RUNNING
        return Liveness.UNKNOWN
