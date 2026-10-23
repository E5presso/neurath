"""기사와 소유한 개정·댓글·열람·사용·알림을 관계로 원자적으로 매핑한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.article import Article
from neurath.domain.article_records import (
    ArticleComment,
    ArticleNotice,
    ArticleNoticeStatus,
    ArticleRead,
    ArticleRevision,
    ArticleUse,
)


@Table(Article)
class ArticleModel(AbstractMappableTable[Article]):
    """기사가 소유한 모든 이력을 기본 저장소로 함께 저장한다.

    Attributes:
        id: 안정적인 기사 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 최초 생성 UTC 시각.
        updated_at: 마지막 변경 UTC 시각.
        revision: 저장소 낙관적 버전.
        project_id: 발행 프로젝트.
        author_id: 최초 작성자.
        revisions: 원문 개정 이력.
        comments: 개정에 연결한 댓글.
        reads: 전체 본문 열람.
        uses: 실제 작업 사용 기록.
        notices: 발행 당시 수신자와 제출 상태.
    """

    __tablename__ = "core_articles"
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_projects.id"), nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_peers.id"), nullable=False)
    __mapper_args__ = {"version_id_col": revision}
    revisions: Mapped[list[ArticleRevisionModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ArticleRevisionModel.number"
    )
    comments: Mapped[list[ArticleCommentModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ArticleCommentModel.number"
    )
    reads: Mapped[list[ArticleReadModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ArticleReadModel.revision_number"
    )
    uses: Mapped[list[ArticleUseModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ArticleUseModel.revision_number"
    )
    notices: Mapped[list[ArticleNoticeModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ArticleNoticeModel.revision_number"
    )

    @classmethod
    @override
    def from_domain(cls, domain: Article) -> Self:
        """기사와 소유 기록을 선언형 ORM 관계로 변환한다.

        Args:
            domain: 저장할 기사 aggregate.

        Returns:
            Self: 이력을 포함한 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            project_id=domain.project_id,
            author_id=domain.author_id,
            revisions=[
                ArticleRevisionModel.from_value(value, domain.uid) for value in domain.revisions
            ],
            comments=[
                ArticleCommentModel.from_value(value, domain.uid) for value in domain.comments
            ],
            reads=[ArticleReadModel.from_value(value, domain.uid) for value in domain.reads],
            uses=[ArticleUseModel.from_value(value, domain.uid) for value in domain.uses],
            notices=[ArticleNoticeModel.from_value(value, domain.uid) for value in domain.notices],
        )

    @override
    def to_domain(self) -> Article:
        """관계에 보존한 원문과 사건을 독립적인 도메인으로 복원한다.

        Returns:
            Article: 전체 이력을 보존한 기사.
        """
        return Article(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            project_id=self.project_id,
            author_id=self.author_id,
            revisions=tuple(value.to_value() for value in self.revisions),
            comments=tuple(value.to_value() for value in self.comments),
            reads=tuple(value.to_value() for value in self.reads),
            uses=tuple(value.to_value() for value in self.uses),
            notices=tuple(value.to_value() for value in self.notices),
        )


@Table()
class ArticleRevisionModel(AbstractTable):
    """기사에 종속된 revisions 기록을 매핑한다.

    Attributes:
        article_id: 소유 기사.
        number: 기사 개정 번호.
        title: 선택 조회할 제목.
        body: 전체 본문.
        references: 발견의 근거.
        reason: 발행 또는 정정 이유.
    """

    __tablename__ = "core_article_revisions"
    article_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_articles.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)

    @classmethod
    def from_value(cls, value: ArticleRevision, article_id: UUID) -> Self:
        """불변 사건을 기사 소유 레코드로 변환한다.

        Args:
            value: 보존할 사건.
            article_id: 소유 기사.

        Returns:
            Self: 기사에 종속된 저장 레코드.
        """
        return cls(
            article_id=article_id,
            number=value.number,
            title=value.title,
            body=value.body,
            references=list(value.references),
            reason=value.reason,
        )

    def to_value(self) -> ArticleRevision:
        """저장된 사건을 원래 불변 기록으로 복원한다.

        Returns:
            ArticleRevision: 보존한 사건의 값.
        """
        return ArticleRevision(
            number=self.number,
            title=self.title,
            body=self.body,
            references=self.references,
            reason=self.reason,
        )


