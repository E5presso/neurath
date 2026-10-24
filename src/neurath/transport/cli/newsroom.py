"""프로젝트 기사의 선택 조회·발행·정정·댓글을 공식 CLI로 노출한다."""

import json
import sys
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.comment_on_article import (
    CommentOnArticleCommand,
    CommentOnArticleUseCase,
)
from neurath.application.usecases.list_articles import ListArticlesQuery, ListArticlesUseCase
from neurath.application.usecases.publish_article import (
    PublishArticleCommand,
    PublishArticleUseCase,
)
from neurath.application.usecases.read_article import ReadArticleQuery, ReadArticleUseCase
from neurath.application.usecases.record_article_read import (
    RecordArticleReadCommand,
    RecordArticleReadUseCase,
)
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.revise_article import ReviseArticleCommand, ReviseArticleUseCase
from neurath.application.usecases.subscribe_peer import SubscribePeerCommand, SubscribePeerUseCase
from neurath.serialization import encode_uuid


@CliController("newsroom")
class NewsroomCliController:
    """명세의 기사 명령을 해석하고 본문 선택 조회와 제목 출력을 구분한다."""

    def __init__(
        self,
        publish: PublishArticleUseCase,
        revise: ReviseArticleUseCase,
        read: ReadArticleUseCase,
        articles: ListArticlesUseCase,
        comment: CommentOnArticleUseCase,
        connection: AsyncConnectionManager,
        receipt: RecordArticleReadUseCase,
        context: ResolveSessionContextUseCase,
        subscription: SubscribePeerUseCase,
    ) -> None:
        """기사를 소유한 작업 단위와 명령 루프에서 정리할 연결을 받는다.

        Args:
            publish: 최초 기사 발행.
            revise: 기대 개정을 확인한 정정.
            read: 전체 본문 조회와 해당 개정 열람.
            articles: 제목과 개정의 제한 조회.
            comment: 읽은 개정에 연결한 댓글.
            connection: 명령을 실행한 이벤트 루프에서 정리할 엔진.
            receipt: 전체 출력이 반환된 뒤 기록할 개정별 열람.
            context: 현재 실제 호스트 피어를 자동 조회한다.
            subscription: 현재 피어의 뉴스룸 알림 설정만 변경한다.
        """
        self.publish = publish
        self.revise = revise
        self.read = read
        self.articles = articles
        self.comment = comment
        self.connection = connection
        self.receipt = receipt
        self.context = context
        self.subscription = subscription

    async def _peer(self, selected: UUID | None) -> UUID:
        """명시 범위가 없으면 실제 현재 호스트에서 기사 행위자를 찾는다.

        Args:
            selected: 명시적으로 선택한 피어 또는 None.

        Returns:
            UUID: 실제 관찰된 현재 행위자.

        Raises:
            ValueError: 현재 호스트 피어가 없는 경우.
        """
        if selected is not None:
            return selected
        scope = await self.context.run(ResolveSessionContextQuery())
        if scope.peer is None:
            raise ValueError("The current host peer has not been observed")
        return scope.peer.uid

    @command("publish")
    async def publish_article(
        self,
        *,
        peer_id: Annotated[UUID | None, Option("--peer-id")] = None,
        title: Annotated[str, Option("--title")],
        body: Annotated[str, Option("--body")],
        reference: Annotated[list[str], Option("--reference")],
    ) -> None:
        """기사와 근거를 저장하고 활성 구독자에게 제목 알림을 예약한다.

        Args:
            peer_id: 실제 발행 피어.
            title: 기사 제목.
            body: 전체 원문이며 -는 표준입력 전체를 뜻함.
            reference: 반복 지정하는 근거 참조.
        """
        try:
            peer_id = await self._peer(peer_id)
            result = await self.publish.run(
                PublishArticleCommand(
                    peer_id=peer_id,
                    title=title,
                    body=sys.stdin.read() if body == "-" else body,
                    references=reference,
                )
            )
            echo(
                json.dumps(
                    {"id": result.uid, "revision_number": result.current.number},
                    default=encode_uuid,
                )
            )
        finally:
            await self.connection.dispose()

    @command("revise")
    async def revise_article(
        self,
        *,
        peer_id: Annotated[UUID | None, Option("--peer-id")] = None,
        article_id: Annotated[UUID, Option("--article-id")],
        expected_revision: Annotated[int, Option("--expected-revision")],
        title: Annotated[str, Option("--title")],
        body: Annotated[str, Option("--body")],
        reference: Annotated[list[str], Option("--reference")],
        reason: Annotated[str, Option("--reason")],
    ) -> None:
        """원 작성자의 기사 정정과 이전 본문을 함께 보존한다.

        Args:
            peer_id: 실제 원 작성자.
            article_id: 정정할 기사.
            expected_revision: 읽고 확인한 기사 개정 번호.
            title: 새 제목.
            body: 새 전체 본문이며 -는 표준입력 전체를 뜻함.
            reference: 정정 근거 참조.
            reason: 정정 이유.
        """
        try:
            peer_id = await self._peer(peer_id)
            result = await self.revise.run(
                ReviseArticleCommand(
                    peer_id=peer_id,
                    article_id=article_id,
                    expected_revision=expected_revision,
                    title=title,
                    body=sys.stdin.read() if body == "-" else body,
                    references=reference,
                    reason=reason,
                )
            )
            echo(
                json.dumps(
                    {"id": result.uid, "revision_number": result.current.number},
                    default=encode_uuid,
                )
            )
        finally:
            await self.connection.dispose()

    @command("list")
    async def list_articles(
        self,
        *,
        peer_id: Annotated[UUID | None, Option("--peer-id")] = None,
        text: str = "",
        after_id: UUID | None = None,
        limit: int = 20,
    ) -> None:
        """제목과 현재 개정·열람·실제 사용 작업의 정정 영향을 제한 조회한다.

        Args:
            peer_id: 현재 조회 피어.
            text: 제목 검색 문자열.
            after_id: 이전 페이지의 마지막 기사 식별자.
            limit: 최대 결과 개수.
        """
        try:
            peer_id = await self._peer(peer_id)
            result = await self.articles.run(
                ListArticlesQuery(peer_id=peer_id, text=text, after_id=after_id, limit=limit)
            )
            echo(
                json.dumps(
                    [asdict(item) for item in result], default=encode_uuid, ensure_ascii=False
                )
            )
        finally:
            await self.connection.dispose()

    @command("read")
    async def read_article(
        self,
        *,
        peer_id: Annotated[UUID | None, Option("--peer-id")] = None,
        article_id: Annotated[UUID, Option("--article-id")],
        revision_number: Annotated[int, Option("--revision-number")],
        task_id: UUID | None = None,
    ) -> None:
        """선택 개정의 본문·댓글 전체를 반환하고 그 개정만 열람으로 남긴다.

        Args:
            peer_id: 실제 읽는 피어.
            article_id: 선택한 기사.
            revision_number: 실제 반환할 개정.
            task_id: 실제 해당 개정을 사용하는 작업이며 단순 열람이면 None.
        """
        try:
            peer_id = await self._peer(peer_id)
            result = await self.read.run(
                ReadArticleQuery(
                    peer_id=peer_id,
                    article_id=article_id,
                    revision_number=revision_number,
                    task_id=task_id,
                )
            )
            echo(json.dumps(asdict(result), default=encode_uuid, ensure_ascii=False))
            await self.receipt.run(
                RecordArticleReadCommand(
                    peer_id=peer_id,
                    article_id=article_id,
                    revision_number=revision_number,
                    task_id=task_id,
                    expected_definition_number=result.task_definition_number,
                )
            )
        finally:
            await self.connection.dispose()

    @command("comment")
    async def comment_on_article(
        self,
        *,
        peer_id: Annotated[UUID | None, Option("--peer-id")] = None,
        article_id: Annotated[UUID, Option("--article-id")],
        revision_number: Annotated[int, Option("--revision-number")],
        body: Annotated[str, Option("--body")],
    ) -> None:
        """실제 읽은 개정에 댓글을 남기고 작업 결과의 성공은 변경하지 않는다.

        Args:
            peer_id: 실제 댓글 작성 피어.
            article_id: 논의할 기사.
            revision_number: 읽고 댓글을 붙일 개정.
            body: 댓글 원문이며 -는 표준입력 전체를 뜻함.
        """
        try:
            peer_id = await self._peer(peer_id)
            result = await self.comment.run(
                CommentOnArticleCommand(
                    peer_id=peer_id,
                    article_id=article_id,
                    revision_number=revision_number,
                    body=sys.stdin.read() if body == "-" else body,
                )
            )
            echo(json.dumps(asdict(result.comments[-1]), default=encode_uuid, ensure_ascii=False))
        finally:
            await self.connection.dispose()

    @command("subscribe")
    async def configure_subscription(
        self, enabled: Annotated[bool, Option("--enabled/--disabled")] = True
    ) -> None:
        """현재 대화의 뉴스룸 제목 알림을 설정하고 다른 주제 구독은 유지한다.

        Args:
            enabled: 제목 알림을 받을지 여부.

        Raises:
            ValueError: 실제 현재 피어가 관찰되지 않은 경우.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            if scope.peer is None:
                raise ValueError("The current host peer has not been observed")
            topics = [topic for topic in scope.peer.subscriptions if topic != "newsroom"]
            if enabled:
                topics.append("newsroom")
            peer = await self.subscription.run(
                SubscribePeerCommand(peer_id=scope.peer.uid, topics=topics)
            )
            echo(json.dumps({"topics": peer.subscriptions}))
        finally:
            await self.connection.dispose()
