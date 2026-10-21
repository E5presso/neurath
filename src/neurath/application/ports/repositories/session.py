"""호스트 세션의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.session import HostSession


class ISessionRepository(IAsyncGenericRepository[HostSession, str], ABC):
    """프로젝트 소속과 작업 경로를 가진 세션의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find(
        self, project_id: str, provider: str, host_session_id: str
    ) -> HostSession | None:
        """프로젝트 안에서 실제 네이티브 식별자에 대응하는 세션을 찾는다.

        Args:
            project_id: 세션을 소유한 프로젝트.
            provider: 호스트 공급자.
            host_session_id: 실제 호스트의 세션 식별자.

        Returns:
            HostSession | None: 프로젝트·공급자·네이티브 ID가 일치하는 세션이며 미등록이면 None.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
