"""커밋된 체크포인트 사건을 외부 갱신과 결과 기록 유스케이스로 전달한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.usecases.record_checkpoint_graph import (
    RecordCheckpointGraphCommand,
    RecordCheckpointGraphUseCase,
)
from neurath.application.usecases.update_checkpoint_graph import (
    UpdateCheckpointGraphCommand,
    UpdateCheckpointGraphUseCase,
)
from neurath.domain.memory_events import CheckpointGraphObserved, CheckpointGraphRequested


@EventHandler()
class CheckpointEventHandler:
    """각 사건을 담당 유스케이스의 입력으로 변환하며 외부 작업을 직접 수행하지 않는다."""

    def __init__(
        self, update: UpdateCheckpointGraphUseCase, record: RecordCheckpointGraphUseCase
    ) -> None:
        """갱신과 관찰 결과 저장을 담당하는 유스케이스를 받는다.

        Args:
            update: DB 밖에서 외부 갱신을 수행한다.
            record: 관찰 결과를 새 트랜잭션에 저장한다.
        """
        self.update = update
        self.record = record

    @on_event(CheckpointGraphRequested)
    async def update_graph(self, event: CheckpointGraphRequested) -> None:
        """커밋된 요청을 외부 갱신 입력으로 전달한다.

        Args:
            event: 검증과 저장이 끝난 보고의 요청 사건.
        """
        await self.update.run(
            UpdateCheckpointGraphCommand(memory_id=event.memory_id, directory=event.directory)
        )

    @on_event(CheckpointGraphObserved)
    async def record_graph(self, event: CheckpointGraphObserved) -> None:
        """외부 관찰을 보고 결과 저장 입력으로 전달한다.

        Args:
            event: 동일 요청의 성공 또는 실패 관찰.
        """
        await self.record.run(
            RecordCheckpointGraphCommand(
                memory_id=event.memory_id,
                directory=event.directory,
                reference=event.reference,
                error=event.error,
            )
        )
