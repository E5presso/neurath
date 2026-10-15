"""가변 도메인 엔티티와 분리된 불변 요청 결과 스냅샷을 제공한다."""

from dataclasses import dataclass

from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession


@dataclass(frozen=True)
class ProjectContext:
    """완료된 한 요청에서 관찰한 프로젝트 상태를 나타낸다.

    Attributes:
        id: 프로젝트의 안정적인 식별자.
        root_path: 프로젝트의 정규 루트 경로.
    """

    id: str
    root_path: str


@dataclass(frozen=True)
class HostSessionContext:
    """완료된 한 요청에서 관찰한 세션 상태를 나타낸다.

    Attributes:
        id: 세션의 안정적인 식별자.
        project_id: 세션이 속한 프로젝트의 안정적인 식별자.
        provider: 호스트 공급자의 이름 공간.
        host_session_id: 호스트의 네이티브 식별자.
        working_directory: 마지막으로 수용한 정규 디렉터리.
        revision: 이 결과를 만들 때 저장된 낙관적 버전.
    """

    id: str
    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int


@dataclass(frozen=True)
class SessionContext:
    """엔티티 동일성 대신 상태로 동등성을 비교하는 결과 값이다.

    Attributes:
        project: 프로젝트의 불변 상태.
        session: 해당 프로젝트에 속한 세션의 불변 상태.
    """

    project: ProjectContext
    session: HostSessionContext

    @classmethod
    def from_entities(cls, project: Project, session: HostSession) -> "SessionContext":
        """엔티티를 안정적이고 독립적인 요청 결과로 복사한다.

        Args:
            project: 요청이 지정한 프로젝트 엔티티.
            session: 저장 또는 조회를 마친 세션 엔티티.

        Returns:
            SessionContext: 살아 있는 엔티티나 ORM 참조가 없는 불변 스냅샷.
        """
        return cls(
            ProjectContext(project.id, project.root_path),
            HostSessionContext(
                session.id,
                session.project_id,
                session.provider,
                session.host_session_id,
                session.working_directory,
                session.revision,
            ),
        )
