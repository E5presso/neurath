"""호출 세션의 프로젝트에 원문을 새 출처로 기록한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.request_source import RequestSource, SourceKind


@dataclass(frozen=True)
class RecordSourceCommand(AbstractCommand):
    """프로젝트에 보존할 원문과 발신 맥락·용도·정정 대상을 지정한다.

    Attributes:
        project_id: 원문을 조회하거나 기록할 프로젝트 ID.
        session_id: 해당 프로젝트에 속한 호출 세션 ID.
        kind: 요구·정정·상태 질문·요약 중 원문의 용도.
        body: 원래 문장을 그대로 보존할 본문. 공백만 있는 값은 허용하지 않는다.
        author: 알려진 발신 맥락. 없으면 None이며 인증 수단으로 사용하지 않는다.
        reference: 티켓·문서·호스트 사건 등 원문 위치. 별도 위치가 없으면 None.
        corrects_id: correction일 때 필수인 기존 출처 ID. 다른 kind에서는 None.
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
    """새로 기록한 원문과 그 발신 맥락·정정 참조를 반환한다.

    Attributes:
        source: 저장한 원문과 발신 맥락.
    """

    source: RequestSource


@UseCase(scope=Pod.Scope.CONTEXT)
class RecordSourceUseCase(IAsyncCommandUseCase[RecordSourceCommand, RecordSourceResult]):
    """호출 세션의 프로젝트에 원문을 새 출처로 기록한다.

    정정 출처는 같은 프로젝트의 기존 출처를 가리켜야 한다. 원문 저장만으로
    태스크를 만들거나 기존 요구를 정정하지 않으며, 같은 본문의 반복 요청도 새 출처를 만든다.
    기존 원문을 재사용할 때는 이미 저장된 출처 ID를 사용한다.
    """

    def __init__(self, sessions: ISessionRepository, sources: IRequestSourceRepository) -> None:
        """최초 기록 세션을 확인하고 원문·정정 참조를 보존할 저장소를 받는다.

        Args:
            sessions: 원문을 기록하는 세션의 프로젝트 소속을 확인한다.
            sources: 정정 대상 출처를 조회하고 새 원문을 저장한다.
        """
        self.sessions = sessions
        self.sources = sources

    @override
    async def run(self, command: RecordSourceCommand) -> RecordSourceResult:
        """원문 용도·정정 참조와 프로젝트 범위를 확인하고 새 출처를 저장한다.

        Args:
            command: 원문 본문·용도, 최초 기록 세션과 선택적인 발신자·참조·정정 대상.

        Returns:
            RecordSourceResult: 새 uid와 최초 기록 세션을 가진 출처.
        """
        session = await self.sessions.get(command.session_id)
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
            parent = await self.sources.get(command.corrects_id)
            parent.require_project(command.project_id)
        return RecordSourceResult(source=(await self.sources.save(source)))
