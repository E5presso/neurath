"""RecordSource 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.request_source import RequestSource, SourceKind


@dataclass(frozen=True)
class RecordSourceCommand(AbstractCommand):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
        kind: 원문의 용도.
        body: 실제 원문.
        author: 제공된 발신 맥락.
        reference: 원문의 참조.
        corrects_id: 정정 대상 출처.
    """

    project_id: str
    session_id: str
    kind: SourceKind
    body: str
    author: str | None = None
    reference: str | None = None
    corrects_id: str | None = None


@dataclass(frozen=True)
class RecordSourceResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        source: 저장한 원문과 발신 맥락.
    """

    source: RequestSource


@UseCase()
class RecordSourceUseCase(ICommandUseCase[RecordSourceCommand, RecordSourceResult]):
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, sessions: ISessionRepository, sources: IRequestSourceRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            sessions: 요청에 속하는 sessions 저장소.
            sources: 요청에 속하는 sources 저장소.
        """
        self.sessions = sessions
        self.sources = sources

    @override
    def run(self, command: RecordSourceCommand) -> RecordSourceResult:
        """명시한 요청을 적용하고 결과를 반환한다.

        Args:
            command: 원문·범위·관찰에 연결된 입력.

        Returns:
            RecordSourceResult: 처리한 원장과 현재 상태.
        """
        session = self.sessions.get(command.session_id)
        session.require_project(command.project_id)
        source = RequestSource.create(
            command.project_id,
            command.session_id,
            command.kind,
            command.body,
            command.author,
            command.reference,
            command.corrects_id,
        )
        if command.corrects_id is not None:
            parent = self.sources.get(command.corrects_id)
            parent.require_project(command.project_id)
        return RecordSourceResult(source=self.sources.save(source))
