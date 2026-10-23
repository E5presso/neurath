"""외부 시작 직전에 커밋된 배정이 현재 요구에 여전히 유효한지 확인한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.delegation import Delegation


@dataclass(frozen=True)
class CheckProviderStartQuery(AbstractQuery):
    """외부 시작 직전에 커밋된 배정이 현재 요구에 여전히 유효한지 확인한다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
    """

    delegation_id: str


@UseCase()
class CheckProviderStartUseCase(IAsyncQueryUseCase[CheckProviderStartQuery, Delegation]):
    """외부 시작 직전에 커밋된 배정이 현재 요구에 여전히 유효한지 확인한다."""

    def __init__(
        self,
        delegations: IDelegationRepository,
        tasks: ITaskRepository,
        sessions: ISessionRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
            sessions: 배정 발신자의 실제 세션 소유 상태를 확인한다.
        """
        self.delegations = delegations
        self.sessions = sessions
        self.tasks = tasks

    @transactional
    @override
    async def run(self, query: CheckProviderStartQuery) -> Delegation:
        """외부 시작 직전에 커밋된 배정이 현재 요구에 여전히 유효한지 확인한다.

        Args:
            query: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        delegation = await self.delegations.get(query.delegation_id)
        task = await self.tasks.get(delegation.task_id)
        (await self.sessions.get(task.owner_session_id)).require_current_owner()
        delegation.require_current(task)
        return delegation
