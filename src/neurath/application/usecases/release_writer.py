"""호스트 관찰 이후 현재 소유 상태를 재검사하여 확정 결과만 반영한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.writer import Writer
from neurath.domain.runtime_records import Liveness


@immutable
class ReleaseWriterCommand(AbstractCommand):
    """외부 조회와 대조할 소유 식별자와 실제 관찰을 전달한다.

    Attributes:
        writer_id: 결과를 반영할 원장의 식별자.
        execution_id: 관찰 당시의 소유자.
        generation: 관찰 당시의 임대 세대.
        liveness: 실제 호스트에서 관찰한 종료 상태.
    """

    writer_id: UUID
    execution_id: UUID
    generation: int
    liveness: Liveness


@UseCase()
class ReleaseWriterUseCase(IAsyncCommandUseCase[ReleaseWriterCommand, Writer]):
    """호스트 조회 중 변경된 소유자·턴·세대를 덮어쓰지 않고 관찰을 반영한다."""

    def __init__(self, writers: IWriterRepository) -> None:
        """최신 상태를 재조회하고 저장할 저장소를 받는다.

        Args:
            writers: 상태 재검사와 결과 저장을 수행한다.
        """
        self.writers = writers

    @transactional
    @override
    async def run(self, command: ReleaseWriterCommand) -> Writer:
        """최신 상태를 읽고 관찰한 대상과 일치할 때 결과를 반영한다.

        Args:
            command: 관찰한 대상과 실제 호스트 결과.

        Returns:
            Writer: 결과가 반영된 현재 원장.
        """
        current = await self.writers.get(command.writer_id)
        current.release(command.execution_id, command.generation, command.liveness)
        return await self.writers.save(current)
