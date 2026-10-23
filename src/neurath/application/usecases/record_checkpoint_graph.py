"""커밋된 체크포인트 요청에 외부 갱신의 관찰 결과를 기록한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.domain.aggregates.memory import Memory


@dataclass(frozen=True)
class RecordCheckpointGraphCommand(AbstractCommand):
    """외부 갱신에서 확인한 결과를 원래 보고 ID에 연결한다.

    Attributes:
        memory_id: 결과를 기록할 체크포인트 ID.
        directory: 실제 갱신 요청의 경로.
        reference: 검증된 그래프 참조이며 실패면 None.
        error: 외부 실패 관찰이며 성공이면 None.
    """

    memory_id: str
    directory: str
    reference: str | None
    error: str | None


@UseCase()
class RecordCheckpointGraphUseCase(IAsyncCommandUseCase[RecordCheckpointGraphCommand, Memory]):
    """원래 보고와 출처를 유지하며 요청에 일치하는 결과만 별도 트랜잭션에 저장한다."""

    def __init__(self, memories: IMemoryRepository) -> None:
        """결과를 붙일 기억 저장 계약을 받는다.

        Args:
            memories: 커밋된 요청 조회와 결과 저장.
        """
        self.memories = memories

    @transactional
    @override
    async def run(self, command: RecordCheckpointGraphCommand) -> Memory:
        """같은 요청인지 도메인에 확인한 뒤 실제 결과를 저장한다.

        Args:
            command: 외부 갱신에서 관찰한 결과.

        Returns:
            Memory: 원래 본문과 관찰 결과를 가진 보고.
        """
        memory = await self.memories.get(command.memory_id)
        memory.record_graph_update(command.directory, command.reference, command.error)
        return await self.memories.save(memory)
