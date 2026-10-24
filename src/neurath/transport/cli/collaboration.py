"""현재 호스트 피어의 메시지·위임·독립 평가를 실제 협업 경로에 연결한다."""

import json
import sys
from dataclasses import asdict
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.dispatch_work_assignment import (
    DispatchWorkAssignmentCommand,
    DispatchWorkAssignmentUseCase,
)
from neurath.application.usecases.get_collaboration_context import (
    GetCollaborationContextQuery,
    GetCollaborationContextUseCase,
    PeerAddress,
)
from neurath.application.usecases.observe_delegation import (
    ObserveDelegationCommand,
    ObserveDelegationUseCase,
)
from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand
from neurath.application.usecases.read_message import ReadMessageQuery, ReadMessageUseCase
from neurath.application.usecases.record_message_read import (
    RecordMessageReadCommand,
    RecordMessageReadUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.send_peer_message import (
    SendPeerMessageCommand,
    SendPeerMessageUseCase,
)
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.enums.delegation_route import DelegationRoute
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.domain.values.provider_plan import ProviderPlan
from neurath.serialization import encode_uuid


@CliController("collaboration")
class CollaborationCliController:
    """호스트 주소로 동료를 선택하며 사용자 재입력 없이 원 지시를 전달한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        peers: GetCollaborationContextUseCase,
        send: SendPeerMessageUseCase,
        read: ReadMessageUseCase,
        receipt: RecordMessageReadUseCase,
        dispatch: DispatchWorkAssignmentUseCase,
        observe: ObserveDelegationUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """기존 협업의 조회·전달·배정·보고 경계를 받는다.

        Args:
            context: 현재 호스트와 피어.
            peers: 관찰된 동료 주소.
            send: 원 메시지의 멱등 저장.
            read: 본문 조회.
            receipt: 출력 뒤 읽음 기록.
            dispatch: 기존 작업 배정과 평가 단계 연결.
            observe: 원 배정의 실제 결과 조회와 유한 대기.
            connection: 명령 이벤트 루프 정리.
        """
        self.context = context
        self.peers = peers
        self.send = send
        self.read = read
        self.receipt = receipt
        self.dispatch = dispatch
        self.observe = observe
        self.connection = connection

    async def _recipient(self, sender_id: UUID, address: str) -> PeerAddress:
        """기존 호스트 세션·자식 주소를 실제 관찰된 동료에 연결한다.

        Args:
            sender_id: 현재 실제 발신 피어.
            address: 호스트 세션 또는 네이티브 자식 주소.

        Returns:
            PeerAddress: 해당 주소의 실제 피어와 관찰된 호스트·자식 주소.

        Raises:
            ValueError: 주소가 없거나 여러 동료에 해당하는 경우.
        """
        matched: list[PeerAddress] = []
        after = None
        while True:
            current = await self.peers.run(
                GetCollaborationContextQuery(peer_id=sender_id, limit=100, after_id=after)
            )
            matched.extend(
                peer
                for peer in current.peers
                if address in (peer.host_session_id, peer.agent_id, str(peer.id))
                and peer.id != sender_id
            )
            after = current.next_peer_after_id
            if after is None:
                break
        if len(matched) != 1:
            raise ValueError(
                "Select one observed peer from context show --section collaboration; create native children with the host's own delegation tool"
            )
        return matched[0]

    @command("send")
    async def send_message(
        self,
        recipient: Annotated[str, Option("--recipient")],
        title: Annotated[str, Option("--title")],
        body: Annotated[str, Option("--body")],
        key: Annotated[str, Option("--key")] = "",
    ) -> None:
        """원문 메시지를 지정 동료에게 전달하도록 저장한다.

        Args:
            recipient: 실제 호스트 동료 주소.
            title: 제목 알림.
            body: 본문이며 -는 stdin.
            key: 동일 메시지 재전송을 구분하는 호출 키.

        Raises:
            ValueError: 현재 발신 피어가 관찰되지 않은 경우.
        """
        try:
            content = sys.stdin.read() if body == "-" else body
            if not content.strip() or not title.strip():
                raise ValueError("A message requires its title and body")
            scope = await self.context.run(ResolveSessionContextQuery())
            if scope.peer is None:
                raise ValueError("The current host peer has not been observed")
            receiver = await self._recipient(scope.peer.uid, recipient)
            result = await self.send.run(
                SendPeerMessageCommand(
                    sender_id=scope.peer.uid,
                    recipient_id=receiver.id,
                    key=key
                    or sha256(
                        repr(
                            (scope.execution.turn_id if scope.execution else "", title, content)
                        ).encode()
                    ).hexdigest(),
                    title=title,
                    body=content,
                )
            )
            echo(
                json.dumps(
                    {"id": result.uid, "status": result.status, "submitted_to_host": False},
                    default=encode_uuid,
                )
            )
        finally:
            await self.connection.dispose()

    @command("read")
    async def read_message(self, message_id: Annotated[UUID, Option("--message-id")]) -> None:
        """원 메시지 전체를 출력한 뒤에만 읽음 기록을 반영한다.

        Args:
            message_id: 인박스의 원 메시지 ID.

        Raises:
            ValueError: 현재 수신 피어를 확인할 수 없는 경우.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            if scope.peer is None:
                raise ValueError("The current host peer has not been observed")
            result = await self.read.run(
                ReadMessageQuery(message_id=message_id, peer_id=scope.peer.uid)
            )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "sender": result.sender_id,
                        "title": result.title,
                        "body": result.body,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
            await self.receipt.run(
                RecordMessageReadCommand(message_id=message_id, peer_id=scope.peer.uid)
            )
        finally:
            await self.connection.dispose()

    @command("delegate")
    async def delegate_task(
        self,
        task_id: Annotated[UUID, Option("--task-id")],
        scope_text: Annotated[str, Option("--scope")],
        role: DelegationRole = DelegationRole.EXECUTOR,
        recipient: str = "",
        provider: ProviderKind | None = None,
        model: str = "",
        policy: str = "",
        artifact: list[str] | None = None,
        verification: list[str] | None = None,
        retry_of: UUID | None = None,
    ) -> None:
        """원 작업의 수행 또는 현재 후보의 독립 평가를 실제 수신 경로에 연결한다.

        Args:
            task_id: 원 요청에 연결된 작업.
            scope_text: 기존 사용자 지시 안의 맡길 범위.
            role: 수행자 또는 검토자.
            recipient: 실제 관찰된 호스트 세션·자식 주소.
            provider: 별도 provider를 명시적으로 실행할 때의 종류.
            model: provider의 실제 지원 모델.
            policy: provider에 사용할 실제 실행 정책.
            artifact: 평가할 현재 산출물의 실제 참조.
            verification: 실제 검사·문제 관찰 참조.
            retry_of: 종료를 확인한 이전 배정의 명시 재시도.

        Raises:
            ValueError: 경로가 모호하거나 현재 실행 피어가 없거나 평가 자료가 없는 경우.
        """
        try:
            if bool(recipient) == (provider is not None):
                raise ValueError("Choose one observed recipient or one explicit provider")
            current = await self.context.run(ResolveSessionContextQuery())
            if current.peer is None:
                raise ValueError("The current host peer has not been observed")
            receiver = await self._recipient(current.peer.uid, recipient) if recipient else None
            plan = (
                None
                if provider is None
                else ProviderPlan(
                    provider=provider,
                    model=model,
                    policy=policy,
                    directory=current.session.working_directory,
                    parent_session_id=current.session.uid,
                )
            )
            route = DelegationRoute.PEER
            if plan is not None:
                route = DelegationRoute.PROVIDER
            elif (
                receiver is not None
                and receiver.agent_id
                and receiver.host_session_id == current.session.host_session_id
            ):
                route = DelegationRoute.CHILD
            assignment = await self.dispatch.run(
                DispatchWorkAssignmentCommand(
                    project_id=current.session.project_id,
                    session_id=current.session.uid,
                    assignment=PrepareDelegationCommand(
                        task_id=task_id,
                        sender_id=current.peer.uid,
                        role=role,
                        scope=scope_text,
                        route=route,
                        recipient_id=None if receiver is None else receiver.id,
                        plan=plan,
                        retry_of=retry_of,
                    ),
                    artifacts=() if artifact is None else artifact,
                    verification=() if verification is None else verification,
                )
            )
            echo(
                json.dumps(
                    {
                        "id": assignment.uid,
                        "status": assignment.status,
                        "provider_status": assignment.provider_status,
                        "message_id": assignment.message_id,
                    },
                    default=encode_uuid,
                )
            )
        finally:
            await self.connection.dispose()

    @command("observe")
    async def observe_provider(
        self,
        delegation_id: Annotated[UUID, Option("--delegation-id")],
        wait_seconds: Annotated[float, Option("--wait", min=0, max=300)] = 0,
    ) -> None:
        """기존 provider의 실제 관찰 결과를 저장하며 새 모델 실행을 만들지 않는다.

        Args:
            delegation_id: 기존 실행을 조회할 원 배정.
            wait_seconds: 새 모델 호출 없이 기다릴 최대 초.

        Raises:
            ValueError: 현재 호스트 피어가 관찰되지 않은 경우.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            if scope.peer is None:
                raise ValueError("The current host peer has not been observed")
            result = await self.observe.run(
                ObserveDelegationCommand(
                    delegation_id=delegation_id, peer_id=scope.peer.uid, wait_seconds=wait_seconds
                )
            )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "status": result.status,
                        "provider_status": result.provider_status,
                        "report": None if result.report is None else asdict(result.report),
                        "provider_output": result.provider_output,
                        "provider_error": result.provider_error,
                        "reference": result.execution_reference,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()
