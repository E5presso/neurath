"""세션 기본 CRUD를 상속하고 네이티브 식별자 조회만 추가한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IGenericRepository

from neurath.domain.aggregates.session import HostSession


class ISessionRepository(IGenericRepository[HostSession, str], ABC):
    """기본 저장 계약과 프로젝트·공급자별 네이티브 식별자 조회를 제공한다."""

    @abstractmethod
    def find(self, project_id: str, provider: str, host_session_id: str) -> HostSession | None:
        """지정한 범위의 네이티브 세션을 조회한다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
            host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.

        Returns:
            HostSession | None: 해당 프로젝트·공급자 범위의 세션이며 없으면 None.

        Raises:
            NotImplementedError: 구체 어댑터가 추가 조회 메서드를 구현하지 않은 경우.
        """
        raise NotImplementedError
