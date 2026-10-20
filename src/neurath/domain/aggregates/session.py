"""특정 프로젝트 안에서 가변 호스트 세션의 동일성과 버전 규칙을 관리한다."""

from dataclasses import dataclass
from typing import Self
from uuid import uuid4

from neurath.domain.errors import RevisionConflict


@dataclass(eq=False)
class HostSession:
    """동일성을 유지하면서 작업 경로가 바뀌는 호스트 관찰 엔티티다.

    Attributes:
        id: 세션의 안정적인 식별자.
        project_id: 이 세션이 속한 프로젝트.
        provider: 호스트 공급자의 이름 공간.
        host_session_id: 인증 수단이 아닌 네이티브 식별자.
        working_directory: 가장 최근에 수용한 정규 디렉터리.
        revision: 오래된 요청을 거부하기 위해 저장한 낙관적 버전.
    """

    id: str
    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int

    def __eq__(self, other: object) -> bool:
        """관찰 상태와 독립적인 안정적 세션 식별자로 동일성을 비교한다.

        Args:
            other: 세션 동일성을 비교할 대상 객체.

        Returns:
            bool: 두 객체가 같은 세션을 나타내는지 여부.
        """
        if not isinstance(other, HostSession):
            return NotImplemented
        return self.id == other.id

    @classmethod
    def create(
        cls, project_id: str, provider: str, host_session_id: str, working_directory: str
    ) -> Self:
        """유효한 네이티브 식별자로 최초 관찰을 등록한다.

        Args:
            project_id: 호스트 세션이 속한 프로젝트.
            provider: 비어 있지 않은 호스트 공급자 이름 공간.
            host_session_id: 해당 공급자가 전달한 비어 있지 않은 식별자.
            working_directory: 관찰한 정규 디렉터리.

        Returns:
            Self: 버전이 1인 새 세션.

        Raises:
            ValueError: 공급자 또는 네이티브 식별자가 빈 문자열인 경우.
        """
        if not provider.strip() or not host_session_id.strip():
            raise ValueError("provider and host_session_id must be non-empty")
        return cls(str(uuid4()), project_id, provider, host_session_id, working_directory, 1)

    def move(self, working_directory: str, expected_revision: int) -> None:
        """호출자가 현재 버전을 관찰한 경우에만 새 디렉터리를 수용한다.

        Args:
            working_directory: 이 세션의 프로젝트 안에 있는 정규 디렉터리.
            expected_revision: 이동 요청 전에 호출자가 관찰한 버전.

        Raises:
            RevisionConflict: 호출자가 관찰한 버전이 오래된 경우.
        """
        if expected_revision != self.revision:
            raise RevisionConflict("Session changed; read current context before updating")
        self.working_directory = working_directory
