"""피어·인박스·배정 상태를 제한된 범위로 조회하며 발신하거나 실행하지 않는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import or_, select

from neurath.domain.errors import ContextNotFound
from neurath.infrastructure.models.delegation import DelegationModel
from neurath.infrastructure.models.message import MessageModel
from neurath.infrastructure.models.peer import PeerModel
from neurath.infrastructure.models.session import SessionModel


@immutable
class GetCollaborationContextQuery(AbstractQuery):
    """등록 피어가 볼 인박스와 관련 배정의 페이지를 지정한다.

    Attributes:
        peer_id: 현재 등록 피어.
        after_id: 이전 페이지 마지막 메시지 ID이며 처음이면 None.
        limit: 영역별 최대 결과 수. 1부터 100까지.
    """

    peer_id: UUID
    after_id: UUID | None = None
    limit: int = 20


@immutable
class MessageSummary:
    """전체 본문을 자동 주입하지 않는 인박스 항목이다.

    Attributes:
        id: 선택 조회할 원 메시지.
        conversation_id: 대화 연결.
        sender_id: 등록된 실제 발신 피어.
        title: 선택 조회를 위한 제목.
        delivery_status: 실제 전달 관찰.
        read: 본문 열람 여부.
        acknowledged: 해당 메시지 ACK 여부.
    """

    id: UUID
    conversation_id: UUID
    sender_id: UUID
    title: str
    delivery_status: str
    read: bool
    acknowledged: bool


@immutable
class PeerAddress:
    """프로젝트 안에서 관찰된 실제 호스트 주소다.

    Attributes:
        id: Neurath 피어 ID.
        provider: 실제 호스트 공급자.
        host_session_id: 호스트의 원 세션 ID.
        agent_id: 네이티브 자식 ID 또는 빈 문자열.
        active: 등록된 수신 활성 상태.
        subscriptions: 명시한 주제 구독.
    """

    id: UUID
    provider: str
    host_session_id: str
    agent_id: str
    active: bool
    subscriptions: Sequence[str]


@immutable
class DelegationSummary:
    """보고 원문을 자동 주입하지 않는 현재 배정 요약이다.

    Attributes:
        id: 상세 조회할 배정 ID.
        task_id: 관련 원 태스크.
        definition_number: 배정 당시 요구 개정.
        role: 수행 또는 검토 책임.
        status: 배정의 현재 상태.
        provider_status: 실제 provider 실행 관찰.
        has_report: 선택 조회할 결과 보고가 있는지 여부.
        stop_unconfirmed: 중단 요청은 있으나 실제 중단 관찰이 없는지 여부.
    """

    id: UUID
    task_id: UUID
    definition_number: int
    role: str
    status: str
    provider_status: str | None
    has_report: bool
    stop_unconfirmed: bool


@immutable
class CollaborationContext:
    """현재 피어와 직접 관련된 메시지·배정 및 같은 프로젝트의 주소 목록이다.

    Attributes:
        peers: 같은 프로젝트의 등록 주소.
        inbox: 본문을 제외한 원 메시지 요약.
        delegations: 발신하거나 수신한 배정과 실제 결과.
        next_after_id: 다음 메시지 페이지의 시작점이며 마지막이면 None.
    """

    peers: Sequence[PeerAddress]
    inbox: Sequence[MessageSummary]
    delegations: Sequence[DelegationSummary]
    next_after_id: UUID | None


@UseCase()
class GetCollaborationContextUseCase(
    IAsyncQueryUseCase[GetCollaborationContextQuery, CollaborationContext]
):
    """DB의 현재 협업 상태만 읽으며 조회가 재전송·재실행을 만들지 않게 한다."""

    def __init__(self, sessions: AsyncSessionManager) -> None:
        """조회 투영을 위한 프레임워크 세션을 받는다.

        Args:
            sessions: 요청별 SQLAlchemy 조회 세션.
        """
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: GetCollaborationContextQuery) -> CollaborationContext:
        """같은 프로젝트 주소와 이 피어의 인박스·배정만 제한해서 반환한다.

        Args:
            query: 등록 피어와 페이지 크기.

        Returns:
            CollaborationContext: 본문 자동 주입과 외부 변경이 없는 조회 결과.

        Raises:
            ValueError: 페이지 크기가 지원 범위 밖인 경우.
            ContextNotFound: 등록되지 않은 피어인 경우.
        """
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        session = self.sessions.session
        project_id = await session.scalar(
            select(SessionModel.project_id)
            .join(PeerModel, PeerModel.session_id == SessionModel.id)
            .where(PeerModel.id == query.peer_id)
        )
        if project_id is None:
            raise ContextNotFound("Peer has no observed host session")
        addresses = await session.execute(
            select(PeerModel, SessionModel)
            .join(SessionModel, PeerModel.session_id == SessionModel.id)
            .where(SessionModel.project_id == project_id)
            .order_by(PeerModel.id)
            .limit(query.limit)
        )
        peers = tuple(
            PeerAddress(
                id=p.id,
                provider=s.provider,
                host_session_id=s.host_session_id,
                agent_id=p.agent_id,
                active=p.active,
                subscriptions=p.subscriptions,
            )
            for p, s in addresses
        )
        inbox_query = select(MessageModel).where(MessageModel.recipient_id == query.peer_id)
        if query.after_id is not None:
            inbox_query = inbox_query.where(MessageModel.id > query.after_id)
        messages = list(
            await session.scalars(inbox_query.order_by(MessageModel.id).limit(query.limit + 1))
        )
        page = messages[: query.limit]
        inbox = tuple(
            MessageSummary(
                id=m.id,
                conversation_id=m.conversation_id,
                sender_id=m.sender_id,
                title=m.title,
                delivery_status=m.status,
                read=m.read,
                acknowledged=m.acknowledged,
            )
            for m in page
        )
        assignments = await session.scalars(
            select(DelegationModel)
            .where(
                or_(
                    DelegationModel.sender_id == query.peer_id,
                    DelegationModel.recipient_id == query.peer_id,
                )
            )
            .order_by(DelegationModel.id)
            .limit(query.limit)
        )
        return CollaborationContext(
            peers=peers,
            inbox=inbox,
            delegations=tuple(
                DelegationSummary(
                    id=d.id,
                    task_id=d.task_id,
                    definition_number=d.definition_number,
                    role=d.role,
                    status=d.status,
                    provider_status=d.provider_status,
                    has_report=d.report_summary is not None,
                    stop_unconfirmed=d.stop_reason is not None and d.stop_evidence is None,
                )
                for d in assignments
            ),
            next_after_id=page[-1].id if len(messages) > query.limit else None,
        )