@Table()
class ArticleCommentModel(AbstractTable):
    """기사에 종속된 comments 기록을 매핑한다.

    Attributes:
        article_id: 소유 기사.
        number: 댓글 순서.
        revision_number: 읽고 논의한 개정.
        peer_id: 댓글 작성 피어.
        body: 댓글 원문.
    """

    __tablename__ = "core_article_comments"
    article_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_articles.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    peer_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_peers.id"), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)

    @classmethod
    def from_value(cls, value: ArticleComment, article_id: UUID) -> Self:
        """불변 사건을 기사 소유 레코드로 변환한다.

        Args:
            value: 보존할 사건.
            article_id: 소유 기사.

        Returns:
            Self: 기사에 종속된 저장 레코드.
        """
        return cls(
            article_id=article_id,
            number=value.number,
            revision_number=value.revision_number,
            peer_id=value.peer_id,
            body=value.body,
        )

    def to_value(self) -> ArticleComment:
        """저장된 사건을 원래 불변 기록으로 복원한다.

        Returns:
            ArticleComment: 보존한 사건의 값.
        """
        return ArticleComment(
            number=self.number,
            revision_number=self.revision_number,
            peer_id=self.peer_id,
            body=self.body,
        )


@Table()
class ArticleReadModel(AbstractTable):
    """기사에 종속된 reads 기록을 매핑한다.

    Attributes:
        article_id: 소유 기사.
        peer_id: 본문을 반환한 피어.
        revision_number: 실제 반환한 개정.
    """

    __tablename__ = "core_article_reads"
    article_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_articles.id"), primary_key=True
    )
    peer_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_peers.id"), primary_key=True)
    revision_number: Mapped[int] = mapped_column(Integer, primary_key=True)

    @classmethod
    def from_value(cls, value: ArticleRead, article_id: UUID) -> Self:
        """불변 사건을 기사 소유 레코드로 변환한다.

        Args:
            value: 보존할 사건.
            article_id: 소유 기사.

        Returns:
            Self: 기사에 종속된 저장 레코드.
        """
        return cls(
            article_id=article_id,
            peer_id=value.peer_id,
            revision_number=value.revision_number,
        )

    def to_value(self) -> ArticleRead:
        """저장된 사건을 원래 불변 기록으로 복원한다.

        Returns:
            ArticleRead: 보존한 사건의 값.
        """
        return ArticleRead(
            peer_id=self.peer_id,
            revision_number=self.revision_number,
        )


@Table()
class ArticleUseModel(AbstractTable):
    """기사에 종속된 uses 기록을 매핑한다.

    Attributes:
        article_id: 소유 기사.
        task_id: 실제 사용 작업.
        definition_number: 사용 당시 요구 개정.
        revision_number: 사용한 기사 개정.
        peer_id: 실제 사용한 피어.
    """

    __tablename__ = "core_article_uses"
    article_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_articles.id"), primary_key=True
    )
    task_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_tasks.id"), primary_key=True)
    definition_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    peer_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_peers.id"), primary_key=True)

    @classmethod
    def from_value(cls, value: ArticleUse, article_id: UUID) -> Self:
        """불변 사건을 기사 소유 레코드로 변환한다.

        Args:
            value: 보존할 사건.
            article_id: 소유 기사.

        Returns:
            Self: 기사에 종속된 저장 레코드.
        """
        return cls(
            article_id=article_id,
            task_id=value.task_id,
            definition_number=value.definition_number,
            revision_number=value.revision_number,
            peer_id=value.peer_id,
        )

    def to_value(self) -> ArticleUse:
        """저장된 사건을 원래 불변 기록으로 복원한다.

        Returns:
            ArticleUse: 보존한 사건의 값.
        """
        return ArticleUse(
            task_id=self.task_id,
            definition_number=self.definition_number,
            revision_number=self.revision_number,
            peer_id=self.peer_id,
        )


@Table()
class ArticleNoticeModel(AbstractTable):
    """기사에 종속된 notices 기록을 매핑한다.

    Attributes:
        article_id: 소유 기사.
        peer_id: 발행 당시 활성 수신자.
        revision_number: 발행 기사 개정.
        status: 대기·응답 제출·폐기의 구분.
    """

    __tablename__ = "core_article_notices"
    article_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_articles.id"), primary_key=True
    )
    peer_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_peers.id"), primary_key=True)
    revision_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)

    @classmethod
    def from_value(cls, value: ArticleNotice, article_id: UUID) -> Self:
        """불변 사건을 기사 소유 레코드로 변환한다.

        Args:
            value: 보존할 사건.
            article_id: 소유 기사.

        Returns:
            Self: 기사에 종속된 저장 레코드.
        """
        return cls(
            article_id=article_id,
            peer_id=value.peer_id,
            revision_number=value.revision_number,
            status=value.status.value,
        )

    def to_value(self) -> ArticleNotice:
        """저장된 사건을 원래 불변 기록으로 복원한다.

        Returns:
            ArticleNotice: 보존한 사건의 값.
        """
        return ArticleNotice(
            peer_id=self.peer_id,
            revision_number=self.revision_number,
            status=ArticleNoticeStatus(self.status),
        )
