"""프로젝트 범위의 호스트 세션을 위한 명시적 저장 계약이다."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.session import HostSession


class ISessionRepository(ABC):
    """호출자가 소유한 기존 트랜잭션 안에서 세션을 조회하고 저장한다."""

    @abstractmethod
    def find(self, project_id: str, provider: str, host_session_id: str) -> HostSession | None:
        """지정한 범위의 네이티브 세션이 있으면 반환한다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
            host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.

        Returns:
            HostSession | None: 해당 프로젝트·공급자 범위의 세션이며 없으면 None.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str, session_id: str) -> HostSession:
        """명시적으로 지정한 프로젝트에 속할 때만 세션을 조회한다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            session_id: 지정한 프로젝트 안에 있는 세션의 식별자.

        Returns:
            HostSession: 명시적으로 지정한 프로젝트에 속한 세션.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, session: HostSession) -> HostSession:
        """신규 또는 기존 엔티티를 저장하고 저장된 버전을 반환한다.

        Args:
            session: 현재 트랜잭션에 저장할 도메인 세션 엔티티.

        Returns:
            HostSession: 현재 저장 버전을 가진 저장된 세션.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError
