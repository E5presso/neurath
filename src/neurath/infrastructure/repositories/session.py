"""프로젝트 범위의 호스트 세션 관찰을 SQLAlchemy로 저장한다."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ContextNotFound, RevisionConflict
from neurath.infrastructure.models.session import SessionModel


class SessionRepository(ISessionRepository):
    """ORM의 낙관적 버전 검사로 호스트 관찰을 저장한다."""

    def __init__(self, session: Session) -> None:
        """캐시된 연결 대신 기존 요청 트랜잭션을 주입받는다.

        Args:
            session: 현재 요청의 SQLAlchemy 세션.
        """
        self.session = session

    @override
    def find(self, project_id: str, provider: str, host_session_id: str) -> HostSession | None:
        """프로젝트와 공급자 범위 안에서만 네이티브 식별자를 찾는다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
            host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.

        Returns:
            HostSession | None: 해당 프로젝트·공급자 범위의 세션이며 없으면 None.
        """
        record = self.session.scalar(
            select(SessionModel).where(
                SessionModel.project_id == project_id,
                SessionModel.provider == provider,
                SessionModel.host_session_id == host_session_id,
            )
        )
        if record is None:
            return None
        return record.to_domain()

    @override
    def get(self, project_id: str, session_id: str) -> HostSession:
        """다른 프로젝트에 속하는 세션 식별자를 거부한다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            session_id: 지정한 프로젝트 안에 있는 세션의 식별자.

        Returns:
            HostSession: 명시적으로 지정한 프로젝트에 속한 세션.
        """
        record = self._get_record(project_id, session_id)
        return record.to_domain()

    def _get_record(self, project_id: str, session_id: str) -> SessionModel:
        """현재 트랜잭션 안에서 지정한 범위의 ORM 레코드를 읽는다.

        Args:
            project_id: 조회 대상 프로젝트의 안정적인 식별자.
            session_id: 지정한 프로젝트 안에 있는 세션의 식별자.

        Returns:
            SessionModel: 분리된 엔티티로 변환할 지정 범위의 ORM 레코드.

        Raises:
            ContextNotFound: 지정한 프로젝트 또는 세션이 요청한 범위에 없는 경우.
        """
        record = self.session.scalar(
            select(SessionModel).where(
                SessionModel.project_id == project_id, SessionModel.id == session_id
            )
        )
        if record is None:
            raise ContextNotFound("Session does not exist in the requested project")
        return record

    @override
    def save(self, session: HostSession) -> HostSession:
        """SQLAlchemy의 낙관적 버전 검사로 신규 또는 분리된 엔티티를 저장한다.

        SQLAlchemy는 상태를 복사하기 전과 UPDATE 실행 시 전달된 버전을 비교한다.
        변경이 없는 상태에는 ORM의 일반적인 변경 감지를 적용한다.

        Args:
            session: 호출자가 최초 관찰한 버전을 가진 엔티티.

        Returns:
            HostSession: SQLAlchemy가 생성한 버전으로 저장된 세션.

        Raises:
            RevisionConflict: 다른 쓰기 요청이 저장된 버전을 변경한 경우.
        """
        try:
            record = self.session.merge(SessionModel.from_domain(session))
            self.session.flush()
        except StaleDataError as error:
            raise RevisionConflict(
                "Session changed; read current context before updating"
            ) from error
        return record.to_domain()
