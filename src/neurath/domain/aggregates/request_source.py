"""원문·발신 맥락·참조와 정정 관계를 보존하는 출처 aggregate다."""

from enum import StrEnum
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import ContextNotFound, InvalidTaskState


class SourceKind(StrEnum):
    """요구 출처와 상태 질문·과거 요약의 용도를 구분한다.

    Attributes:
        PROMPT: 직접 요청 원문.
        TICKET: 지정 티켓 원문.
        SPEC: 지정 명세 원문.
        CORRECTION: 실제 정정 원문.
        STATUS: 상태 질문.
        SUMMARY: 과거 요약.
    """

    PROMPT = "prompt"
    TICKET = "ticket"
    SPEC = "spec"
    CORRECTION = "correction"
    STATUS = "status"
    SUMMARY = "summary"


@mutable
class RequestSource(AbstractAggregateRoot[UUID]):
    """요구의 원문과 최초 기록 세션, 발신 맥락 및 정정 대상 ID를 보존한다.

    Attributes:
        project_id: 출처가 속하는 프로젝트.
        session_id: 최초로 기록한 세션.
        kind: 원문의 용도.
        body: 보존한 원문.
        author: 제공된 발신 맥락이며 불완전하면 None.
        reference: 티켓·문서·호스트 사건의 참조.
        corrects_id: 정정 대상인 기존 출처.
        revision: 저장소의 낙관적 버전.
    """

    project_id: UUID
    session_id: UUID
    kind: SourceKind
    body: str
    author: str | None = None
    reference: str | None = None
    corrects_id: UUID | None = None
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """새 출처 식별자를 생성한다.

        Returns:
            UUID: 독립적으로 보존할 출처 식별자.
        """
        return uuid7()

    @classmethod
    def create(
        cls,
        project_id: UUID,
        session_id: UUID,
        kind: SourceKind,
        body: str,
        author: str | None = None,
        reference: str | None = None,
        corrects_id: UUID | None = None,
    ) -> Self:
        """새 uid로 원문 객체를 만들고 본문·정정 용도의 일관성을 검증한다.

        같은 본문도 별도 출처로 생성한다. 기존 출처의 존재·프로젝트 확인과 DB 저장은
        호출하는 유스케이스가 담당하며, author는 인증값으로 사용하지 않는다.

        Args:
            project_id: 관련 프로젝트.
            session_id: 원문을 기록한 세션.
            kind: 원문의 용도.
            body: 보존할 원문.
            author: 제공된 발신 맥락.
            reference: 원문을 찾을 참조.
            corrects_id: 실제 정정 대상의 출처.

        Returns:
            Self: 최초 맥락을 유지하는 새 출처.
        """
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            session_id=session_id,
            kind=kind,
            body=body,
            author=author,
            reference=reference,
            corrects_id=corrects_id,
        )

    @override
    def validate(self) -> None:
        """공백 본문을 거부하고 correction일 때만 정정 대상 ID를 요구한다.

        Raises:
            InvalidTaskState: 정정 용도와 대상 참조가 일치하지 않는 경우.
            ValueError: 원문이 공백만 포함한 경우.
        """
        if not self.body.strip():
            raise ValueError("body must be non-empty")
        if (self.kind is SourceKind.CORRECTION) != (self.corrects_id is not None):
            raise InvalidTaskState(
                "Corrections require an existing source; other source kinds cannot correct"
            )

    def require_project(self, project_id: UUID) -> None:
        """프로젝트 밖의 출처 참조를 거부한다.

        Args:
            project_id: 요청한 프로젝트.

        Raises:
            ContextNotFound: 다른 프로젝트의 출처인 경우.
        """
        if self.project_id != project_id:
            raise ContextNotFound("Source does not belong to this project")

    def require_requirement(self) -> None:
        """출처 용도가 status·summary이면 태스크 목표로 사용하는 것을 거부한다.

        용도 값을 검사하며 원문 내용이 실제 사용자 의도에 맞는지는 판정하지 않는다.

        Raises:
            InvalidTaskState: 원문이 요구 정의용 출처가 아닌 경우.
        """
        if self.kind in (SourceKind.STATUS, SourceKind.SUMMARY):
            raise InvalidTaskState("Status questions and summaries cannot define requirements")

    def require_correction(self, current_source_id: UUID) -> None:
        """정정한 출처와 현재 요구의 관계를 확인한다.

        Args:
            current_source_id: 현재 정의에 연결된 출처.

        Raises:
            InvalidTaskState: 현재 요구를 정정하는 출처가 아닌 경우.
        """
        self.require_requirement()
        if self.kind is SourceKind.CORRECTION and self.corrects_id != current_source_id:
            raise InvalidTaskState("Correction must refer to the current requirement source")
