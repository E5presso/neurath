"""특정 프로젝트 안에서 가변 호스트 세션의 동일성과 버전 규칙을 관리한다."""

from typing import Self, override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import ContextNotFound, RevisionConflict


@mutable
class HostSession(AbstractAggregateRoot[str]):
    """동일성을 유지하면서 작업 경로가 바뀌는 호스트 관찰 엔티티다.

    Attributes:
        project_id: 이 세션이 속한 프로젝트.
        provider: 호스트 공급자의 이름 공간.
        host_session_id: 인증 수단이 아닌 네이티브 식별자.
        working_directory: 가장 최근에 수용한 정규 디렉터리.
        revision: 오래된 요청을 거부하기 위해 저장한 낙관적 버전.
    """

    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int

    @property
    def id(self) -> str:
        """기존 참조를 유지하는 도메인 식별자를 반환한다.

        Returns:
            str: 기존 요청과 저장 기록에서 사용하는 식별자.
        """
        return self.uid

    @classmethod
    @override
    def next_id(cls) -> str:
        """새 aggregate의 안정적인 식별자를 생성한다.

        Returns:
            str: 새 도메인 인스턴스에 사용할 식별자.
        """
        return str(uuid4())

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
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            provider=provider,
            host_session_id=host_session_id,
            working_directory=working_directory,
            revision=1,
        )

    def require_project(self, project_id: str) -> None:
        """이 세션이 요청한 프로젝트 범위에 속하는지 검사한다.

        Args:
            project_id: 호출자가 지정한 프로젝트 식별자.

        Raises:
            ContextNotFound: 세션이 다른 프로젝트에 속하는 경우.
        """
        if self.project_id != project_id:
            raise ContextNotFound("Session does not exist in the requested project")

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
        if self.working_directory != working_directory:
            self.working_directory = working_directory
