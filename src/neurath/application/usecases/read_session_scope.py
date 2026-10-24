"""관찰된 호스트 세션에서 프로젝트·실행·피어의 내부 식별자를 조회한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import or_, select

from neurath.domain.aggregates.execution import Execution
from neurath.domain.aggregates.peer import Peer
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ContextNotFound
from neurath.infrastructure.models.execution import ExecutionModel
from neurath.infrastructure.models.peer import PeerModel
from neurath.infrastructure.models.project import ProjectLocationModel
from neurath.infrastructure.models.session import SessionModel


@immutable
class ReadSessionScopeQuery(AbstractQuery):
    """호스트 주소 또는 명시적인 내부 범위로 조회 대상을 지정한다.

    Attributes:
        directory: 프로젝트의 정규 폴더 또는 Git 공통 디렉터리.
        native_session: 현재 호스트의 세션/자식 주소.
        provider: 호스트 종류이며 미지정은 빈 문자열.
        project_id: 명시적으로 다른 범위를 조회할 때의 프로젝트.
        session_id: 명시적으로 다른 세션을 조회할 때의 내부 ID.
    """

    directory: str
    native_session: str = ""
    provider: str = ""
    project_id: UUID | None = None
    session_id: UUID | None = None


@immutable
class SessionScope:
    """실제 관찰된 현재 세션과 그 실행·피어를 반환한다.

    Attributes:
        session: 같은 프로젝트에 연결된 세션.
        execution: 실제 관찰한 현재 실행이며 미관찰이면 None.
        peer: 실제 관찰한 협업 주소이며 미관찰이면 None.
        invocation_directory: 조회 호출의 실제 작업 폴더이며 세션 소유 경로와 구분한다.
    """

    session: HostSession
    execution: Execution | None
    peer: Peer | None
    invocation_directory: str = ""


@UseCase()
class ReadSessionScopeUseCase(IAsyncQueryUseCase[ReadSessionScopeQuery, SessionScope]):
    """모호한 여러 세션 중 하나를 임의로 선택하지 않는 읽기 전용 조회다."""

    def __init__(self, sessions: AsyncSessionManager) -> None:
        """현재 읽기 트랜잭션의 세션을 받는다.

        Args:
            sessions: 프레임워크 SQLAlchemy 세션.
        """
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: ReadSessionScopeQuery) -> SessionScope:
        """호스트 주소·폴더를 대조하고 필요한 내부 값을 한 번에 반환한다.

        Args:
            query: 실제 호출 맥락 또는 명시적 조회 범위.

        Returns:
            SessionScope: 실제로 조회한 단일 세션 범위.

        Raises:
            ContextNotFound: 세션이 없거나 여러 후보를 구분할 실제 주소가 없는 경우.
        """
        statement = select(SessionModel)
        if query.session_id is None and not query.native_session:
            statement = statement.where(SessionModel.successor_id.is_(None))
        if query.session_id is not None:
            statement = statement.where(SessionModel.id == query.session_id)
        elif not query.native_session:
            statement = statement.where(
                SessionModel.project_id.in_(
                    select(ProjectLocationModel.project_id).where(
                        ProjectLocationModel.path == query.directory
                    )
                )
            )
        if query.project_id is not None:
            statement = statement.where(SessionModel.project_id == query.project_id)
        if query.provider:
            statement = statement.where(SessionModel.provider == query.provider)
        if query.native_session:
            statement = statement.where(
                or_(
                    SessionModel.host_session_id == query.native_session,
                    SessionModel.id.in_(
                        select(ExecutionModel.session_id).where(
                            ExecutionModel.agent_id == query.native_session
                        )
                    ),
                )
            )
        records = (await self.sessions.session.scalars(statement)).all()
        if len(records) > 1 and query.native_session and query.project_id is None:
            projects = set(
                (
                    await self.sessions.session.scalars(
                        select(ProjectLocationModel.project_id).where(
                            ProjectLocationModel.path == query.directory
                        )
                    )
                ).all()
            )
            matching = [item for item in records if item.project_id in projects]
            if matching:
                records = matching
        if len(records) != 1:
            addresses = [
                f"{item.provider}:{item.host_session_id} project={item.project_id} directory={item.working_directory}"
                for item in records
            ]
            raise ContextNotFound(
                f"Current host session is unavailable or ambiguous: {addresses}. Use --session with an observed host address and --provider/--project-id only to disambiguate observed links; check the session hook installation."
            )
        session = records[0]
        executions = (
            await self.sessions.session.scalars(
                select(ExecutionModel).where(ExecutionModel.session_id == session.id)
            )
        ).all()
        execution = next(
            (item for item in executions if item.agent_id == query.native_session), None
        )
        if execution is None:
            execution = next((item for item in executions if not item.agent_id), None)
        agent = execution.agent_id if execution is not None else ""
        peer = await self.sessions.session.scalar(
            select(PeerModel).where(PeerModel.session_id == session.id, PeerModel.agent_id == agent)
        )
        return SessionScope(
            session=session.to_domain(),
            execution=None if execution is None else execution.to_domain(),
            peer=None if peer is None else peer.to_domain(),
        )
