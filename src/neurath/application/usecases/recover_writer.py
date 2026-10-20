"""DB 잠금 밖에서 실제 작성 종료를 관찰하고 같은 세대만 회수한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.persistency.transaction import AbstractTransaction
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.application.ports.services.writer_observer import IWriterObserverService
from neurath.domain.aggregates.writer import Writer
from neurath.domain.errors import InvalidExecutionState


@dataclass(frozen=True)
class RecoverWriterCommand(AbstractCommand):
    """회수 전에 읽은 작성 임대와 세대를 지정한다.

    Attributes:
        writer_id: 회수할 작업 폴더 임대 ID.
        generation: 사용자가 조회한 세대가 아닌 실행 어댑터가 관찰할 세대.
    """

    writer_id: str
    generation: int


@UseCase()
class RecoverWriterUseCase(ICommandUseCase[RecoverWriterCommand, Writer]):
    """실제 종료 관찰과 재조회한 소유자·세대가 일치할 때만 해제한다.

    이 유스케이스는 자체 트랜잭션을 사용한다. 생존을 관찰하는 동안 DB 잠금을
    잡지 않으며 다른 작성자가 취득했으면 도메인의 세대 검사에서 회수를 거절한다.
    """

    def __init__(
        self,
        writers: IWriterRepository,
        observer: IWriterObserverService,
        transaction: AbstractTransaction,
    ) -> None:
        """임대 저장소·호스트 생존 관찰·요청 트랜잭션을 받는다.

        Args:
            writers: 회수 전후 동일 소유자·세대를 조회할 저장소.
            observer: 실제 호스트 종료를 조회하는 실행 어댑터.
            transaction: 짧은 조회·저장 경계를 여는 프레임워크 트랜잭션.
        """
        self.writers = writers
        self.observer = observer
        self.transaction = transaction

    @override
    def run(self, command: RecoverWriterCommand) -> Writer:
        """생존 상태를 조회하고 바뀌지 않은 임대의 실제 종료만 저장한다.

        Args:
            command: 회수 대상 임대와 예상 세대.

        Returns:
            Writer: 실제 종료가 확인되어 해제된 임대.

        Raises:
            InvalidExecutionState: 회수 대상이 없거나 조회한 세대가 오래된 경우.
        """
        with self.transaction:
            before = self.writers.get(command.writer_id)
            if before.execution_id is None or before.generation != command.generation:
                raise InvalidExecutionState("No matching active writer to recover")
        liveness = self.observer.observe(before)
        with self.transaction:
            current = self.writers.get(command.writer_id)
            current.release(before.execution_id, command.generation, liveness)
            return self.writers.save(current)
