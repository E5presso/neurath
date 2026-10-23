"""커밋된 체크포인트의 Graphify 갱신을 DB 잠금 없이 실행한다."""

import asyncio
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.event.event_publisher import IAsyncEventPublisher

from neurath.application.ports.services.graph import IGraphService
from neurath.domain.memory_events import CheckpointGraphObserved


@immutable
class UpdateCheckpointGraphCommand(AbstractCommand):
    """검증·커밋된 보고와 외부 갱신 대상을 전달한다.

    Attributes:
        memory_id: 요청이 커밋된 체크포인트 ID.
        directory: 요청에 기록한 Graphify 경로.
    """

    memory_id: UUID
    directory: str


@UseCase()
class UpdateCheckpointGraphUseCase(IAsyncCommandUseCase[UpdateCheckpointGraphCommand, None]):
    """외부 갱신의 성공·실패를 관찰하고 후속 저장 유스케이스에 전달한다."""

    def __init__(self, graph: IGraphService, publisher: IAsyncEventPublisher) -> None:
        """기존 도구의 실행 계약과 관찰 결과 발행자를 받는다.

        Args:
            graph: Graphify 실행과 문서 관계 보존 검사.
            publisher: 실제 관찰 결과를 전달하는 표준 이벤트 발행자.
        """
        self.graph = graph
        self.publisher = publisher

    @override
    async def run(self, command: UpdateCheckpointGraphCommand) -> None:
        """외부 변경을 수행한 뒤 성공 참조 또는 실패를 같은 보고에 연결한다.

        Args:
            command: 커밋된 보고의 갱신 요청.
        """
        reference: str | None = None
        error: str | None = None
        try:
            reference = await asyncio.to_thread(self.graph.update, command.directory)
            if not reference.strip():
                reference = None
                error = "ValueError: Graph update returned an empty reference"
        except Exception as failure:
            reference = None
            error = f"{type(failure).__name__}: {failure}"
        await self.publisher.publish(
            CheckpointGraphObserved(
                memory_id=command.memory_id,
                directory=command.directory,
                reference=reference,
                error=error,
            )
        )
