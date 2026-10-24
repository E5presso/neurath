"""현재 세션·작업의 enclave와 저장 개정을 조회한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.enclave import IEnclaveRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.enclave import Enclave


@immutable
class GetEnclaveQuery(AbstractQuery):
    """현재 사실을 읽을 소유 범위를 지정한다.

    Attributes:
        project_id: 프로젝트 범위.
        session_id: 현재 세션.
        task_id: 작업별 사실 또는 세션 공통 사실의 None.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID | None = None


@UseCase()
class GetEnclaveUseCase(IAsyncQueryUseCase[GetEnclaveQuery, Enclave | None]):
    """모델이 저장 개정을 기억하지 않아도 현재 사실을 확인할 수 있게 한다."""

    def __init__(self, sessions: ISessionRepository, enclaves: IEnclaveRepository) -> None:
        """범위 확인과 현재 사실의 조회 계약을 받는다.

        Args:
            sessions: 세션 소유 범위 확인.
            enclaves: 현재 사실과 이력 조회.
        """
        self.sessions = sessions
        self.enclaves = enclaves

    @transactional
    @override
    async def run(self, query: GetEnclaveQuery) -> Enclave | None:
        """같은 범위의 현재 개정을 변경 없이 읽는다.

        Args:
            query: 현재 사실의 정확한 범위.

        Returns:
            Enclave | None: 기존 사실 저장소 또는 아직 저장하지 않은 None.
        """
        session = await self.sessions.get(query.session_id)
        session.require_project(query.project_id)
        return next(
            (
                item
                for item in await self.enclaves.find_by_session_id(query.session_id)
                if item.task_id == query.task_id
            ),
            None,
        )
