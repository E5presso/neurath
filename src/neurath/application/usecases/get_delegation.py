"""원 배정의 계획·현재 상태·결과를 조회하며 다시 전달하거나 실행하지 않는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.errors import ContextNotFound


@immutable
class GetDelegationQuery(AbstractQuery):
    """원 배정의 계획·현재 상태·결과를 조회하며 다시 전달하거나 실행하지 않는다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        peer_id: 호출한 등록 피어.
    """

    delegation_id: UUID
    peer_id: UUID


@UseCase()
class GetDelegationUseCase(IAsyncQueryUseCase[GetDelegationQuery, Delegation]):
    """원 배정의 계획·현재 상태·결과를 조회하며 다시 전달하거나 실행하지 않는다."""

    def __init__(self, delegations: IDelegationRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
        """
        self.delegations = delegations

    @transactional
    @override
    async def run(self, query: GetDelegationQuery) -> Delegation:
        """원 배정의 계획·현재 상태·결과를 조회하며 다시 전달하거나 실행하지 않는다.

        Args:
            query: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            ContextNotFound: 요청한 피어·발신자·대화가 지정된 소유 범위와 다른 경우.
        """
        delegation = await self.delegations.get(query.delegation_id)
        if query.peer_id not in (delegation.sender_id, delegation.recipient_id):
            raise ContextNotFound("Peer is outside this assignment")
        return delegation
