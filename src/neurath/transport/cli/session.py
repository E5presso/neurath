"""세션 인수 미리보기와 실행 재개를 세션 명령 그룹으로 제공한다."""

import json
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.preview_session import PreviewSessionQuery, PreviewSessionUseCase
from neurath.application.usecases.resume_session import ResumeSessionCommand, ResumeSessionUseCase
from neurath.serialization import encode_uuid


@CliController("session")
class SessionCliController:
    """소유권을 바꾸지 않는 미리보기와 실제 세션 재개·인수를 구분해 호출한다."""

    def __init__(
        self,
        preview: PreviewSessionUseCase,
        resume: ResumeSessionUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """세션 작업 단위와 명령 루프에서 정리할 연결을 받는다.

        Args:
            preview: 원 세션의 현재 작업을 조회하는 유스케이스.
            resume: 확인된 후속 세션으로 실제 작업을 재개·인수하는 유스케이스.
            connection: 명령 실행 이벤트 루프에서 정리할 비동기 엔진.
        """
        self.preview = preview
        self.resume = resume
        self.connection = connection

    @command("preview")
    async def preview_session(
        self,
        project_id: Annotated[UUID, Option("--project-id")],
        session_id: Annotated[UUID, Option("--session-id")],
    ) -> None:
        """원문·작업·runner·현재 맥락을 소유권 변경 없이 인수 전에 미리 본다.

        Args:
            project_id: 조회할 프로젝트 ID.
            session_id: 미리 볼 원 세션 ID.
        """
        try:
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
        project_id: Annotated[UUID, Option("--project-id")],
        source_session_id: Annotated[UUID, Option("--source-session-id")],
        target_session_id: Annotated[UUID, Option("--target-session-id")],
        expected_revision: Annotated[int, Option("--expected-revision")],
        turn_id: Annotated[str, Option("--turn-id")],
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
