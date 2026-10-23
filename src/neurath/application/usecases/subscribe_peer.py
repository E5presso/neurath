"""피어의 구독만 갱신하며 과거 전달 대상과 메시지는 변경하지 않는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.peer import Peer


@immutable
class SubscribePeerCommand(AbstractCommand):
    """피어의 구독만 갱신하며 과거 전달 대상과 메시지는 변경하지 않는다.

    Attributes:
        peer_id: 호출한 등록 피어.
        topics: 앞으로 수신할 주제.
    """

    peer_id: UUID
    topics: Sequence[str]


@UseCase()
class SubscribePeerUseCase(IAsyncCommandUseCase[SubscribePeerCommand, Peer]):
    """피어의 구독만 갱신하며 과거 전달 대상과 메시지는 변경하지 않는다."""

    def __init__(self, peers: IPeerRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            peers: Peer aggregate의 범위 조회와 저장.
        """
        self.peers = peers

    @transactional
    @override
    async def run(self, command: SubscribePeerCommand) -> Peer:
        """피어의 구독만 갱신하며 과거 전달 대상과 메시지는 변경하지 않는다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Peer: 요청한 범위에서 저장 또는 조회한 결과.
        """
        peer = await self.peers.get(command.peer_id)
        peer.subscribe(command.topics)
        return await self.peers.save(peer)
