"""특정 프로젝트 안에서 가변 호스트 세션의 동일성과 버전 규칙을 관리한다."""

from typing import Self, override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import ContextNotFound, InvalidExecutionState, RevisionConflict


@mutable
class HostSession(AbstractAggregateRoot[str]):
    """프로젝트·공급자·네이티브 ID로 구분되는 세션과 현재 작업 경로를 보존한다.

    Attributes:
        project_id: 이 세션이 속한 프로젝트.
        provider: 호스트 공급자의 이름 공간.
        host_session_id: 인증 수단이 아닌 네이티브 식별자.
        working_directory: 가장 최근에 수용한 정규 디렉터리.
        revision: 오래된 요청을 거부하기 위해 저장한 낙관적 버전.
        successor_id: 인수가 확정된 후속 세션이며 아직 없으면 None.
    """

    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int
    successor_id: str | None = None

    @property
    def id(self) -> str:
        """기존 세션 참조와의 호환을 위해 uid를 id로 읽는다.

        Returns:
            str: 이 세션의 uid와 같은 식별자.
        """
        return self.uid

    @classmethod
    @override
    def next_id(cls) -> str:
        """호스트의 네이티브 ID와 별개인 세션 UUID 문자열을 생성한다.

        Returns:
            str: Neurath 세션의 uid로 사용할 UUID 문자열.
        """
        return str(uuid4())

    @classmethod
    def create(
        cls, project_id: str, provider: str, host_session_id: str, working_directory: str
    ) -> Self:
        """공급자·네이티브 ID의 빈 값을 검사하고 revision 1의 세션 객체를 만든다.

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
        """읽은 revision이 일치할 때 작업 경로를 바꾸고 동일 경로는 유지한다.

        목적지가 같은 프로젝트인지는 호출자가 먼저 확인해야 한다. 이 메서드는
        경로를 관찰하거나 정수 revision을 올리지 않으며 revision은 ORM 저장 시 갱신된다.

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

    def require_current_owner(self) -> None:
        """후속 세션에 넘긴 원 실행의 쓰기 재개를 거절한다.

        Raises:
            InvalidExecutionState: 인수가 이미 확정된 세션인 경우.
        """
        if self.successor_id is not None:
            raise InvalidExecutionState(f"Session work was handed off to {self.successor_id}")

    def hand_off(self, successor: Self, expected_revision: int) -> None:
        """같은 프로젝트의 후속 세션으로 작업 연결을 넘긴 사실을 보존한다.

        Args:
            successor: 실제 등록된 후속 세션.
            expected_revision: 인수 미리보기에서 읽은 원 세션 개정.

        Raises:
            RevisionConflict: 원 세션이 미리보기 이후 변경된 경우.
            InvalidExecutionState: 자기 자신에게 인수를 요청한 경우.
        """
        self.require_current_owner()
        successor.require_current_owner()
        successor.require_project(self.project_id)
        if self.revision != expected_revision:
            raise RevisionConflict("Source session changed")
        if successor.uid == self.uid:
            raise InvalidExecutionState("A handoff requires a different session")
        self.successor_id = successor.uid
