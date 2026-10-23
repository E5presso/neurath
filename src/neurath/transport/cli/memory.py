"""기억·현재 맥락·인수 유스케이스를 공식 Typer 명령으로 노출한다."""

import json
import sys
from dataclasses import asdict
from typing import Annotated

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.preview_session import PreviewSessionQuery, PreviewSessionUseCase
from neurath.application.usecases.query_graph import QueryGraphQuery, QueryGraphUseCase
from neurath.application.usecases.read_memory import ReadMemoryQuery, ReadMemoryUseCase
from neurath.application.usecases.resume_session import ResumeSessionCommand, ResumeSessionUseCase
from neurath.application.usecases.save_checkpoint import (
    SaveCheckpointCommand,
    SaveCheckpointUseCase,
)
from neurath.application.usecases.search_memory import SearchMemoryQuery, SearchMemoryUseCase
from neurath.application.usecases.update_enclave import (
    RemoveEnclaveFact,
    SetEnclaveFact,
    UpdateEnclaveCommand,
    UpdateEnclaveUseCase,
)
from neurath.application.usecases.update_graph import UpdateGraphCommand, UpdateGraphUseCase
from neurath.domain.enclave_records import EnclaveFact, EnclaveKind


@CliController("memory")
class MemoryCliController:
    """memory 하위 명령에서 입력을 해석하고 유스케이스의 결과를 JSON으로 반환한다."""

    def __init__(
        self,
        update: UpdateEnclaveUseCase,
        checkpoint: SaveCheckpointUseCase,
        read: ReadMemoryUseCase,
        search: SearchMemoryUseCase,
        preview: PreviewSessionUseCase,
        resume: ResumeSessionUseCase,
        connection: AsyncConnectionManager,
        query_graph: QueryGraphUseCase,
        update_graph: UpdateGraphUseCase,
    ) -> None:
        """현재 맥락·과거 기억·미리보기·인수의 작업 단위를 주입받는다.

        Args:
            update: 현재 맥락 변경.
            checkpoint: 보고 저장.
            read: 선택 기록 조회.
            search: 관련 기록 검색.
            preview: 현재 세션의 인수 미리보기.
            resume: 실제 작업 인수 또는 재개.
            connection: 같은 명령 루프에서 정리할 비동기 엔진.
            query_graph: 기존 Graphify 관계 조회.
            update_graph: 문서 관계 보존을 확인하는 갱신.
        """
        self.update = update
        self.checkpoint = checkpoint
        self.read = read
        self.search = search
        self.preview = preview
        self.resume = resume
        self.connection = connection
        self.query_graph = query_graph
        self.update_graph = update_graph

    @command("update")
    async def update_enclave(
        self,
        project_id: Annotated[str, Option("--project-id")],
        session_id: Annotated[str, Option("--session-id")],
        expected_revision: Annotated[int, Option("--expected-revision")],
        changes: Annotated[str, Option("--changes")],
        task_id: str | None = None,
    ) -> None:
        """JSON 변경 목록을 같은 개정의 현재 맥락에 원자적으로 적용한다.

        Args:
            project_id: 프로젝트 ID.
            session_id: 현재 세션 ID.
            expected_revision: 최초 생성 0 또는 조회한 개정.
            changes: op=set/remove와 key를 가진 JSON 배열. set은 value·kind·references와 선택적 details를 포함한다.
            task_id: 선택한 작업 ID.
        """
        try:
            result = await self.update.run(
                UpdateEnclaveCommand(
                    project_id, session_id, task_id, expected_revision, self._changes(changes)
                )
            )
            echo(
                json.dumps(
                    {
                        "id": result.uid,
                        "revision": result.revision,
                        "facts": [asdict(fact) for fact in result.facts],
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @staticmethod
    def _changes(value: str) -> list[SetEnclaveFact | RemoveEnclaveFact]:
        """외부 JSON의 형식과 구분을 확인해 타입이 있는 변경 목록으로 변환한다.

        Args:
            value: CLI가 받은 변경 배열 JSON이며 -는 표준입력을 뜻한다.

        Returns:
            list[SetEnclaveFact | RemoveEnclaveFact]: 형식을 확인한 변경 목록.

        Raises:
            ValueError: 배열·항목·문자열·출처·변경 종류의 형식이 잘못된 경우.
        """
        data: object = json.load(sys.stdin) if value == "-" else json.loads(value)
        if not isinstance(data, list):
            raise ValueError("changes must be an array")
        changes: list[SetEnclaveFact | RemoveEnclaveFact] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                raise ValueError("Each change requires a string key")
            if item.get("op") == "remove":
                changes.append(RemoveEnclaveFact(item["key"]))
                continue
            references = item.get("references")
            if (
                item.get("op") != "set"
                or not isinstance(item.get("value"), str)
                or not isinstance(item.get("kind"), str)
                or not isinstance(references, list)
                or not all(isinstance(reference, str) for reference in references)
            ):
                raise ValueError("set requires value, kind and string references")
            details = item.get("details")
            if details is not None and not isinstance(details, str):
                raise ValueError("details must be a string")
            changes.append(
                SetEnclaveFact(
                    EnclaveFact(
                        key=item["key"],
                        value=item["value"],
                        kind=EnclaveKind(item["kind"]),
                        references=references,
                    ),
                    details,
                )
            )
        return changes

    @command("checkpoint")
    async def save_checkpoint(
        self,
        project_id: Annotated[str, Option("--project-id")],
        session_id: Annotated[str, Option("--session-id")],
        content: Annotated[str, Option("--content")],
        reference: Annotated[list[str], Option("--reference")],
        task_id: str | None = None,
        graph_directory: str | None = None,
    ) -> None:
        """원문 참조와 결과·남은 일·다음 행동의 보고를 저장한다.

        Args:
            project_id: 프로젝트 ID.
            session_id: 보고 세션 ID.
            content: 보고 본문. -를 지정하면 표준입력 전체를 읽는다.
            reference: 반복 지정하는 출처·산출물 참조.
            task_id: 관련 작업 ID.
            graph_directory: 명시적으로 갱신·검증할 Graphify 프로젝트 경로.
        """
        try:
            if graph_directory is not None:
                reference = [
                    *reference,
                    await self.update_graph.run(UpdateGraphCommand(graph_directory)),
                ]
            content = sys.stdin.read() if content == "-" else content
            result = await self.checkpoint.run(
                SaveCheckpointCommand(project_id, session_id, content, reference, task_id)
            )
            echo(json.dumps({"id": result.uid, "kind": result.kind.value}))
        finally:
            await self.connection.dispose()

    @command("search")
    async def search_memory(
        self,
        project_id: Annotated[str, Option("--project-id")],
        text: str = "",
        session_id: str | None = None,
        task_id: str | None = None,
        limit: int = 20,
        graph_directory: str | None = None,
    ) -> None:
        """관련 범위의 과거 자료를 검색해 상세 조회할 ID를 반환한다.

        Args:
            project_id: 프로젝트 ID.
            text: 본문 검색 문자열.
            session_id: 기록 작성 세션 제한.
            task_id: 관련 작업 제한.
            limit: 결과 개수.
            graph_directory: 함께 조회할 기존 Graphify 프로젝트 경로.
        """
        try:
            result = await self.search.run(
                SearchMemoryQuery(project_id, text, session_id, task_id, limit)
            )
            graph_result = (
                None
                if graph_directory is None
                else await self.query_graph.run(QueryGraphQuery(graph_directory, text))
            )
            echo(json.dumps({"memory_ids": result, "graph": graph_result}, ensure_ascii=False))
        finally:
            await self.connection.dispose()

    @command("read")
    async def read_memory(
        self,
        project_id: Annotated[str, Option("--project-id")],
        memory_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """선택 기록을 읽거나 원 세션의 현재 상태를 인수 전에 미리 본다.

        Args:
            project_id: 프로젝트 ID.
            memory_id: 선택할 과거 기록 ID.
            session_id: 미리 볼 세션 ID. memory_id와 둘 중 하나를 지정한다.

        Raises:
            ValueError: 기록과 세션 중 정확히 하나를 지정하지 않은 경우.
        """
        try:
            if (memory_id is None) == (session_id is None):
                raise ValueError("Specify exactly one of memory-id or session-id")
            if memory_id is not None:
                result = await self.read.run(ReadMemoryQuery(project_id, memory_id))
                echo(
                    json.dumps(
                        {
                            "id": result.uid,
                            "kind": result.kind.value,
                            "content": result.content,
                            "references": result.references,
                            "session_id": result.session_id,
                            "task_id": result.task_id,
                        },
                        ensure_ascii=False,
                    )
                )
                return
            result = await self.preview.run(PreviewSessionQuery(project_id, str(session_id)))
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
                    ensure_ascii=False,
                )
            )
        finally:
            await self.connection.dispose()

    @command("resume")
    async def resume_session(
        self,
        project_id: Annotated[str, Option("--project-id")],
        source_session_id: Annotated[str, Option("--source-session-id")],
        target_session_id: Annotated[str, Option("--target-session-id")],
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
                    project_id, source_session_id, target_session_id, expected_revision, turn_id
                )
            )
            echo(json.dumps({"session_id": result.uid, "resumed": True}))
        finally:
            await self.connection.dispose()
