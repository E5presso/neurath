"""DB 잠금 밖에서 실제 작성 종료를 관찰하고 같은 세대만 회수한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.writer import Writer


@immutable
class RecoverWriterCommand(AbstractCommand):
    """회수 전에 읽은 작성 임대와 세대를 지정한다.

    Attributes:
        writer_id: 회수할 작업 폴더 임대 ID.
        generation: 사용자가 조회한 세대가 아닌 실행 어댑터가 관찰할 세대.
    """

    writer_id: UUID
    generation: int


@UseCase()
class RecoverWriterUseCase(IAsyncCommandUseCase[RecoverWriterCommand, Writer]):
    """현재 임대 소유자·세대를 검증하고 커밋 뒤 실제 생존 관찰을 요청한다.

    임대는 여기서 해제하지 않는다. RuntimeEventHandler의 관찰 뒤 ReleaseWriterUseCase가
    같은 소유자·세대인지 재검사하여 확인된 종료만 반영한다.
    """

    def __init__(self, writers: IWriterRepository) -> None:
        """현재 상태와 후속 관찰 요청을 저장할 저장소를 받는다.

        Args:
            writers: 실제 소유 상태를 조회하고 요청을 기록한다.
        """
        self.writers = writers

    @transactional
    @override
    async def run(self, command: RecoverWriterCommand) -> Writer:
        """활성 임대의 세대를 대조하고 실제 작성 종료를 조회할 사건을 기록한다.

        Args:
            command: 회수 대상 임대와 관찰할 세대.

        Returns:
            Writer: 요청 시점의 상태이며 종료 확인을 뜻하지 않는다.
        """
        current = await self.writers.get(command.writer_id)
        current.request_recovery(command.generation)
        return await self.writers.save(current)
