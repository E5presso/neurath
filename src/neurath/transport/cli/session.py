"""세션 인수 미리보기와 실행 재개를 세션 명령 그룹으로 제공한다."""

import json
from dataclasses import asdict
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.interpret_turn import InterpretTurnCommand, InterpretTurnUseCase
from neurath.application.usecases.preview_session import PreviewSessionQuery, PreviewSessionUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.resume_session import ResumeSessionCommand, ResumeSessionUseCase
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.errors import ContextNotFound
from neurath.serialization import encode_uuid


class TurnSourceKind(StrEnum):
    """현재 보존 원문에 지정할 수 있는 두 용도만 CLI에 노출한다.

    Attributes:
        PROMPT: 실제 결과 요구가 있거나 아직 요구 여부가 미분류인 원문.
        STATUS: 결과 요구를 바꾸지 않는 상태·설명·턴 제어 원문.
    """

    PROMPT = "prompt"
    STATUS = "status"


@CliController("session")
class SessionCliController:
    """소유권을 바꾸지 않는 미리보기와 실제 세션 재개·인수를 구분해 호출한다."""

    def __init__(
        self,
        preview: PreviewSessionUseCase,
        resume: ResumeSessionUseCase,
        connection: AsyncConnectionManager,
        context: ResolveSessionContextUseCase,
        interpret: InterpretTurnUseCase,
    ) -> None:
        """세션 작업 단위와 명령 루프에서 정리할 연결을 받는다.

        Args:
            preview: 원 세션의 현재 작업을 조회하는 유스케이스.
            resume: 확인된 후속 세션으로 실제 작업을 재개·인수하는 유스케이스.
            connection: 명령 실행 이벤트 루프에서 정리할 비동기 엔진.
            context: 실제 호스트에서 현재 세션·턴을 찾는다.
            interpret: 현재 원문의 용도와 이번 턴 제어 반환을 연결한다.
        """
        self.preview = preview
        self.resume = resume
        self.connection = connection
        self.context = context
        self.interpret = interpret

    @command("interpret")
    async def interpret_turn(
        self,
        kind: Annotated[
            TurnSourceKind,
            Option("--kind", help="현재 원문의 prompt(요구) 또는 status(상태·설명) 용도"),
        ],
        reason: Annotated[str, Option("--reason", help="원문에 근거한 판단 이유")],
        pause: bool = False,
        source_id: UUID | None = None,
    ) -> None:
        """현재 원문에 대한 판단을 연결하고 필요한 경우 이번 턴만 제어권을 반환한다.

        Args:
            kind: 실제 새 요구인지 상태·설명인지에 대한 에이전트의 판단.
            reason: 원문에서 확인한 구체적인 판단 근거.
            pause: 원 TODO·phase를 유지한 채 이번 턴 수행을 중지할지 여부.
            source_id: 현재 턴의 특정 원문이며 미지정이면 마지막 원문.

        Raises:
            ContextNotFound: 현재 호스트 실행이 관찰되지 않은 경우.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            if scope.execution is None:
                raise ContextNotFound("Current host execution has not been observed")
            result = await self.interpret.run(
                InterpretTurnCommand(
                    project_id=scope.session.project_id,
                    session_id=scope.session.uid,
                    execution_id=scope.execution.uid,
                    turn_id=scope.execution.turn_id,
                    kind=SourceKind(kind.value),
                    reason=reason,
                    pause=pause,
                    source_id=source_id,
                )
            )
            echo(json.dumps(asdict(result), default=encode_uuid, ensure_ascii=False))
        finally:
            await self.connection.dispose()

    @command("preview")
    async def preview_session(
        self,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        session_id: Annotated[UUID | None, Option("--session-id")] = None,
    ) -> None:
        """원문·작업·runner·현재 맥락을 소유권 변경 없이 인수 전에 미리 본다.

        Args:
            project_id: 조회할 프로젝트 ID.
            session_id: 미리 볼 원 세션 ID.
        """
        try:
            scope = await self.context.run(
                ResolveSessionContextQuery(project_id=project_id, session_id=session_id)
            )
            project_id, session_id = scope.session.project_id, scope.session.uid
            result = await self.preview.run(
                PreviewSessionQuery(project_id=project_id, session_id=session_id)
            )
            echo(
                json.dumps(
                    {
                        "session_id": result.session.uid,
                        "revision": result.session.revision,
                        "successor_id": result.session.successor_id,
                        "sources": [
                            {"id": source.uid, "text": source.body} for source in result.sources
                        ],
                        "tasks": [
                            {
                                "id": task.uid,
                                "status": task.status.value,
                                "definition": asdict(task.definition),
                            }
                            for task in result.tasks
                        ],
                        "workflows": [
                            {
                                "id": run.uid,
                                "revision": run.revision,
                                "definition": asdict(run.definition),
                                "attempts": [asdict(item) for item in run.attempts],
                            }
                            for run in result.workflows
                        ],
                        "enclaves": [
                            {
                                "id": item.uid,
                                "task_id": item.task_id,
                                "revision": item.revision,
                                "facts": [asdict(fact) for fact in item.facts],
                            }
                            for item in result.enclaves
                        ],
                        "memory_ids": result.memory_ids,
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @command("resume")
    async def resume_session(
        self,
        project_id: Annotated[UUID | None, Option("--project-id")] = None,
        source_session_id: Annotated[UUID | None, Option("--source-session-id")] = None,
        target_session_id: Annotated[UUID | None, Option("--target-session-id")] = None,
        expected_revision: Annotated[int | None, Option("--expected-revision")] = None,
        turn_id: Annotated[str, Option("--turn-id")] = "",
    ) -> None:
        """종료·작성 해제 확인 뒤 미완료 작업과 현재 맥락을 이어받는다.

        Args:
            project_id: 같은 프로젝트 범위.
            source_session_id: 원 작업 세션.
            target_session_id: 실제 후속 세션.
            expected_revision: 미리보기의 원 세션 개정.
            turn_id: 후속 호스트의 현재 턴.
        """
        try:
            current = await self.context.run(
                ResolveSessionContextQuery(project_id=project_id, session_id=target_session_id)
            )
            source = (
                current
                if source_session_id is None
                else await self.context.run(
                    ResolveSessionContextQuery(project_id=project_id, session_id=source_session_id)
                )
            )
            project_id = current.session.project_id
            source_session_id, target_session_id = source.session.uid, current.session.uid
            if expected_revision is None:
                expected_revision = source.session.revision
            if not turn_id and current.execution is not None:
                turn_id = current.execution.turn_id
            result = await self.resume.run(
                ResumeSessionCommand(
                    project_id=project_id,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                    expected_revision=expected_revision,
                    turn_id=turn_id,
                )
            )
            echo(json.dumps({"session_id": result.uid, "resumed": True}, default=encode_uuid))
        finally:
            await self.connection.dispose()
